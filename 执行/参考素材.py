# -*- coding: utf-8 -*-
"""纯逻辑：参考素材槽位与 <Picture N>/<Video K>/<Audio J> 标签解析。

上限真源（前端 Task 16/17 JS 若变化需同步本文件）：图片 9、音频 3、视频 3。
Autogrow 键 0-based（ref_image_0..8）；prompt 序号 1-based（<Picture 1..9>）。

音频标签按官方顺序：有音轨的视频依次占位，再排独立音频；无音轨的视频不占位。
上传上限仍为各类 9/3/3，Audio 标签联合编号最多为 6。
"""
import re
import json
import os
from typing import Any, Dict, List, Optional, Tuple

上限 = {"图片": 9, "音频": 3, "视频": 3}
标签上限 = {**上限, "音频": 上限["视频"] + 上限["音频"]}
_标签到槽 = {"Picture": "图片", "Audio": "音频", "Video": "视频"}
_标签re = re.compile(r"<(Picture|Audio|Video)\s*(\d+)>", re.IGNORECASE)


def 视频音频模式(refs):
    模式 = (refs or {}).get("视频音频模式", "默认")
    if 模式 not in ("默认", "生成音频", "素材原声"):
        raise ValueError("视频音频模式须为默认、生成音频或素材原声")
    return 模式


def 禁用音轨提示词(prompt, 音轨数):
    """保留编辑器的素材编号，执行时移除禁用音轨标签并平移独立音频编号。"""
    def 替换(m):
        if m.group(1).lower() != "audio":
            return m.group(0)
        n = int(m.group(2))
        return "" if n <= 音轨数 else f"<Audio {n - 音轨数}>"
    return _标签re.sub(替换, prompt or "")


def 视频有音轨(路径):
    """只探测容器流，不解码画面；损坏容器不能当作无声视频处理。"""
    import av
    try:
        with av.open(路径) as container:
            return bool(container.streams.audio)
    except (av.FFmpegError, OSError) as exc:
        raise ValueError(f"无法读取参考视频音轨信息：{路径}：{exc}") from exc


def 参考标签槽位(槽位, 视频音轨):
    """视频音轨为与视频逐项配对的布尔列表；输出标签的文件映射。"""
    return {**槽位, "音频": [名 for 名, 有音 in zip(槽位["视频"], 视频音轨) if 有音]
            + list(槽位["音频"])}


def 探测参考音轨(槽位, 媒体根):
    # 改写可包含尚未上传的名称；不存在的文件不给音频标签，执行前由素材预检点名。
    return [os.path.isfile(p) and 视频有音轨(p) for p in
            (n if os.path.isabs(n) else os.path.join(媒体根, n) for n in 槽位["视频"])]


def 规范全局参考(value):
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except (ValueError, TypeError):
            value = {}
    return value if isinstance(value, dict) else {}


def 查找共用参考(refs组, 全局参数):
    """执行与改写共用的优先级：段级共用优先，其次全局共用。"""
    for refs in refs组:
        if isinstance(refs, dict) and refs.get("共用"):
            shared = {k: refs.get(k) or [] for k in ("图片", "音频", "视频")}
            if "视频音频模式" in refs:
                shared["视频音频模式"] = 视频音频模式(refs)
            return shared
    if 全局参数.get("参考共用"):
        return 规范全局参考(全局参数.get("参考素材"))
    return None


def 合并参考素材(refs, 全局参数, 共用素材=None):
    """保持槽位顺序；未开启共用时全局素材仅兜底缺失键。"""
    if refs is not None and not isinstance(refs, dict):
        raise ValueError("参考素材须为对象")
    result = dict(refs or {})
    result.pop("共用", None)
    global_refs = 规范全局参考(全局参数.get("参考素材"))
    if 共用素材 is not None:
        result.pop("视频音频模式", None)
        result.update(共用素材)
    elif 全局参数.get("参考共用"):
        result.pop("视频音频模式", None)
        result.update(global_refs)
    else:
        for k, v in global_refs.items():
            result.setdefault(k, v)
    return result


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
    N<1 或 N>对应标签上限 抛 ValueError；prompt 非字符串（None 除外）也抛。
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
        if not 1 <= n <= 标签上限[类]:
            raise ValueError(
                f"标签 <{m.group(1)} {n}> 编号非法：{类}标签仅 1-{标签上限[类]}"
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
            说明 = ("音频包含视频自带音轨和独立音频，请核对本段素材及编号" if 类 == "音频"
                  else f"超出上限 {上限[类]} 的部分已截断")
            raise ValueError(
                f"提示词引用第 {n} 个{类}，但该段只有 {实} 个"
                f"（{说明}）"
            )
