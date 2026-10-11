"""消费初采产物的独立「放大和重绘」V3 节点（节点类名与数据键仍为 精修与放大）。"""
import uuid

from comfy_api.latest import io
from comfy.samplers import KSampler


def _广播进度(node_id, run_id, seq, value, total):
    """整体进度走自有事件；上报失败必须吞掉，不能把已在跑的后处理轮次拖成报错
    （同 长视频规划师._广播进度 口径：try 体只含宿主调用，无我方逻辑）。"""
    try:
        from comfy_execution.utils import get_executing_context
        from server import PromptServer
        context = get_executing_context()
        server = getattr(PromptServer, "instance", None)
    except Exception:  # noqa: BLE001 - try 体仅第三方调用，拿不到宿主上下文就静默跳过进度
        return
    if context is None or server is None:
        return
    try:
        server.send_sync("长视频规划师_后处理进度", {
            "node": str(node_id), "prompt_id": context.prompt_id, "run": run_id,
            "seq": seq, "value": value, "max": total,
        }, server.client_id)
    except Exception:  # noqa: BLE001 - try 体仅第三方调用，进度失败不得影响生成
        pass


class 精修与放大(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        if "." in __package__:
            from ..执行.H3潜空间放大 import 列兼容H3放大模型
            from ..执行.像素放大模型 import 列像素放大模型
        else:
            from 执行.H3潜空间放大 import 列兼容H3放大模型
            from 执行.像素放大模型 import 列像素放大模型
        return io.Schema(
            # 改名只动 display_name：数据键是存档 class_type 与连线匹配用的真源（同 SelfLift配置 口径）。
            # 界面显隐见 网页资源/放大重绘显隐.js——它按下面的数据键匹配组件，镜像锁在 测试_常量同步.py。
            node_id="精修与放大", display_name="放大和重绘", search_aliases=_别名,
            category="长视频规划师", description=_说明,
            inputs=[
                io.Custom("LVP_FIRST_PASS").Input("初采产物"),
                io.Model.Input("fl2va模型", optional=True),
                io.Model.Input("ref2va模型", optional=True),
                io.Clip.Input("CLIP编码器", optional=True),
                io.Vae.Input("视频VAE"),
                io.Vae.Input("音频VAE", optional=True),
                # 声明顺序＝节点上下顺序（V3 无 widget 排序 API）：放大段→重绘段→缓存段。
                io.Combo.Input("放大方式", options=["H3潜空间", "像素模型", "Lanczos"], default="H3潜空间",
                               tooltip="H3潜空间＝在潜空间放大，需 H3 放大权重；像素模型＝按权重文件放大，需「像素放大模型」；"
                                       "Lanczos＝免模型插值。选中哪一档，节点上才显示对应的权重下拉"),
                io.Float.Input("放大倍率", default=2.0, min=1.0, max=4.0, step=0.25,
                               display_mode=io.NumberDisplay.slider, tooltip="1.0 等于不放大，这一档不读放大权重；目标尺寸按 32 像素网格向上取整，小画布取整后可能仍是原尺寸"),
                io.Combo.Input("H3放大权重", options=列兼容H3放大模型(), default="未选择",
                               tooltip="只在「H3潜空间」下生效；下拉只列 models/latent_upscale_models/ 里符合 H3 24 通道 3D 架构的 "
                                       ".safetensors，插件不自动下载"),
                io.Combo.Input("像素放大模型", options=列像素放大模型(), default="未选择",
                               tooltip="只在「像素模型」下生效；列 models/upscale_models/ 里的 .pth/.ckpt/.safetensors，"
                                       "与官方「Load Upscale Model」读同一目录同一套模型，无需再摆加载器节点"),
                io.Boolean.Input("重绘开关", default=False, socketless=True,
                                 tooltip="关闭＝只放大不重绘，不需要模型和 CLIP，重绘参数也不显示；"
                                         "打开＝按下面的重绘强度逐段重新采样"),
                io.Float.Input("精修强度", display_name="重绘强度", default=0.20, min=0.1, max=1.0, step=0.1,
                               display_mode=io.NumberDisplay.slider,
                               tooltip="最低 0.1；一点都不重绘请关「重绘开关」（关掉时送给后端的强度恒为 0）。强度大于 0 需要对应H3模型与CLIP，1可能大幅改画面"),
                io.Int.Input("精修步数", display_name="重绘步数", default=20, min=2, max=50, step=1,
                             display_mode=io.NumberDisplay.slider,
                             tooltip="越大越细、耗时越长；两阶段采样至少要 2 步，50 步以上等于重生成而不是重绘"),
                io.Int.Input("精修种子", display_name="重绘种子", default=0, min=0, max=2**64 - 1, step=1),
                io.Combo.Input("采样器", options=list(KSampler.SAMPLERS), default="res_multistep"),
                io.Combo.Input("调度器", options=list(KSampler.SCHEDULERS), default="simple"),
                io.Int.Input("缓存失效版本", default=0, min=0, max=999999, step=1,
                             tooltip="原位更换模型权重后+1；只影响独立后处理缓存"),
            ],
            outputs=[io.Image.Output("图像"), io.Audio.Output("音频"), io.Float.Output("帧率"),
                     io.Int.Output("帧数"), io.String.Output("报告")],
            hidden=[io.Hidden.unique_id, io.Hidden.prompt],
        )

    @classmethod
    def fingerprint_inputs(cls, 放大方式="H3潜空间", 放大倍率=2.0, H3放大权重="未选择", 初采产物=None, **kwargs):
        if 放大方式 != "H3潜空间" or 放大倍率 == 1:
            return None
        if "." in __package__:
            from ..执行.H3潜空间放大 import 预检H3放大权重
            from ..执行.视频放大 import 计算目标尺寸
        else:
            from 执行.H3潜空间放大 import 预检H3放大权重
            from 执行.视频放大 import 计算目标尺寸
        try:
            if isinstance(初采产物, dict) and 初采产物.get("type") == "LVP_FIRST_PASS":
                source = 初采产物["segments"][0]
                size = source["width"], source["height"]
                if 计算目标尺寸(*size, 放大倍率) == size:
                    return None
            elif 放大倍率 < 1.5:
                # 宿主指纹阶段不给连线值；小倍率是否跨32网格须在execute确认，不能猜源尺寸。
                return float("nan")
            return 预检H3放大权重(H3放大权重)["digest"]
        except (OSError, ValueError):
            return float("nan")

    @classmethod
    def execute(cls, 初采产物, 视频VAE, fl2va模型=None, ref2va模型=None, CLIP编码器=None,
                音频VAE=None, 像素放大模型="未选择", 精修强度=0.20, 精修步数=20, 精修种子=0,
                采样器="res_multistep", 调度器="simple", 放大方式="H3潜空间", 放大倍率=2.0,
                H3放大权重="未选择", 缓存失效版本=0, 重绘开关=False):
        if (type(初采产物) is not dict or type(初采产物.get("version")) is not int
                or 初采产物["version"] != 1):
            raise ValueError("未知初采产物类型或版本")
        node_id = display_id = getattr(cls.hidden, "unique_id", None)
        内存直连 = 初采产物.get("type") == "LVP_FIRST_PASS"
        if 内存直连:
            if "." in __package__:
                from ..执行.后处理核心 import 执行后处理 as run
            else:
                from 执行.后处理核心 import 执行后处理 as run
        elif 初采产物.get("type") == "LVP_FIRST_PASS_DISK":
            if "." in __package__:
                from ..执行.初采产物 import 校验磁盘初采引用
                from ..执行.跨任务清理 import 取得协调器
                from ..执行.后处理核心 import 执行磁盘后处理 as run
            else:
                from 执行.初采产物 import 校验磁盘初采引用
                from 执行.跨任务清理 import 取得协调器
                from 执行.后处理核心 import 执行磁盘后处理 as run
            校验磁盘初采引用(初采产物)
            display_id = 取得协调器().取磁盘执行上下文(初采产物)["cache_node_id"]
        else:
            raise ValueError("未知初采产物类型或版本")
        run_id, seq = uuid.uuid4().hex, 0

        def progress(value, total):
            nonlocal seq
            seq += 1
            _广播进度(display_id, run_id, seq, value, total)

        models = {"fl2va_model": fl2va模型, "ref2va_model": ref2va模型, "clip": CLIP编码器,
                  "vae": 视频VAE, "audio_vae": 音频VAE}
        # 被 重绘开关 隐藏的重绘组件仍照常进 prompt：开关是唯一真源，关掉就按强度 0 走免采样的只放大通道。
        params = {"精修强度": 精修强度 if 重绘开关 else 0, "精修步数": 精修步数, "精修种子": 精修种子,
                  "采样器": 采样器, "调度器": 调度器, "缓存失效版本": 缓存失效版本}
        像素 = None
        if 放大方式 == "像素模型":     # 同理：只有当前档位点亮的下拉才被读，未选中那档的残值不参与
            if "." in __package__:
                from ..执行.像素放大模型 import 加载像素放大模型
            else:
                from 执行.像素放大模型 import 加载像素放大模型
            像素 = 加载像素放大模型(像素放大模型)
        upscale = {"放大方式": 放大方式, "放大倍率": 放大倍率, "H3放大权重": H3放大权重,
                   "像素放大模型": 像素}
        if 内存直连:
            images, audio, report = run(初采产物, models, params, upscale, node_id, 进度回调=progress)
        else:
            images, audio, report = run(初采产物, models, params, upscale, 进度回调=progress)
        if "." in __package__:
            from ..制作.结果接收 import 交付生成结果
        else:
            from 制作.结果接收 import 交付生成结果
        ui_data = 交付生成结果(images, audio, float(初采产物["output_fps"]), 初采产物, cls.hidden)
        return io.NodeOutput(images, audio, float(初采产物["output_fps"]), int(初采产物["frame_count"]), report, ui=ui_data)


# 说明与别名放在文件末尾的模块常量里：schema 段内的连线口声明与磁盘引用校验那两行被多份文档
# 按 `文件:行号` 引用，说明若在 define_schema 里占行就会整体搬移这些锚点。
_别名 = ["精修与放大", "精修", "重绘", "放大", "upscale", "refine"]
_说明 = (
    "【作用】把初采结果独立地再处理一遍：先按原尺寸逐段重绘，再整体放大，一次输出成片。"
    "不改初采节点的连线与段缓存，音轨和帧数保持原样，结果也不回写初采。\n"
    "【用法】不接交接时，把「长视频规划师」的初采产物直接连进来（内存直连）；接了「初采交接与清理」时，"
    "把它的输出连进来——二采阶段会由协调器换成逐段读盘，本节点按收到的数据类型自动分派。默认只做放大："
    "选好放大方式和权重下拉，补齐视频 VAE，正常 Queue 即可。要重绘就打开「重绘开关」，再补齐模型与 CLIP。\n"
    "【参数】\n"
    "- 初采产物：必填连线。内存包走内存直连；磁盘引用逐段从盘读取，进度与缓存归属沿用交接时的节点号。\n"
    "- 放大方式：默认 H3潜空间。H3潜空间（需 H3 放大权重）／像素模型（需像素放大模型）／Lanczos（免模型）。"
    "选中哪一档，节点上才显示对应的权重下拉；两档都需要模型时才有额外显存开销。\n"
    "- 放大倍率：滑块 1～4（步进 0.25），默认 2.0；1.0 等于不放大，这一档不读放大权重。目标尺寸按 32 像素网格向上取整，小画布取整后可能仍是原尺寸。\n"
    "- H3放大权重：只在「H3潜空间」下生效，下拉只列 latent_upscale_models 目录里符合 H3 24 通道 3D 架构的 .safetensors（同目录里别家的放大模型不适用于本节点，故不显示）；「未选择」表示不用。\n"
    "- 像素放大模型：只在「像素模型」下生效，下拉列 models/upscale_models/ 里的 .pth/.ckpt/.safetensors，"
    "与官方「Load Upscale Model」读同一目录、同一套模型，不用再摆一个加载器节点。\n"
    "- 重绘开关：默认关闭＝只放大不重绘，不需要模型和 CLIP，下面的重绘参数也不显示；关掉时送给后端的强度恒为 0。\n"
    "- 重绘强度：滑块 0.1～1（步进 0.1），默认 0.20，滑不到 0——一点都不重绘请用「重绘开关」。数值越大改动越明显，1 可能大幅改变画面内容。\n"
    "- 重绘步数：滑块 2～50，默认 20，越大越细、耗时越长；50 步以上等于重新生成而不是重绘。\n"
    "- 重绘种子：默认 0，逐段派生基准种子，换它等于换一批结果。\n"
    "- 采样器／调度器：默认 res_multistep／simple，与初采用同一套设置最稳。\n"
    "- fl2va模型／ref2va模型：首尾帧（FL2VA）与参考生视频（Ref2VA）两套模型，重绘时按每段的生成方式各取所需，用到哪个接哪个。\n"
    "- CLIP编码器：重绘（开关打开且强度大于 0）必需的文本编码器，要与所用模型配套。\n"
    "- 视频VAE：唯一必填连线，负责视频潜空间与像素的往返。\n"
    "- 音频VAE：仅当带音频的参考生视频段在初采时用音频 VAE 编码过才需要。\n"
    "- 缓存失效版本：默认 0；原位换过模型权重或想整体作废重算时 +1，只影响本节点的后处理缓存，不动段缓存。\n"
    "【注意】重绘与放大都要重新采样和编解码，显存与耗时随成片规模上升；报告里的预算是跨阶段保守相加，"
    "不代表精确峰值，也不保证不溢出，建议先单段试跑。命中缓存的段不会重算，后处理缓存不在工具条"
    "「清空段缓存」按钮的范围内——要重算请增加缓存失效版本，或按报错点名的文件路径手动处理。"
)
