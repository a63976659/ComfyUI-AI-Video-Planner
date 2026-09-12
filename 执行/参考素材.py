# -*- coding: utf-8 -*-
"""纯逻辑：参考素材槽位与 <Picture N>/<Video K>/<Audio J> 标签解析。

上限真源（前端 Task 16/17 JS 若变化需同步本文件）：图片 9、音频 3、视频 3。
Autogrow 键 0-based（ref_image_0..8）；prompt 序号 1-based（<Picture 1..9>）。

v1 偏移规则：<Video k> 参考视频自带音轨不占用 <Audio> 序号空间（本模块
组装参考入参时不传 ref_video_audios 音轨）。**v2 若启用参考视频音轨**：官方
`nodes_minimax_h3.py:333` 会让音轨先占位再排独立音频，届时 提取标签 需要按
「视频数 + 独立音频数」的联合序号空间重写映射，否则 <Audio 1> 集体错位一位。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

上限 = {"图片": 9, "音频": 3, "视频": 3}
_标签到槽 = {"Picture": "图片", "Audio": "音频", "Video": "视频"}
_标签re = re.compile(r"<(Picture|Audio|Video)\s*(\d+)>", re.IGNORECASE)


def _规范列表(类, 值):
    """单文件名字符串 → 包成一项；数组 → 逐项校验为字符串；其余一律 ValueError。"""
    if 值 is None:
        return []
    if isinstance(值, str):
        值 = [值]
    elif isinstance(值, dict):
        raise ValueError(f"参考槽位「{类}」必须是文件名数组或文件名字符串，收到对象")
    elif not isinstance(值, (list, tuple)):
        raise ValueError(f"参考槽位「{类}」必须是数组，收到 {type(值).__name__}")
    项 = []
    for x in 值:
        if x is None:
            continue
        if not isinstance(x, str):
            raise ValueError(f"参考槽位「{类}」的元素必须是文件名字符串，收到 {type(x).__name__}")
        x = x.strip()
        if x:
            项.append(x)
    return 项


def 解析槽位(refs: "Optional[Dict[str, Any]]") -> "Dict[str, List[str]]":
    """把 refs 归一为「图片/音频/视频」三键固定、每键按 上限 截断的文件名列表。

    输出顺序 = Autogrow 序号契约：官方 MiniMax H3 按 .values() 插入顺序赋
    `<Picture N>`，故 list 顺序即 N-1；调用方不得对结果再排序/去重/重排。
    截断会静默丢弃超限项，若 prompt 引用被丢弃项，需用 校验标签 交叉检查。
    未知键（如 首帧/尾帧/源视频）静默忽略——它们不进入 Autogrow。
    """
    if refs is not None and not isinstance(refs, dict):
        raise ValueError(
            f"参考素材必须是已解析的对象，收到 {type(refs).__name__}（需先 json.loads）"
        )
    src = refs or {}
    return {类: _规范列表(类, src.get(类))[: 上限[类]] for 类 in 上限}


def 提取标签(prompt: "Optional[str]") -> "List[Tuple[str, int]]":
    """返回 [(槽位类, 1-based 编号), ...]，按出现顺序，不去重。

    编号 N 对应 Autogrow 第 N-1 项（官方序号 1-based / 键 0-based）。
    N<1 或 N>对应槽位上限 抛 ValueError；prompt 非字符串（None 除外）也抛。
    与 Task 16 前端 JS 正则 `/<(Picture|Audio|Video)\\s*(\\d+)>/gi` 字面同构。
    """
    if prompt is None:
        return []
    if not isinstance(prompt, str):
        raise ValueError(f"提示词必须是字符串，收到 {type(prompt).__name__}")
    res = []
    for m in _标签re.finditer(prompt):
        类 = _标签到槽[m.group(1).capitalize()]
        n = int(m.group(2))
        if not 1 <= n <= 上限[类]:
            raise ValueError(
                f"标签 <{m.group(1)} {n}> 编号非法：{类}槽位仅 1-{上限[类]}"
            )
        res.append((类, n))
    return res


def 校验标签(prompt: "Optional[str]", 槽位: "Dict[str, List[str]]") -> None:
    """交叉检查：prompt 中每个 <Picture N> 等标签必须指向 解析槽位 实际留存的条目。

    场景：refs 有 12 张图 → 解析槽位 截断到 9；prompt 若写 `<Picture 10>` 会命中
    一个不存在的槽位；官方 tokenizer 会静默忽略 → 产物与预期不符。此函数把该静默
    失败前移为显式 ValueError。
    Task 8/9 在把 refs 送进 Autogrow 之前调用本函数。
    """
    for 类, n in 提取标签(prompt):
        实 = len(槽位.get(类, []))
        if n > 实:
            raise ValueError(
                f"提示词引用第 {n} 个{类}，但该段只有 {实} 个"
                f"（超出上限 {上限[类]} 的部分已截断）"
            )
