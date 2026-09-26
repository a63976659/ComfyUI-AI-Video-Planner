"""单段 latent 精修：视频局部去噪，原音频只作冻结工作支，永不导出采样音频。"""
import math

import torch

from .官方管线适配 import 调用节点
from .执行核心 import _补丁模型
from .条件组装 import 选模型槽
from .段间连续 import _FRAME_PER_TOKEN, 验证宿主续拍条件
from .精修条件 import 构建精修条件, _浮点张量


def 定位帧token(frame_index, token_count):
    """按非均匀时间覆盖定位整帧所属的 token。"""
    if (type(frame_index) is not int or type(token_count) is not int
            or frame_index < 0 or token_count <= 0):
        raise ValueError("帧号及 token 数须为有效整数")
    end = 0
    for token in range(token_count):
        end += _FRAME_PER_TOKEN[token % len(_FRAME_PER_TOKEN)]
        if frame_index < end:
            return token
    raise ValueError(f"帧 {frame_index} 超出 {token_count} 个 token 的覆盖范围")


def _结果(seg, video, padding):
    return {"index": seg["index"], "video_latent": video, "frame_count": seg["frame_count"],
            "anchor_frames": seg["anchor_frames"], "audio_padding": padding}


def 精修一段(段快照, 模型输入, 生成记录, 精修参数, 前段精修结果):
    """返回视频和段元信息；强度零借用只读源视频，不触及采样资源。"""
    seg, params = 段快照, 精修参数
    strength = params.get("精修强度")
    if type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("精修强度须为 [0,1] 内的有限数")
    if strength == 0:
        return _结果(seg, seg["video_latent"], 0)
    steps, seed = params.get("精修步数"), params.get("精修种子")
    if type(steps) is not int or steps <= 0 or type(seed) is not int:
        raise ValueError("精修步数须为正整数，精修种子须为整数")
    for name in ("采样器", "调度器"):
        if not isinstance(params.get(name), str) or not params[name]:
            raise ValueError(f"精修参数缺少{name}")
    work = 构建精修条件(seg, 模型输入, 生成记录, 前段精修结果)
    if "model_p" in 模型输入:
        model_p = 模型输入["model_p"]
    else:
        slot = 选模型槽(seg["task"]) + "_model"
        model = 模型输入.get(slot)
        if model is None:
            raise ValueError(f"精修缺少原模型输入 {slot}")
        for name in ("shift_video", "shift_audio"):
            value = 生成记录.get(name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"精修缺少有效初采 {name} 记录")
        model_p = _补丁模型(model, 生成记录)
    if model_p is None:
        raise ValueError("精修需要有效的局部 model_p")
    if work["prefix_tokens"]:
        验证宿主续拍条件(model_p)
    from comfy.nested_tensor import NestedTensor

    video, audio = work["video_latent"], work["audio_latent"]
    expected_shape, source_dtype = tuple(video.shape), video.dtype
    tokens = list(work["protected_tokens"])
    # 高级索引取得独立小备份：采样器即使原位改写整个输入，也能逐值恢复保护区。
    protected = video[:, :, tokens] if tokens else None
    video_mask = torch.ones_like(video)
    if tokens:
        video_mask[:, :, tokens] = 0
    latent = {"samples": NestedTensor([video, audio]),
              "noise_mask": NestedTensor([video_mask, torch.zeros_like(audio)])}
    positive = work["positive"]
    sampled = 调用节点("KSampler", model=model_p, seed=(seed + seg["index"]) % (2**64),
                       steps=steps, cfg=1.0, sampler_name=params["采样器"], scheduler=params["调度器"],
                       positive=positive, negative=positive, latent_image=latent, denoise=strength)[0]
    samples = sampled.get("samples") if isinstance(sampled, dict) else None
    if not isinstance(samples, NestedTensor) or len(samples.tensors) != 2:
        raise ValueError("精修采样必须返回 AV NestedTensor 双支")
    result = samples.tensors[0]  # 完全不接纳/验证/保存采样后的音频。
    _浮点张量(result, expected_shape, "精修采样视频")
    # 不让低精度采样输出把原初采保护值再次量化；更高精度输出也不向下强转。
    dtype = torch.promote_types(result.dtype, source_dtype)
    result = result.detach().to(device="cpu", dtype=dtype, copy=True)
    if tokens:
        result[:, :, tokens] = protected.to(dtype=dtype)
    return _结果(seg, result, work["audio_padding"])
