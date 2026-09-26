"""统一目标画布与官方像素放大；批次由呈现编排逐帧提供。"""
import math

import torch

from .官方管线适配 import 调用节点


def 计算目标尺寸(width, height, scale):
    if (type(width) is not int or type(height) is not int
            or width < 32 or height < 32 or width % 32 or height % 32):
        raise ValueError("源画布须为正的 32 倍数")
    if type(scale) not in (int, float) or not math.isfinite(scale) or not 1 <= scale <= 4:
        raise ValueError("放大倍率须在 1 到 4 之间")
    # 半格一律进位：round() 是半偶舍入，64×1.25＝80（恰在 64/96 中间）会被舍回 64，
    # 同一次均匀请求里出现「宽不动、高放大」的静默零放大。倍率按 0.25 步进，乘法无浮点误差。
    target_w = max(width, 32 * math.floor(width * scale / 32 + 0.5))
    target_h = max(height, 32 * math.floor(height * scale / 32 + 0.5))
    if max(target_w, target_h) > 16384:
        raise ValueError("目标尺寸超过当前官方图像节点上限")
    return target_w, target_h


def _校验图像(images, shape, name):
    if (type(images) is not torch.Tensor or images.ndim != 4 or min(images.shape) < 1
            or images.shape[-1] != 3 or not images.is_floating_point()
            or tuple(images.shape) != tuple(shape) or not bool(torch.isfinite(images).all())):
        raise ValueError(f"{name}须为有限 RGB 图像且尺寸、帧数匹配")


def 放大图像批(images, 方式, 目标宽, 目标高, 模型=None):
    _校验图像(images, getattr(images, "shape", ()), "放大输入")
    if 方式 not in ("Lanczos", "像素模型"):
        raise ValueError("未知像素放大方式")
    if (type(目标宽) is not int or type(目标高) is not int
            or 目标宽 % 32 or 目标高 % 32 or max(目标宽, 目标高) > 16384
            or 目标宽 < images.shape[2] or 目标高 < images.shape[1]):
        raise ValueError("目标画布须为不小于源尺寸的 32 倍数，且不超过16384")
    if (images.shape[2], images.shape[1]) == (目标宽, 目标高):
        return images
    count = images.shape[0]
    if 方式 == "像素模型":
        if getattr(模型, "patcher", None) is None:
            raise ValueError("请连接官方放大模型加载器的 UPSCALE_MODEL 输出")
        images = 调用节点("ImageUpscaleWithModel", upscale_model=模型, image=images)[0]
        _校验图像(images, (count, *getattr(images, "shape", ())[1:]), "放大结果")
    if (images.shape[2], images.shape[1]) != (目标宽, 目标高):
        images = 调用节点("ImageScale", image=images.to(dtype=torch.float32), upscale_method="lanczos",
                        width=目标宽, height=目标高, crop="disabled")[0]
    _校验图像(images, (count, 目标高, 目标宽, 3), "放大结果")
    return images
