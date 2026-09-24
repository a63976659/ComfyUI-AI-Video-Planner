# -*- coding: utf-8 -*-
"""长视频规划师 主节点（V3 io.ComfyNode）：widgets 为唯一真源，驱动多段生成。"""
from comfy_api.latest import io, ComfyAPISync

from .节点公用 import (
    任务选项,
    解析任务,
    分辨率选项,
    默认分辨率,
    默认百万像素,
    分辨率到宽高,
    采样器选项,
    调度器选项,
)

# widget 边界与 节点公用/采样与解码 单一真源对齐（Task 4 §接口约束：禁散落魔法）。
_帧率下限 = 1.0
_帧率上限 = 120.0
_百万像素下限 = 0.1                  # 与 ResolutionSelector/_megapixels_input 同源
_百万像素上限 = 4.0                   # H3 上限收紧为 4（原 16，不再与 ResolutionSelector 同源）
_步数下限 = 1                        # 与 KSampler steps min 同源
_步数上限 = 10000

# 段级进度的**自有** websocket 事件名（前端 网页资源/状态栏入口.js 按字面量镜像，同步锁见
# 测试_常量同步.py 的 test_段级进度事件名_前后端同步）。为何不能复用宿主事件，见 _广播进度 docstring。
_进度事件名 = "长视频规划师_进度"


def _广播进度(node_id, 当前, 总数, 事件信息=None):
    """把段级进度推到自有 websocket 通道，供状态栏面板显示「生成中 3/7（段）」。

    ⚠️ 为何必须自有通道（而非复用宿主的进度事件）：
      • `api.execution.set_progress` 只写宿主的 progress registry（`comfy_api/latest/__init__.py`
        的 `Execution.set_progress` 仅调 `get_progress_state().update_progress(...)`），它**不发**
        legacy `"progress"` websocket 事件 ⇒ 只听 `"progress"` 的前端**从来收不到**我方段级进度。
      • 发 legacy `"progress"` 的是宿主 `main.py` 里 `hijack_progress` 装的全局 hook，而 KSampler
        的内部去噪步进正是走那条路；它缺省从 `get_executing_context()` 取 node_id ＝**本长视频规划师节点**，
        与我方 `set_progress` 写的是同一 node_id 的同一条 registry entry。改听合并态 `"progress_state"`
        也一样分不开（它按 node_id 键，两者同键）。
      ⇒ 按 `node` 过滤只能滤掉**别的**节点，滤不掉同节点的 KSampler 步进；唯一可靠区分是自有事件名。

    3.1(98)：事件信息 可选。传入时（来自 执行时间轴 的 `_发进度`）与基础 payload 合入，
    前端可用 run/stage/segment/stage_done/stage_total 做两阶段可视化与 stale 丢弃；不传（向后
    兼容的 2 形参 调用）仅发 {node, value, max}，旧前端行为不变。

    best-effort：拿不到 PromptServer（无服务器上下文/单测）或 send_sync 报错都**吞掉**——
    进度上报失败绝不能把已跑了数小时的生成轮次拖成报错。try 体只含宿主 API 调用、无我方
    逻辑，故宽 except 不会把我方 bug 洗成静默（同 段缓存.读缓存 第 2 层的口径）。"""
    try:
        from server import PromptServer
        srv = PromptServer.instance
        数据 = {"node": node_id, "value": 当前, "max": 总数}
        if 事件信息:
            数据.update(事件信息)
        srv.send_sync(_进度事件名, 数据, srv.client_id)
    except Exception:  # noqa: BLE001 - try 体仅第三方调用（见 docstring），进度失败不得影响生成
        pass


class 长视频规划师(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="长视频规划师",
            display_name="长视频规划师",
            category="长视频规划师",
            description="多段时间轴 + 底部状态栏驱动官方 MiniMax H3 生成音视频",
            inputs=[
                # 双模型输入（选填）：节点按段任务类型自动匹配——fl2va模型 服务图生视频管线
                #   (t2v/i2v/fl2v)，ref2va模型 服务参考生视频管线 (r2v/v2v/rv2v)。二者 optional：
                #   执行核心只校验「本时间轴实际用到的任务」对应模型已连接（只跑 t2v 可不连 ref2va模型）。
                io.Model.Input("fl2va模型", optional=True,
                               tooltip="图生视频管线(t2v/i2v/fl2v)所用模型；时间轴含这些任务时须连接"),
                io.Model.Input("ref2va模型", optional=True,
                               tooltip="参考生视频管线(r2v/v2v/rv2v)所用模型；时间轴含这些任务时须连接"),
                io.Clip.Input("CLIP编码器", tooltip="需连接 type=minimax 的 CLIP（Qwen3-VL）"),
                io.Vae.Input("视频VAE"),
                io.Vae.Input("音频VAE"),
                io.Combo.Input("任务类型", options=任务选项, default=任务选项[0]),
                io.String.Input("全局提示词", multiline=True, default="",
                                tooltip="逐段 prompt 的全局前缀（由状态栏 画风+预设正文 拼接而成）",
                                extra_dict={"hidden": True}),   # 节点上不显示，经状态栏 画风/预设 编辑
                io.String.Input("时间轴数据", multiline=True, default='{"segments":[]}'),
                io.String.Input("参考素材", multiline=True,
                                default='{"图片":[],"音频":[],"视频":[]}'),
                io.String.Input("运行选择", multiline=True, default="{}"),
                io.Float.Input("帧率", default=24.0, min=_帧率下限, max=_帧率上限, step=1.0),
                io.Combo.Input("输出分辨率", options=分辨率选项, default=默认分辨率,
                               tooltip="宽高比；与百万像素共同决定画布（替代原 宽/高 widget）",
                               extra_dict={"hidden": True}),   # 节点上不显示，经状态栏 @ 行编辑
                io.Float.Input("百万像素", default=默认百万像素, min=_百万像素下限,
                               max=_百万像素上限, step=0.1,
                               tooltip="总像素预算，1.0≈1024x1024；与输出分辨率共同决定画布",
                               extra_dict={"hidden": True}),   # 节点上不显示，经状态栏 @ 行编辑
                io.Int.Input("步数", default=20, min=_步数下限, max=_步数上限, step=1,
                             tooltip="KSampler 去噪步数"),   # step 必填且=1（与 KSampler steps 同源）：io.Int 缺省 step=None 会被 prune_dict 剔除，前端数值 widget 拖拽/滚轮增量失效 → 步数无法调整
                io.Combo.Input("采样器", options=采样器选项, default="res_multistep",
                               tooltip="KSampler 采样算法"),
                io.Combo.Input("调度器", options=调度器选项, default="simple",
                               tooltip="KSampler 噪声调度"),
                # 参考共用 置于 inputs 末尾（向后兼容铁律）：ComfyUI 载入旧存档时 base litegraph
                # 按位置回填 widgets_values，新 widget 插中间会令其后所有 widget 错位一位；追加到
                # 末尾则旧存档前 11 个 widget 正确对齐、参考共用 拿默认 False。且与 execute 签名
                # （参考共用 已是最后一个参数）顺序一致。
                io.Boolean.Input("参考共用", default=False,
                                 tooltip="参考生视频(r2v/v2v/rv2v)下开启：所有段统一使用开启段的参考素材（覆盖其他段自有素材），只需编辑每段提示词；关闭时每段使用各自的素材。现已改为段级控制（存储在各段 refs.共用），此全局 widget 仅作向后兼容",
                                 extra_dict={"hidden": True}),   # 节点上不显示，经状态栏参考区右侧开关编辑
                # 尾帧锚定 同样置于 inputs 末尾（向后兼容铁律，见上 参考共用 注释）：旧存档 widgets_values
                #   不含本 widget → 载入时拿默认 False（尾帧锚定关闭）。与 execute 签名末位参数一致。
                io.Boolean.Input("尾帧锚定", default=False,
                                 tooltip="开启：把上一段的尾帧画面与约 1 秒尾音频作为续拍条件锚入下一段（等效官方 MiniMaxH3AddGuide，但直接传 latent、不经解码再编码，故更快也更保真），接缝零重叠硬切、只对续拍段开头做低频色光衔接（不混叠两段画面）；关闭：各段独立生成、接缝硬切、不做任何过渡处理。默认关闭",
                                 extra_dict={"hidden": True}),   # 节点上不显示，经时间轴工具条「尾帧锚定」开关编辑
                # 剪辑草稿 同样置于 inputs 末尾（向后兼容铁律，见 参考共用 注释）：旧存档不含本 widget
                #   → 载入时拿默认空草稿。
                # 🔒 fix18a3：剪辑草稿 真源已迁至前端 node.properties.剪辑草稿——properties 随工作流序列化保存，
                #   但**不进入 prompt / 执行缓存签名**，故编辑草稿不会作废节点缓存、不触发重执行。本 widget 退化为
                #   **恒默认值的占位/迁移载体**：保留它一是避免删 input 致旧存档 widgets_values 位置错位，二是供
                #   状态栏入口.js onConfigure 把旧工作流存于 widget 的草稿迁入 properties 后重置为默认。widget 值恒默认、
                #   永不承载数据 ⇒ 对执行缓存签名无影响。生成链路只消费 时间轴数据，execute 接收本参数但有意忽略。
                # ⚠️ 不加 extra_dict={"hidden":True}：剪辑草稿 与 时间轴数据 同属「multiline JSON、由 DOM
                #   组件接管编辑」的 widget，隐藏走 时间轴面板.js 幽灵widget 名单（步骤5）而非 extra_dict。
                #   若误加 extra_dict hidden，会被 测试_常量同步.py::test_隐藏widget名_前后端同步 计入后端隐藏
                #   集合（变 6 项），而前端 状态栏入口.js 隐藏widget名 仍 5 项 → 该镜像锁失败。
                io.String.Input("剪辑草稿", multiline=True, default='{"brief":{},"segments":[]}'),
                # 缓存失效版本 同样置于 inputs 末尾（向后兼容铁律，见 参考共用 注释）：旧存档不含本 widget
                #   → 载入时拿默认 0（不因子把既有段缓存误作废）。§B-2：模/CLIP/VAE 只在上游 loader 携带
                #   内容绑定、可复现标识（约定属性 lvp_模型身份，由 执行核心.提取模型链身份 自动纳入指纹）时才会
                #   自动感知换 ckpt；ComfyUI 自带 loader 不提供此类标识（也不每段扫权重）→ 换型后把本值 +1
                #   即可整体作废段缓存重采样（可靠兼底）。普通可见数值 widget（非 hidden），无需前端镜像同步。
                io.Int.Input("缓存失效版本", default=0, min=0, max=999999, step=1,
                             tooltip="换模型/权重后手动 +1 以整体作废段缓存重采样（自动失效需 loader 携带可复现模型标识）；默认 0"),
            ],
            outputs=[
                io.Image.Output("图像"),
                io.Audio.Output("音频"),
                io.Float.Output("帧率"),
                io.Int.Output("帧数"),
                io.String.Output("报告"),
            ],
            hidden=[io.Hidden.unique_id],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        """§B-4：V3 IS_CHANGED——把「时间轴引用素材的文件内容」补进宿主缓存签名。

        为何需要：同名换内容（绕过上传直接换盘上文件）时，时间轴数据/参考素材 等 widget 值
        不变、也无上游模型链变化 → 宿主按输入签名判“未变”而**跳过 execute**，我方磁盘段缓存
        根本没机会被查 → 陈旧产物。本指纹仅**叠加**素材内容这一维（缓存签名仍含全部 widget 值，
        见 caching.py:117），内容一变即重跑；模型/CLIP/VAE 靠连线依赖失效，无需入本指纹。
        不覆写 validate_inputs（I1）：本方法只影响重跑判定，不关原生入参校验。
        异常不外抛：真发生异常时交由宿主按 NaN 处理＝保守重跑（宁可重算也不给陈旧产物）。"""
        try:                                        # ComfyUI 运行时（包形式加载）
            from ..执行.执行核心 import _外部依赖指纹
            from ..后端路由.媒体路由 import 媒体根 as 取媒体根
        except ImportError:                         # pytest（插件根在 sys.path，`..` 越界）I4
            from 执行.执行核心 import _外部依赖指纹
            from 后端路由.媒体路由 import 媒体根 as 取媒体根
        return _外部依赖指纹(
            kwargs.get("时间轴数据") or '{"segments":[]}',
            取媒体根(),
            kwargs.get("缓存失效版本", 0))

    @classmethod
    def execute(cls, *, fl2va模型=None, ref2va模型=None, CLIP编码器, 视频VAE, 音频VAE,
                任务类型, 全局提示词, 时间轴数据, 参考素材, 运行选择, 帧率,
                输出分辨率, 百万像素, 步数, 采样器, 调度器,
                参考共用=False, 尾帧锚定=False, 剪辑草稿='{"brief":{},"segments":[]}',
                缓存失效版本=0):
        # 剪辑草稿：widget 恒为默认值占位（真源已迁前端 node.properties，详 schema 注释）；生成链路只消费 时间轴数据 ⇒ 有意忽略。
        try:                                        # ComfyUI 运行时（以包形式加载）
            from ..执行.执行核心 import 执行时间轴
            from ..后端路由.媒体路由 import 媒体根
        except ImportError:                         # pytest（插件根在 sys.path，`..` 越界）I4
            from 执行.执行核心 import 执行时间轴
            from 后端路由.媒体路由 import 媒体根

        api = ComfyAPISync()
        # V3 运行时 hidden 由 io  machinery 注到类型克隆上（_clone_with_hidden）；直接以类调用
        # （静态单测 I2 契约锁）时 cls.hidden 为 None，降级为 node_id=None，不阻断报错路径。
        node_id = getattr(cls.hidden, "unique_id", None)
        # 全局 widgets → 全局参数：执行核心逐段合并（运行选择/全局提示词/参考素材/默认任务）
        # 帧数按 (seg.end-seg.start)*基座 FPS=24 逐段算（Task 9 §约束 1：与用户「帧率」widget
        # 解耦）；无全局帧数 widget——每段帧数只由时间轴跨度决定。
        宽, 高 = 分辨率到宽高(输出分辨率, 百万像素)
        全局参数 = {
            "帧率": 帧率, "宽": 宽, "高": 高,
            "步数": 步数, "采样器": 采样器, "调度器": 调度器,
            "默认任务": 解析任务(任务类型), "全局提示词": 全局提示词,
            "参考素材": 参考素材, "运行选择": 运行选择,
            "参考共用": bool(参考共用),
            # §B-2：换 ckpt 无可证模型标识时的手动作废入口；int 归一防前端传字符串造成
            #   指纹类型敏感（json 区分 0 与 "0"）。执行核心 将其入采样参数（不入则无效果）。
            "缓存失效版本": int(缓存失效版本 or 0),
        }
        # 尾帧锚定开关 → 上下文帧数（段间锚定的总闸；接缝自 2026-09 起恒零重叠硬切）：
        #   执行核心以「上下文帧数>0」判定是否把上一段尾帧/尾音频 latent 锚入下一段
        #   （取尾帧_latent / _采样段 两处均以此为闸）。开启时**不传该键**，沿用执行核心的
        #   默认上下文帧数(22)；关闭时显式置 0 → 完全跳过锚定。拼接不再有接缝交叉淡化
        #   （_拼接重叠帧数=0），色光衔接只作用于真实续拍接缝（段间连续.匹配开头色光）。
        #   上下文帧数 已入段缓存指纹（执行核心 采样参数 与 指纹源），
        #   开关切换会自动作废受影响的旧采样缓存。
        if not 尾帧锚定:
            全局参数["上下文帧数"] = 0
        # 键名对齐执行核心：fl2va_model/ref2va_model＝两管线模型，vae＝视频 VAE，audio_vae＝音频 VAE
        #   （dict 键为内部 ASCII，与 socket 中文名解耦）。执行核心按段任务经 选模型槽 取 f"{槽}_model"，
        #   并在生成前按需校验「本时间轴用到的任务」对应模型已连接（缺则报明确错误）。
        模型输入 = {"fl2va_model": fl2va模型, "ref2va_model": ref2va模型,
                    "clip": CLIP编码器, "vae": 视频VAE, "audio_vae": 音频VAE}

        def 进度(当前, 总数, 事件信息=None):
            # V3 set_progress(value, max_value, node_id)；显式带 node_id，避免依赖执行上下文传播。
            # 它只更新宿主 progress registry（供宿主自己的进度条/合并态用），**不发** legacy "progress"
            # 事件 ⇒ 自家状态栏面板看不到；面板靠下一行的自有通道（缘由详 _广播进度 docstring）。
            # 3.1(98)：事件信息（run/stage/segment/...）仅走自有通道——宿主 set_progress 无 extra 接口。
            api.execution.set_progress(当前, 总数, node_id=node_id)
            _广播进度(node_id, 当前, 总数, 事件信息)

        images, audio, report = 执行时间轴(
            时间轴数据, 全局参数, 模型输入, node_id, 媒体根(), 进度回调=进度)

        # I2（Task 11 code review）：全段 skip+无缓存 时 执行核心 返回 images=None。V3 无输出
        #   optional 标记，None 会静默向下游传播 → 下游 SaveVideo 抛无法定位的 TypeError，
        #   帧数=0 看着像正常。此处显式转 ValueError（Task 11 UI 边界契约），让 ComfyUI
        #   红面板显示报告摘要。
        if images is None:
            raise ValueError(f"长视频规划师 无有效产物：{report or '所有段均未运行且无缓存'}")

        fps = float(帧率)
        # IMAGE 为 [T,H,W,C]，帧数在 dim0
        frame_count = int(images.shape[0])
        return io.NodeOutput(images, audio, fps, frame_count, report)
