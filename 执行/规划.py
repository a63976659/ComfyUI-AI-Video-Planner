# -*- coding: utf-8 -*-
"""纯逻辑：把长视频规划师时间轴 JSON 解析为不可变 Plan（浅不可变）。不依赖 ComfyUI。"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

默认任务 = "t2v"
默认段秒 = 5.0


@dataclass(frozen=True)
class SegmentPlan:
    """单段执行计划。frozen=True 保证字段绑定不可改；refs 内容仍可改（浅不可变）；
    因含 dict 字段整体不可哈希。Task 6 段缓存指纹请用
    json.dumps(refs, ensure_ascii=False, sort_keys=True) 而非 hash(seg)。
    """

    index: int
    task: str
    prompt: str
    refs: Dict[str, Any] = field(default_factory=dict)
    start: float = 0.0
    end: float = 默认段秒
    run: bool = True


@dataclass(frozen=True)
class DirectorPlan:
    segments: Tuple[SegmentPlan, ...] = ()

    @property
    def 运行段(self) -> List[SegmentPlan]:
        return [s for s in self.segments if s.run]


def _解析运行值(v) -> bool:
    """run 字段：None 视为未设置=参与；bool 原样；数值 0=不参；字符串识别 false/no/off/空串为不参。"""
    if v is None:
        return True
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(v)


def 解析时间轴(raw: "str | None") -> DirectorPlan:
    if raw is None:
        return DirectorPlan(segments=())
    if not isinstance(raw, str):
        raise ValueError(f"时间轴数据必须是字符串: {type(raw).__name__}")
    if not raw.strip():
        return DirectorPlan(segments=())
    try:
        data = json.loads(raw)
    except Exception as e:
        raise ValueError(f"时间轴数据非法 JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"时间轴顶层必须是对象: {type(data).__name__}")
    segs_raw = data.get("segments")
    if segs_raw is None:
        segs_raw = []
    if not isinstance(segs_raw, list):
        raise ValueError("时间轴 segments 必须是数组")
    segs = []
    for i, s in enumerate(segs_raw):
        if not isinstance(s, dict):
            raise ValueError(f"第 {i} 段必须是对象")
        try:
            start = float(s.get("start", 0.0) or 0.0)
            end = float(s.get("end", 0.0) or 0.0)
        except (TypeError, ValueError) as e:
            raise ValueError(f"第 {i} 段 start/end 必须是数字: {e}") from e
        if end <= start:
            end = start + 默认段秒
        try:
            refs = dict(s.get("refs") or {})
        except (TypeError, ValueError) as e:
            raise ValueError(f"第 {i} 段 refs 必须是对象: {e}") from e
        segs.append(SegmentPlan(
            index=i,
            task=str(s.get("task") or 默认任务),
            prompt=str(s.get("prompt") or ""),
            refs=refs,
            start=start, end=end,
            run=_解析运行值(s.get("run")),
        ))
    return DirectorPlan(segments=tuple(segs))
