# -*- coding: utf-8 -*-
"""条件组装：把统一任务枚举映射到官方 MiniMax H3 节点与其入参约定。纯逻辑可测。

官方权威来源 comfy_extras/nodes_minimax_h3.py：节点类名与 schema.node_id 一致
（MiniMaxH3ImageToVideo / MiniMaxH3ReferenceToVideo），execute 的参考入参名
ref_images / ref_videos / ref_video_audios / ref_audios 与下方键名逐字对应。
"""

图生视频任务 = {"t2v", "i2v", "fl2v"}
参考生视频任务 = {"r2v", "v2v", "rv2v"}

_管线表 = {
    **{t: "MiniMaxH3ImageToVideo" for t in 图生视频任务},
    **{t: "MiniMaxH3ReferenceToVideo" for t in 参考生视频任务},
}


def _规范任务(task) -> str:
    """将入参 task 规范成小写 key；非字符串包为 ValueError，保证 Task 11 UI
    边界只 catch (ValueError, RuntimeError) 就能接住（避免 `task or ""` 对非字符串
    真值（如 123）逃逸 AttributeError。与项目 ValueError-only 契约一致。"""
    if not isinstance(task, str):
        raise ValueError(f"任务类型必须是字符串，收到 {type(task).__name__}：{task!r}")
    return task.strip().lower()


def 选管线(task: str) -> str:
    t = _规范任务(task)
    if t not in _管线表:
        raise ValueError(f"未知任务类型「{t}」，合法值：{sorted(_管线表)}")
    return _管线表[t]


def 需要首帧(task: str) -> bool:
    return _规范任务(task) in {"i2v", "fl2v"}


def 需要尾帧(task: str) -> bool:
    return _规范任务(task) == "fl2v"


def 组装参考入参(图片列表=None, 视频列表=None, 视频音频列表=None, 音频列表=None) -> dict:
    """把「已加载为张量」的参考素材组装成官方 MiniMaxH3ReferenceToVideo 的 Autogrow 字典入参。
    键名严格遵循官方前缀（0-based）：ref_image_ / ref_video_ / ref_video_audio_ / ref_audio_；
    视频音频按序号与其视频配对（ref_video_audio_N ↔ ref_video_N）。纯逻辑可测。
    顺序契约：官方按字典**插入顺序**（不看键名里的 index 数字）赋 <Picture i>/<Video k>/<Audio j>
    序号，故此处 enumerate 产出的插入顺序 = 入参列表顺序 = 提示词标签顺序（与 Task 3「解析槽位」、
    Task 9 调用侧一致）。
    """
    kwargs = {}
    if 图片列表:
        kwargs["ref_images"] = {f"ref_image_{i}": t for i, t in enumerate(图片列表) if t is not None}
    if 视频列表:
        kwargs["ref_videos"] = {f"ref_video_{i}": t for i, t in enumerate(视频列表) if t is not None}
    if 视频音频列表:
        kwargs["ref_video_audios"] = {f"ref_video_audio_{i}": t for i, t in enumerate(视频音频列表) if t is not None}
    if 音频列表:
        kwargs["ref_audios"] = {f"ref_audio_{i}": t for i, t in enumerate(音频列表) if t is not None}
    return kwargs
