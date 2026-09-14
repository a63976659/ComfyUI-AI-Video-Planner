# -*- coding: utf-8 -*-
"""段间连续性：规范锚帧数/裁前缀/crossfade 权重为纯函数；上下文钉入直接传 latent（方案 B）。"""
import torch

默认上下文帧数 = 22


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


# ---------- 段间锚定：直接传 latent（方案 B，取代官方 MiniMaxH3AddGuide 往返） ----------
#
# 官方链路：上段 images 尾帧 → vae.encode → keyframe["latent"]；尾音频 → audio_vae.encode
# → keyframe["audio_latent"]。方案 B 直接切 KSampler 输出 latent 的尾部 token 当 keyframe，
# 省掉「VAE decode 出像素 → 再 VAE encode 回 latent」这一整个往返：16GB 卡上它正是显存
# 乒乓的重灾区（1.0MP@16s 实测 AV 解码 52s → 839s），顺带免掉一次编解码量化损失。
#
# 与官方等价的依据（comfy/ldm/minimax/model.py）：
#   1. FRAME_PER_TOKEN = (1,4,4,4,4)（周期 5、和 17）→ video_latent_t(17k+5) = 5k+2，
#      即 T_lat ≡ 2 (mod 5) 恒成立。故从尾部切 5m+2 个 token，其**绝对**下标 mod 5 的序列
#      恰为 0,1,2,3,4,0,1…，与 PackedLayout 里 _video_t_grid(vt, origin) 按 k=0.. 生成的
#      _video_t_spans 完全同相位 → 时间栅格与官方 vae.encode 路径逐值一致。
#   2. 空间维：PackedLayout 用**目标画布**的 frame_rows 给 keyframe 计行数
#      （n = vt * frame_rows），故 keyframe latent 的 H/W 必须等于本段画布；不符会在模型
#      内部炸成难定位的形状错，钉入上下文_from_latent 前移为显式 ValueError。
#   3. 音频侧无 5-token 周期（每 latent 帧推进 1.0），token 数按 FRAME_RESCALE=5/3 由
#      **像素帧数**换算：round(锚帧数 * 40/24)。⚠️ 不是「视频 token 数 × 5/3」。

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


def 取尾帧_latent(video_latent, audio_latent, 上下文帧数: int = 默认上下文帧数):
    """从 KSampler 输出的 AV latent 里切出末尾 上下文帧数 像素帧对应的 latent，作下段锚素材。

    入参：video_latent [B,24,T_lat,H_lat,W_lat]、audio_latent [B,32,2,T_audio]|None
    返回：(尾帧_video, 尾帧_audio, 锚帧数)；上下文帧数<=0 或 video_latent 为 None → (None,None,0)。

    锚帧数 = 规范锚帧数(上下文帧数)——与旧 images 路径逐字同口径（那边是
    `规范锚帧数(上段尾帧.shape[0])`，而上段尾帧正是 min(上下文帧数, 段帧数) 帧），
    供 裁前缀帧数 裁掉本段被锚定的重复前缀。本段比上下文还短时钳到本段全长，锚帧数
    随之按 _latent_t_转帧数 回算，保证「切了多少 latent」与「裁掉多少帧」始终同源。
    切片用 .clone()：返回值会被塞进下段 conditioning 并落进段缓存，不能是上游 latent 的视图
    （视图会让整段 latent 无法回收，10 段就把方案 B 省下的显存全吃回去）。"""
    if int(上下文帧数) <= 0 or video_latent is None:
        return None, None, 0
    锚帧数 = 规范锚帧数(上下文帧数)
    token数 = _帧数转token数(锚帧数)          # “锚帧数 帧占几个 token”，非 _video_latent_t（后者 <=5 帧恒返 2）
    T_lat = int(video_latent.shape[2])
    if token数 > T_lat:                       # 本段比上下文还短 → 整段作锚
        token数 = T_lat
        锚帧数 = 规范锚帧数(_latent_t_转帧数(T_lat))
    尾帧_video = video_latent[:, :, -token数:, :, :].clone()

    尾帧_audio = None
    if audio_latent is not None:
        音频_token数 = max(1, int(round(锚帧数 * _FRAME_RESCALE)))
        音频_token数 = min(音频_token数, int(audio_latent.shape[-1]))   # 同官方 max_rt 钳制
        尾帧_audio = audio_latent[..., -音频_token数:].clone()
    return 尾帧_video, 尾帧_audio, 锚帧数


def 钉入上下文_from_latent(positive, latent, 尾帧_video_latent, 尾帧_audio_latent, 锚帧数, frame_idx=0):
    """把尾帧 latent 挂进 positive 的 minimax_keyframes（等价官方 MiniMaxH3AddGuide 的产出，
    但跳过 vae.encode / _encode_ref_audio）。返回新 positive。

    锚帧数 由调用方（执行时间轴）从 取尾帧_latent 取得后传入——段缓存指纹与实际锚定共用
    同一个值，避免「指纹算一套、真锚另一套」的假命中。尾帧_video_latent 为 None → 原样返回。
    latent 是本段 AV 空 latent，用于形态校验 + 取目标画布尺寸/总帧数/音频长度做越界与钳制
    （四条守卫口径逐字对齐官方 nodes_minimax_h3.py:190-233）：
      ① AV latent 形态（is_nested / 恰好 2 支 / 视频支 5 维 / 通道 24）；
      ② 尾帧 latent 的 H/W 等于本段画布（PackedLayout 按**目标**画布的 frame_rows 给 keyframe
         计行数，n = vt * frame_rows，尺寸不符会在模型内部炸成难定位的形状错）；
      ③ frame_idx 负值按官方语义「从末尾数」解析，解析后越界则抛；
      ④ 音频按**目标** T_audio 钳制（官方 max_rt），而非只按来源长度钳。
    四条均在当前编排下不可达（latent 恒来自 H3 条件节点的 _empty_av_latent、frame_idx 恒 0、
    目标与来源同时长），但它们是把「形状错在模型深处静默发生」前移成显式 ValueError 的唯一口子。"""
    if 尾帧_video_latent is None:
        return positive

    # 延迟 import：node_helpers 只在下方 conditioning_set_values 用到，而本函数首句就是无尾帧
    # 的早返回——把它放在早返回之前，等于给「一次也不锚定」的常态路径平白挂上一个宿主依赖。
    import node_helpers

    samples = latent["samples"]
    # ① 形态守卫：同官方 AddGuide L191。不放宽 is_nested/2 支：非 AV latent（如单视频管线的
    #    {"samples": Tensor}）没有音频时间轴，下方的 max_rt 钳制无从算起，让它早报错比静默锚错好。
    if (not getattr(samples, "is_nested", False) or len(samples.tensors) != 2
            or samples.tensors[0].ndim != 5 or int(samples.tensors[0].shape[1]) != 24):
        raise ValueError(
            "段间锚定需要 MiniMax H3 的 AV latent（嵌套形态、恰好 video+audio 两支、"
            "video 为 [B,24,T,H,W]）；实际 latent 形态不符，请确认它来自 H3 条件节点"
            "（MiniMaxH3ImageToVideo / MiniMaxH3ReferenceToVideo）而非其他管线")
    video, 目标音频 = samples.tensors
    # ② 画布守卫
    if tuple(尾帧_video_latent.shape[3:]) != tuple(video.shape[3:]):
        raise ValueError(
            f"段间锚定的尾帧 latent 空间尺寸 {tuple(尾帧_video_latent.shape[3:])} 与本段画布 "
            f"{tuple(video.shape[3:])} 不符；PackedLayout 按目标画布行数打包 keyframe，"
            f"尺寸不符会在模型内部炸成难以定位的形状错误")
    总帧数 = _latent_t_转帧数(int(video.shape[2]))
    # ③ frame_idx 解析 + 越界守卫（官方 L211-216 同式：负值从末尾数）
    锚位 = int(frame_idx) if int(frame_idx) >= 0 else 总帧数 + int(frame_idx)
    if 锚位 < 0 or 锚位 + int(锚帧数) > 总帧数:
        raise ValueError(
            f"锚定 {锚帧数} 帧于 frame_idx={int(frame_idx)}（解析为第 {锚位} 帧）超出本段 "
            f"{总帧数} 帧；请调小「上下文帧数」或加长本段时长")

    keyframe = {"resolved_frame_index": 锚位, "latent": 尾帧_video_latent}
    if 尾帧_audio_latent is not None:
        # ④ 音频钳制：两条流共用一条时间轴（每像素帧 FRAME_RESCALE、每音频 latent 帧 1.0），
        #    故本段音频轨从 锚位 起只剩 max_rt 个 token 可放（官方 L228-232 同式）。
        #    int() 而非 math.floor：二者对 >=1 的值全同，而 <1 时一律走 raise 分支，不取到切片长度。
        max_rt = int(目标音频.shape[-1] - _FRAME_RESCALE * 锚位)
        if max_rt < 1:
            raise ValueError(
                f"frame_idx={int(frame_idx)}（解析为第 {锚位} 帧）已超出本段音频轨末尾，"
                f"无法锚定尾帧音频")
        if int(尾帧_audio_latent.shape[-1]) > max_rt:
            尾帧_audio_latent = 尾帧_audio_latent[..., :max_rt].clone()
        keyframe["audio_latent"] = 尾帧_audio_latent
    keyframes = list(positive[0][1].get("minimax_keyframes", []))
    keyframes.append(keyframe)
    return node_helpers.conditioning_set_values(positive, {"minimax_keyframes": keyframes})
