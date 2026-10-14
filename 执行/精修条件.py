"""从初采段快照重建 H3 条件；不读草稿、不借用初采采样编排或跨轮缓存。"""
from dataclasses import dataclass
import os

import torch

from .初采产物 import _复制容器
from .参考素材 import 解析槽位
from .官方管线适配 import 调用节点
from .执行核心 import _内容摘要器, _确保图像, _解析参考张量
from .条件组装 import 选管线, 选模型槽, 需要首帧, 需要尾帧
from .段间连续 import (
    _video_latent_t, _校验来源音频latent,
    取尾帧_latent, 钉入上下文_from_latent, 默认音频上下文帧数,
)


def _错误(seg, message):
    return ValueError(f"精修段{seg['index'] + 1}：{message}")


def _有素材(value):
    return value is not None and not (isinstance(value, str) and not value)


def _有效图像(seg):
    return {slot: seg["refs"].get(slot) for slot, enabled in (
        ("首帧", 需要首帧(seg["task"])), ("尾帧", 需要尾帧(seg["task"])),
        ("中间帧", 需要尾帧(seg["task"])),
    ) if enabled and _有素材(seg["refs"].get(slot))}


def _参考记录(seg, generation):
    slots = 解析槽位(seg["refs"])
    if (slots["音频"] or slots["视频"]) and type(generation.get("audio_vae")) is not bool:
        raise _错误(seg, "参考音频需要明确的 generation.audio_vae 布尔记录")
    return slots


def 校验精修素材(段快照, 生成记录):
    """供非零精修/S0预检复用；仅校验本任务实际读取的文件，每次重新完整计算源摘要。"""
    seg = 段快照
    if 选模型槽(seg["task"]) == "ref2va":
        needed = [(slot, i, path) for slot, paths in _参考记录(seg, 生成记录).items()
                  for i, path in enumerate(paths)]
    else:
        needed = [(slot, 0, value) for slot, value in _有效图像(seg).items() if isinstance(value, str)]
    if not needed:
        return
    digest_file = _内容摘要器()  # 全文件流式 SHA-256 前16位；不使用 mtime/跨轮备忘录。
    for slot, ordinal, path in needed:
        label = f"{slot}[{ordinal}] {path}"
        records = [a for a in seg["assets"] if
                   (a["slot"], a["ordinal"], a["path"]) == (slot, ordinal, path)]
        if len(records) != 1 or not os.path.isabs(path):
            raise _错误(seg, label + " 缺少唯一绝对路径素材记录")
        digest = records[0]["digest"]
        if not isinstance(digest, str) or not digest or digest.startswith("<"):
            raise _错误(seg, label + " 缺少可验证的初采内容摘要")
        try:
            current = digest_file(path)
        except OSError as exc:
            raise _错误(seg, label + " 素材不可读") from exc
        if current != digest:
            raise _错误(seg, label + " 素材内容已变化")


def _浮点张量(value, shape, label, *, cpu=False):
    try:
        if (not isinstance(value, torch.Tensor) or value.layout != torch.strided
                or not value.is_floating_point() or tuple(value.shape) != tuple(shape)
                or (cpu and value.device.type != "cpu") or not bool(torch.isfinite(value).all())):
            raise ValueError(f"{label} 须为形状 {tuple(shape)} 的有限浮点{' CPU' if cpu else ''} Tensor")
    finally:
        value = None


def _视频形状(seg):
    frames, width, height = seg["frame_count"], seg["width"], seg["height"]
    if (type(frames) is not int or frames < 5 or frames % 17 != 5
            or any(type(n) is not int or n < 32 or n % 32 for n in (width, height))):
        raise _错误(seg, "视频帧数/原始画布不符合 H3 网格")
    return (1, 24, _video_latent_t(frames), height // 16, width // 16)


def _工作音频(seg):
    source = seg["audio_latent"]
    length = round(seg["frame_count"] / 24 * 40)
    if source is None:
        return seg["video_latent"].new_zeros((1, 32, 2, length)), length
    if not isinstance(source, torch.Tensor) or source.ndim != 4:
        raise _错误(seg, "初采音频须为 [1,32,2,T] Tensor 或 None")
    _浮点张量(source, (1, 32, 2, source.shape[-1]), "初采音频", cpu=True)
    if source.shape[-1] > length:
        raise _错误(seg, "初采音频超长")
    _校验来源音频latent(source, 1, seg["frame_count"])
    padding = length - source.shape[-1]
    if padding:
        return torch.nn.functional.pad(source.detach(), (0, padding)), padding
    return source.detach().clone(), 0


@dataclass(frozen=True, slots=True, eq=False)
class 精修前驱尾:
    index: int
    width: int
    height: int
    context: int
    audio_context: int
    video_digest: str
    tail_video: torch.Tensor
    tail_audio: torch.Tensor | None
    anchor_frames: int
    audio_end_tick: int | None


def 提取精修前驱尾(seg, generation, previous):
    from .后处理缓存 import 张量摘要

    tail_v = tail_a = None
    try:
        tail_v, tail_a, anchor, tick = _前驱尾(seg, generation, previous)
        if tail_v is None:
            return None
        return 精修前驱尾(
            index=previous["index"], width=seg["width"], height=seg["height"],
            context=generation["上下文帧数"], audio_context=generation["音频上下文帧数"],
            video_digest=张量摘要(previous["video_latent"]), tail_video=tail_v,
            tail_audio=tail_a, anchor_frames=anchor, audio_end_tick=tick)
    finally:
        seg = previous = tail_v = tail_a = None


def _前驱尾(seg, generation, previous):
    audio = tail_v = tail_a = None
    try:
        predecessor, anchor = seg["predecessor_index"], seg["anchor_frames"]
        if predecessor is None:
            if anchor != 0:
                raise _错误(seg, "无前驱不能有锚帧")
            return None, None, 0, None
        if isinstance(previous, 精修前驱尾):
            expected = (previous.index, previous.width, previous.height, previous.context,
                        previous.audio_context, previous.anchor_frames)
            actual = (predecessor, seg["width"], seg["height"], generation.get("上下文帧数"),
                      generation.get("音频上下文帧数"), anchor)
            if (any(type(value) is not int for value in actual) or actual != expected
                    or not 0 < anchor <= seg["frame_count"]):
                raise _错误(seg, "前驱尾块的节点、画布、上下文或锚帧合同不匹配")
            # 每次交给条件节点独立小副本，避免第三方原位改写污染后续缓存身份。
            return (previous.tail_video.clone(),
                    None if previous.tail_audio is None else previous.tail_audio.clone(),
                    previous.anchor_frames, previous.audio_end_tick)
        if not isinstance(previous, dict) or previous.get("index") != predecessor:
            raise _错误(seg, "前段精修结果缺失或前驱 ID 不匹配")
        frames = previous.get("frame_count")
        if type(frames) is not int or frames < 5 or frames % 17 != 5:
            raise _错误(seg, "前段 frame_count 不符合原尺寸视频网格")
        shape = (1, 24, _video_latent_t(frames), seg["height"] // 16, seg["width"] // 16)
        _浮点张量(previous.get("video_latent"), shape, "前段精修视频", cpu=True)
        if "audio_latent" not in previous:
            raise _错误(seg, "前段须显式提供原音频 audio_latent（可为 None）")
        context = generation.get("上下文帧数")
        if type(context) is not int or context < 5:
            raise _错误(seg, "真前驱需要初采上下文帧数记录")
        audio_context = generation.get("音频上下文帧数")
        if type(audio_context) is not int or audio_context != 默认音频上下文帧数:
            raise _错误(seg, "音频上下文帧数缺失或不兼容当前原生尾窗合同")
        audio = previous["audio_latent"]
        if audio is not None:
            if not isinstance(audio, torch.Tensor) or audio.ndim != 4:
                raise _错误(seg, "前段原音频形状错误")
            _浮点张量(audio, (1, 32, 2, audio.shape[-1]), "前段原音频", cpu=True)
            if audio.shape[-1] > round(frames / 24 * 40):
                raise _错误(seg, "前段原音频超长")
        tail_v, tail_a, actual, tick = 取尾帧_latent(previous["video_latent"], audio, context)
        if type(anchor) is not int or actual != anchor or not 0 < anchor <= seg["frame_count"]:
            raise _错误(seg, "真实前段尾的锚帧数与快照不匹配")
        return tail_v, tail_a, actual, tick
    finally:
        seg = previous = audio = tail_v = tail_a = None


def _图像副本(value, seg, slot):
    # 字符串加载结果也可能来自第三方共享张量；IMAGE 直连先隔离再交给辅助函数。
    try:
        if isinstance(value, torch.Tensor):
            return _确保图像(value.detach().cpu().clone(), "")
        return _复制容器(_确保图像(value, ""), 克隆张量=True)
    except OSError as exc:
        raise _错误(seg, f"{slot}[0] {value} 素材读取失败") from exc


def _校验空AV(latent, video, audio):
    from comfy.nested_tensor import NestedTensor

    samples = latent.get("samples") if isinstance(latent, dict) else None
    if not isinstance(samples, NestedTensor) or len(samples.tensors) != 2:
        raise ValueError("官方 AV latent 必须是 NestedTensor 视频/音频双支布局")
    for actual, expected in zip(samples.tensors, (video, audio)):
        if (not isinstance(actual, torch.Tensor) or actual.layout != torch.strided
                or actual.shape != expected.shape):
            raise ValueError("官方 AV latent 形状/布局与快照不匹配")


def 构建精修条件(段快照, 模型输入, 生成记录, 前段精修结果):
    """返回条件、AV 工作副本和完整时间 token 保护范围。"""
    from .精修采样 import 定位帧token

    seg, generation = 段快照, 生成记录
    校验精修素材(seg, generation)
    _浮点张量(seg["video_latent"], _视频形状(seg), "初采视频", cpu=True)
    audio, padding = _工作音频(seg)
    tail_v, tail_a, anchor, tick = _前驱尾(seg, generation, 前段精修结果)
    if not isinstance(模型输入, dict) or 模型输入.get("clip") is None or 模型输入.get("vae") is None:
        raise _错误(seg, "精修条件需要 clip 和 vae")
    source = seg["video_latent"]
    dtype = source.dtype if tail_v is None else torch.promote_types(source.dtype, tail_v.dtype)
    video = source.detach().to(dtype=dtype, copy=True)
    protected, prefix = set(), 0
    if tail_v is not None:
        prefix = tail_v.shape[2]
        video[:, :, :prefix] = tail_v
        protected.update(range(prefix))
    kw = dict(clip=模型输入["clip"], vae=模型输入["vae"], prompt=seg["prompt"],
              width=seg["width"], height=seg["height"], length=seg["frame_count"])
    pipeline = 选管线(seg["task"])
    images = {}
    if pipeline == "MiniMaxH3ImageToVideo":
        images = _有效图像(seg)
        for slot, name, frame in (("首帧", "first_frame", 0), ("尾帧", "last_frame", seg["frame_count"] - 1)):
            if slot in images:
                kw[name] = _图像副本(images[slot], seg, slot)
                if slot != "首帧" or tail_v is None:
                    protected.add(定位帧token(frame, video.shape[2]))
    else:
        slots = _参考记录(seg, generation)
        enabled = generation.get("audio_vae") is True
        audio_vae = 模型输入.get("audio_vae") if enabled else None
        if (slots["音频"] or slots["视频"]) and enabled and audio_vae is None:
            raise _错误(seg, "初采启用了参考音频，精修必须提供 audio_vae")
        size = generation.get("参考图尺寸")
        if size not in ("match", "max"):
            raise _错误(seg, "缺少有效的初采参考图尺寸记录")
        try:
            loaded = _解析参考张量({**slots, "视频音频模式": seg["refs"].get("视频音频模式", "默认")}, "", seg["prompt"], 音频窗=seg["reference_audio_window"],
                             参考帧数=seg["frame_count"])
        except OSError as exc:
            校验精修素材(seg, generation)  # 捕获预检到实际读取之间的变化并准确点名。
            names = "、".join(f"{slot}[{i}] {path}" for slot, paths in slots.items()
                             for i, path in enumerate(paths))
            raise _错误(seg, f"参考素材 {names} 读取失败：{exc}") from exc
        # 视频/音频空窗及引用错位由共用解析器检查，与初采采用相同的跳过规则。
        for slot, key, stem in (("图片", "ref_images", "ref_image_"),):
            actual = loaded.get(key, {})
            for i in range(len(slots[slot])):
                if actual.get(f"{stem}{i}") is None:
                    raise _错误(seg, f"{slot}[{i}] 空素材/空音频窗，不能压缩参考序号")
        kw.update(_复制容器(loaded, 克隆张量=True))
        kw.update(audio_vae=audio_vae, ref_image_size=size)
    positive, empty = 调用节点(pipeline, **kw)[:2]
    _校验空AV(empty, video, audio)
    del empty
    from comfy.nested_tensor import NestedTensor

    if tail_v is not None:
        positive = 钉入上下文_from_latent(positive, {"samples": NestedTensor([video, audio])},
                                       tail_v, tail_a, anchor, 音频结束坐标=tick)
    if "中间帧" in images:
        frame = seg["middle_frame_index"]
        if (type(frame) is not int or not seg["crop_prefix"] < frame < seg["frame_count"] - 1):
            raise _错误(seg, "中间帧缺少有效的已解析帧号")
        protected.add(定位帧token(frame, video.shape[2]))
        # guide/第三方包装可以改参数：保护实际初采工作起点不被条件节点原位改写。
        positive = 调用节点("MiniMaxH3AddGuide", positive=positive,
                            latent={"samples": NestedTensor([video.clone(), audio.clone()])},
                            frame_idx=frame, vae=模型输入["vae"],
                            image=_图像副本(images["中间帧"], seg, "中间帧"))[0]
    校验精修素材(seg, generation)
    return {"positive": positive, "video_latent": video, "audio_latent": audio,
            "protected_tokens": tuple(sorted(protected)), "prefix_tokens": prefix,
            "anchor_frames": anchor, "audio_padding": padding}
