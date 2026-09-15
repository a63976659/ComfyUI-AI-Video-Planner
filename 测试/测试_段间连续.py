# -*- coding: utf-8 -*-
import pytest
import torch

from 执行.段间连续 import (crossfade权重, 裁前缀帧数, 帧交叉淡化, 拼接段, 规范锚帧数, 默认上下文帧数,
                          预算总帧数, 流式拼接, 取尾帧_latent, 钉入上下文_from_latent,
                          _FRAME_PER_TOKEN, _FRAME_RESCALE, _latent_t_转帧数, _video_latent_t,
                          _帧数转token数)

try:
    from comfy.nested_tensor import NestedTensor as _官方嵌套
except ImportError:      # 裸 pytest 且未把 ComfyUI 根入 sys.path 时：用只带 is_nested/tensors 的替身
    _官方嵌套 = None     # （钉入上下文_from_latent 只读这两个属性，不依赖 unbind 等其他方法）


def _嵌套(张量列表):
    """官方 comfy NestedTensor（优先）或最小替身：钉入上下文_from_latent 的形态守卫要求
    is_nested 为真且 tensors 恰好两支（同官方 AddGuide L191），故测试必须造嵌套形态。"""
    if _官方嵌套 is not None:
        return _官方嵌套(张量列表)
    return type("_替身嵌套", (), {"is_nested": True, "tensors": list(张量列表)})()


def test_默认上下文帧数():
    assert 默认上下文帧数 == 22


def test_规范锚帧数():
    assert 规范锚帧数(22) == 22   # 22 % 17 == 5，合法锚 clip
    assert 规范锚帧数(5) == 5
    assert 规范锚帧数(3) == 1     # 官方：<5 帧只用首帧
    assert 规范锚帧数(40) == 39   # 向下取 17k+5
    # 边界
    assert 规范锚帧数(0) == 1
    assert 规范锚帧数(4) == 1
    assert 规范锚帧数(17) == 5
    assert 规范锚帧数(21) == 5
    assert 规范锚帧数(124) == 124
    # 幂等性：规范锚帧数输出必是合法锚 clip，再归一化不变
    for i in range(300):
        assert 规范锚帧数(规范锚帧数(i)) == 规范锚帧数(i)


def test_裁前缀帧数_正常():
    assert 裁前缀帧数(124, 22) == 22
    assert 裁前缀帧数(0, 22) == 0        # 帧数-1 下限保护
    assert 裁前缀帧数(124, 25) == 22     # 上下文 25→规范 22（降格路径）
    assert 裁前缀帧数(124, 0) == 0       # 无锚上下文，短路返回 0


def test_裁前缀帧数_上限保护():
    assert 裁前缀帧数(10, 22) == 9   # 不超过 帧数-1
    assert 裁前缀帧数(1, 22) == 0
    assert 裁前缀帧数(124, -5) == 0  # 负上下文（无锚）短路返回 0，不误裁首帧


def test_crossfade权重_端点():
    w = crossfade权重(5)
    assert len(w) == 5
    assert w[0] == 0.0 and w[-1] == 1.0
    assert all(0.0 <= x <= 1.0 for x in w)
    assert w == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_crossfade权重_退化():
    assert crossfade权重(1) == [1.0]
    assert crossfade权重(0) == [1.0]


def test_帧交叉淡化_正常路径():
    前段 = torch.ones(10, 2, 2, 3)   # 前段尾全 1
    后段 = torch.zeros(10, 2, 2, 3)  # 后段头全 0
    out = 帧交叉淡化(前段, 后段, 4)
    assert out.shape == (4, 2, 2, 3)
    # 尾*(1-w)+头*w = 1-w = [1.0, 0.667, 0.333, 0.0]
    assert out[:, 0, 0, 0].tolist() == pytest.approx([1.0, 2 / 3, 1 / 3, 0.0], abs=1e-5)


def test_帧交叉淡化_输入守卫():
    前段 = torch.ones(10, 2, 2, 3)
    后段 = torch.zeros(10, 2, 2, 3)
    with pytest.raises(ValueError):
        帧交叉淡化(前段, 后段, 0)    # 零重叠
    with pytest.raises(ValueError):
        帧交叉淡化(前段, 后段, -1)   # 负重叠（曾静默返回错形状）
    with pytest.raises(ValueError):
        帧交叉淡化(前段, 后段, 15)   # 越界：>min(前段尾, 后段头)


def test_拼接段_帧数不变式():
    段列表 = [torch.zeros(10, 2, 2, 3) for _ in range(3)]
    out = 拼接段(段列表, 4)
    # Σ输入(30) − Σ接缝重叠(2×4=8) = 22
    assert out.shape[0] == 22


def test_拼接段_空与单段():
    assert 拼接段([], 4) is None
    单段 = torch.zeros(7, 2, 2, 3)
    out = 拼接段([单段], 4)
    assert out is 单段
    assert out.shape[0] == 7


def test_拼接段_帧序单调():
    # 段 i 全填 i+1，接缝 crossfade 应线性过渡，帧序整体单调不减
    段列表 = [torch.full((10, 2, 2, 3), float(i + 1)) for i in range(3)]
    out = 拼接段(段列表, 4)
    vals = out[:, 0, 0, 0]
    assert bool((vals[:-1] <= vals[1:] + 1e-6).all())


# ---------- C1：流式拼接（预分配成片，峰值内存 = 成片 + 当前段） ----------

def test_流式拼接_与拼接段同值():
    """C1 核心契约锁：流式拼接（就地写入预分配成片）必须与 拼接段（攒齐再折叠）**逐元素相等**。
    依据：拼接段 的折叠式只读 结果 的末 重叠 帧、只写其后，故「就地覆盖接缝区 + 追写剩余」
    与「重新 cat 一份」同值。不相等就意味着 Phase 2 换写法后成片画面静默变了——而它存在的唯一
    理由是把 CPU 内存峰值从 ≈3N 段量压到 N+1（1.0MP@16s 下 3 段 ≈40GB → ≈20GB）。"""
    for 段帧数 in ([10, 10, 10], [7], [10, 3], [3, 10], [1, 10], [2, 2], [5, 5, 5, 5], [124, 119]):
        段列表 = [torch.full((n, 2, 2, 3), float(i + 1)) for i, n in enumerate(段帧数)]
        期望 = 拼接段(段列表, 4)
        拼 = 流式拼接(预算总帧数(段帧数, 4), 重叠帧数=4)
        for 段 in 段列表:
            拼.追加(段)
        实际 = 拼.结果()
        assert 实际.shape == 期望.shape, f"{段帧数}: 形状 {tuple(实际.shape)} != {tuple(期望.shape)}"
        assert torch.equal(实际, 期望), f"{段帧数}: 逐元素不等（接缝 crossfade 写错位）"


def test_流式拼接_空与忽略():
    """边界：一段也没写 → None（对齐 拼接段([]) 与执行核心「images is None → ValueError」的入口契约）；
    None / 0 帧段直接忽略，不占预算也不建 buf。"""
    拼 = 流式拼接(10, 4)
    assert 拼.结果() is None
    拼.追加(None).追加(torch.zeros(0, 2, 2, 3))
    assert 拼.结果() is None, "0 帧段不得触发分配"
    拼.追加(torch.zeros(6, 2, 2, 3))
    assert 拼.结果().shape[0] == 6


def test_流式拼接_越界不静默丢帧():
    """预算不足即抛 ValueError：不得靠 torch 切片赋值报难定位的 RuntimeError、更不得静默丢帧
    （丢帧 = 成片时长短于时间轴且无任何告警）。诱因通常是段缓存里的 帧数 与 latent 不自洽。"""
    拼 = 流式拼接(5, 4)
    拼.追加(torch.zeros(5, 2, 2, 3))
    with pytest.raises(ValueError, match="超出预算成片长度"):
        拼.追加(torch.zeros(5, 2, 2, 3))
    # 首段就超预算也必须抛（不得先分配一块不够大的 buf 再越界写）
    with pytest.raises(ValueError, match="超出预算成片长度"):
        流式拼接(3, 4).追加(torch.zeros(5, 2, 2, 3))


def test_预算总帧数_与拼接不变式同式():
    """预算必须与 拼接段/流式拼接 的折叠式同式（首段全取、其后每段净减 min(重叠, 本段, 已累计)），
    否则执行核心 Phase 2 的预分配尺寸对不上实际写入量 → 要么越界抛、要么成片尾部多一块未写入垃圾。"""
    assert 预算总帧数([], 4) == 0
    assert 预算总帧数([10], 4) == 10
    assert 预算总帧数([10, 10, 10], 4) == 22      # Σ30 − 2×4（同 test_拼接段_帧数不变式）
    assert 预算总帧数([10, 0, 10], 4) == 16       # 0 帧段跳过
    assert 预算总帧数([2, 2], 4) == 2             # 重叠钳到 min(4, 2, 2)
    assert 预算总帧数([1, 10], 4) == 10           # 重叠钳到 min(4, 10, 1)
    for 段帧数 in ([10, 10, 10], [7], [10, 3], [1, 10], [2, 2], [5, 5, 5, 5]):
        assert 预算总帧数(段帧数, 4) == 拼接段(
            [torch.zeros(n, 2, 2, 3) for n in 段帧数], 4).shape[0]


# ---------- 方案 B：段间锚定直接传 latent（免 decode→encode 往返） ----------

def test_video_latent_t_复刻官方公式():
    """契约锁：必须逐字等同官方 nodes_minimax_h3.video_latent_t（frame_count<=5→2，否则
    ((n-5)//17)*5+2）。它是「latent token 数 ↔ 像素帧数」换算的唯一入口，算错会让段间锚定
    切错长度的尾帧（多切是重复画面、少切是丢锚），且形状兼容不报错。"""
    assert _video_latent_t(1) == 2 and _video_latent_t(5) == 2      # <=5 恒 2
    assert _video_latent_t(22) == 7                                  # 默认上下文帧数
    assert _video_latent_t(39) == 12
    assert _video_latent_t(124) == 37                                # 5 秒 @24fps 对齐后
    # 对齐帧数网格 17k+5 → T_lat=5k+2，故 T_lat ≡ 2 (mod 5) 恒成立：
    # 这正是「从尾部切 5m+2 个 token 与官方 k=0 起始同相位」的前提（见 test_尾切片同相位）
    for k in range(20):
        assert _video_latent_t(17 * k + 5) == 5 * k + 2


def test_latent_t_转帧数_逆换算与畸形输入():
    """_video_latent_t 的逆：逐 token 累加 FRAME_PER_TOKEN（同官方 MiniMaxH3AddGuide 里
    `sum(FRAME_PER_TOKEN[k % 5] for k in range(vt))`）。对齐网格上二者严格互逆；非对齐/畸形
    T_lat 只算出对应帧数、不抛（越界守卫归 钉入上下文_from_latent）。"""
    assert sum(_FRAME_PER_TOKEN[i % 5] for i in range(7)) == 22
    assert _latent_t_转帧数(7) == 22
    assert _latent_t_转帧数(2) == 5
    for k in range(20):                       # 互逆：帧数 → T_lat → 帧数
        n = 17 * k + 5
        assert _latent_t_转帧数(_video_latent_t(n)) == n
    assert _latent_t_转帧数(0) == 0 and _latent_t_转帧数(-3) == 0


def test_尾切片与官方时间栅格同相位():
    """方案 B 的核心数学依据：从 T_lat=5k+2 的尾部切 5m+2 个 token，其**绝对**下标 mod 5 的
    序列恰为 0,1,2,3,4,0,1…，与 PackedLayout 按 k=0.. 生成 _video_t_spans 的相位一致 →
    尾帧 latent 的时间栅格与官方 vae.encode 路径逐值相同。若日后 FRAME_PER_TOKEN 周期不再是 5、
    或切取长度不再取 5m+2，本测必红（那种情况下尾帧锚定会静默错位而非报错）。"""
    T_lat = _video_latent_t(17 * 3 + 5)          # 56 帧段 → 17 token
    m = _video_latent_t(22)                      # 22 帧锚 → 7 token
    绝对下标 = list(range(T_lat - m, T_lat))
    assert [i % 5 for i in 绝对下标] == [k % 5 for k in range(m)]
    assert sum(_FRAME_PER_TOKEN[i % 5] for i in 绝对下标) == 22   # 切出来的正是 22 像素帧


def test_取尾帧_latent_锚帧数与token数同源():
    """video 切 _帧数转token数(锚帧数) 个 token（网格值上 == _video_latent_t(锚帧数)）、audio 切
    round(锚帧数 * 5/3) 个（官方 FRAME_RESCALE=40/24，按**像素帧数**换算）。⚠️ 不是「视频 token 数
    × 5/3」——那样 22 帧会算出 12 而非 37，锚音频比锚画面短近一半，A/V 从第一段接缝起就错位且无声。
    返回的 锚帧数 供下游 裁前缀帧数 裁掉重复前缀，与切取长度必须同源。"""
    v = torch.zeros(1, 24, 37, 4, 4)          # 124 帧段的 latent
    a = torch.zeros(1, 32, 2, 207)            # round(124*5/3)=207
    尾v, 尾a, 锚 = 取尾帧_latent(v, a, 22)
    assert 锚 == 规范锚帧数(22) == 22
    assert tuple(尾v.shape) == (1, 24, _video_latent_t(22), 4, 4)
    assert 尾a.shape[-1] == int(round(22 * _FRAME_RESCALE)) == 37
    # 切的是**尾部**不是头部：末 token 打标记后应落在切片末位
    v[:, :, -1, :, :] = 1.0
    尾v2, _a2, _锚2 = 取尾帧_latent(v, a, 22)
    assert 尾v2[:, :, -1].min().item() == 1.0 and 尾v2[:, :, 0].max().item() == 0.0


def test_取尾帧_latent_返回clone非视图():
    """返回值会被塞进下段 conditioning 并落进段缓存，必须是 clone 而非上游 latent 的视图：
    视图会让整段 latent 无法回收（10 段就把方案 B 省下的显存全吃回去）。用「改源不影响尾」
    反证——只比 data_ptr 抓不到 clone 被换成 narrow/slice 的回归。"""
    v = torch.zeros(1, 24, 37, 4, 4)
    a = torch.zeros(1, 32, 2, 207)
    尾v, 尾a, _锚 = 取尾帧_latent(v, a, 22)
    v[:, :, -7:, :, :] = 5.0
    a[..., -37:] = 5.0
    assert 尾v.abs().max().item() == 0.0, "尾帧视频 latent 随源改动 → 是视图而非 clone"
    assert 尾a.abs().max().item() == 0.0, "尾帧音频 latent 随源改动 → 是视图而非 clone"


def test_取尾帧_latent_短段整段作锚():
    """本段比上下文还短（T_lat < 所需 token 数）→ 整段作锚，且 锚帧数 按 _latent_t_转帧数
    回算：保证「切了多少 latent」与「裁掉多少帧」始终同源。否则 _裁并拼 会按 22 帧去裁一个
    实际只锚了 3 token 的段 → 凭空丢掉真实画面。"""
    v = torch.zeros(1, 24, 3, 4, 4)
    a = torch.zeros(1, 32, 2, 100)
    尾v, 尾a, 锚 = 取尾帧_latent(v, a, 22)
    assert 尾v.shape[2] == 3                                   # 整段
    assert _latent_t_转帧数(3) == 9 and 锚 == 规范锚帧数(9) == 5
    assert 尾a.shape[-1] == int(round(5 * _FRAME_RESCALE))     # 音频随回算后的锚帧数走


def test_取尾帧_latent_音频不足钳到可用长度():
    """音频 latent 比换算值短 → 钳到可用长度（同官方 max_rt 钳制），不得越界切出空张量。"""
    a = torch.zeros(1, 32, 2, 4)
    _尾v, 尾a, 锚 = 取尾帧_latent(torch.zeros(1, 24, 37, 4, 4), a, 22)
    assert 锚 == 22 and 尾a.shape[-1] == 4


def test_取尾帧_latent_无锚与无音频():
    """三条边界：上下文帧数<=0 / video_latent 为 None → (None,None,0)（首段与断裂处的契约）；
    音频 latent 为 None（audio_vae 未接）→ 只返回视频尾帧，音频侧为 None。"""
    视频 = torch.zeros(1, 24, 37, 4, 4)
    assert 取尾帧_latent(None, None, 22) == (None, None, 0)
    assert 取尾帧_latent(视频, None, 0) == (None, None, 0)
    assert 取尾帧_latent(视频, None, -1) == (None, None, 0)
    尾v, 尾a, 锚 = 取尾帧_latent(视频, None, 22)
    assert 尾a is None and 锚 == 22 and 尾v.shape[2] == 7


def _正条件():
    """官方形态的 positive：[(cond_dict, {"minimax_keyframes": [...]})]。"""
    return [({"text": "P"}, {"minimax_keyframes": []})]


def _空latent(T_lat=37, H=4, W=4, T_audio=207):
    """本段 AV 空 latent，**官方嵌套形态**（video [1,24,T,H,W] + audio [1,32,2,T_audio]）。

    必须嵌套：钉入上下文_from_latent 的形态守卫逐字对齐官方 AddGuide L191（is_nested / 恰好 2 支 /
    video 5 维 / 通道 24），而生产路径上它恒来自官方 _empty_av_latent（无条件同时造两支）。
    旧版测试用的是非嵌套 {"samples": Tensor}，恰好把生产实际走的那一行（samples.tensors[0]）排除在
    覆盖之外（L5）——守卫加严后那种形态已被正面拒收。
    默认 T_lat=37 → 总帧数 _latent_t_转帧数(37)=124；T_audio=207 = round(124*5/3)，与官方同口径。"""
    return {"samples": _嵌套([torch.zeros(1, 24, T_lat, H, W), torch.zeros(1, 32, 2, T_audio)])}


def test_钉入上下文_from_latent_挂keyframe():
    """等价官方 MiniMaxH3AddGuide 的产出：尾帧 latent 追加进 positive 的 minimax_keyframes，
    resolved_frame_index=frame_idx、音频挂 audio_latent 键；返回**新** positive
    （conditioning_set_values 不改原对象）。"""
    尾v = torch.zeros(1, 24, 7, 4, 4)
    尾a = torch.zeros(1, 32, 2, 37)
    正 = _正条件()
    新 = 钉入上下文_from_latent(正, _空latent(), 尾v, 尾a, 22, frame_idx=0)
    kf = 新[0][1]["minimax_keyframes"]
    assert len(kf) == 1 and kf[0]["resolved_frame_index"] == 0
    assert kf[0]["latent"] is 尾v and kf[0]["audio_latent"] is 尾a
    assert 正[0][1]["minimax_keyframes"] == [], "不得原地改写传入的 positive"
    # 无音频：不挂 audio_latent 键（audio_vae 未接时 keyframe 只有画面，同官方语义）
    新2 = 钉入上下文_from_latent(_正条件(), _空latent(), 尾v, None, 22)
    assert "audio_latent" not in 新2[0][1]["minimax_keyframes"][0]
    # 尾帧为 None（首段/断裂处）：原样返回同一对象，不挂任何 keyframe
    assert 钉入上下文_from_latent(正, _空latent(), None, None, 0) is 正


def test_钉入上下文_from_latent_空间尺寸守卫():
    """keyframe latent 的 H/W 必须等于本段画布：PackedLayout 按**目标画布**的 frame_rows 给
    keyframe 计行数（n = vt * frame_rows），尺寸不符会在模型内部炸成难定位的形状错，故前移为
    显式 ValueError（项目 ValueError-only 契约）。"""
    with pytest.raises(ValueError, match="空间尺寸"):
        钉入上下文_from_latent(_正条件(), _空latent(H=4, W=4),
                              torch.zeros(1, 24, 7, 2, 2), None, 22)


def test_钉入上下文_from_latent_越界守卫():
    """frame_idx + 锚帧数 > 本段总帧数 → ValueError（口径同官方 AddGuide 的越界检查）：
    锚超段长会让官方在时间栅格上算出负长度区间，报错点远在模型内部、无从定位。"""
    with pytest.raises(ValueError, match="超出本段"):
        # 本段 T_lat=2 → 5 帧；锚 22 帧于 frame_idx=0 显然越界
        钉入上下文_from_latent(_正条件(), _空latent(T_lat=2),
                              torch.zeros(1, 24, 2, 4, 4), None, 22)


def test_钉入上下文_from_latent_形态守卫():
    """M3①：latent 必须是 H3 的 AV latent（嵌套 / 恰好 2 支 / video 5 维 / 通道 24），同官方
    AddGuide L191。非 AV latent（如单视频管线的 {"samples": Tensor}）没有音频时间轴，下方的
    max_rt 钳制无从算起；不拦就会把一个 4 维像素张量当 latent 挂进 keyframe，到模型深处才炸。"""
    尾v = torch.zeros(1, 24, 7, 4, 4)
    坑 = {
        "非嵌套": {"samples": torch.zeros(1, 24, 37, 4, 4)},
        "只一支": {"samples": _嵌套([torch.zeros(1, 24, 37, 4, 4)])},
        "三支": {"samples": _嵌套([torch.zeros(1, 24, 37, 4, 4)] * 3)},
        "video四维": {"samples": _嵌套([torch.zeros(24, 37, 4, 4), torch.zeros(1, 32, 2, 207)])},
        "通道不是24": {"samples": _嵌套([torch.zeros(1, 16, 37, 4, 4), torch.zeros(1, 32, 2, 207)])},
    }
    拒收 = []
    for 名, 坑latent in 坑.items():
        with pytest.raises(ValueError, match="AV latent"):
            钉入上下文_from_latent(_正条件(), 坑latent, 尾v, None, 22)
        拒收.append(名)
    assert 拒收 == list(坑), "五种非 AV latent 形态均需被正面拒收"


def test_钉入上下文_from_latent_负frame_idx从末尾数():
    """M3②：frame_idx 负值按官方语义「从末尾数」解析（AddGuide L211），解析后越界则抛。
    旧版直接把负值写进 resolved_frame_index → 官方 PackedLayout 会把它当成负偏移，在时间栅格上
    算出错误区间且无报错。本插件当前恒传 0，本测锁的是“口子已封”。"""
    尾v = torch.zeros(1, 24, 7, 4, 4)
    新 = 钉入上下文_from_latent(_正条件(), _空latent(), 尾v, None, 22, frame_idx=-22)
    # 本段 124 帧 → -22 解析为第 102 帧（102 + 22 == 124，刚好容得下）
    assert 新[0][1]["minimax_keyframes"][0]["resolved_frame_index"] == 102
    with pytest.raises(ValueError, match="超出本段"):
        钉入上下文_from_latent(_正条件(), _空latent(), 尾v, None, 22, frame_idx=-200)


def test_钉入上下文_from_latent_音频按目标长度钳制():
    """M3③：音频 token 数按**本段（目标）**T_audio 钳制（官方 max_rt = T_audio − FRAME_RESCALE×锚位），
    而非只按来源长度钳。旧版只在 取尾帧_latent 里按来源钳 → 长段接短段时（来源尾音频比目标
    音轨还长）会把超量 token 挂进 keyframe，官方在音频时间轴上算出越界区间。"""
    尾v = torch.zeros(1, 24, 7, 4, 4)
    尾a = torch.zeros(1, 32, 2, 10)
    # 目标音轨只剩 3 个 token → 截到 3，且必须是 clone（官方 L232 同口径，不得是视图）
    新 = 钉入上下文_from_latent(_正条件(), _空latent(T_audio=3), 尾v, 尾a, 22)
    挂 = 新[0][1]["minimax_keyframes"][0]["audio_latent"]
    assert 挂.shape[-1] == 3 and 挂 is not 尾a
    # 目标音轨够长 → 原对象直接挂（不做无谓拷贝）
    新2 = 钉入上下文_from_latent(_正条件(), _空latent(T_audio=207), 尾v, 尾a, 22)
    assert 新2[0][1]["minimax_keyframes"][0]["audio_latent"] is 尾a
    # 锚位已过音轨末尾（max_rt < 1）→ 抛，不得挂一个空音频 latent
    with pytest.raises(ValueError, match="音频轨末尾"):
        钉入上下文_from_latent(_正条件(), _空latent(T_lat=37, T_audio=1),
                              尾v, 尾a, 1, frame_idx=-1)


def test_帧数转token数_网格上恒等于官方且非网格给正确值():
    """L4：_帧数转token数 算「n 帧占几个 token」，在 17k+5 网格上与官方 _video_latent_t 恒等，
    非网格值（1~4）给出正确的小值。二者不可互代：_video_latent_t 是「整段 latent 至少 2 个 token」
    的官方下限公式，拿它算 1 帧会给出 2 → 多切一倍。与 _latent_t_转帧数 在网格上严格互逆。"""
    assert _帧数转token数(1) == 1 and _video_latent_t(1) == 2      # 分歧点：<5 帧
    assert [_帧数转token数(i) for i in range(1, 6)] == [1, 2, 2, 2, 2]
    assert _帧数转token数(22) == 7 == _video_latent_t(22)
    assert _帧数转token数(39) == 12 == _video_latent_t(39)
    assert _帧数转token数(124) == 37 == _video_latent_t(124)
    for k in range(20):
        n = 17 * k + 5
        assert _帧数转token数(n) == _video_latent_t(n) == 5 * k + 2
        assert _latent_t_转帧数(_帧数转token数(n)) == n
    assert _帧数转token数(0) == 0 and _帧数转token数(-5) == 0


def test_取尾帧_latent_上下文小于5只锚1帧():
    """L4 回归：上下文帧数∈[1,4] → 规范锚帧数 兜底为 1 帧，切片长度必须随之为 1 个 token。
    旧实现用 _video_latent_t(1)=2 → 切 2 个 token（=5 像素帧）当锚、却按 锚帧数=1 只裁 1 帧前缀，
    成片接缝处多出 4 帧重复画面且全程无报错（官方 AddGuide 在 <5 时是 image[:1]，只锚 1 帧）。
    生产不可达（长视频规划师不开放 上下文帧数 widget，只开/关），但“锚帧数与切片长度同源”是本模块的
    核心不变式，开了口子就得封。"""
    v = torch.zeros(1, 24, 37, 4, 4)
    a = torch.zeros(1, 32, 2, 207)
    for n in (1, 2, 3, 4):
        尾v, 尾a, 锚 = 取尾帧_latent(v, a, n)
        assert 锚 == 规范锚帧数(n) == 1, f"上下文帧数={n} 应兜底为 1 帧"
        assert 尾v.shape[2] == 1, f"上下文帧数={n} 应只切 1 个 token，实际 {尾v.shape[2]}"
        assert 尾a.shape[-1] == int(round(1 * _FRAME_RESCALE)) == 2
    # 同源反向：锚 5 帧（网格值）仍是 2 token，与旧实现一致（本修正只影响 <5 分支）
    尾v5, _a5, 锚5 = 取尾帧_latent(v, a, 5)
    assert 锚5 == 5 and 尾v5.shape[2] == 2
