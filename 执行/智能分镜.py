# -*- coding: utf-8 -*-
"""智能分镜（可选）：PySceneDetect 检测源视频镜头切点 → 时间轴段。缺依赖时优雅降级。"""


def 依赖可用() -> bool:
    try:
        import scenedetect  # noqa: F401
        return True
    except Exception:
        return False


def 秒区间转段(区间列表, 任务: str = "v2v", 视频槽: int = 1) -> list:
    """把 [(起秒, 止秒), ...] 转为时间轴段 dict 列表；源段绑定 <Video 视频槽>。"""
    段 = []
    for i, (起, 止) in enumerate(区间列表):
        段.append({
            "index": i,
            "task": 任务,
            "prompt": "",
            "start": float(起),
            "end": float(止),
            "run": True,
            "refs": {"视频": [f"<Video {视频槽}>"]},
        })
    return 段


def 检测分镜(视频路径: str, 阈值: float = 27.0) -> list:
    """返回 [(起秒, 止秒), ...]；未装依赖时抛 RuntimeError 提示安装。GPU/IO 集成验证。"""
    if not 依赖可用():
        raise RuntimeError("智能分镜需安装依赖：pip install scenedetect[opencv]")
    from scenedetect import detect, ContentDetector
    场景 = detect(视频路径, ContentDetector(threshold=阈值))
    return [(s.get_seconds(), e.get_seconds()) for s, e in 场景]
