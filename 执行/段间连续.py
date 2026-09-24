# -*- coding: utf-8 -*-
"""段间连续性：规范锚帧数/裁前缀/crossfade 权重为纯函数；上下文钉入直接传 latent（方案 B）。"""
import math
from numbers import Integral

import torch

默认上下文帧数 = 22
默认音频上下文帧数 = 24
续拍算法标识 = "native_end_aligned_v1"


def 规范锚帧数(n: int) -> int:
    """复刻官方 MiniMaxH3AddGuide 的 clip 长度规则：<5→1；否则向下取 17k+5(5/22/39...)。

    **幂等**（规范锚帧数(规范锚帧数(n)) == 规范锚帧数(n)）：输出恒为 1 或 17k+5，再喂回本函数
    原样返回。执行核心._裁并拼 依赖此性质——它拿到的 锚帧数 已是 取尾帧_latent 规范过的值，
    却仍经 裁前缀帧数 再规范一次；不幂等就会「切 latent 用一个数、裁前缀用另一个数」，成片多一段
    重复画面且全程无报错。由 test_规范锚帧数 末尾的幂等断言（i 跑 0..299）锁住。"""
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
    不变式：输出帧数 = Σ输入帧数 − Σ接缝重叠帧数；音频必须由调用方（Task 9 执行核心）按同规则对称裁剪或淡化，否则 A/V 漂移。

    编排层（执行核心 Phase 2）已改用 流式拼接——它逐段写进预分配成片，峰值内存只有
    「成片 + 当前段」，而本函数要先攒齐全部段再折叠（峰值 ≈3N 段量，1.0MP@16s 下 3 段差 ~20GB）。
    本函数保留：① 单段直接返回原对象（零拷贝），② 作 流式拼接 的同值参照被测试锁定。"""
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


def 预算总帧数(段帧数列表, 重叠帧数: int = 4) -> int:
    """成片总帧数预算：首段全取，其后每段净减 min(重叠帧数, 本段, 已累计)。

    入参是各段**裁前缀后**的帧数（执行核心由 帧数 − 裁前缀帧数(帧数, 锚帧数) 算出，
    无需先解码）。折叠式与 拼接段 / 流式拼接 逐字同式，故预算恒等于实际写入量；
    不等只可能是「解码出的帧数 ≠ 缓存里的 帧数」，那由 流式拼接 显式拦下（ValueError）
    而非静默越界写。跳过 0 帧段（与 流式拼接.追加 的忽略行为对齐）。"""
    总, 首 = 0, True
    for 帧 in 段帧数列表:
        帧 = max(0, int(帧))
        if 帧 == 0:
            continue
        if 首:
            总, 首 = 帧, False
        else:
            总 += 帧 - min(int(重叠帧数), 帧, 总)
    return 总


class 流式拼接:
    """把「已裁前缀」的段 IMAGE [T,H,W,C] 逐段写进一块**预分配**成片（与 拼接段 严格同值）。

    为什么不直接用 拼接段：后者要先攒齐全部段再折叠，峰值内存 = 全量段列表(N 段)
    + 折叠中间量(≈2N) ≈ 3N 段量；而解码输出恒落 **CPU float32**（comfy/sd.py:1079 的
    output_device = model_management.intermediate_device()，dtype 同文件 :1131），
    1.0MP@16s 单段 images ≈5.0GB（1376×768×396帧×3通道×4字节）→ 3 段峰值 ≈40GB。
    本类只持「成片(N) + 当前段(1)」→ 同样 3 段 ≈20GB（方案 B 把 DiT 请出显存后，
    CPU 内存就是下一个瓶颈）。

    同值依据：拼接段 的折叠式 `结果 = cat([结果[:-重叠], 帧交叉淡化(结果, 段, 重叠), 段[重叠:]])`
    只**读** 结果 的末 重叠 帧、只**写** 其后；故「就地覆盖已写入的接缝区 + 追写本段剩余」
    与「重新 cat 一份」逐元素相等。由 test_流式拼接_与拼接段同值 锁住。

    用法：拼 = 流式拼接(预算总帧数([...])) → 逐段 拼.追加(images) → 拼.结果()。
    总帧数 在解码前即可精确预算（各段 帧数/锚帧数 已在采样产物里），故只分配一次、不增长。
    音频不走本类：_拼接音频 的量级是 MB 而非 GB（同样 16s 约 3MB），攒列表再 cat 即可。"""

    def __init__(self, 总帧数: int, 重叠帧数: int = 4):
        self._总帧数 = max(0, int(总帧数))
        self._重叠 = int(重叠帧数)
        self._buf = None      # 预分配成片；首段到达时才分配（那时才知道 H/W/C/dtype/device）
        self._写 = 0          # 已写入帧数（= 下一段的写入起点）

    def 追加(self, 段):
        """写入一段（None 或 0 帧则忽略）。返回 self 以便链式调用。"""
        if 段 is None or int(段.shape[0]) == 0:
            return self
        n = int(段.shape[0])
        if self._buf is None:
            self._首段(n, 段)
            return self
        重叠 = min(self._重叠, n, self._写)          # 同 拼接段 的动态重叠钳制
        if 重叠 > 0:
            # 就地覆盖接缝区：帧交叉淡化 读 buf 视图 + 本段头 重叠 帧，产新小张量（4 帧量级）再写回。
            尾 = self._buf[self._写 - 重叠:self._写]
            self._buf[self._写 - 重叠:self._写] = 帧交叉淡化(尾, 段[:重叠], 重叠)
            段, n = 段[重叠:], n - 重叠
        self._容得下(n)
        self._buf[self._写:self._写 + n] = 段
        self._写 += n
        return self

    def 结果(self):
        """成片 [T,H,W,C]；一段也没写则 None。T = 实际写入帧数（预算有富余时截断到实际值）。"""
        return None if self._buf is None else self._buf[:self._写]

    def _首段(self, n, 段):
        self._容得下(n)
        self._buf = torch.empty((self._总帧数, *段.shape[1:]), dtype=段.dtype, device=段.device)
        self._buf[:n] = 段
        self._写 = n

    def _容得下(self, n):
        """写入越界守卫：预算不足即抛，不得静默丢帧（torch 切片赋值长度不匹配会报
        难定位的 RuntimeError，越过项目 ValueError-only 契约）。"""
        if self._写 + n > self._总帧数:
            raise ValueError(
                f"流式拼接：写入超出预算成片长度（已写 {self._写} 帧 + 本次 {n} 帧 > "
                f"预算 {self._总帧数} 帧）；预算来自各采样产物的 帧数/锚帧数，与实际解码帧数"
                f"不符通常意味着段缓存里的 帧数 与 latent 不自洽（试清缓存目录重跑）")


# ---------- 段间锚定：原生视频整块与独立音频尾窗 ----------

_FRAME_PER_TOKEN = (1, 4, 4, 4, 4)   # 官方 comfy/ldm/minimax/model.py:30
_FRAME_RESCALE = 5.0 / 3.0           # 官方 FRAME_RESCALE = AUDIO_LATENT_FPS(40) / FPS(24)


def _video_latent_t(frame_count: int) -> int:
    """像素帧数 → **整段** latent 的时间 token 数（官方 nodes_minimax_h3.py:42-43 video_latent_t）。

    ⚠️ 只适用于「一段完整视频」：frame_count<=5 时返回官方下限 2（整段 latent 至少 2 个 token），
    故**不能**用来算「n 帧占几个 token」——n=1 会给出 2，多切一倍。切片长度一律走 _帧数转token数。"""
    return 2 if frame_count <= 5 else ((frame_count - 5) // 17) * 5 + 2


def _帧数转token数(帧数: int) -> int:
    """n 个像素帧**占用**的视频 latent token 数（_latent_t_转帧数 的最小逆）。

    逐 token 累加 FRAME_PER_TOKEN 直到覆盖 n 帧，不假设 n 落在 17k+5 网格上：
    1→1、5→2、22→7、39→12。在网格值上与官方 _video_latent_t 恒等（由 test 锁），
    非网格值（1~4，即 上下文帧数 被调到 规范锚帧数 的 <5→1 兜底时）才给出正确的 1——
    那边若误用 _video_latent_t 会切 2 个 token（=5 帧）当锚、却按 锚帧数=1 只裁 1 帧前缀，
    成片接缝处多出 4 帧重复画面（官方 AddGuide 在 <5 时是 `image[:1]`，只锚 1 帧）。"""
    token数, 累计 = 0, 0
    while 累计 < max(0, int(帧数)):
        累计 += _FRAME_PER_TOKEN[token数 % 5]
        token数 += 1
    return token数


def _latent_t_转帧数(T_lat: int) -> int:
    """视频 latent token 数 → 像素帧数（_video_latent_t 的逆）。

    对齐输入下 T_lat=5k+2 ↔ 帧数=17k+5。逐 token 累加 FRAME_PER_TOKEN（与官方
    MiniMaxH3AddGuide.execute 里 `sum(FRAME_PER_TOKEN[k % 5] for k in range(vt))` 同式），
    不假设上游一定给对齐值 → 畸形 T_lat 也只算出对应帧数、不抛。"""
    return sum(_FRAME_PER_TOKEN[i % 5] for i in range(max(0, int(T_lat))))


def _校验视频latent(视频, 描述, 批次=None):
    if (not isinstance(视频, torch.Tensor) or 视频.ndim != 5 or 视频.shape[1] != 24
            or min(视频.shape) <= 0 or (批次 is not None and 视频.shape[0] != 批次)):
        raise ValueError(f"{描述}视频 latent 形状须为非空 [B,24,T,H,W]，且批次一致")


def _校验音频latent(音频, 描述, 批次):
    if (not isinstance(音频, torch.Tensor) or 音频.ndim != 4 or tuple(音频.shape[1:3]) != (32, 2)
            or min(音频.shape) <= 0 or 音频.shape[0] != 批次):
        raise ValueError(f"{描述}音频 latent 形状须为非空 [B,32,2,T]，且批次一致")


def 取尾帧_latent(video_latent, audio_latent, 上下文帧数: int = 默认上下文帧数):
    """返回独立克隆的视频尾块、音频尾窗、实际锚帧数及相对锚起点的音频结束 tick。"""
    if int(上下文帧数) <= 0 or video_latent is None:
        return None, None, 0, None
    _校验视频latent(video_latent, "来源")
    T_lat = int(video_latent.shape[2])
    来源视频帧数 = _latent_t_转帧数(T_lat)
    锚帧数 = 规范锚帧数(min(int(上下文帧数), 来源视频帧数))
    token数 = _帧数转token数(锚帧数)
    if (T_lat - token数) % len(_FRAME_PER_TOKEN) != 0:
        raise ValueError("视频尾 token 源相位与锚时间网格不符，不能把覆盖 4 帧的 token 当作 1 帧")
    锚帧数 = _latent_t_转帧数(token数)
    尾帧_video = video_latent[:, :, -token数:, :, :].clone()

    尾帧_audio, 音频结束坐标 = None, None
    if audio_latent is not None:
        _校验音频latent(audio_latent, "来源", video_latent.shape[0])
        音频长 = int(audio_latent.shape[-1])
        窗口 = round(默认音频上下文帧数 * _FRAME_RESCALE)
        音频_token数 = min(窗口, 音频长)
        视频结束坐标 = 来源视频帧数 * _FRAME_RESCALE
        # 与宿主 temporal_shape 同序先除 24 再乘 40 取整，短音频也按完整长度推导可为负的 overhang。
        期望音频长 = round(来源视频帧数 / 24 * 40)
        if 音频长 >= 窗口 and 音频长 != 期望音频长:
            raise ValueError("来源音频长度不在完整视频时间网格上，不能推断尾音频对齐坐标")
        overhang = 期望音频长 - 视频结束坐标
        尾帧_audio = audio_latent[..., -音频_token数:].clone()
        音频结束坐标 = round(锚帧数 * _FRAME_RESCALE + overhang)
    return 尾帧_video, 尾帧_audio, 锚帧数, 音频结束坐标


def 钉入上下文_from_latent(positive, latent, 尾帧_video_latent, 尾帧_audio_latent, 锚帧数, frame_idx=0,
                          *, 音频结束坐标=None):
    """分别钉入整块视频和结束对齐的音频，真续拍只替换零帧画面且不修改输入条件。"""
    if 尾帧_video_latent is None:
        return positive

    samples = latent.get("samples") if isinstance(latent, dict) else None
    tensors = getattr(samples, "tensors", None)
    if (not getattr(samples, "is_nested", False) or not isinstance(tensors, (list, tuple))
            or len(tensors) != 2):
        raise ValueError("段间锚定需要 MiniMax H3 的 AV latent（嵌套形态、恰好 video+audio 两支）")
    video, 目标音频 = tensors
    _校验视频latent(video, "AV latent 的")
    _校验音频latent(目标音频, "AV latent 的", video.shape[0])
    _校验视频latent(尾帧_video_latent, "尾帧", video.shape[0])
    if tuple(尾帧_video_latent.shape[3:]) != tuple(video.shape[3:]):
        raise ValueError(
            f"段间锚定的尾帧 latent 空间尺寸 {tuple(尾帧_video_latent.shape[3:])} 与本段画布 "
            f"{tuple(video.shape[3:])} 不符")
    if (not isinstance(锚帧数, Integral) or isinstance(锚帧数, bool) or 锚帧数 <= 0
            or 规范锚帧数(锚帧数) != 锚帧数 or _latent_t_转帧数(尾帧_video_latent.shape[2]) != 锚帧数):
        raise ValueError("锚帧数须为合法窗口并与完整视频尾块的实际帧数一致")
    总帧数 = _latent_t_转帧数(int(video.shape[2]))
    锚位 = int(frame_idx) if int(frame_idx) >= 0 else 总帧数 + int(frame_idx)
    if 锚位 < 0 or 锚位 + int(锚帧数) > 总帧数:
        raise ValueError(
            f"锚定 {锚帧数} 帧于 frame_idx={int(frame_idx)}（解析为第 {锚位} 帧）超出本段 "
            f"{总帧数} 帧；请调小「上下文帧数」或加长本段时长")

    新锚 = [{"resolved_frame_index": 锚位, "latent": 尾帧_video_latent}]
    if 尾帧_audio_latent is not None:
        _校验音频latent(尾帧_audio_latent, "尾帧", video.shape[0])
        if (not isinstance(音频结束坐标, Integral) or isinstance(音频结束坐标, bool) or 音频结束坐标 <= 0):
            raise ValueError("有尾帧音频时必须提供正整数音频结束坐标")
        音频_token数 = int(尾帧_audio_latent.shape[-1])
        音频起点 = (音频结束坐标 - 音频_token数) / _FRAME_RESCALE + 锚位
        max_rt = math.floor(目标音频.shape[-1] - (音频结束坐标 - 音频_token数 + _FRAME_RESCALE * 锚位))
        if max_rt < 1:
            raise ValueError(f"frame_idx={int(frame_idx)} 的尾音频起点已超出本段音频轨末尾，无法放入完整 token")
        if 音频_token数 > max_rt:
            尾帧_audio_latent = 尾帧_audio_latent[..., :max_rt].clone()
        新锚.append({"resolved_frame_index": 音频起点, "audio_latent": 尾帧_audio_latent})

    新条件 = []
    for 条件, 信息 in positive:
        keyframes = []
        for 原锚 in 信息.get("minimax_keyframes", []):
            锚 = 原锚.copy()
            if 锚位 == 0 and 锚.get("resolved_frame_index") == 0 and "latent" in 锚:
                del 锚["latent"]
                if set(锚) == {"resolved_frame_index"}:
                    continue
            keyframes.append(锚)
        keyframes.extend(锚.copy() for 锚 in 新锚)
        新条件.append([条件, {**信息, "minimax_keyframes": keyframes}])
    return 新条件


def _批量方框模糊(frames, kernel):
    x = frames.detach().float().permute(0, 3, 1, 2)
    pad = kernel // 2
    x = torch.nn.functional.pad(x, (pad, pad, pad, pad), mode="reflect")
    # 方框核可分离，避免 65×65 直接池化在 CPU 上重复求和。
    x = torch.nn.functional.avg_pool2d(x, (1, kernel), stride=1)
    x = torch.nn.functional.avg_pool2d(x, (kernel, 1), stride=1)
    return x.permute(0, 2, 3, 1)


@torch.no_grad()
def 匹配开头色光(body, previous_last):
    """原位调整最多十二帧的低频色光与亮度，不复制整段或重叠时间。"""
    if len(body) == 0:
        return body
    n = min(12, len(body))
    kernel = min(65, 2 * min(body.shape[1:3]) - 1)
    guide_blur = _批量方框模糊(previous_last.unsqueeze(0), kernel)
    opening_blur = _批量方框模糊(body[:n], kernel)
    weights = body.new_tensor([0.70 * (1 - i / n) for i in range(n)], dtype=torch.float32).view(-1, 1, 1, 1)
    body[:n] = (body[:n].float() + weights * (guide_blur - opening_blur)).clamp_(0, 1).to(body.dtype)
    if len(body) < 3:
        return body
    n = min(12, len(body) - 1)
    coeffs = body.new_tensor([0.299, 0.587, 0.114])
    luma = (body[:n + 1].float() * coeffs).sum(dim=-1).mean(dim=(1, 2))
    start = (previous_last.float() * coeffs).sum(dim=-1).mean()
    end = luma[n]
    if (abs(luma[0] - start) < 0.008 and abs(luma[1] - luma[0]) + abs(luma[2] - luma[1]) < 0.008
            and abs(end - start) < 0.008):
        return body
    t = torch.arange(n, device=body.device, dtype=torch.float32) / n
    delta = (start * (1 - t) + end * t - luma[:n]).clamp_(-0.10, 0.10)
    delta = torch.where(delta.abs() < 1e-5, 0, delta).view(-1, 1, 1, 1)
    body[:n] = (body[:n].float() + delta).clamp_(0, 1).to(body.dtype)
    return body


@torch.no_grad()
def 验证宿主续拍条件(model_p):
    """以 CPU 小条件验证当前补丁模型的续拍行为，不修改宿主或跨轮保留模型。"""
    def 检查(成立, 描述):
        if not 成立:
            raise ValueError(描述)

    def 坐标相等(实际, 期望):
        检查(实际.shape == 期望.shape and torch.allclose(实际, 期望, rtol=0, atol=1e-9),
             "PackedLayout 坐标不符")

    try:
        model = model_p.model
        text = torch.zeros((1, 5, model.diffusion_model.hidden_size), device="cpu")
        video = torch.zeros((1, 24, 7, 4, 4), device="cpu")
        audio = torch.zeros((1, 32, 2, 40), device="cpu")
        keyframes = [{"resolved_frame_index": 0, "latent": video},
                     {"resolved_frame_index": -1.8, "audio_latent": audio}]
        refs = [
            {"kind": "audio", "ref_audio_t": 6,
             "audio_latent": torch.zeros((1, 32, 2, 6), device="cpu")},
            {"kind": "image", "latent_h": 4, "latent_w": 4,
             "latent": torch.zeros((1, 24, 1, 4, 4), device="cpu")},
            {"kind": "video_audio", "latent_t": 2, "latent_h": 4, "latent_w": 4, "ref_audio_t": 3,
             "latent": torch.zeros((1, 24, 2, 4, 4), device="cpu"),
             "audio_latent": torch.zeros((1, 32, 2, 3), device="cpu")},
        ]
        期望视频 = [video, refs[1]["latent"], refs[2]["latent"]]
        期望音频 = [audio, refs[0]["audio_latent"], refs[2]["audio_latent"]]
        out = model.extra_conds(cross_attn=text, device=torch.device("cpu"),
                                latent_shapes=[(1, 24, 37, 4, 4), (1, 32, 2, 207)],
                                minimax_keyframes=keyframes, minimax_refs=refs)
        payload = out["minimax_payload"].cond
        for 名, 期望 in (("cond_video_latents", 期望视频), ("cond_audio_latents", 期望音频)):
            实际 = payload[名]
            检查(len(实际) == len(期望) and all(a is b for a, b in zip(实际, 期望)),
                 f"{名} 合并后身份或数量不符")
        layout = payload["layout"]
        期望段 = []
        起点 = 0
        for 名, 长度 in (("text", 5), ("cond", 28), ("cond_audio", 80), ("ref_audio", 12),
                         ("ref_img", 4), ("ref_audio", 6), ("ref_img", 8), ("audio", 414), ("video", 148)):
            期望段.append((起点, 起点 + 长度, 名))
            起点 += 长度
        检查(layout.segments == 期望段 and layout.seq_len == 起点, "PackedLayout 条件行数量或顺序不符")
        检查(layout.position_ids.shape == (起点, 3), "PackedLayout 坐标形状不符")
        for 模态, 名单 in (("audio", ("cond_audio", "ref_audio", "audio")),
                           ("img", ("cond", "ref_img", "video"))):
            选段 = [(a, b, k) for a, b, k in 期望段 if k in 名单]
            位置 = torch.cat([torch.arange(a, b, device="cpu") for a, b, _ in 选段])
            更新 = torch.cat([torch.full((b - a,), k in ("audio", "video"), dtype=torch.bool, device="cpu")
                              for a, b, k in 选段])
            检查(torch.equal(getattr(layout, 模态 + "_pos"), 位置)
                 and torch.equal(getattr(layout, 模态 + "_update"), 更新), "PackedLayout 更新 mask 不符")
        原点 = 5 + 6 + 1 + 25 / 3
        网格 = torch.tensor([[0, 0], [0, 16], [16, 0], [16, 16]], dtype=torch.float64, device="cpu")
        for a, b, 名 in 期望段:
            if 名 not in ("cond", "cond_audio", "audio", "video"):
                continue
            坐标 = layout.position_ids[a:b]
            if 名 in ("cond_audio", "audio"):
                长度, 开始 = (40, -3) if 名 == "cond_audio" else (207, 0)
                时间 = torch.arange(开始, 开始 + 长度, dtype=torch.float64, device="cpu").repeat(2)
                空间 = torch.tensor([[0, 0]] * 长度 + [[0, 16]] * 长度, dtype=torch.float64, device="cpu")
            else:
                长度 = 7 if 名 == "cond" else 37
                时间 = torch.tensor([sum(_FRAME_PER_TOKEN[i % 5] for i in range(t)) for t in range(长度)],
                                    dtype=torch.float64, device="cpu").repeat_interleave(4) * _FRAME_RESCALE
                空间 = 网格.repeat(长度, 1)
            坐标相等(坐标[:, 0] - 原点, 时间)
            坐标相等(坐标[:, 1:], 空间)
    except Exception as exc:
        raise ValueError(f"宿主续拍条件不兼容：{exc}；请检查其他插件补丁") from exc
