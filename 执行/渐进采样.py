# -*- coding: utf-8 -*-
"""SelfLift 渐进分辨率采样：单段内「低清前缀 k 步 → latent 抬升 → 高清剩余 步数−k 步」。

为什么必须换宿主自定义采样链：官方 `KSampler` 节点只吃 `steps/sampler_name/scheduler`
字符串，不接受切片 sigmas，无法把一段的 N 步拆成两阶段。而
`RandomNoise + CFGGuider + KSamplerSelect + BasicScheduler + SamplerCustomAdvanced`
与 `KSampler` 节点走的是**同一个** comfy 入口（静态核对，非实测结论）：
    nodes.py `KSampler` → `common_ksampler` → `comfy.sample.sample`
      → `comfy.samplers.KSampler.sample` → `comfy.samplers.sample`
      → `CFGGuider(model).set_conds/set_cfg` → `guider.sample(noise, latent_image, sampler, sigmas, ...)`
末行正是 `SamplerCustomAdvanced.execute` 里的同一次调用。差异只有 ① 采样器名（本模块强制
euler）② `SamplerCustomAdvanced` 额外把最后一步的 x0 经 `process_latent_out` 作为
`denoised_output` 返回——本模块要的就是那个 x0，无需回调或 monkeypatch。

过渡公式与参考实现 `ComfyUI_MiniMaxH3_Director/director/selflift/sample.py:450-477` 同解，
但用宿主约定表达（故不在本模块里手写 noise_scaling / Euler / 反缩放）：参考实现先
`noise_scaling(σ_{k-1}, ε, z0_high)`，再一步 Euler 到 σ_k：
    x(σ_k) = x(σ_{k-1}) + (x − z0)/σ_{k-1} · (σ_k − σ_{k-1})
           = σ_k·ε + (1 − σ_k)·z0_high     （代入 x(σ_{k-1}) = σ_{k-1}ε + (1−σ_{k-1})z0 展开即得）
而宿主采样器对「从 σ_j 起步」的构造恰是 `noise_scaling(sigmas[0]=σ_j, ε, latent_image)`
⇒ 把抬升后的 x0 当作高清阶段的 `latent_image`、切片 `sigmas[k:]`、ε 用 `种子+1`，与参考实现
的三步显式写法等值。参考实现额外做了 `inverse_noise_scaling(σ_k, ·) = ÷(1−σ_k)`，下一阶段的
`noise_scaling` 会把噪声幅度叠成约 2σ_k；本模块**不除**，于是 σ 阶梯与「同参数单阶段跑」逐值
一致——A/B/C 对照只测出分辨率差异，不掺过渡引入的额外噪声。

音频支不参与空间抬升：取低清最后一步的 x0 原样交给高清阶段（`process_latent_in/out` 里
AV 类只对音频切片乘 `audio_scale`，而 `CONST.noise_scaling` 的噪声项**不**乘该系数，故任何
在本模块内手工重加噪的写法都会落到「噪声与信号不同空间」的坑里；交回宿主采样器则与单阶段
路径完全同构，零新增风险）。
"""
import time

import torch

# ⚠️ H3潜空间放大 只在 _抬升 内惰性 import：它经 后处理缓存 → 精修条件 → 执行核心 绕回本模块的
# 消费者（执行核心），模块级引入会构成循环导入（执行核心 先到 渐进采样 时拿到半初始化模块）。
# 与 后处理核心 用 加载H3放大模型 时的惰性写法同口径。
from .采样与解码 import CANVAS_MULTIPLE
from .段间连续 import 缩放视频latent空间
from .官方管线适配 import 官方节点可用, 调用节点

配置类型名 = "LVP_SELFLIFT_CONFIG"
配置版本 = 1
采样器要求 = "euler"
缩放下限 = 0.25
_权重未选 = "未选择"

_自定义链 = ("RandomNoise", "CFGGuider", "KSamplerSelect", "BasicScheduler", "SamplerCustomAdvanced")


def 自定义链缺失():
    """宿主自定义采样链里尚未注册的节点名（空列表 = 可用）。供执行核心在采样前点名提示。"""
    return [名 for 名 in _自定义链 if not 官方节点可用(名)]


def 构造配置(低清缩放, 高清步数, 放大权重, 允许插值降级):
    """SelfLift配置 节点的产物：只做类型归一，语义校验留给 校验配置（单一真源，防两处规则漂移）。

    放大权重 的「未选择」归一为 None：None 且未勾选降级 = 配置不完整，由 校验配置 报错，
    本函数不报错（节点侧 widget 默认值就是这个组合，报错会让节点每次刷新都红）。"""
    权重 = 放大权重 if isinstance(放大权重, str) and 放大权重 != _权重未选 else None
    return {"type": 配置类型名, "version": 配置版本,
            "低清缩放": float(低清缩放), "高清步数": int(高清步数),
            "放大权重": 权重, "允许插值降级": bool(允许插值降级)}


def 低清画布(宽, 高, 缩放):
    """目标画布 × 缩放 后对齐 CANVAS_MULTIPLE(32)；latent 尺寸由像素 ÷16 得到，故 32 倍数是硬要求。

    平局按 `round()` 取偶，与 采样与解码.对齐画布 同口径（勿改半进位）。钳到不低于一个 32 格，
    并拒绝「取整后等于原尺寸」——那等于没降分辨率，只是白跑一次抬升。"""
    宽, 高 = int(宽), int(高)
    for 名, 值 in (("宽", 宽), ("高", 高)):
        if 值 <= 0 or 值 % CANVAS_MULTIPLE:
            raise ValueError(f"渐进采样的目标画布{名}须为 {CANVAS_MULTIPLE} 的正倍数，收到 {值}")
    缩放 = float(缩放)
    if not 缩放下限 <= 缩放 < 1.0:
        raise ValueError(f"低清缩放须在 [{缩放下限}, 1.0) 区间（1.0 等于不启用），收到 {缩放}")
    低宽 = max(CANVAS_MULTIPLE, round(宽 * 缩放 / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
    低高 = max(CANVAS_MULTIPLE, round(高 * 缩放 / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
    if (低宽, 低高) == (宽, 高):
        raise ValueError(f"低清缩放 {缩放} 在画布 {宽}x{高} 上取整后仍是原尺寸，没有降分辨率；请调小低清缩放或加大目标画布")
    return 低宽, 低高


def 划分步数(步数, 高清步数):
    """低清步数 k = 步数 − 高清步数，强制 1 ≤ k ≤ 步数−1（两阶段各至少一步，否则接缝无意义）。"""
    步数, 高清步数 = int(步数), int(高清步数)
    if 步数 < 2:
        raise ValueError(f"渐进采样需要至少 2 步（低清与高清各至少 1 步），收到 步数={步数}")
    if not 1 <= 高清步数 <= 步数 - 1:
        raise ValueError(f"高清步数须在 1 到 {步数 - 1}（=步数-1）之间，收到 {高清步数}")
    return 步数 - 高清步数


def 校验配置(配置, *, 采样器, 步数, 宽, 高):
    """采样前门控 → (低宽, 低高, k)。不合法一律 ValueError 点名参数，绝不静默回退普通路径。

    强制 euler：过渡等价性（模块头推导）只在「一阶确定性步 + s_churn=0」下成立；
    祖先/带 churn 的采样器每步自带新噪声，接缝处的噪声连续性无定义。"""
    if type(配置) is not dict or 配置.get("type") != 配置类型名:
        raise ValueError(f"渐进采样配置类型未知：{配置!r}")
    if 配置.get("version") != 配置版本:
        raise ValueError(f"未知渐进采样配置版本：{配置.get('version')!r}")
    if str(采样器) != 采样器要求:
        raise ValueError(
            f"渐进采样只支持采样器「{采样器要求}」（过渡公式按 euler 一阶步推导），当前是「{采样器}」；"
            f"请把节点采样器改为 euler，或断开 SelfLift配置 回退普通采样")
    低宽, 低高 = 低清画布(宽, 高, 配置["低清缩放"])
    k = 划分步数(步数, 配置["高清步数"])
    if 配置.get("放大权重") is None and not 配置.get("允许插值降级"):
        raise ValueError("渐进采样需要在「放大模型」里选一个 H3 潜空间放大模型；若要改用双线性插值抬升（画质明显更差），请显式勾选「允许插值降级」")
    return 低宽, 低高, k


def 指纹维度(配置, 权重摘要=None):
    """→ 执行核心.构建采样参数 用的 JSON-safe 维度；配置为 None（未连接）时返回 None。

    关闭态返回 None 而非空 dict：给既有非 SelfLift 段的采样参数凭空加键会让指纹全变，
    而语义上什么都没发生。权重摘要（文件内容哈希）与权重名并列：同名换文件也要失效。"""
    if 配置 is None:
        return None
    return {"低清缩放": float(配置["低清缩放"]), "高清步数": int(配置["高清步数"]),
            "放大权重": 配置.get("放大权重"), "允许插值降级": bool(配置.get("允许插值降级")),
            "权重摘要": 权重摘要}


def _两支(latent, 描述):
    """嵌套 AV latent → (video, audio)；形态不符即 ValueError（本模块只服务 H3 的 AV latent）。"""
    samples = latent.get("samples") if type(latent) is dict else None
    张量 = getattr(samples, "tensors", None)
    if not getattr(samples, "is_nested", False) or not isinstance(张量, (list, tuple)) or len(张量) != 2:
        raise ValueError(f"{描述}须是嵌套 AV latent（恰好 video+audio 两支）")
    return 张量[0], 张量[1]


def _单阶段(条件, latent, 模型, 采样器, sigmas, 种子):
    """一次「噪声→guider→切片 sigmas→采样」的宿主自定义链调用，返回 (output, denoised_output)。

    cfg=1.0 ⇒ negative 分支被跳过，故 negative 与 positive 同值（与 执行核心._采样段 的
    KSampler 调用一致）。种子直接透传给 RandomNoise：其内部就是
    `comfy.sample.prepare_noise(latent["samples"], seed)`，与参考实现的取噪方式同一。"""
    return 调用节点("SamplerCustomAdvanced",
                    noise=调用节点("RandomNoise", noise_seed=int(种子))[0],
                    guider=调用节点("CFGGuider", model=模型, positive=条件, negative=条件,
                                    cfg=1.0)[0],
                    sampler=采样器, sigmas=sigmas, latent_image=latent)[:2]


def _抬升(视频x0, 目标宽, 目标高, 权重信息, 允许插值降级):
    """低清 x0 视频支 → 目标画布的 latent 尺寸；有权重走 H3 专用 3D 网络，无权重只在显式勾选后插值。

    抬升只改空间维：token 数（时间轴）与通道数原样保留，故 帧数/锚帧数/音频时间网格 全不变，
    段间连续与 Phase 2 解码无需感知本模块。"""
    from .H3潜空间放大 import 加载H3放大模型, 放大H3视频latent   # 惰性：见模块头循环导入说明
    if not bool(torch.isfinite(视频x0).all()):
        raise ValueError("低清阶段的 x0 含非有限值（NaN/Inf），无法抬升；请调大低清缩放或增加步数，或断开 SelfLift配置 回退普通采样")
    高, 宽 = int(目标高) // 16, int(目标宽) // 16
    if 权重信息 is not None:
        with 加载H3放大模型(权重信息) as 放大模型:
            out = 放大H3视频latent(视频x0.detach().cpu(), 放大模型, int(目标宽), int(目标高))
    elif 允许插值降级:
        out = 缩放视频latent空间(视频x0, 高, 宽)
    else:
        raise ValueError("渐进采样缺少「放大模型」里选中的 H3 潜空间放大模型，且未勾选「允许插值降级」")
    if tuple(out.shape[-2:]) != (高, 宽):
        raise ValueError(f"抬升后的 latent 尺寸 {tuple(out.shape[-2:])} 与目标画布的 latent 尺寸 {(高, 宽)} 不符")
    return out


def 渐进采样段(*, 低清条件, 低清latent, 高清条件, 高清latent, 模型, 调度器, 步数,
               种子, 切换步, 目标宽, 目标高, 权重信息=None, 允许插值降级=False):
    """跑完一个段的三阶段，返回 (采样产物, {"低清采样": 秒, "抬升": 秒, "高清采样": 秒})。

    采样产物与普通 KSampler 路径同形（`{"samples": NestedTensor(video, audio)}`，CPU），
    故 `_拆_av_latent`、段缓存落盘、Phase 2 解码、流式拼接全部无感。

    NFE 恒等：低清吃 `sigmas[:k+1]`（k 次前向）、高清吃 `sigmas[k:]`（步数−k 次），σ_k 只作
    接缝共享、不额外占一次前向 ⇒ 总前向数 == 步数（与单阶段同种子同步步数完全相同）。

    两阶段的条件与空 latent 由调用方（执行核心）按各自画布各建一份：官方条件节点与
    MiniMaxH3AddGuide 都从传入的 width/height/latent 推导画布，故低清条件天然带低清首/尾帧
    与参考图；只有**上一段尾块的锚定 latent** 需要调用方先用 段间连续.缩放视频latent空间
    降到低清尺寸（高清阶段仍用原始高清尾块，连续性由高清阶段保证）。"""
    from comfy.nested_tensor import NestedTensor

    k = int(切换步)
    步数 = int(步数)
    if not 1 <= k <= 步数 - 1:
        raise ValueError(f"切换步 k 须在 1 到 {步数 - 1} 之间，收到 {k}")
    采样器 = 调用节点("KSamplerSelect", sampler_name=采样器要求)[0]
    sigmas = 调用节点("BasicScheduler", model=模型, scheduler=str(调度器),
                      steps=步数, denoise=1.0)[0]
    if int(sigmas.numel()) != 步数 + 1:
        raise ValueError(f"调度器「{调度器}」给出 {sigmas.numel()} 个 sigma，与 步数+1={步数 + 1} 不符，无法切分两阶段")

    时刻0 = time.perf_counter()
    x0低 = _单阶段(低清条件, 低清latent, 模型, 采样器, sigmas[:k + 1], 种子)[1]
    低清秒 = time.perf_counter() - 时刻0

    时刻1 = time.perf_counter()
    视频x0, 音频x0 = _两支(x0低, "低清阶段的 x0")
    抬升视频 = _抬升(视频x0, 目标宽, 目标高, 权重信息, bool(允许插值降级))
    高视, 高音 = _两支(高清latent, "高清阶段的空 latent")
    if tuple(音频x0.shape) != tuple(高音.shape):
        raise ValueError(
            f"低清阶段的音频支 {tuple(音频x0.shape)} 与高清画布的音频支 {tuple(高音.shape)} 不符；"
            f"两阶段必须同帧数、同音频时间网格（帧数与分辨率无关，出现此错说明两阶段条件参数不一致）")
    高清起点 = dict(高清latent)
    高清起点["samples"] = NestedTensor([
        抬升视频.to(device=高视.device, dtype=高视.dtype),
        音频x0.to(device=高音.device, dtype=高音.dtype)])
    抬升秒 = time.perf_counter() - 时刻1

    时刻2 = time.perf_counter()
    产物 = _单阶段(高清条件, 高清起点, 模型, 采样器, sigmas[k:], (int(种子) + 1) % (1 << 64))[0]
    高清秒 = time.perf_counter() - 时刻2
    return 产物, {"低清采样": 低清秒, "抬升": 抬升秒, "高清采样": 高清秒}
