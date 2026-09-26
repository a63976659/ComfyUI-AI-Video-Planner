import math
import os
import re
import uuid
from typing import Literal, TypedDict

import torch
from torch import Tensor

from .条件组装 import 选模型槽, 需要首帧, 需要尾帧
from .参考素材 import 解析槽位
from .段间连续 import 裁前缀帧数, _video_latent_t


class 音轨(TypedDict):
    waveform: Tensor
    sample_rate: int


class 素材记录(TypedDict):
    slot: str
    ordinal: int
    path: str
    digest: str | None


class 段快照(TypedDict):
    index: int
    task: str
    model_slot: Literal["fl2va", "ref2va"]
    prompt: str
    refs: dict
    assets: list[素材记录]
    start: float
    end: float
    reference_audio_window: tuple[float, float] | None
    source_cache_key: str
    video_latent: Tensor
    audio_latent: Tensor | None
    width: int
    height: int
    frame_count: int
    anchor_frames: int
    crop_prefix: int
    output_start: int
    output_end: int
    predecessor_index: int | None
    middle_frame_index: int | None
    color_match: bool


class 初采包(TypedDict):
    type: Literal["LVP_FIRST_PASS"]
    version: Literal[1]
    source_node_id: str
    source_run_id: str
    sampling_fps: int
    output_fps: float
    frame_count: int
    generation: dict
    segments: tuple[段快照, ...]
    audio: 音轨 | None


class 磁盘初采引用(TypedDict):
    type: Literal["LVP_FIRST_PASS_DISK"]
    version: Literal[1]
    artifact_id: str
    manifest_sha256: str
    source_node_id: str
    source_run_id: str
    frame_count: int
    output_fps: float


_生成字段 = frozenset({
    "宽", "高", "采样器", "调度器", "步数", "种子", "cfg", "shift_video", "shift_audio",
    "上下文帧数", "音频上下文帧数", "audio_vae", "参考图尺寸", "参考共用", "续拍算法标识", "模型链身份", "缓存失效版本",
})


def _复制容器(值, *, 克隆张量=False):
    if isinstance(值, Tensor):
        if 克隆张量:
            return 值.detach().cpu().clone()
        return 值.detach().cpu() if 值.requires_grad or 值.device.type != "cpu" else 值
    if type(值) is dict:
        return {k: _复制容器(v, 克隆张量=克隆张量) for k, v in 值.items() if type(k) is str}
    if type(值) in (list, tuple):
        return type(值)(_复制容器(v, 克隆张量=克隆张量) for v in 值)
    return 值 if 值 is None or type(值) in (str, bool, int, float) else None


def 记录初采段(seg, 产物, *, 指纹, 素材记录, 前段序号, 参考音频窗, 中间帧号, 已解析refs=None) -> 段快照:
    video = _复制容器(产物["video_latent"])
    frames, anchor = int(产物["帧数"]), int(产物.get("锚帧数", 0))
    crop = 裁前缀帧数(frames, anchor)
    return {
        "index": int(seg.index), "task": seg.task, "model_slot": 选模型槽(seg.task),
        "prompt": seg.prompt, "refs": _复制容器(seg.refs if 已解析refs is None else 已解析refs, 克隆张量=True),
        "assets": _复制容器(素材记录), "start": float(seg.start), "end": float(seg.end),
        "reference_audio_window": _复制容器(参考音频窗), "source_cache_key": 指纹,
        "video_latent": video, "audio_latent": _复制容器(产物.get("audio_latent")),
        "width": int(video.shape[-1]) * 16, "height": int(video.shape[-2]) * 16,
        "frame_count": frames, "anchor_frames": anchor, "crop_prefix": crop,
        "output_start": 0, "output_end": frames - crop,
        "predecessor_index": 前段序号 if anchor > 0 else None,
        "middle_frame_index": 中间帧号, "color_match": False,
    }


def 组装初采产物(段快照列表, *, 最终音频, 总帧数, 输出帧率, 全局参数, 来源节点, 运行标识) -> 初采包:
    generation = {k: _复制容器(v) for k, v in 全局参数.items() if k in _生成字段}
    generation["cfg"] = 1.0
    audio = None if 最终音频 is None else {
        "waveform": _复制容器(最终音频["waveform"]), "sample_rate": int(最终音频["sample_rate"]),
    }
    return {
        "type": "LVP_FIRST_PASS", "version": 1,
        "source_node_id": str(来源节点) if 来源节点 is not None else "",
        "source_run_id": str(运行标识) if 运行标识 is not None else "",
        "sampling_fps": 24, "output_fps": float(输出帧率), "frame_count": int(总帧数),
        "generation": generation, "segments": tuple(_复制容器(s) for s in 段快照列表), "audio": audio,
    }


def _要求(成立, 字段):
    if not 成立:
        raise ValueError(f"初采产物无效：{字段}")


def _整数(值, 最小=0):
    return type(值) is int and 值 >= 最小


def _有限数(值):
    return type(值) in (int, float) and math.isfinite(值)


def _张量(值, 字段):
    _要求(type(值) is Tensor and 值.device.type == "cpu" and 值.layout == torch.strided
        and 值.is_floating_point(), 字段 + " 须为 CPU 浮点 Tensor")
    _要求(bool(torch.isfinite(值).all()), 字段 + " 须有限")


def _容器(值, *, 允许张量=True, 活跃=None):
    if 活跃 is None:
        活跃 = set()
    if type(值) is Tensor:
        _要求(允许张量, "此元信息不允许 Tensor")
        _张量(值, "Tensor")
    elif type(值) in (dict, list, tuple):
        _要求(id(值) not in 活跃, "循环容器")
        活跃.add(id(值))
        if type(值) is dict:
            _要求(all(type(k) is str for k in 值), "字典键须为字符串")
            项 = 值.values()
        else:
            项 = 值
        for v in 项:
            _容器(v, 允许张量=允许张量, 活跃=活跃)
        活跃.remove(id(值))
    else:
        _要求(值 is None or type(值) in (str, bool, int, float), "不支持的对象类型")
        if type(值) is float:
            _要求(math.isfinite(值), "非有限元信息")


def _字段(值, 合同, 名):
    _要求(type(值) is dict and set(值) == set(合同.__annotations__), 名 + " 字段不匹配")


def _校验素材(seg):
    refs, task = seg["refs"], seg["task"]
    expected = []
    if seg["model_slot"] == "ref2va":
        for slot, names in 解析槽位(refs).items():
            expected.extend((slot, i, path) for i, path in enumerate(names))
    else:
        for slot, enabled in (("首帧", 需要首帧(task)), ("尾帧", 需要尾帧(task)), ("中间帧", 需要尾帧(task))):
            value = refs.get(slot)
            if enabled and type(value) is str and value:
                expected.append((slot, 0, value))
    _要求(type(seg["assets"]) is list, "assets 须为列表")
    actual = []
    for asset in seg["assets"]:
        _字段(asset, 素材记录, "素材")
        _要求(type(asset["slot"]) is str and _整数(asset["ordinal"]), "素材槽位")
        _要求(type(asset["path"]) is str and os.path.isabs(asset["path"]), "素材路径须绝对")
        digest = asset["digest"]
        _要求(digest is None or type(digest) is str and bool(digest) and not digest.startswith("<"),
            "素材摘要须为 None 或非空可读字符串")
        actual.append((asset["slot"], asset["ordinal"], asset["path"]))
    _要求(actual == expected, "素材须与任务有效 refs 槽位及顺序一致")


def 校验初采产物(包) -> 初采包:
    _字段(包, 初采包, "包")
    _要求(type(包["type"]) is str and 包["type"] == "LVP_FIRST_PASS"
        and type(包["version"]) is int and 包["version"] == 1, "type/version")
    _要求(type(包["source_node_id"]) is str and type(包["source_run_id"]) is str, "来源标识")
    _要求(type(包["segments"]) is tuple and bool(包["segments"]), "segments 须为非空 tuple")
    _要求(type(包["sampling_fps"]) is int and 包["sampling_fps"] == 24, "sampling_fps 须为 24")
    _要求(_有限数(包["output_fps"]) and 包["output_fps"] > 0, "output_fps 须为正有限数")
    _要求(_整数(包["frame_count"], 1), "总帧数")
    generation = 包["generation"]
    _要求(type(generation) is dict and set(generation) <= _生成字段, "generation 白名单")
    if "audio_vae" in generation:
        _要求(type(generation["audio_vae"]) is bool, "generation.audio_vae 须为 bool")
    if "音频上下文帧数" in generation:
        _要求(_整数(generation["音频上下文帧数"]), "generation.音频上下文帧数 须为非负 int（不含 bool）")
    _容器(generation, 允许张量=False)
    seen, cursor, canvas = {}, 0, None
    for seg in 包["segments"]:
        _字段(seg, 段快照, "段")
        index = seg["index"]
        _要求(_整数(index) and index not in seen, "段 index 须唯一")
        _要求(type(seg["task"]) is str and type(seg["model_slot"]) is str
            and seg["model_slot"] == 选模型槽(seg["task"]), "task/model_slot")
        _要求(type(seg["prompt"]) is str and type(seg["source_cache_key"]) is str
            and bool(seg["source_cache_key"]), "prompt/source_cache_key")
        _要求(type(seg["refs"]) is dict, "refs")
        _容器(seg["refs"])
        _校验素材(seg)
        _要求(_有限数(seg["start"]) and _有限数(seg["end"]) and seg["end"] > seg["start"], "段时间窗")
        width, height, frames = seg["width"], seg["height"], seg["frame_count"]
        _要求(_整数(width, 32) and _整数(height, 32) and width % 32 == height % 32 == 0, "画布须 32 对齐")
        _要求(canvas is None or canvas == (width, height), "所有段画布须一致")
        canvas = (width, height)
        _要求(_整数(frames, 5) and frames % 17 == 5, "frame_count 须为 17k+5")
        video, audio = seg["video_latent"], seg["audio_latent"]
        _张量(video, "video_latent")
        _要求(tuple(video.shape) == (1, 24, _video_latent_t(frames), height // 16, width // 16), "video_latent 形状")
        if audio is not None:
            _张量(audio, "audio_latent")
            _要求(audio.ndim == 4 and tuple(audio.shape[:3]) == (1, 32, 2)
                and 0 < audio.shape[-1] <= round(frames / 24 * 40), "audio_latent 形状或长度")
        anchor, crop = seg["anchor_frames"], seg["crop_prefix"]
        _要求(_整数(anchor) and (anchor == 0 or anchor >= 5 and anchor % 17 == 5), "anchor_frames")
        _要求(_整数(crop) and crop == 裁前缀帧数(frames, anchor) and crop < frames, "crop_prefix")
        predecessor = seg["predecessor_index"]
        if predecessor is None:
            _要求(anchor == 0, "无前段不能正锚")
        else:
            _要求(_整数(predecessor) and predecessor in seen and anchor > 0, "predecessor_index 须指向已出现真实段")
            previous = seen[predecessor]
            _要求((previous["width"], previous["height"]) == canvas
                and anchor <= previous["frame_count"], "前段尺寸或锚长度")
        _要求(_整数(seg["output_start"]) and seg["output_start"] == cursor, "output_start 区间须连续")
        cursor += frames - crop
        _要求(_整数(seg["output_end"], 1) and seg["output_end"] == cursor, "output_end 半开区间")
        middle, middle_ref = seg["middle_frame_index"], seg["refs"].get("中间帧")
        if 需要尾帧(seg["task"]):
            _要求(middle_ref is None or type(middle_ref) is str, "中间帧须为图片文件名")
        enabled = 需要尾帧(seg["task"]) and bool(middle_ref)
        if middle is not None:
            _要求(enabled and _整数(middle) and crop < middle < frames - 1, "middle_frame_index 范围或任务")
        else:
            _要求(not enabled, "启用中间帧须记录帧号")
        window = seg["reference_audio_window"]
        if window is not None:
            _要求(seg["model_slot"] == "ref2va" and type(window) is tuple and len(window) == 2
                and all(_有限数(v) for v in window) and window == (seg["start"], seg["end"]), "reference_audio_window")
        _要求(type(seg["color_match"]) is bool, "color_match")
        if seg["color_match"]:
            _要求(predecessor is not None and predecessor == index - 1 and anchor > 0
                and _整数(generation.get("上下文帧数"), 1), "color_match 须为真实连续段")
        seen[index] = seg
    _要求(cursor == 包["frame_count"], "最后区间须等于总帧数")
    if 包["audio"] is not None:
        _字段(包["audio"], 音轨, "audio")
        _要求(_整数(包["audio"]["sample_rate"], 1), "sample_rate")
        _张量(包["audio"]["waveform"], "waveform")
    return 包


def 校验磁盘初采引用(引用) -> 磁盘初采引用:
    _字段(引用, 磁盘初采引用, "磁盘引用")
    _要求(type(引用["type"]) is str and 引用["type"] == "LVP_FIRST_PASS_DISK"
        and type(引用["version"]) is int and 引用["version"] == 1, "磁盘 type/version")
    artifact = 引用["artifact_id"]
    _要求(type(artifact) is str, "artifact_id")
    try:
        parsed = uuid.UUID(artifact)
    except ValueError as exc:
        raise ValueError("初采产物无效：artifact_id 须为标准 UUID") from exc
    _要求(str(parsed) == artifact and parsed.version == 4, "artifact_id 须为标准 UUID4")
    digest = 引用["manifest_sha256"]
    _要求(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "manifest_sha256")
    _要求(type(引用["source_node_id"]) is str and type(引用["source_run_id"]) is str, "来源标识")
    _要求(_整数(引用["frame_count"], 1), "总帧数")
    _要求(_有限数(引用["output_fps"]) and 引用["output_fps"] > 0, "output_fps")
    return 引用
