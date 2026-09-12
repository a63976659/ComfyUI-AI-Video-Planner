# -*- coding: utf-8 -*-
"""段间连续性：规范锚帧数/裁前缀/crossfade 权重为纯函数；上下文钉入(官方 AddGuide)为 GPU 封装。"""
import torch

默认上下文帧数 = 22


def 规范锚帧数(n: int) -> int:
    """复刻官方 MiniMaxH3AddGuide 的 clip 长度规则：<5→1；否则向下取 17k+5(5/22/39...)。"""
    n = int(n)
    if n < 5:
        return 1
    while n % 17 != 5:
        n -= 1
    return n


def 裁前缀帧数(帧数: int, 上下文帧数: int = 默认上下文帧数) -> int:
    """采样后应裁掉的锚定前缀帧数 = min(规范锚帧数(上下文帧数), 帧数-1)，且 >=0。
    上下文帧数<=0 视为「无锚」直接返回 0，避免误用 规范锚帧数 的 <5→1 兜底把首帧裁掉。"""
    if int(上下文帧数) <= 0:
        return 0
    锚 = 规范锚帧数(上下文帧数)
    return max(0, min(锚, int(帧数) - 1))


def crossfade权重(重叠帧数: int):
    """长度=重叠帧数的线性淡入权重 [0..1]；退化时返回 [1.0]。
    重叠帧数<=1 时返回 [1.0] 仅供 拼接段 兜底路径，不供 帧交叉淡化 使用；帧交叉淡化 直接拒绝 <=0。"""
    n = int(重叠帧数)
    if n <= 1:
        return [1.0]
    return [i / (n - 1) for i in range(n)]


def 帧交叉淡化(前段尾: torch.Tensor, 后段头: torch.Tensor, 重叠帧数: int) -> torch.Tensor:
    """对 ComfyUI IMAGE [T,H,W,C]（时间维=0）接缝做 overlap-crossfade，返回重叠区混合张量。GPU 集成验证。
    重叠帧数须满足 0 < 重叠帧数 <= min(前段尾帧数, 后段头帧数)，否则抛 ValueError。"""
    n = int(重叠帧数)
    if n <= 0 or n > min(前段尾.shape[0], 后段头.shape[0]):
        raise ValueError(
            f"帧交叉淡化：重叠帧数须为正且不超过两段帧数，实际 重叠帧数={n}、"
            f"前段尾={前段尾.shape[0]}帧、后段头={后段头.shape[0]}帧"
        )
    w = crossfade权重(n)
    尾 = 前段尾[-n:]
    头 = 后段头[:n]
    权重 = torch.tensor(w, device=尾.device, dtype=尾.dtype).view(-1, 1, 1, 1)
    return 尾 * (1 - 权重) + 头 * 权重


def 拼接段(段列表, 重叠帧数: int = 4):
    """把多段「已裁前缀」的 IMAGE [T,H,W,C] 交叉淡化拼接为整片。
    前缀裁切由执行核心按锚帧数统一做（images/audio 同步），此处只负责接缝平滑，避免二次裁切。GPU 集成验证。
    不变式：输出帧数 = Σ输入帧数 − Σ接缝重叠帧数；音频必须由调用方（Task 9 执行核心）按同规则对称裁剪或淡化，否则 A/V 漂移。"""
    结果 = None
    for 段 in 段列表:
        if 结果 is None:
            结果 = 段
            continue
        重叠 = min(重叠帧数, 段.shape[0], 结果.shape[0])
        if 重叠 <= 0:
            结果 = torch.cat([结果, 段], dim=0)
            continue
        接缝 = 帧交叉淡化(结果, 段, 重叠)
        结果 = torch.cat([结果[:-重叠], 接缝, 段[重叠:]], dim=0)
    return 结果


def 钉入上下文(positive, latent, 上段尾帧, 上段尾音频, video_vae, audio_vae, frame_idx=0):
    """调用官方 MiniMaxH3AddGuide 把上段尾帧(clip)+尾音频锚入下段条件的 frame_idx 处，
    返回 (新positive, 规范锚帧数)。锚帧数供采样后裁前缀用。GPU 集成验证。"""
    from .官方管线适配 import 调用节点
    锚帧数 = 规范锚帧数(上段尾帧.shape[0]) if 上段尾帧 is not None else 0
    kwargs = dict(positive=positive, latent=latent, frame_idx=frame_idx)
    if 上段尾帧 is not None:
        kwargs.update(vae=video_vae, image=上段尾帧)
    if 上段尾音频 is not None:
        kwargs.update(audio_vae=audio_vae, audio=上段尾音频)
    新positive = 调用节点("MiniMaxH3AddGuide", **kwargs)[0]
    return 新positive, 锚帧数
