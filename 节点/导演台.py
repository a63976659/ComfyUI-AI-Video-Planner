# -*- coding: utf-8 -*-
"""H3导演台 主节点（V3 io.ComfyNode）：widgets 为唯一真源，驱动多段生成。"""
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


class H3导演台(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3DYT_Director",
            display_name="H3导演台",
            category="H3导演台",
            description="多段时间轴 + 底部状态栏驱动官方 MiniMax H3 生成音视频",
            inputs=[
                io.Model.Input("模型"),
                io.Vae.Input("视频VAE"),
                io.Vae.Input("音频VAE"),
                io.Clip.Input("CLIP编码器", tooltip="需连接 type=minimax 的 CLIP（Qwen3-VL）"),
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
                io.Int.Input("步数", default=25, min=_步数下限, max=_步数上限, step=1,
                             tooltip="KSampler 去噪步数"),   # step 必填且=1（与 KSampler steps 同源）：io.Int 缺省 step=None 会被 prune_dict 剔除，前端数值 widget 拖拽/滚轮增量失效 → 步数无法调整
                io.Combo.Input("采样器", options=采样器选项, default="res_multistep",
                               tooltip="KSampler 采样算法"),
                io.Combo.Input("调度器", options=调度器选项, default="simple",
                               tooltip="KSampler 噪声调度"),
                io.String.Input("模型标识", default="",
                                tooltip="选填：本次所用 checkpoint 名，仅用于段缓存失效判定。换模型时改动它可让旧缓存作废重算；留空则退化为自动探测（ModelPatcher 通常不带 ckpt 名，多半探测不到，换模型可能命中旧缓存返回上个模型的旧画面）"),
                # 参考共用 置于 inputs 末尾（向后兼容铁律）：ComfyUI 载入旧存档时 base litegraph
                # 按位置回填 widgets_values，新 widget 插中间会令其后所有 widget 错位一位；追加到
                # 末尾则旧存档前 12 个 widget 正确对齐、参考共用 拿默认 False。且与 execute 签名
                # （参考共用 已是最后一个参数）顺序一致。
                io.Boolean.Input("参考共用", default=False,
                                 tooltip="参考生视频(r2v/v2v/rv2v)下开启：所有段统一使用「参考素材」全局池（覆盖段级 refs），只需编辑每段提示词；关闭时段级 refs 优先、全局兜底",
                                 extra_dict={"hidden": True}),   # 节点上不显示，经状态栏参考区右侧开关编辑
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
    def execute(cls, 模型, 视频VAE, 音频VAE, CLIP编码器, 任务类型, 全局提示词,
                时间轴数据, 参考素材, 运行选择, 帧率, 输出分辨率, 百万像素,
                步数, 采样器, 调度器, 模型标识="", 参考共用=False):
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
        }
        # 键名对齐执行核心：vae＝视频 VAE，audio_vae＝音频 VAE（dict 键为内部 ASCII，与 socket 中文名解耦）
        模型输入 = {"model": 模型, "clip": CLIP编码器,
                    "vae": 视频VAE, "audio_vae": 音频VAE}
        # 模型标识（ckpt 名）入段缓存指纹（⚠️#1 换 ckpt 失效类）：io.Model 传入的是内存
        #   ModelPatcher，通常不带 model_path/ckpt_name，执行核心._模型标识 自动探测多半落空
        #   → 换 ckpt 时指纹不变、命中旧缓存返回上个模型的旧画面。故由本 widget 显式提供。
        #   留空("")时 _模型标识 的 `if v:` 会跳过它、退化为原探测兜底，行为与未加此键一致。
        模型输入["模型标识"] = 模型标识

        def 进度(当前, 总数):
            # V3 set_progress(value, max_value, node_id)；显式带 node_id，避免依赖执行上下文传播。
            api.execution.set_progress(当前, 总数, node_id=node_id)

        images, audio, report = 执行时间轴(
            时间轴数据, 全局参数, 模型输入, node_id, 媒体根(), 进度回调=进度)

        # I2（Task 11 code review）：全段 skip+无缓存 时 执行核心 返回 images=None。V3 无输出
        #   optional 标记，None 会静默向下游传播 → 下游 SaveVideo 抛无法定位的 TypeError，
        #   帧数=0 看着像正常。此处显式转 ValueError（Task 11 UI 边界契约），让 ComfyUI
        #   红面板显示报告摘要。
        if images is None:
            raise ValueError(f"H3导演台 无有效产物：{report or '所有段均未运行且无缓存'}")

        fps = float(帧率)
        # IMAGE 为 [T,H,W,C]，帧数在 dim0
        frame_count = int(images.shape[0])
        return io.NodeOutput(images, audio, fps, frame_count, report)
