"""消费初采产物的独立精修与放大V3节点。"""
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
            from ..执行.H3潜空间放大 import 列H3放大权重
        else:
            from 执行.H3潜空间放大 import 列H3放大权重
        return io.Schema(
            node_id="精修与放大", display_name="精修与放大", category="长视频规划师",
            description="先原尺寸精修全部初采段，再放大；保留原音轨与帧数，不回写初采",
            inputs=[
                io.Custom("LVP_FIRST_PASS").Input("初采产物"),
                io.Model.Input("fl2va模型", optional=True),
                io.Model.Input("ref2va模型", optional=True),
                io.Clip.Input("CLIP编码器", optional=True),
                io.Vae.Input("视频VAE"),
                io.Vae.Input("音频VAE", optional=True),
                io.Custom("UPSCALE_MODEL").Input("像素放大模型", optional=True),
                io.Float.Input("精修强度", default=0.20, min=0.0, max=1.0, step=0.01,
                               tooltip="0只放大；大于0需要对应H3模型与CLIP，1可能大幅改画面"),
                io.Int.Input("精修步数", default=20, min=1, max=10000, step=1),
                io.Int.Input("精修种子", default=0, min=0, max=2**64 - 1, step=1),
                io.Combo.Input("采样器", options=list(KSampler.SAMPLERS), default="res_multistep"),
                io.Combo.Input("调度器", options=list(KSampler.SCHEDULERS), default="simple"),
                io.Combo.Input("放大方式", options=["Lanczos", "像素模型", "H3潜空间"], default="Lanczos"),
                io.Float.Input("放大倍率", default=2.0, min=1.0, max=4.0, step=0.25),
                io.Combo.Input("H3放大权重", options=列H3放大权重(), default="未选择"),
                io.Int.Input("缓存失效版本", default=0, min=0, max=999999, step=1,
                             tooltip="原位更换模型权重后+1；只影响独立后处理缓存"),
            ],
            outputs=[io.Image.Output("图像"), io.Audio.Output("音频"), io.Float.Output("帧率"),
                     io.Int.Output("帧数"), io.String.Output("报告")],
            hidden=[io.Hidden.unique_id],
        )

    @classmethod
    def fingerprint_inputs(cls, 放大方式="Lanczos", 放大倍率=2.0, H3放大权重="未选择", 初采产物=None, **kwargs):
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
                音频VAE=None, 像素放大模型=None, 精修强度=0.20, 精修步数=20, 精修种子=0,
                采样器="res_multistep", 调度器="simple", 放大方式="Lanczos", 放大倍率=2.0,
                H3放大权重="未选择", 缓存失效版本=0):
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
        params = {"精修强度": 精修强度, "精修步数": 精修步数, "精修种子": 精修种子,
                  "采样器": 采样器, "调度器": 调度器, "缓存失效版本": 缓存失效版本}
        upscale = {"放大方式": 放大方式, "放大倍率": 放大倍率, "H3放大权重": H3放大权重,
                   "像素放大模型": 像素放大模型}
        if 内存直连:
            images, audio, report = run(初采产物, models, params, upscale, node_id, 进度回调=progress)
        else:
            images, audio, report = run(初采产物, models, params, upscale, 进度回调=progress)
        return io.NodeOutput(images, audio, float(初采产物["output_fps"]), int(初采产物["frame_count"]), report)
