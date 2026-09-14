# -*- coding: utf-8 -*-
"""Task 9 执行核心：CPU 侧编排 + ⚠️必修落地 的桩测（不触发 GPU / 官方节点）。

覆盖：
  ⚠️#4 _拼接音频 对称裁（净减帧不变式）
  _裁并拼（锚帧数裁前缀，复用 裁前缀帧数 语义）
  _应用全局（Run-select / 全局提示词 / refs 兜底 / 默认任务）
  Task 8 §约束4 _守卫参考长度（超限 ValueError）
  ⚠️#1 双模型：按需校验（缺槽模型 → ValueError 点名）+ 按段任务自动选 fl2va/ref2va 模型
  ⚠️#2 执行时间轴 端到端：两段采样→二次命中缓存（锚定信息入指纹→跨轮稳定）
  ⚠️#3 执行时间轴 端到端：坏缓存自愈→命中 True 但 读缓存 None→回退 _采样段（不崩）
  Concern #2 帧数入口唯一（秒转帧数 vs 用户帧率 widget 解耦）
  主画布原样透传（不过 对齐画布：官方 adapt_canvas 只规范参考视频，否则百万像素预算被抹平）
  Concern #5 skip+无缓存 下段独立不锚
  C1 参考图尺寸/audio_vae 入指纹（Task 9 code review）
  I2 音频段数 < 视频段数 → 报告告警
  I3 _读json 非 dict 归一（null/[]/int 不抛 AttributeError）
  I4 _解析参考张量 接入 校验标签（prompt 引用截断后不存在的项 → ValueError）
  B 音频按段时间切片（并入「全段共用」）：_音频窗采样点 纯逻辑 / _解析参考张量 音频窗透传 / _采样段 门控 / 参考共用入指纹
  B/C 性能优化：参考缓存按 参考共用 门控（接线 + 作用域语义两层）/ _取缓存 stat 失败降级
    与 None 值与文件戳失效 / _读视频帧 两条路径统一砍到 3 通道 + 帧数上限 + 空视频
  C 预缩放实质：_缩放到画布 尺寸契约 + 降级返回原对象且只告警一次 / _参考视频画布 复刻
    官方目标推导（大视频用 对齐画布、小视频退回源尺寸按 32 取整、下限 32）
  B 图像侧：_读图像 统一 3 通道与 0..1 归一化 / _加载图像 真经缓存且种类键与视频不串 /
    _确保图像 三分支与 _绝对路径 前置 / _解析参考张量 4 个位置参数不错位
    （错位会静默把独立参考音频塞进 ref_video_audios 并与 ref_video_N 配对）
  A 模型缓存接入（双模型按槽）：_取补丁模型 同槽跨轮复用同身份 / 同槽换模型 LRU-1 驱逐 /
    异槽并存不驱逐 / model=None 不入缓存 / _模型缓存键 槽·id·shift 入键
  方案 B 延迟解码：_拆_av_latent/_建_av_latent 往返（NestedTensor ↔ 扁平张量）/ 采样产物真
    落盘可读回（weights_only=True 不认自定义类）/ _是采样产物 形状守卫（单元 + 编排两层：坏形状
    缓存判未命中不崩）/ Phase 2 解 pin（清 模型缓存 + 上次键，让解码独占显存）/ 进度按 2×段数
    上报 / 锚帧数 单一真源链（取尾帧_latent → _采样段 → _解码段 → _裁并拼 裁前缀）

GPU 单段链路（MiniMaxH3SigmaShift/KSampler/VAEDecode…）留 Task 19/20；段间锚定的 keyframe
数学（_video_latent_t / 取尾帧_latent / 钉入上下文_from_latent）在 测试_段间连续.py。
"""
import logging
import os
import sys

import pytest

torch = pytest.importorskip("torch")

from 执行.执行核心 import (  # noqa: E402
    _应用全局,
    _拼接音频,
    _裁并拼,
    _模型缓存键,
    _取补丁模型,
    _守卫参考长度,
    执行时间轴,
)
from 执行.规划 import SegmentPlan  # noqa: E402
from 执行.采样与解码 import 对齐画布, 对齐帧数  # noqa: E402
import 执行.执行核心 as 执行核心  # noqa: E402

_SR = 2400      # 音频采样率
_FPS = 24       # 时间基座（对齐 采样与解码.FPS）
每帧样本 = _SR // _FPS  # 100


def _产物(T=10, 锚=0):
    """方案 B Phase 2 的桩产物：_解码段 的输出（images/audio 段产物，schema 见 执行核心._解码段）。"""
    return {
        "images": torch.zeros(T, 2, 2, 3),
        "audio": {"waveform": torch.zeros(1, T * 每帧样本), "sample_rate": _SR},
        "锚帧数": 锚,
        "帧数": T,
    }


def _T_lat_of(帧数):
    """桩自洽（L6）：由 帧数 走**生产同一条换算链**反算 video latent 的 token 数
    （对齐帧数 上抬到 17k+5 → _video_latent_t）。旧版手写 _T_LAT=9 配 帧数=10，而 9 token 其实
    对应 30 像素帧 —— 端到端用例虽仍绿，但桩自身不自洽，任何依赖「T_lat ↔ 帧数」关系的新
    断言都会被它误导（也盖不到 取尾帧_latent 的整段钳制边界）。"""
    from 执行.段间连续 import _video_latent_t
    from 执行.采样与解码 import 对齐帧数
    return _video_latent_t(对齐帧数(max(5, int(帧数))))


def _T_audio_of(帧数):
    """同上，音频支：官方 temporal_shape 的 round(frame_count / FPS * AUDIO_LATENT_FPS) = round(n*5/3)。"""
    from 执行.采样与解码 import 对齐帧数
    return int(round(对齐帧数(max(5, int(帧数))) * 5 / 3))


# 桩默认 帧数=10 → _采样产物 内先对齐到 22 帧（秒转帧数 的上抬契约）：T_lat=7 == _video_latent_t(22)、
# T_audio=37。两者都**恰好等于** 取尾帧_latent(锚=22) 的切取长度 → 不触发整段/音频钳制（与生产一致：
# 同时长段相接时尾帧切取恰好铺满）；要测钳制分支则显式传小的 T_lat（见 test_取尾帧_latent_短段整段作锚）。
_T_LAT = _T_lat_of(10)      # 7
_T_AUDIO = _T_audio_of(10)  # 37


def _采样产物(帧数=10, 锚=0, index=0, 音频=True, T_lat=None):
    """方案 B Phase 1 的桩产物：CPU 上的扁平 AV latent（schema 见 执行核心._采样段）。

    ⚠️ 桩必须**自洽**：帧数 先过一遍 对齐帧数（同真身 秒转帧数 的上抬契约，10 → 22）再落进
    字典。T_lat 由 对齐帧数(帧数) 派生，若落盘的 帧数 本身不在 17k+5 网格上，产物就自相矛盾
    （帧数=10 而 T_lat=7 其实对应 22 帧）——会被 _是采样产物 的自洽校验判未命中，端到端的
    命中类用例会全退化成重采样。要造「键都对但不自洽」的坏缓存请显式传 T_lat。

    T_lat 缺省由 帧数 派生（见 _T_lat_of），不再是一个与 帧数 无关的魔数。
    必须是**纯张量 + 标量**：真身经 写缓存 落盘、再由 读缓存(weights_only=True) 读回，
    塞自定义类（如 comfy NestedTensor）就读不回来 → 缓存永久失效（见 test_采样产物_真落盘可读回）。"""
    帧数 = 对齐帧数(max(5, int(帧数)))
    return {
        "video_latent": torch.zeros(1, 24, _T_lat_of(帧数) if T_lat is None else T_lat, 2, 2),
        "audio_latent": torch.zeros(1, 32, 2, _T_AUDIO) if 音频 else None,
        "锚帧数": 锚,
        "帧数": 帧数,
        "index": index,
    }


def _桩两阶段(monkeypatch, 采样桩=None, 解码桩=None):
    """把方案 B 的两片 GPU 叶子（_采样段 / _解码段）一起桩掉，返回 {"采样": n, "解码": n} 计数。

    端到端用例只验编排（缓存命中/锚定传递/按段选模型/报告文案/裁并拼），两片真身分别触发
    官方 H3 节点与 VAEDecode。必须**同时**桩：只桩 _采样段 则 Phase 2 真解码、只桩 _解码段
    则 Phase 1 真采样。自定义桩（spy / 丢音频等）经 采样桩/解码桩 覆盖，仍自动计数。
    默认解码桩按 帧数/锚帧数 透传（与真身 _解码段 同语义），故 _裁并拼 的行为被真实覆盖。"""
    计数 = {"采样": 0, "解码": 0}
    采 = 采样桩 or (lambda seg, *a: _采样产物(index=seg.index))
    解 = 解码桩 or (lambda 采产物, *a: _产物(T=采产物["帧数"], 锚=采产物["锚帧数"]))

    def 计采样(seg, *a, **k):
        计数["采样"] += 1
        return 采(seg, *a, **k)

    def 计解码(采产物, *a, **k):
        计数["解码"] += 1
        return 解(采产物, *a, **k)

    monkeypatch.setattr(执行核心, "_采样段", 计采样)
    monkeypatch.setattr(执行核心, "_解码段", 计解码)
    return 计数


def _假KSampler输出(T_lat=_T_LAT):
    """直调 _采样段 的契约锁用：KSampler 的桩输出（单元素 tuple，同 调用节点 的返回约定）。

    用**非嵌套** {"samples": Tensor} 即可让 _拆_av_latent 走直通分支——真身是
    NestedTensor((video, audio))，其拆/建往返与落盘可读回由 test_拆建_av_latent_* 单独锁，
    此处不必拉进 comfy 依赖。"""
    return ({"samples": torch.zeros(1, 24, T_lat, 2, 2)},)


# ---------- ⚠️#4 _拼接音频 ----------

def test_拼接音频_单段透传():
    a = _产物()["audio"]
    assert _拼接音频([a], _FPS) is a


def test_拼接音频_对称裁匹配视频净减():
    """两段各 10 帧：视频侧 拼接段 净减 4 帧 → 16 帧；音频侧应等比 → 16 帧换算的样本数。"""
    from 执行.段间连续 import 拼接段
    p0, p1 = _产物(), _产物()
    视频帧 = 拼接段([p0["images"], p1["images"]]).shape[0]        # 10+10-4=16
    音频 = _拼接音频([p0["audio"], p1["audio"]], _FPS)
    音频帧 = 音频["waveform"].shape[-1] / 每帧样本                 # 应 ≈ 16
    assert 视频帧 == 16
    assert abs(音频帧 - 视频帧) < 1e-6, f"A/V 漂移：视频{视频帧}帧 vs 音频{音频帧}帧"


# ---------- _裁并拼 ----------

def test_裁并拼_锚帧数裁前缀同步audio():
    """锚=5：裁前缀帧数(10,5)=min(规范锚帧数(5)=5, 9)=5 帧，音频同步少 5*每帧样本。"""
    产 = _产物(T=10, 锚=5)
    后 = _裁并拼(产)
    assert 后["images"].shape[0] == 5
    assert 后["audio"]["waveform"].shape[-1] == 5 * 每帧样本
    # 锚=0（无锚语义）：不裁，原样返回
    assert _裁并拼(_产物(T=10, 锚=0))["images"].shape[0] == 10


def test_裁后帧数_与裁并拼同式():
    """流式并入的预算入口：_裁后帧数 必须与 _裁并拼 的实际裁剪同式。它是 Phase 2 预分配成片长度的
    唯一来源（预算总帧数 吃它），对不上就会让 流式拼接._容得下 抛 ValueError → 已跑完的整轮
    采样全白费（而采样才是耗时大头）。两者相等的前提是「解码帧数 == 采样产物[帧数]」。"""
    assert 执行核心._裁后帧数({"帧数": 10, "锚帧数": 0}) == 10
    assert 执行核心._裁后帧数({"帧数": 10, "锚帧数": 5}) == 5
    assert 执行核心._裁后帧数({"帧数": 10, "锚帧数": 22}) == 1     # 裁前缀帧数 的 帧数-1 下限
    assert 执行核心._裁后帧数({}) == 0                            # 缺键不抛（归 0）
    for 帧, 锚 in [(10, 0), (10, 5), (10, 22), (124, 22), (5, 22), (1, 1), (22, 0)]:
        实际 = _裁并拼(_产物(T=帧, 锚=锚))["images"].shape[0]
        预算 = 执行核心._裁后帧数({"帧数": 帧, "锚帧数": 锚})
        assert 预算 == 实际, f"帧={帧} 锚={锚}：预算 {预算} != 实际裁后 {实际}"


# ---------- _应用全局 ----------

def test_应用全局_运行选择与提示词与refs兜底():
    全局 = {
        "运行选择": '{"0": false, "1": true}',
        "全局提示词": "GLOBAL",
        "参考素材": '{"图片": "g.png"}',
        "默认任务": "i2v",
    }
    s0 = SegmentPlan(index=0, task="", prompt="P0", refs={}, start=0.0, end=5.0, run=True)
    r0 = _应用全局(s0, 全局)
    assert r0.run is False                       # 运行选择["0"]=false
    assert r0.prompt == "GLOBAL\nP0"             # 全局提示词作前缀
    assert r0.task == "i2v"                      # 段 task 空 → 默认任务
    assert r0.refs == {"图片": "g.png"}          # 段 refs 空 → 全局兜底
    # 段级优先：seg 已有 task/refs 不被全局覆盖
    s1 = SegmentPlan(index=1, task="r2v", prompt="P1", refs={"图片": "s.png"}, run=False)
    r1 = _应用全局(s1, 全局)
    assert r1.task == "r2v" and r1.refs["图片"] == "s.png"
    assert r1.run is True                        # 运行选择["1"]=true 覆盖 seg.run=False


# ---------- Task 8 §约束4 长度守卫 ----------

def test_守卫参考长度_超限抛ValueError():
    with pytest.raises(ValueError, match="参考图片"):
        _守卫参考长度(["a"] * 10, [], [])
    with pytest.raises(ValueError, match="参考视频"):
        _守卫参考长度([], ["v"] * 4, [])
    with pytest.raises(ValueError, match="参考音频"):
        _守卫参考长度([], [], ["x"] * 4)
    _守卫参考长度(["a"] * 9, ["v"] * 3, ["x"] * 3)   # 恰好在上限内：不抛


# ---------- A：模型缓存接入（跨轮复用已打补丁的 model） ----------

@pytest.fixture(autouse=True)
def _桩补丁模型(monkeypatch):
    """CPU 侧统一桩掉 _补丁模型 的官方节点分支：真身经 调用节点 触发官方 MiniMaxH3SigmaShift
    （GPU/官方节点，本模块不跑）。双模型改造后端到端例须给 fl2va/ref2va 传非 None 模型以过
    「按需校验」，主循环遂会真调 _取补丁模型→_补丁模型；桩掉即隔离官方节点。刻意保留
    model=None→None 的真实契约（直调 _采样段 的单测据此仍拿到 model_p=None），仅把非 None
    分支换成哨兵。测试模型缓存的用例各自 monkeypatch 覆盖本桩以计数，互不影响。"""
    monkeypatch.setattr(执行核心, "_补丁模型",
                        lambda model, 全局参数: None if model is None else object())


@pytest.fixture
def _重置模型缓存():
    """每例前后清空 模型缓存 的进程级 dict 与 执行核心 的按槽 LRU-1 上次键，避免用例间串味。"""
    from 执行.模型缓存 import 清缓存
    清缓存()
    执行核心._模型缓存上次键 = {}
    yield
    清缓存()
    执行核心._模型缓存上次键 = {}


def test_取补丁模型_model为None不入缓存(_重置模型缓存):
    """单测桩/无模型：早返回 None，不触 模型缓存、不污染上次键（行为同旧版直调 _补丁模型）。"""
    assert _取补丁模型({"fl2va_model": None, "ref2va_model": None}, {}, "fl2va") is None
    assert 执行核心._模型缓存上次键 == {}


def test_取补丁模型_同键跨轮复用同身份(_重置模型缓存, monkeypatch):
    """同一 (槽, id(model), shift) 跨轮只 clone 一次；第二轮返回**同一** patcher 身份 → 宿主跳过重载。

    ⚠️ **作用域：本测锁的是 `_取补丁模型` 的单元行为，端到端从不触发它**。方案 B 下
    `执行时间轴` 每轮进 Phase 2 前会 `补丁.clear()` + `清缓存()` + `_模型缓存上次键.clear()` 解 pin
    ⇒ 下一轮必 miss、必重新打补丁（既定取舍，换来解码跑在空显存上）。Phase 1 内的**段间**复用
    来自局部 `补丁` dict（`该槽首段 = 槽 not in 补丁`，每槽每轮只调一次本函数），**不是** `模型缓存`；
    后者现存价值只剩「Phase 1 中途抛异常 → pin 未解 → 同轮重试命中同一身份」。
    故本测绿灯**不代表**生产在用跨轮复用（详 11 §K）；反过来说，删掉解 pin 会让本测的语义
    变成生产语义，但会把 ⑤AV解码 打回 839s。"""
    计数 = {"n": 0}

    def 假补丁(model, 全局参数):
        计数["n"] += 1
        return object()

    monkeypatch.setattr(执行核心, "_补丁模型", 假补丁)
    模型输入 = {"fl2va_model": object(), "ref2va_model": None}
    第一次 = _取补丁模型(模型输入, {}, "fl2va")   # shift 缺省 12/3
    第二次 = _取补丁模型(模型输入, {}, "fl2va")   # 模拟下一轮：同 model 同 shift
    assert 第二次 is 第一次                       # 复用同一身份（宿主 LoadedModel.__eq__ 据此判已加载）
    assert 计数["n"] == 1                         # 全程只 clone 一次


def test_取补丁模型_同槽换模型驱逐旧(_重置模型缓存, monkeypatch):
    """同槽 LRU-1：同一槽换 model（id 变）即驱逐旧补丁 → 回到旧 model 必重新 clone
    （单槽任何时刻只钉住一份 DiT，护 16GB 显存）。"""
    计数 = {"n": 0}

    def 假补丁(model, 全局参数):
        计数["n"] += 1
        return object()

    monkeypatch.setattr(执行核心, "_补丁模型", 假补丁)
    mA, mB = object(), object()
    a = _取补丁模型({"fl2va_model": mA}, {}, "fl2va")
    b = _取补丁模型({"fl2va_model": mB}, {}, "fl2va")    # 同槽换 model（id 变）→ 驱逐 a
    a2 = _取补丁模型({"fl2va_model": mA}, {}, "fl2va")   # a 已驱逐 → 必重载
    assert a is not b and a2 is not a and a2 is not b
    assert 计数["n"] == 3


def test_取补丁模型_异槽并存不驱逐(_重置模型缓存, monkeypatch):
    """按槽各自 LRU-1：fl2va/ref2va 交替**不互相驱逐**（消除混合时间轴抖动）→ 两槽各留一份、
    各只 clone 一次（合计 2 次）。对照 test_取补丁模型_同槽换模型驱逐旧（同槽换模型必驱逐）。"""
    计数 = {"n": 0}

    def 假补丁(model, 全局参数):
        计数["n"] += 1
        return object()

    monkeypatch.setattr(执行核心, "_补丁模型", 假补丁)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object()}
    f1 = _取补丁模型(模型输入, {}, "fl2va")
    r1 = _取补丁模型(模型输入, {}, "ref2va")
    f2 = _取补丁模型(模型输入, {}, "fl2va")    # 回到 fl2va：ref2va 未驱逐它 → 命中复用
    r2 = _取补丁模型(模型输入, {}, "ref2va")   # 回到 ref2va：fl2va 未驱逐它 → 命中复用
    assert f2 is f1 and r2 is r1               # 两槽各自复用同身份
    assert f1 is not r1                        # 两槽补丁互不相同
    assert 计数["n"] == 2                      # 全程只 clone 两次（每槽一次），无交替重载


def test_模型缓存键_槽与id与shift入键(_重置模型缓存):
    """键身份口径：(槽, id(model), shift_video, shift_audio)。槽隔离两管线模型（fl2va/ref2va
    天然不撞键 → 可并存）；id(model) 借 ComfyUI loader 对象缓存（同 ckpt→同对象→id 稳定命中，
    换 ckpt→新对象→id 变→未命中重载）；shift 改变补丁内容故必入键。"""
    模型 = object()
    k = _模型缓存键("fl2va", 模型, {})
    assert k == ("fl2va", f"id:{id(模型)}", 12.0, 3.0)               # 槽 + id + shift 缺省 12/3
    assert k == _模型缓存键("fl2va", 模型, {})                       # 同对象同槽两次算键相同 → 跨轮命中
    assert _模型缓存键("ref2va", 模型, {})[0] == "ref2va"            # 换槽 → 键首维不同（两槽隔离）
    assert _模型缓存键("fl2va", 模型, {"shift_video": 9.0})[2] == 9.0   # shift_video 入键
    assert _模型缓存键("fl2va", 模型, {"shift_audio": 5.0})[3] == 5.0   # shift_audio 入键


# ---------- ⚠️#2/#3 端到端编排（stub 掉 GPU 生成 + 临时缓存目录） ----------

def _时间轴():
    import json
    return json.dumps({"segments": [
        {"start": 0.0, "end": 5.0, "task": "t2v", "prompt": "A"},
        {"start": 5.0, "end": 10.0, "task": "t2v", "prompt": "B"},
    ]})


def _全局():
    return {"帧率": _FPS, "宽": 1344, "高": 768, "上下文帧数": 22,
            "种子": 100, "步数": 25}


def test_执行时间轴_两段采样再命中缓存(tmp_path, monkeypatch):
    """⚠️#2 + 方案 B 两阶段编排：首轮两段各采样一次、各解码一次；二次全同 → 命中缓存不再采样，
    但**仍要解码**（缓存里存的是 latent，不是 images）。进度按 2×段数 上报。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    计数 = _桩两阶段(monkeypatch)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    进度 = []

    images, audio, 报告 = 执行时间轴(_时间轴(), _全局(), 模型输入, "n1", str(tmp_path),
                                    进度回调=lambda i, n: 进度.append((i, n)))
    assert 计数 == {"采样": 2, "解码": 2}
    assert "段1: 已采样" in 报告 and "段2: 已采样" in 报告
    assert images.shape[0] == 40 and audio["waveform"].shape[-1] == 40 * 每帧样本
    assert 进度 == [(1, 4), (2, 4), (3, 4), (4, 4)], f"进度须按 2×段数 上报，实际 {进度}"

    # 再跑一次：参数与锚定信息全同 → 命中缓存（⚠️#2 锚定信息入指纹后仍跨轮稳定命中）
    进度.clear()
    images2, _音频2, 报告2 = 执行时间轴(_时间轴(), _全局(), 模型输入, "n1", str(tmp_path),
                                       进度回调=lambda i, n: 进度.append((i, n)))
    assert 计数 == {"采样": 2, "解码": 4}, "第二次不应再采样，但缓存的 latent 仍须解码"
    assert "段1: 命中缓存" in 报告2 and "段2: 命中缓存" in 报告2
    assert images2.shape[0] == 40
    assert len(进度) == 4


def test_执行时间轴_坏缓存自愈回退采样(tmp_path, monkeypatch):
    """⚠️#3：命中 True 但 读缓存 返回 None（坏文件自愈）→ 必须回退 _采样段，不得直接下标崩。"""
    from 执行.段缓存 import 缓存格式版本
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    计数 = _桩两阶段(monkeypatch)

    执行时间轴(_时间轴(), _全局(), 模型输入, "n1", str(tmp_path))   # 先落盘

    缓存目录 = tmp_path / 缓存格式版本       # h3-6 起文件落在版本子目录，不在 tmp_path 根下
    for 名 in os.listdir(缓存目录):                              # 污染所有 .pt
        if 名.endswith(".pt"):
            (缓存目录 / 名).write_bytes(b"definitely-not-a-torch-payload")

    images, audio, 报告 = 执行时间轴(_时间轴(), _全局(), 模型输入, "n1", str(tmp_path))
    assert 计数 == {"采样": 4, "解码": 4}                    # 回退采样，而非命中
    assert "段1: 已采样" in 报告 and "段2: 已采样" in 报告
    assert "命中缓存" not in 报告
    assert images.shape[0] == 40 and audio is not None


# ---------- ⚠️#1 双模型：按需校验 + 按段选模型 ----------

def test_执行时间轴_缺槽模型_按需报错(tmp_path, monkeypatch):
    """Q2 按需校验：时间轴含 t2v（fl2va 管线）但 fl2va模型 未连接（None）→ 采样前即抛明确
    ValueError（点名「fl2va模型」），不跑到一半才崩。反之只跑 t2v 时不校验 ref2va模型
    （见 test_执行时间轴_两段采样再命中缓存：ref2va_model 未用到即不报缺）。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    计数 = _桩两阶段(monkeypatch)
    模型输入 = {"fl2va_model": None, "ref2va_model": object(), "clip": None, "vae": None}
    with pytest.raises(ValueError, match="fl2va模型"):
        执行时间轴(_时间轴(), _全局(), 模型输入, "n缺槽", str(tmp_path))
    assert 计数 == {"采样": 0, "解码": 0}, "校验须在两阶段之前，不得先跑一段才报错"


def test_执行时间轴_按段选模型(tmp_path, monkeypatch):
    """双模型核心契约：混合时间轴（段0 t2v→fl2va、段1 r2v→ref2va）按段任务自动选模型——
    每段送进 _采样段 的 模型输入["model"] 必须是该段任务对应槽的模型（t2v 拿 fl2va_model、
    r2v 拿 ref2va_model），无需用户手动切换。spy _采样段 捕获每段实际拿到的 model 身份。"""
    import json
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    拿到 = []

    def spy采样(seg, 全局, 段模型输入, *a, **k):
        拿到.append((seg.task, 段模型输入["model"]))
        return _采样产物(index=seg.index)

    _桩两阶段(monkeypatch, 采样桩=spy采样)
    fl2va, ref2va = object(), object()
    模型输入 = {"fl2va_model": fl2va, "ref2va_model": ref2va, "clip": None, "vae": None}
    时间轴 = json.dumps({"segments": [
        {"start": 0.0, "end": 5.0, "task": "t2v", "prompt": "A"},
        {"start": 5.0, "end": 10.0, "task": "r2v", "prompt": "B"},
    ]})
    执行时间轴(时间轴, _全局(), 模型输入, "n选模型", str(tmp_path))
    assert 拿到 == [("t2v", fl2va), ("r2v", ref2va)], \
        f"每段须拿到对应槽模型（t2v→fl2va、r2v→ref2va），实际 {拿到}"


# ---------- 契约回归锁 ----------

def test_采样段_帧数走秒转帧数与用户帧率解耦(monkeypatch):
    """Concern #2 契约锁（Task 4 §接口约束）：_采样段 只能经 秒转帧数 拿帧数；
    用户「帧率」widget 在此例里刻意设为 30（与基座 FPS=24 不同），验证其不影响
    送给官方节点的 length。若日后有人改回 `对齐帧数(round(秒*用户帧率))`，本测必红。
    顺带锁产物 schema：帧数 与 length 同源（Phase 2 的 _裁并拼 靠它与解码出的帧数对齐）、
    锚帧数/index 原样回带。"""
    秒记录 = {}

    def spy_秒转帧数(秒):
        秒记录["秒"] = 秒
        return 124  # 5.0 秒 @ FPS=24 → 对齐帧数(120)=124

    长度捕获 = {}

    def spy_调用节点(类名, **kw):
        if 类名 == "KSampler":
            return _假KSampler输出()
        if 类名 == "MiniMaxH3ImageToVideo":
            长度捕获["length"] = kw.get("length")
        return (None, None)

    monkeypatch.setattr(执行核心, "秒转帧数", spy_秒转帧数)
    monkeypatch.setattr(执行核心, "选管线", lambda t: "MiniMaxH3ImageToVideo")
    monkeypatch.setattr(执行核心, "需要首帧", lambda t: False)
    monkeypatch.setattr(执行核心, "需要尾帧", lambda t: False)
    monkeypatch.setattr(执行核心, "调用节点", spy_调用节点)

    seg = SegmentPlan(index=0, task="t2v", prompt="A", refs={}, start=0.0, end=5.0, run=True)
    全局 = {"帧率": 30, "宽": 1344, "高": 768, "上下文帧数": 22}
    模型输入 = {"model": None, "clip": None, "vae": None}
    产物 = 执行核心._采样段(seg, 全局, 模型输入, None, None, 0, "/tmp")

    assert 秒记录["秒"] == 5.0, "应把段时长 5.0 直接交给 秒转帧数，不乘用户帧率"
    assert 长度捕获["length"] == 124, "官方节点 length 不受用户「帧率=30」影响"
    assert 产物["帧数"] == 124 and 产物["锚帧数"] == 0 and 产物["index"] == 0
    assert 产物["video_latent"].shape[2] == _T_LAT and 产物["audio_latent"] is None, \
        "非嵌套 KSampler 输出 → 音频 latent 为 None（_拆_av_latent 的直通分支）"


def test_采样段_主画布原样透传不过对齐画布(monkeypatch):
    """契约锁：主画布必须原样透传 分辨率到宽高 的产出，**不得**再过 对齐画布。
    官方 adapt_canvas 的唯一调用点是 MiniMaxH3ReferenceToVideo.execute L319 的参考视频循环，
    主画布走 _empty_av_latent(width, height, length) 直接用用户值。输入取 9:16+0.4MP 的 480x864
    （对齐画布 会把它托到 768x1376）：回归成过 对齐画布 → 宽高断言红；同时锁 对齐画布 在主画布
    路径上根本没被调用（防“改成等价写法但绕开 spy”漏网）。
    参考视频侧仍须用 对齐画布，由 test_参考视频画布_* 单独锁，本测不涉及。"""
    捕获 = {}
    对齐调用 = []

    def spy_调用节点(类名, **kw):
        if 类名 == "KSampler":
            return _假KSampler输出()
        if 类名 == "MiniMaxH3ImageToVideo":
            捕获["宽高"] = (kw.get("width"), kw.get("height"))
        return (None, None)

    # 刻意返回与入参不同的值：若主画布误过 对齐画布，宽高断言也会红（双重保护）
    monkeypatch.setattr(执行核心, "对齐画布",
                        lambda w, h: (对齐调用.append((w, h)), (768, 1376))[1])
    monkeypatch.setattr(执行核心, "秒转帧数", lambda s: 124)
    monkeypatch.setattr(执行核心, "选管线", lambda t: "MiniMaxH3ImageToVideo")
    monkeypatch.setattr(执行核心, "需要首帧", lambda t: False)
    monkeypatch.setattr(执行核心, "需要尾帧", lambda t: False)
    monkeypatch.setattr(执行核心, "调用节点", spy_调用节点)

    seg = SegmentPlan(index=0, task="t2v", prompt="A", refs={}, start=0.0, end=5.0, run=True)
    执行核心._采样段(seg, {"宽": 480, "高": 864, "上下文帧数": 0},
                    {"model": None, "clip": None, "vae": None}, None, None, 0, "/tmp")

    assert 捕获["宽高"] == (480, 864), "主画布须原样透传，不被 对齐画布 托到短边 768"
    assert 对齐调用 == [], "主画布路径不得调用 对齐画布（它只属于参考视频画布）"


def test_跳过段无缓存_下段独立不锚(tmp_path, monkeypatch):
    """Concern #5 契约锁：skip 段且无缓存时，下段采样时 尾帧_video/尾帧_audio 必须为 None
    （时间轴已断裂，下段作为独立段生成，不锚到“两段之前”的旧素材）；锚帧数 同步归 0——
    它既入指纹又是真锚定用的值，留着非零会让指纹与产物互相矛盾。"""
    import json
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    锚记录 = []

    def spy采样(seg, 全局, 模型, 尾帧_video, 尾帧_audio, 锚帧数, 媒体):
        锚记录.append((seg.index, 尾帧_video, 尾帧_audio, 锚帧数))
        return _采样产物(index=seg.index)

    _桩两阶段(monkeypatch, 采样桩=spy采样)
    时间轴 = json.dumps({"segments": [
        {"start": 0.0, "end": 5.0, "task": "t2v", "prompt": "A"},                 # 段0 run
        {"start": 5.0, "end": 10.0, "task": "t2v", "prompt": "B", "run": False},   # 段1 skip+无缓存
        {"start": 10.0, "end": 15.0, "task": "t2v", "prompt": "C"},                # 段2 run
    ]})
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    _images, _audio, 报告 = 执行时间轴(时间轴, _全局(), 模型输入, "n5", str(tmp_path))

    assert len(锚记录) == 2, "段1 应被 skip、不触发采样"
    # 段0：首段，无上段
    assert 锚记录[0][0] == 0 and 锚记录[0][1] is None and 锚记录[0][3] == 0
    # 段2：若无 fix（旧行为）会错误锚到段 0 尾帧（非 None）；fix 后 skip+无缓存 → 下段独立
    assert 锚记录[1][0] == 2
    assert 锚记录[1][1] is None, "skip+无缓存 后 尾帧视频 latent 必须为 None"
    assert 锚记录[1][2] is None, "skip+无缓存 后 尾帧音频 latent 必须为 None"
    assert 锚记录[1][3] == 0, "断裂处 锚帧数 必须归 0（它入指纹，留非零即与产物矛盾）"
    assert "段2: 跳过（未选运行）" in 报告


def test_段间锚定传递latent而非像素(tmp_path, monkeypatch):
    """方案 B 的核心接线锁：段 i+1 拿到的锚素材必须是**段 i 的 latent 尾切片**（5 维
    [B,24,T_lat,H,W]），而不是解码后的像素 images（4 维 [T,H,W,C]）。二者极易写混，而写混的
    后果是官方 PackedLayout 把像素当 latent 打包 → 模型内部形状错或静默产出错乱画面。
    同时锁 锚帧数 与切片长度同源（22 帧 ↔ 7 个 video token、37 个 audio token）。"""
    from 执行.段间连续 import _video_latent_t
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    锚记录 = []

    def spy采样(seg, 全局, 模型, 尾帧_video, 尾帧_audio, 锚帧数, 媒体):
        锚记录.append((seg.index, 尾帧_video, 尾帧_audio, 锚帧数))
        return _采样产物(index=seg.index)

    _桩两阶段(monkeypatch, 采样桩=spy采样)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    执行时间轴(_时间轴(), _全局(), 模型输入, "n锚", str(tmp_path))   # 上下文帧数=22

    assert len(锚记录) == 2
    _i, 尾v, 尾a, 锚 = 锚记录[1]                        # 段1 拿到段0 的尾帧
    assert 锚 == 22, f"锚帧数应为 规范锚帧数(22)=22，实际 {锚}"
    assert 尾v is not None and 尾v.ndim == 5, f"锚素材须是 latent（5 维），实际 {尾v.shape}"
    assert 尾v.shape[2] == _video_latent_t(22) == 7, "video token 数须与锚帧数同源"
    assert 尾a.shape[-1] == 37, "audio token 数须按 round(锚帧数*5/3) 而非视频 token 数换算"
    # 反向验证「不是像素」：像素尾帧会是 [22,2,2,3]（4 维、首维=帧数）
    assert 尾v.shape[0] != 22 and 尾v.ndim != 4


def test_命中缓存的段仍向下游传锚(tmp_path, monkeypatch):
    """缓存命中的段同样要切尾帧给下段：命中分支只 append 产物、忘了更新尾帧的话，下段会锚到
    「两段之前」的旧素材（画面回跳一截）而不报错。用「段0 已落盘、段1 首轮」构造：第二轮里
    段0 命中缓存，段1 仍须拿到段0 的尾帧。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    锚记录 = []

    def spy采样(seg, 全局, 模型, 尾帧_video, 尾帧_audio, 锚帧数, 媒体):
        锚记录.append((seg.index, 尾帧_video is not None, 锚帧数))
        return _采样产物(index=seg.index)

    _桩两阶段(monkeypatch, 采样桩=spy采样)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    执行时间轴(_时间轴(), _全局(), 模型输入, "n命中传锚", str(tmp_path))
    assert 锚记录 == [(0, False, 0), (1, True, 22)]

    # 第二轮：两段都命中缓存 → spy 一次也不该被调用，但报告须显示两段都命中
    锚记录.clear()
    _i, _a, 报告 = 执行时间轴(_时间轴(), _全局(), 模型输入, "n命中传锚", str(tmp_path))
    assert 锚记录 == [], "全命中时不得再采样"
    assert 报告.count("命中缓存") == 2


# ---------- 方案 B：latent 拆建 / 落盘可读回 / 形状守卫 ----------

def test_拆建_av_latent_往返():
    """KSampler 的 AV 嵌套 latent ↔ 扁平张量字典 必须无损往返，且张量顺序恒为 (video, audio)：
    官方 VAEDecode 取 unbind()[0]、VAEDecodeAudio 取 unbind()[-1]，顺序写反会把音频 latent
    当画面解码（形状不兼容时报错，兼容时静默产出噪声画面）。"""
    NestedTensor = pytest.importorskip("comfy.nested_tensor").NestedTensor
    v = torch.arange(1 * 24 * 7 * 2 * 2, dtype=torch.float32).reshape(1, 24, 7, 2, 2)
    a = torch.arange(1 * 32 * 2 * 37, dtype=torch.float32).reshape(1, 32, 2, 37)

    拆v, 拆a = 执行核心._拆_av_latent({"samples": NestedTensor([v, a])})
    assert torch.equal(拆v, v) and torch.equal(拆a, a), \
        "拆出的两张量须与嵌套内一致，且顺序为 (video, audio)"
    还原 = 执行核心._建_av_latent(拆v, 拆a)["samples"]
    assert 还原.is_nested, "须还原成 NestedTensor（官方 VAEDecode 靠 is_nested 分派）"
    assert torch.equal(还原.unbind()[0], v), "VAEDecode 取 unbind()[0]，必须是 video"
    assert torch.equal(还原.unbind()[-1], a), "VAEDecodeAudio 取 unbind()[-1]，必须是 audio"

    # 无音频管线（audio_vae 未接）：audio 侧恒 None，重建后只包 video
    拆v2, 拆a2 = 执行核心._拆_av_latent({"samples": NestedTensor([v])})
    assert torch.equal(拆v2, v) and 拆a2 is None
    单 = 执行核心._建_av_latent(v, None)["samples"]
    assert len(单.unbind()) == 1 and torch.equal(单.unbind()[0], v)
    assert 执行核心._建_av_latent(v, None)["samples"].is_nested

    # 非嵌套（桩/旧式单 latent）→ 直通，audio 恒 None
    assert 执行核心._拆_av_latent({"samples": v}) == (v, None)


def test_采样产物_真落盘可读回(tmp_path, monkeypatch):
    """方案 B 的**存活性**锁：采样产物必须能经 写缓存 → 读缓存(weights_only=True) 原样回来。

    读缓存 用 weights_only=True（安全默认），自定义类不在其白名单 → 一旦落盘内容混进
    comfy NestedTensor，读回必失败并按「坏缓存」删文件重算：段缓存永久失效、每轮都白写一遍，
    症状只是「没改参数却每次都重跑」，无报错、极难定位。故本测正反两面都锁。"""
    from 执行.段缓存 import 段指纹, 写缓存, 读缓存
    NestedTensor = pytest.importorskip("comfy.nested_tensor").NestedTensor
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))

    产物 = _采样产物(帧数=124, 锚=22, index=3)
    写缓存("nB落盘", 3, 段指纹({"task": "t2v"}, {"宽": 1344}), 产物)
    回 = 读缓存("nB落盘", 3, 段指纹({"task": "t2v"}, {"宽": 1344}))
    assert 回 is not None, "扁平 latent 产物必须能被 weights_only=True 读回"
    assert torch.equal(回["video_latent"], 产物["video_latent"])
    assert torch.equal(回["audio_latent"], 产物["audio_latent"])
    assert (回["锚帧数"], 回["帧数"], 回["index"]) == (22, 124, 3)
    assert 回["video_latent"].device.type == "cpu", "读回须在 CPU（Phase 2 才按需搬上显存）"

    # 反面：嵌套形态落盘 → 读不回来（正是 _拆_av_latent 存在的理由）
    指纹坏 = 段指纹({"task": "t2v"}, {"宽": 768})
    写缓存("nB落盘", 3, 指纹坏,
           {"sampled": NestedTensor([产物["video_latent"], 产物["audio_latent"]])})
    assert 读缓存("nB落盘", 3, 指纹坏) is None, \
        "NestedTensor 不在 weights_only 白名单 → 必须读不回来（故落盘前须 _拆_av_latent）"


def test_是采样产物_形状守卫():
    """缓存形状守卫：h3-4 只认「5 维 video_latent + int 帧数 + 两者自洽」。旧版 images 形态、
    4 维像素张量、None、非 dict 一律判未命中 → 重算自愈。少了它，键不对的 dict 会在主循环
    深处抛 KeyError，越过项目 ValueError-only 契约。

    第三条（帧数 ↔ T_lat 自洽）单独锁：生产里两者同源（帧数 = 秒转帧数(…) 已在 17k+5 网格上、
    T_lat = 官方 video_latent_t(帧数) 在 5k+2 网格上，17k+5 ↔ 5k+2 严格互逆），故相等恒成立；
    不相等只可能是文件被外力改坏。后果链见 test_执行时间轴_不自洽缓存判未命中不抛ValueError。"""
    assert 执行核心._是采样产物(_采样产物()) is True
    assert 执行核心._是采样产物(_采样产物(音频=False)) is True
    assert 执行核心._是采样产物(_产物()) is False, "h3-3 的 images 形态不得被当成采样产物"
    assert 执行核心._是采样产物({**_采样产物(), "video_latent": torch.zeros(22, 2, 2, 3)}) is False, \
        "4 维像素张量（[T,H,W,C]）不是 latent"
    assert 执行核心._是采样产物({**_采样产物(), "帧数": 10.0}) is False, \
        "帧数须是 int（同 段指纹 的数值类型敏感口径）"
    # 自洽：桩缺省 T_lat=7 对应 22 帧（_latent_t_转帧数(7)==22），改 帧数 或改 T_lat 都破坏同源
    assert 执行核心._是采样产物({**_采样产物(), "帧数": 30}) is False, \
        "帧数 与 latent 时长不同源（T_lat=7 对应 22 帧）须判未命中"
    assert 执行核心._是采样产物(_采样产物(帧数=22, T_lat=12)) is False, \
        "T_lat=12 对应 39 帧，与 帧数=22 不自洽"
    assert 执行核心._是采样产物(_采样产物(帧数=22)) is True, "同源的 (22, T_lat=7) 须命中"
    assert 执行核心._是采样产物(_采样产物(帧数=124)) is True, "17k+5 网格上的其他点也须命中"
    for 坏 in (None, {}, [], "x", 3, {"video_latent": None, "帧数": 10}):
        assert 执行核心._是采样产物(坏) is False, f"{坏!r} 须判未命中"


def test_解码段_建嵌套后交官方解码(monkeypatch):
    """Phase 2 的接线锁：_解码段 必须先用 _建_av_latent 把扁平张量还原成官方认的
    {"samples": NestedTensor} 再交 解码音视频；并把 锚帧数/帧数 原样带进段产物——
    _裁并拼 靠 锚帧数 裁掉被锚定的重复前缀，丢了就会让成片重复一段画面且不报错。"""
    pytest.importorskip("comfy.nested_tensor")
    收到 = {}

    def spy解码(av_latent, vae, audio_vae):
        收到["latent"], 收到["vae"] = av_latent, (vae, audio_vae)
        return (torch.zeros(124, 2, 2, 3),
                {"waveform": torch.zeros(1, 124 * 每帧样本), "sample_rate": _SR})

    monkeypatch.setattr(执行核心, "解码音视频", spy解码)
    采产物 = _采样产物(帧数=124, 锚=22, index=7)
    段 = 执行核心._解码段(采产物, "VAE", "AVAE")

    assert 收到["latent"]["samples"].is_nested, "须还原成 NestedTensor 再交官方 VAEDecode"
    assert [tuple(t.shape) for t in 收到["latent"]["samples"].unbind()] == \
        [tuple(采产物["video_latent"].shape), tuple(采产物["audio_latent"].shape)]
    assert 收到["vae"] == ("VAE", "AVAE")
    assert 段["锚帧数"] == 22 and 段["帧数"] == 124, "锚帧数/帧数 须原样带进段产物"
    assert 段["images"].shape[0] == 124 and 段["audio"]["sample_rate"] == _SR


def test_采样段_有尾帧才钉入上下文且锚帧数原样透传(monkeypatch):
    """_采样段 的锚定接线：尾帧_video 非 None → 必须调 钉入上下文_from_latent，且 锚帧数
    **原样透传**（不在函数内重算——它既是段缓存指纹的一维、又是真锚定用的值，两处不同源
    就会假命中）；尾帧为 None（首段/断裂处）→ 一次也不调。"""
    钉入 = []

    def spy钉入(positive, latent, 尾v, 尾a, 锚帧数, frame_idx=0):
        钉入.append((尾v, 尾a, 锚帧数, frame_idx))
        return positive

    monkeypatch.setattr(执行核心, "钉入上下文_from_latent", spy钉入)
    monkeypatch.setattr(执行核心, "秒转帧数", lambda s: 124)
    monkeypatch.setattr(执行核心, "选管线", lambda t: "MiniMaxH3ImageToVideo")
    monkeypatch.setattr(执行核心, "需要首帧", lambda t: False)
    monkeypatch.setattr(执行核心, "需要尾帧", lambda t: False)
    monkeypatch.setattr(执行核心, "调用节点",
                        lambda 类名, **kw: _假KSampler输出() if 类名 == "KSampler" else (None, None))

    seg = SegmentPlan(index=1, task="t2v", prompt="A", refs={}, start=5.0, end=10.0, run=True)
    模型输入 = {"model": None, "clip": None, "vae": None}
    尾v, 尾a = torch.zeros(1, 24, 7, 2, 2), torch.zeros(1, 32, 2, 37)

    首 = 执行核心._采样段(seg, {}, 模型输入, None, None, 0, "/tmp")
    assert 钉入 == [], "无尾帧（首段/断裂处）不得钉入任何 keyframe"
    assert 首["锚帧数"] == 0

    产物 = 执行核心._采样段(seg, {}, 模型输入, 尾v, 尾a, 22, "/tmp")
    assert len(钉入) == 1
    assert 钉入[0][0] is 尾v and 钉入[0][1] is 尾a, "须把上段尾帧 latent 原样交给钉入"
    assert 钉入[0][2] == 22 and 钉入[0][3] == 0, "锚帧数原样透传、锚在本段 frame_idx=0"
    assert 产物["锚帧数"] == 22, "产物里的锚帧数须与真锚定同源（Phase 2 靠它裁前缀）"


def test_执行时间轴_坏形状缓存判未命中不崩(tmp_path, monkeypatch):
    """_是采样产物 的**编排层**接线锁：把 h3-3 形态（images）的字典手工塞进当前版本的缓存路径，
    命中() 仍为真（指纹在文件名里）、读缓存 也读得回来（纯张量+int），必须靠形状守卫判未命中
    → 回退重采样，而不是在 Phase 2 取 ["video_latent"] 时抛 KeyError 越过 ValueError-only 契约。
    这正是 缓存格式版本 h3-3→h3-4 升版遗漏时的实际后果（旧文件被同一指纹命中）。"""
    from 执行.段缓存 import 缓存格式版本
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    计数 = _桩两阶段(monkeypatch)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}

    执行时间轴(_时间轴(), _全局(), 模型输入, "n坏形状", str(tmp_path))   # 首轮落盘 latent 形态
    assert 计数 == {"采样": 2, "解码": 2}

    缓存目录 = tmp_path / 缓存格式版本       # h3-6 起文件落在版本子目录，不在 tmp_path 根下
    for 名 in os.listdir(缓存目录):
        if 名.endswith(".pt"):
            torch.save(_产物(), 缓存目录 / 名)   # 换成 h3-3 的 images 形态（键不对）
    images, _audio, 报告 = 执行时间轴(_时间轴(), _全局(), 模型输入, "n坏形状", str(tmp_path))

    assert 计数 == {"采样": 4, "解码": 4}, "坏形状须判未命中 → 两段全重采样，而非崩或假命中"
    assert 报告.count("已采样") == 2 and "命中缓存" not in 报告
    assert images.shape[0] == 40


def test_执行时间轴_不自洽缓存判未命中不抛ValueError(tmp_path, monkeypatch):
    """_是采样产物 第三条（帧数 ↔ T_lat 自洽）的**编排层**接线锁，也是它存在的唯一理由。

    造一个「键全对、纯张量+int、能 weights_only 读回、video_latent 也是合法 5 维」但 帧数 与
    latent 时长不同源的坏文件（帧数 改成 10，T_lat 仍是 7 = 22 帧）。解码桩按真身语义行事：
    VAE 解出多少帧只看 T_lat，与 产物["帧数"] 无关。

    只查前两条时它会一路通过守卫：Phase 2 的 预算总帧数 按 帧数=10 预分配成片（10+6=16），
    而 VAE 实际解出 22 帧 → 流式拼接._容得下 抛 ValueError。那已是 Phase 1 全跑完
    （1.0MP@16s 七段 ≈4.4 小时）**之后**，且坏文件仍在盘上 ⇒ 重跑立刻在同一处再抛，
    形成必须手动清目录才能解开的**硬锁**。本测先锁真守卫把它前移成「判未命中 → 重算」，
    再把守卫退回旧口径做**反证**（同一批坏文件就会一路走到 Phase 2 才抛）。"""
    from 执行.段缓存 import 缓存格式版本
    from 执行.段间连续 import _latent_t_转帧数
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}

    def 解码按latent时长(采产物, *a):
        # 真身语义：解出帧数由 T_lat 定，不看 产物["帧数"]——不自洽在这里才变成尺寸对不上
        return _产物(T=_latent_t_转帧数(int(采产物["video_latent"].shape[2])), 锚=采产物["锚帧数"])

    计数 = _桩两阶段(monkeypatch, 解码桩=解码按latent时长)
    执行时间轴(_时间轴(), _全局(), 模型输入, "n不自洽", str(tmp_path))
    assert 计数 == {"采样": 2, "解码": 2}

    缓存目录 = tmp_path / 缓存格式版本       # h3-6 起文件落在版本子目录，不在 tmp_path 根下

    def 污染帧数(值):
        for 名 in os.listdir(缓存目录):
            if 名.endswith(".pt"):
                产 = torch.load(缓存目录 / 名, map_location="cpu", weights_only=True)
                产["帧数"] = 值              # T_lat 不动（仍是 7 = 22 帧）→ 与 10 不同源
                torch.save(产, 缓存目录 / 名)

    污染帧数(10)
    images, _audio, 报告 = 执行时间轴(_时间轴(), _全局(), 模型输入, "n不自洽", str(tmp_path))
    assert 计数 == {"采样": 4, "解码": 4}, "不自洽须当场判未命中重算，不得留到 Phase 2 才炸"
    assert "命中缓存" not in 报告 and images.shape[0] == 40

    # 反证：守卫退回「只查 5 维 + int」的旧口径，同一批坏文件就会硬锁成 Phase 2 的 ValueError
    污染帧数(10)
    monkeypatch.setattr(执行核心, "_是采样产物",
                        lambda 产: isinstance(产, dict)
                        and getattr(产.get("video_latent"), "ndim", 0) == 5
                        and isinstance(产.get("帧数"), int))
    with pytest.raises(ValueError, match="超出预算成片长度"):
        执行时间轴(_时间轴(), _全局(), 模型输入, "n不自洽", str(tmp_path))


def test_执行时间轴_Phase2解pin让出显存(tmp_path, monkeypatch, _重置模型缓存):
    """方案 B 的显存锁：解码前必须解除我方对 DiT 的钉住（模型缓存._已加载 与
    执行核心._模型缓存上次键 都清空）。宿主 free_memory() 以 sys.getrefcount 排卸载序，
    被钉住的模型排最后才卸；不先 清缓存() 就解码，16GB 卡上 DiT 仍占显存 → VAEDecode
    触发 offload 数据乒乓，正是本方案要治的 ⑤52s→839s。"""
    from 执行 import 模型缓存
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    采样期pin, 解码期pin = [], []

    def 采样并记pin(seg, *a):
        采样期pin.append(len(模型缓存._已加载))
        return _采样产物(index=seg.index)

    def 解码并记pin(采样产物, *a):
        解码期pin.append(len(模型缓存._已加载))
        return _产物(T=采样产物["帧数"], 锚=采样产物["锚帧数"])

    计数 = _桩两阶段(monkeypatch, 采样桩=采样并记pin, 解码桩=解码并记pin)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    执行时间轴(_时间轴(), _全局(), 模型输入, "npin", str(tmp_path))

    assert 计数 == {"采样": 2, "解码": 2}
    assert 采样期pin == [1, 1], "前提漂移：Phase 1 期间 模型缓存 应一直钉着 1 份 DiT（两段同槽复用）"
    assert 解码期pin == [0, 0], "解码前必须已 清缓存()，否则钉住的 DiT 排最后卸载"
    assert 执行核心._模型缓存上次键 == {}, "上次键也须清空：留着会让下一轮误以为旧 patcher 仍在缓存里"


def test_执行时间轴_锚帧数一路带到裁前缀(tmp_path, monkeypatch):
    """锚帧数 单一真源链：取尾帧_latent 算出 → 入 _采样段 → 落进采样产物 → _解码段 原样带出 →
    _裁并拼 据此裁掉被锚定的重复前缀（images 与 audio 同步）。任一环丢值都会让成片多一段重复
    画面且 A/V 漂移，全程无报错。用「上下文帧数=5」构造可整除的算术（桩内已把 帧数 对齐到
    22 帧）：段1 锚 5 帧 → 22 帧裁成 17 帧 → 拼接 22+17−4=35 帧；音频 2200+(1700−400)=3500=35×100 样本。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))

    def 采样带锚(seg, 全局, 模型, 尾帧_video, 尾帧_audio, 锚帧数, 媒体):
        return _采样产物(index=seg.index, 锚=锚帧数)   # 真身语义：锚帧数原样透传进产物

    _桩两阶段(monkeypatch, 采样桩=采样带锚)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    images, audio, 报告 = 执行时间轴(_时间轴(), {**_全局(), "上下文帧数": 5},
                                    模型输入, "n锚裁", str(tmp_path))

    assert "段1: 已采样 22帧（锚5）" in 报告
    assert images.shape[0] == 35, f"22 + (22−5) − 4 = 35，实际 {images.shape[0]}"
    assert audio["waveform"].shape[-1] == 35 * 每帧样本, "音频须与视频净减帧同口径对称裁"


# ---------- L2 进度满格 / 内存峰值项：Phase 2 流式并入 ----------
# ⚠️ 本区块说的「流式并入」对应 2026-09 回归审查的 C1（CPU 内存峰值），与下方
# 「Task 9 code review C1」（参考图尺寸/audio_vae 入指纹）是不同编号体系，不要混读。

def _三段时间轴():
    import json
    return json.dumps({"segments": [
        {"start": 0.0, "end": 5.0, "task": "t2v", "prompt": "A"},
        {"start": 5.0, "end": 10.0, "task": "t2v", "prompt": "B"},
        {"start": 10.0, "end": 15.0, "task": "t2v", "prompt": "C"},
    ]})


def test_执行时间轴_跳过无缓存段进度仍满格(tmp_path, monkeypatch):
    """L2：skip 段（未选运行）且无缓存 → 它既不采样也不解码，旧版因此少上报两步：
    3 段例里只上报过 1,3,4,5 而 max 恒为 6 → 前端进度条卡在 83% 直到节点结束。
    修法两条：skip 段也占掉它在 Phase 1 的那一步；Phase 2 前把 总步数 从「上界 2N」收敛为
    「N + 实际解码段数」。本测锁「最后一步恒为 value == max」。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    计数 = _桩两阶段(monkeypatch)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    进度 = []

    images, _audio, 报告 = 执行时间轴(
        _三段时间轴(), {**_全局(), "运行选择": '{"1": false}'},   # 段1 未选运行且无缓存
        模型输入, "nL2", str(tmp_path), 进度回调=lambda i, n: 进度.append((i, n)))

    assert 计数 == {"采样": 2, "解码": 2}, "段1 未选运行且无缓存 → 不采样也不解码"
    assert "段1: 跳过（未选运行）" in 报告
    # Phase 1 三段各一步（max=6 上界）→ Phase 2 收敛为 3+2=5 → 最后一步满格
    assert 进度 == [(1, 6), (2, 6), (3, 6), (4, 5), (5, 5)], f"实际 {进度}"
    assert 进度[-1][0] == 进度[-1][1], "最终一步必须 value == max（否则进度条永远到不了 100%）"
    assert images.shape[0] == 40, "段1 断裂 → 段0/段2 各自独立生成，22+22−4=40"


def test_执行时间轴_全部跳过无缓存补满格(tmp_path, monkeypatch):
    """L2 边界：所有段都 skip 且都无缓存 → 一个解码段也没有，Phase 1 的上报停在 (N, 2N)=50%，
    必须补一发满格（此时 images=None，由节点层报 ValueError，但进度不得卡半）。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    计数 = _桩两阶段(monkeypatch)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    进度 = []

    images, audio, 报告 = 执行时间轴(
        _三段时间轴(), {**_全局(), "运行选择": '{"0": false, "1": false, "2": false}'},
        模型输入, "nL2b", str(tmp_path), 进度回调=lambda i, n: 进度.append((i, n)))

    assert 计数 == {"采样": 0, "解码": 0} and images is None and audio is None
    assert 报告.count("跳过（未选运行）") == 3
    assert 进度 == [(1, 6), (2, 6), (3, 6), (3, 3)], f"末尾须补 (N, N) 满格，实际 {进度}"


def test_执行时间轴_Phase2流式并入不攒全量段(tmp_path, monkeypatch):
    """Phase 2 流式并入的编排层接线锁：必须「预算总帧数 → 逐段（解码 → 裁前缀 → 追加 → 丢本段引用）」
    交错进行，而不是把 N 段 images 全攒进列表再一次性 拼接段。
    后者峰值 = 全量段(N) + 折叠中间量(≈2N) ≈ 3N；而解码输出恒落 CPU float32
    （comfy/sd.py:1079 + model_management.py:1257），1.0MP@16s 单段 ≈5.0GB → 3 段 ≈40GB 系统内存。
    流式写入把峰值压到 成片(N) + 当前段(1) ≈ 20GB——方案 B 把 DiT 请出显存后，这就是下一个瓶颈。
    spy 流式拼接 验三件事：① 预算在**解码前**就算好且等于实际写入量；② 解码与追加交错（非批量）；
    ③ 返回的 images 就是 流式拼接.结果()。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    顺序 = []
    真类 = 执行核心.流式拼接

    class spy拼(真类):
        def __init__(self, 总帧数, 重叠帧数=4):
            顺序.append(("预算", int(总帧数)))
            super().__init__(总帧数, 重叠帧数)

        def 追加(self, 段):
            顺序.append(("追加", 0 if 段 is None else int(段.shape[0])))
            return super().追加(段)

    def 解码并记(采产物, *a):
        顺序.append(("解码", 采产物["index"]))
        return _产物(T=采产物["帧数"], 锚=采产物["锚帧数"])

    monkeypatch.setattr(执行核心, "流式拼接", spy拼)
    计数 = _桩两阶段(monkeypatch, 解码桩=解码并记)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}

    images, _audio, _报告 = 执行时间轴(_时间轴(), _全局(), 模型输入, "nC1", str(tmp_path))

    assert 计数 == {"采样": 2, "解码": 2}
    # 预算先于一切解码；两段各 22 帧（桩已对齐）、锚 0 → 22 + (22−4) = 40
    assert 顺序 == [("预算", 40), ("解码", 0), ("追加", 22), ("解码", 1), ("追加", 22)], \
        f"预算须在解码前、且解码与追加必须交错（非攒齐再拼），实际 {顺序}"
    assert images.shape[0] == 40, "预分配尺寸必须与实际写入量对得上"


def test_执行时间轴_预算对不上实际写入则抛不静默(tmp_path, monkeypatch):
    """流式并入的反面：解码出的帧数与采样产物[帧数] 不符（缓存被外力改坏、或日后改了 对齐帧数 忘同步）
    → 预分配尺寸对不上写入量，必须由 流式拼接._容得下 抛 ValueError，而不是静默丢帧
    （丢帧 = 成片时长短于时间轴、A/V 漂移且全程无告警）。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))

    def 解码多出帧(采产物, *a):
        return _产物(T=采产物["帧数"] + 3, 锚=采产物["锚帧数"])   # 故意比预算多 3 帧

    _桩两阶段(monkeypatch, 解码桩=解码多出帧)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    with pytest.raises(ValueError, match="超出预算成片长度"):
        执行时间轴(_时间轴(), _全局(), 模型输入, "nC1b", str(tmp_path))


# ---------- Task 9 code review C1/I2/I3/I4 ----------

def test_应用全局_json非dict归一不抛(tmp_path):
    """I3 契约锁：_读json 对已解析为非 dict 的入参（"null"/"[]"/"3"）必须归一为 {}，
    不得让 运行选择.get / .items 抛 AttributeError 越过 ValueError-only 契约。"""
    s = SegmentPlan(index=0, task="", prompt="P", refs={}, start=0.0, end=5.0, run=True)
    # 入参 json.loads 后分别为 None/list/int：均不得抛，行为等同未配
    for 坏 in ("null", "[]", "3", '{"k": 1}'):  # 最后一项为 dict，归一后取 k=1
        r = _应用全局(s, {"运行选择": 坏, "参考素材": 坏})
        assert isinstance(r.refs, dict)
    # 真实 dict 入参仍可取段行为（非完全归 {}）
    r = _应用全局(s, {"运行选择": '{"0": false}'})
    assert r.run is False


def test_应用全局_参考共用_全局覆盖段级():
    """参考共用=True（状态栏素材区右侧「全段共用」开关）：全局「参考素材」池覆盖段级 refs →
    r2v/v2v/rv2v 全段统一用全局素材、只需编辑各段提示词。对照缺省/False：段级优先、全局兜底。"""
    s = SegmentPlan(index=0, task="r2v", prompt="P",
                    refs={"图片": ["段级.png"]}, start=0.0, end=5.0, run=True)
    池 = '{"图片":["全局.png"],"音频":["a.mp3"]}'
    # 开启共用：全局覆盖段级同名键（图片换成全局），并入段级没有的键（音频）
    r = _应用全局(s, {"参考素材": 池, "参考共用": True})
    assert r.refs["图片"] == ["全局.png"]
    assert r.refs["音频"] == ["a.mp3"]
    # 关闭共用（缺省）：段级优先（图片保留段级），全局仅兜底缺失键（音频）
    r2 = _应用全局(s, {"参考素材": 池})
    assert r2.refs["图片"] == ["段级.png"]
    assert r2.refs["音频"] == ["a.mp3"]


def test_采样参数_参考图尺寸与audio_vae入指纹(tmp_path, monkeypatch):
    """C1 契约锁：_采样段 实际消费与产物相关的另两维必须入指纹，否则改后仍命中旧缓存。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    计数 = _桩两阶段(monkeypatch)
    模型输入无v = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    模型输入有v = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None, "audio_vae": object()}
    基 = {"帧率": _FPS, "宽": 1344, "高": 768, "上下文帧数": 22, "种子": 1, "步数": 25}

    # 基线：无 audio_vae + 参考图尺寸=match → 首次采样，二次命中
    执行时间轴(_时间轴(), {**基, "参考图尺寸": "match"}, 模型输入无v, "nC1a", str(tmp_path))
    执行时间轴(_时间轴(), {**基, "参考图尺寸": "match"}, 模型输入无v, "nC1a", str(tmp_path))
    assert 计数["采样"] == 2, "基线参数完全相同时，第二次应命中缓存"
    # 变维 1：参考图尺寸 match → fixed → 必须重采样（入指纹）
    执行时间轴(_时间轴(), {**基, "参考图尺寸": "fixed"}, 模型输入无v, "nC1a", str(tmp_path))
    assert 计数["采样"] == 4, "参考图尺寸 变更后必须重采样两段"
    # 变维 2：audio_vae 从无到有 → 必须重采样（入指纹）
    计数["采样"] = 0
    执行时间轴(_时间轴(), {**基, "参考图尺寸": "fixed"}, 模型输入无v, "nC1b", str(tmp_path))
    执行时间轴(_时间轴(), {**基, "参考图尺寸": "fixed"}, 模型输入有v, "nC1b", str(tmp_path))
    assert 计数["采样"] == 4, "audio_vae 存在性变更后必须重采样（入指纹）"


def test_拼接_音频段数不足告警(tmp_path, monkeypatch):
    """I2 契约锁：若 段产物 中存在 audio=None 而其他段有 audio，报告行必留告警 tripwire。
    audio=None 只能出自解码侧（audio_vae 未接/中途接入），故桩在 _解码段；顺带证明
    采样产物里的 index 一路带到了 Phase 2（否则无法按段号区分丢哪一段的音频）。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))

    def 解码丢中段audio(采样产物, *a):
        产 = _产物(T=采样产物["帧数"], 锚=采样产物["锚帧数"])
        if 采样产物["index"] == 1:
            产["audio"] = None   # 中段 audio=None
        return 产

    _桩两阶段(monkeypatch, 解码桩=解码丢中段audio)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    _images, _audio, 报告 = 执行时间轴(_时间轴(), _全局(), 模型输入, "nI2", str(tmp_path))
    assert "警告" in 报告 and "A/V 可能错位" in 报告, f"未抛警告 tripwire：{报告}"


def test_解析参考张量_校验标签悬空报ValueError():
    """I4 契约锁：refs 截断后 prompt 引用不存在的 <Picture N> → _解析参考张量 抛 ValueError
    （前移为显式报错，避免官方 tokenizer 静默忽略导致产物与预期不符）。"""
    refs = {"图片": [f"i{i}.png" for i in range(12)]}   # 12 图 → 解析槽位 截断为 9
    # prompt 引用 <Picture 10>：截断后不存在 → 校验标签 抛 ValueError
    # （实际 提取标签 已先拦下编号非法，与 校验标签 形成双保险）
    with pytest.raises(ValueError, match="Picture 10|超范围|不存在的槽位|截断|编号非法"):
        执行核心._解析参考张量(refs, "/tmp", prompt="参照 <Picture 10>")


# ---------- B：音频按段时间切片（并入「全段共用」） ----------

def test_音频窗采样点_按秒窗切与钳制():
    """B 纯逻辑核：全局时间轴秒窗 [起,止) → 采样点区间 [a,b)，钳到 [0,总样本]；无窗=整段。"""
    sr, 总 = 1000, 5000                        # 5 秒音频
    assert 执行核心._音频窗采样点(None, None, sr, 总) == (0, 5000)   # 无窗→整段
    assert 执行核心._音频窗采样点(0, 2, sr, 总) == (0, 2000)          # [0,2s)
    assert 执行核心._音频窗采样点(2, 5, sr, 总) == (2000, 5000)       # [2,5s)
    assert 执行核心._音频窗采样点(3, 9, sr, 总) == (3000, 5000)       # 止超长度→钳到总样本
    assert 执行核心._音频窗采样点(6, 9, sr, 总) == (5000, 5000)       # 起超长度→空窗 a==b
    assert 执行核心._音频窗采样点(-1, 2, sr, 总) == (0, 2000)         # 负起→钳 0


def test_解析参考张量_音频窗透传_全部同样切(monkeypatch):
    """B：音频窗给定时 refs 里每条音频都用同一 (起秒,止秒) 窗加载（“全部同样切”）。
    stub _加载音频 记录窗口并返回 None（模拟空切片）→ 组装参考入参 丢弃、不产 ref_audios 张量。"""
    记录 = []

    def spy_加载音频(路径, 起秒=None, 止秒=None):
        记录.append((起秒, 止秒))
        return None

    monkeypatch.setattr(执行核心, "_加载音频", spy_加载音频)
    执行核心._解析参考张量({"音频": ["a.mp3", "b.mp3"]}, "/tmp", prompt="", 音频窗=(5.0, 10.0))
    assert 记录 == [(5.0, 10.0), (5.0, 10.0)], "两条音频须用同一时间窗切片"


def test_采样段_参考共用_门控音频窗(monkeypatch):
    """B 契约锁：参考共用=True → _采样段 把 (seg.start,seg.end) 作音频窗传给 _解析参考张量
    （每段只引用自己那段音频）；参考共用 缺省 → 音频窗=None（整段引用、现状不变）。"""
    捕获 = {}

    def spy_解析参考张量(refs, 媒体根, prompt=None, 音频窗=None):
        捕获["音频窗"] = 音频窗
        return {}

    def spy_调用节点(类名, **kw):
        return _假KSampler输出() if 类名 == "KSampler" else (None, None)

    monkeypatch.setattr(执行核心, "_解析参考张量", spy_解析参考张量)
    monkeypatch.setattr(执行核心, "秒转帧数", lambda s: 124)
    monkeypatch.setattr(执行核心, "选管线", lambda t: "MiniMaxH3ReferenceToVideo")
    monkeypatch.setattr(执行核心, "调用节点", spy_调用节点)

    seg = SegmentPlan(index=1, task="r2v", prompt="P", refs={"音频": ["a.mp3"]},
                      start=5.0, end=10.0, run=True)
    模型输入 = {"model": None, "clip": None, "vae": None, "audio_vae": None}
    执行核心._采样段(seg, {"参考共用": True, "宽": 1344, "高": 768, "上下文帧数": 0},
                    模型输入, None, None, 0, "/tmp")
    assert 捕获["音频窗"] == (5.0, 10.0)
    执行核心._采样段(seg, {"宽": 1344, "高": 768, "上下文帧数": 0},
                    模型输入, None, None, 0, "/tmp")
    assert 捕获["音频窗"] is None, "参考共用 缺省时不得切片（整段引用）"


def test_采样参数_参考共用入指纹(tmp_path, monkeypatch):
    """B 契约锁：参考共用 必须入段缓存指纹。构造段无自有 refs、全局也无参考素材 → 开/关共用时
    seg.refs 与 start/end 全同，唯一差异是音频切片与否；若不入指纹则假命中（改了开关产物不变）。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    计数 = _桩两阶段(monkeypatch)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    基 = {"帧率": _FPS, "宽": 1344, "高": 768, "上下文帧数": 22, "种子": 1, "步数": 25}

    执行时间轴(_时间轴(), {**基, "参考共用": False}, 模型输入, "nB", str(tmp_path))
    执行时间轴(_时间轴(), {**基, "参考共用": False}, 模型输入, "nB", str(tmp_path))
    assert 计数["采样"] == 2, "参考共用 不变时第二次应命中缓存"
    执行时间轴(_时间轴(), {**基, "参考共用": True}, 模型输入, "nB", str(tmp_path))
    assert 计数["采样"] == 4, "参考共用 变更后必须重采样两段（入指纹）"


# ---------- B/C 性能优化：参考缓存门控与视频帧通道统一 ----------

def test_执行时间轴_参考共用门控缓存启用(tmp_path, monkeypatch):
    """P1 **接线**契约锁：执行时间轴 必须以 参考共用 开关决定是否启用参考缓存。
    缓存是轮内累积的（退出 with 才丢引用）：ON 时全段共用同一批素材、命中率 100% →
    纯收益；OFF（导演台.py 的缺省值）时段级 refs 优先、各段素材通常互不相同 → 命中率低
    而峰值从「单段素材量」涨到「全轮素材总量」（10 段各带一条 15s 参考视频即 10×4.5GB）。
    只测 _参考缓存作用域 的 启用 参数拦不住「调用处忘了传开关」这类回归，故本测盯接线。"""
    monkeypatch.setenv("H3_段缓存_DIR", str(tmp_path))
    捕获 = []
    真作用域 = 执行核心._参考缓存作用域

    def spy(启用=True):
        捕获.append(启用)
        return 真作用域(启用=启用)

    monkeypatch.setattr(执行核心, "_参考缓存作用域", spy)
    _桩两阶段(monkeypatch)
    模型输入 = {"fl2va_model": object(), "ref2va_model": object(), "clip": None, "vae": None}
    基 = {"帧率": _FPS, "宽": 1344, "高": 768, "上下文帧数": 22, "种子": 1, "步数": 25}

    执行时间轴(_时间轴(), {**基, "参考共用": True}, 模型输入, "nP1a", str(tmp_path))
    assert 捕获[-1] is True, "参考共用 ON 必须启用缓存（否则白白重解码 N-1 次）"
    执行时间轴(_时间轴(), {**基, "参考共用": False}, 模型输入, "nP1b", str(tmp_path))
    assert 捕获[-1] is False, "参考共用 OFF 必须关闭缓存（否则轮内累积抬高内存峰值）"
    执行时间轴(_时间轴(), 基, 模型输入, "nP1c", str(tmp_path))
    assert 捕获[-1] is False, "参考共用 缺省必须关闭缓存"


def test_参考缓存作用域_启用门控与作用域外降级(tmp_path):
    """P1 **语义**契约锁：启用=False 不得建 dict；未进入作用域（直调 _加载图像 等的单测/
    外部路径）与退出作用域后，_参考缓存 必须为 None → _取缓存 退回「每次现算」，与加缓存
    前的行为逐字相同。若日后有人把门控去掉（无条件建 dict）或忘了退出时恢复，本测必红。"""
    f = tmp_path / "a.png"
    f.write_bytes(b"x")
    计数 = {"n": 0}

    def 加载():
        计数["n"] += 1
        return "张量"

    # 作用域外：每次现算
    assert 执行核心._参考缓存 is None, "模块初始态必须为 None"
    执行核心._取缓存("图", str(f), None, 加载)
    执行核心._取缓存("图", str(f), None, 加载)
    assert 计数["n"] == 2, "作用域外必须每次现算（行为同旧版）"

    # 启用=True：同键只加载一次，退出恢复 None
    计数["n"] = 0
    with 执行核心._参考缓存作用域(启用=True) as 缓:
        assert isinstance(缓, dict)
        assert 执行核心._取缓存("图", str(f), None, 加载) is \
               执行核心._取缓存("图", str(f), None, 加载)
        assert 计数["n"] == 1, "ON 应命中缓存，实际加载 %d 次" % 计数["n"]
    assert 执行核心._参考缓存 is None, "退出必须恢复 None（不跨轮驻留）"

    # 启用=False：不建 dict → 每次现算
    计数["n"] = 0
    with 执行核心._参考缓存作用域(启用=False):
        assert 执行核心._参考缓存 is None, "OFF 不得建 dict"
        执行核心._取缓存("图", str(f), None, 加载)
        执行核心._取缓存("图", str(f), None, 加载)
        assert 计数["n"] == 2, "OFF 必须每次现算，实际 %d 次" % 计数["n"]
    assert 执行核心._参考缓存 is None


def test_取缓存_stat失败降级与None值与文件戳失效(tmp_path):
    """_取缓存 的三条边界（均为实施时刻意设计，无测试则会静默退化）：
      1. os.stat 失败 → 直接 加载()，让 FileNotFoundError 等原始异常从 加载() 原样抛出，
         不被缓存层改写成别的错（守住项目 ValueError-only 契约的可诊断性）；
      2. None 是合法缓存值（_加载视频帧 对空视频返回 None）→ 必须用 `键 not in` 而非 .get，
         否则空视频每段都被重新解码，B 项对空视频完全失效；
      3. 键含 mtime_ns+size → 源文件被同名覆盖后自动失效，不需手动清缓存。"""
    缺失 = str(tmp_path / "不存在.png")
    计数 = {"n": 0}

    def 加载并抛():
        计数["n"] += 1
        raise FileNotFoundError(缺失)

    存在的 = tmp_path / "素材.bin"
    存在的.write_bytes(b"x")

    with 执行核心._参考缓存作用域(启用=True):
        with pytest.raises(FileNotFoundError):
            执行核心._取缓存("图", 缺失, None, 加载并抛)
        assert 计数["n"] == 1, "stat 失败应降级为直接加载，原异常原样上抛"

        n2 = {"n": 0}

        def 加载None():
            n2["n"] += 1
            return None

        assert 执行核心._取缓存("视", str(存在的), None, 加载None) is None
        assert 执行核心._取缓存("视", str(存在的), None, 加载None) is None
        assert n2["n"] == 1, "None 也是合法缓存值，不得因 .get 语义而重复加载"

        n3 = {"n": 0}

        def 加载计():
            n3["n"] += 1
            return n3["n"]

        执行核心._取缓存("音", str(存在的), None, 加载计)
        assert 执行核心._取缓存("音", str(存在的), None, 加载计) == 1
        assert n3["n"] == 1
        存在的.write_bytes(b"yy")            # 改变 size → 键必失效
        assert 执行核心._取缓存("音", str(存在的), None, 加载计) == 2, "文件戳变化后必须失效"


def test_读视频帧_两条路径统一3通道与帧数上限与空视频(monkeypatch):
    """C 项残留修复的契约锁：_读视频帧 有「缩放」与「原尺寸直通」两条路径（源尺寸恰
    等于目标画布时不缩放，如源就是 1344x768）。`[..., :3]` 必须放在**解码处**（分叉点
    上游）——只在 _缩放到画布 里砍会漏掉直通路径，使 RGBA 素材两条路径通道数不一致
    （直通 4 通道 / 缩放 3 通道）。若日后有人把切片移回 _缩放到画布，本测必红。
    缩放能力本身不在此测（用假缩放解耦 comfy.utils），由 test_缩放到画布_* 单独锁；此处
    额外断言「输出恒为 32x32」与「直通路径不调用缩放」，锁住两条路径的分派正确。
    帧数按 int(上限秒*fps) 截断（15s*24fps=360）；空视频 → None（该 None 需可被缓存，
    见 test_取缓存_stat失败降级与None值与文件戳失效 第 2 条）。"""
    iio = pytest.importorskip("imageio.v3")     # 可选依赖：缺失时跳过而非报错
    import numpy as np

    # 解耦官方画布常量：固定目标为 32x32，则 32x32 源走直通、8x8 源走缩放
    monkeypatch.setattr(执行核心, "_参考视频画布", lambda w, h: (32, 32))
    # 亦解耦 comfy.utils：真 _缩放到画布 由 test_缩放到画布_* 单独锁，此处用确定性假缩放，
    # 使本测在无 comfy 环境下也能跑，且能断言「直通路径根本没调用缩放」——比只比尺寸更强。
    缩放调用 = []

    def 假缩放(帧, 宽, 高):
        缩放调用.append((宽, 高))
        return torch.zeros((帧.shape[0], 高, 宽, 3))

    monkeypatch.setattr(执行核心, "_缩放到画布", 假缩放)

    def 造(高, 宽, 通道):
        return lambda p: iter([np.full((高, 宽, 通道), 128, dtype=np.uint8)] * 6)

    for 高, 宽, 通道, 标签, 应缩放 in ((32, 32, 4, "直通+RGBA", False), (32, 32, 3, "直通+RGB", False),
                                      (8, 8, 4, "缩放+RGBA", True), (8, 8, 3, "缩放+RGB", True)):
        缩放调用.clear()
        monkeypatch.setattr(iio, "imiter", 造(高, 宽, 通道))
        out = 执行核心._读视频帧("假.mp4", 24, 15)
        assert out.shape[-1] == 3, f"{标签} 末维应为 3，实际 {tuple(out.shape)}"
        assert out.shape[0] == 6, f"{标签} 帧数应为 6，实际 {tuple(out.shape)}"
        assert tuple(out.shape[1:3]) == (32, 32), \
            f"{标签} 应统一到目标画布 32x32，实际 {tuple(out.shape)}"
        assert bool(缩放调用) is 应缩放, f"{标签} 是否调用缩放应为 {应缩放}，实际 {缩放调用}"

    monkeypatch.setattr(iio, "imiter",
                        lambda p: iter([np.zeros((32, 32, 3), dtype=np.uint8)] * 500))
    assert 执行核心._读视频帧("假.mp4", 24, 15).shape[0] == 360, "15s*24fps 应截断到 360 帧"

    monkeypatch.setattr(iio, "imiter", lambda p: iter([]))
    assert 执行核心._读视频帧("假.mp4", 24, 15) is None, "空视频应返回 None"


def test_缩放到画布_尺寸契约():
    """C 项**内存优化的实质**契约锁：预缩放必须真把帧缩到目标画布。
    _读视频帧 的测试用假缩放解耦了 comfy.utils（见该测），故真实缩放能力只能在此锁。
    若本函数静默失效（如走 fallback 返回原尺寸），4K/15s 素材照旧堆 ~36GB float32，而
    _读视频帧 的测试仍全绿——用户只看到内存暴涨却无从定位。同时锁 H/W 与 宽/高 的对应：
    movedim(-1,1) 前后极易把宽高写反（写反不报错，只是默默产出转置的画布）。"""
    pytest.importorskip("comfy.utils", reason="真缩放路径依赖 comfy.utils（可选环境）")
    for 入形状, 宽, 高, 期望 in (((1, 8, 8, 3), 32, 32, (1, 32, 32, 3)),
                                 ((1, 8, 16, 3), 64, 32, (1, 32, 64, 3)),   # 高=32 宽=64，勿写反
                                 ((1, 8, 8, 4), 32, 32, (1, 32, 32, 3))):  # RGBA：[..., :3] 幂等
        out = 执行核心._缩放到画布(torch.zeros(入形状), 宽, 高)
        assert tuple(out.shape) == 期望, \
            f"{入形状} 宽={宽} 高={高} 应得 {期望}，实际 {tuple(out.shape)}"


def test_缩放到画布_降级返回原对象且只告警一次(monkeypatch, caplog):
    """comfy.utils 不可导入时的降级契约（无需真装 comfy：把 sys.modules 置 None 即使
    函数内 `from comfy.utils import ...` 抛 ImportError）：
      ①返回**原对象**——不复制、不新增峰值副本（C 项失效时至少不比旧版更耗内存）；
      ②只告警一次——_缩放到画布 逐帧调用，360 帧不能刷 360 条同样日志；
      ③标志位 _缩放降级已告警 置 True（跨调用记忆，故须 monkeypatch 重置并自动恢复，
         否则会污染后续用例、也让本测重跑时假绿）。"""
    monkeypatch.setattr(执行核心, "_缩放降级已告警", False)
    monkeypatch.setitem(sys.modules, "comfy.utils", None)
    帧 = torch.zeros((1, 8, 8, 3))
    with caplog.at_level(logging.WARNING, logger="H3导演台.执行核心"):
        for _ in range(3):                      # 模拟逐帧调用
            out = 执行核心._缩放到画布(帧, 32, 32)
            assert out is 帧, "降级须返回原对象（不复制）"
            assert tuple(out.shape) == (1, 8, 8, 3), "降级须保持原尺寸"
    告警 = [r for r in caplog.records if "comfy.utils 不可导入" in r.getMessage()]
    assert len(告警) == 1, f"3 帧只应告警 1 次，实际 {len(告警)} 次"
    assert 执行核心._缩放降级已告警 is True


def test_参考视频画布_复刻官方目标推导():
    """C 项「预缩放目标算得对」的契约锁——尺寸缩对了但目标算错，内存优化照样失效，
    或把小视频无谓放大。本函数逐行复刻官方 MiniMaxH3ReferenceToVideo.execute L318-322：
    先 对齐画布（=官方 adapt_canvas：短边 768 / 面积上限 768*1344 / 每轴 32 倍数），
    源面积小于它则退回「源尺寸按 32 取整」。_读视频帧 的测试把本函数 monkeypatch 成常量
    以解耦官方画布值，故其退回分支只在此锁。期望值均按官方常量实算核对过。"""
    for 源宽, 源高, 期望, 说明 in (
            (1920, 1080, (1344, 768), "大视频 → 对齐画布（面积上限压到 768*1344）"),
            (1344, 768, (1344, 768), "源恰等于画布 → _读视频帧 走直通路径的触发条件"),
            (1080, 1920, (768, 1344), "竖屏 → 宽高互换"),
            (768, 1344, (768, 1344), "竖屏且恰等于画布"),
            (640, 360, (640, 352), "小视频 → 退回源尺寸按 32 取整（360→352，非 360）"),
            (100, 100, (96, 96), "退回取整（100→96）"),
            (32, 32, (32, 32), "退回且恰为 32 倍数"),
            (10, 10, (32, 32), "退回后 round(10/32)=0 → max(32,0) 下限保护"),
            (1, 1, (32, 32), "极端小视频仍不得低于 32")):
        实 = 执行核心._参考视频画布(源宽, 源高)
        assert 实 == 期望, f"{源宽}x{源高} 应得 {期望}（{说明}），实际 {实}"

    # 退回分支的存在性：漏掉它则小视频被放大到画布尺寸（640x360 → 1344x768，面积 4.5 倍）
    assert 对齐画布(640, 360) == (1344, 768), "前提漂移：对齐画布 应把 640x360 推到 1344x768"
    assert 执行核心._参考视频画布(640, 360) != 对齐画布(640, 360), "小视频不得被放大到画布尺寸"


# ---------- B 图像侧：通道契约 / 缓存接线 / 双入口 / 位置参数映射 ----------

def test_读图像_统一RGB三通道与归一化(tmp_path):
    """图像侧的**通道契约**锁，与视频侧 `[..., :3]`（见 test_读视频帧_*）同源同一目的：
    把任意 PIL 模式统一到 [1,H,W,3] float32 0..1。靠的是 convert("RGB")，而它无覆盖时最危险——
    实测不 convert 则 RGBA→(H,W,4)、L/P→(H,W) **二维无通道维**，unsqueeze(0) 后仅三维，
    喂官方 ReferenceToVideo 的 Autogrow（期望四维 [B,H,W,C]）会崩或产出错乱；而灰度 PNG、
    索引色 PNG、带透明通道的 PNG 都是常见用户素材，不是构造出来的边界。
    同时锁 /255.0：漏掉则值域 0..255，官方按 0..1 解释 → 产物爆白；除数写错则由精确值断言抓。"""
    Image = pytest.importorskip("PIL.Image")
    import numpy as np

    for 模式, 像素, 期望极值, 说明 in (
            ("RGB", (10, 20, 30), (10 / 255.0, 30 / 255.0), "已是 3 通道"),
            ("RGBA", (10, 20, 30, 128), (10 / 255.0, 30 / 255.0), "带透明 → alpha 被砍掉"),
            ("L", 42, (42 / 255.0, 42 / 255.0), "灰度 → 原本二维无通道维"),
            ("P", None, None, "索引色 → 原本二维；调色板量化不定，只验形状与值域")):
        p = tmp_path / f"t_{模式}.png"
        if 模式 == "P":
            Image.new("RGB", (5, 7), (60, 70, 80)).save(p)
            Image.open(p).convert("P").save(p)      # 转索引色后重存
        else:
            Image.new(模式, (5, 7), 像素).save(p)   # (宽=5, 高=7) → 数组 (7,5,C)

        t = 执行核心._读图像(str(p))
        assert tuple(t.shape) == (1, 7, 5, 3), \
            f"{模式}（{说明}）应得 [1,H,W,3]=[1,7,5,3]，实际 {tuple(t.shape)}"
        assert t.dtype == torch.float32, f"{模式} dtype 应为 float32，实际 {t.dtype}"
        assert 0.0 <= t.min().item() and t.max().item() <= 1.0, \
            f"{模式} 值域应在 0..1（/255.0 归一化），实际 [{t.min()}, {t.max()}]"
        if 期望极值 is not None:
            assert t.min().item() == pytest.approx(期望极值[0]), f"{模式} min 应={期望极值[0]}"
            assert t.max().item() == pytest.approx(期望极值[1]), f"{模式} max 应={期望极值[1]}"

        # 前提漂移探测：证明 convert("RGB") 对该模式确实在做事，否则本锁是空转
        原始 = np.array(Image.open(str(p)))
        if 模式 == "RGB":
            assert 原始.shape == (7, 5, 3), "RGB 前提漂移：原本就该是 3 通道"
        else:
            assert 原始.shape != (7, 5, 3), \
                f"{模式} 前提漂移：不 convert 也已是 (7,5,3)，本锁对该模式失去意义"


def test_加载图像_真经缓存且种类键与视频不串(tmp_path, monkeypatch):
    """B 项图像侧的**收益实质**锁：_加载图像 必须真经 _取缓存 而非直接 _读图像，否则
    「同一轮内按路径+文件戳复用解码结果」失效 → N 段各带同一张参考图就重解码 N 次。
    _取缓存 的三条边界锁（见 test_取缓存_*）只证明机制可用，证明不了调用方接上了——
    这与 P1 门控是同一类缺口（机制对 ≠ 接线对），故此处从调用侧数解码次数。
    另锁**种类键 '图' 的区分度**：与 _加载视频帧 的 '视' 共用同一个 _参考缓存 dict，
    种类字段若写重，同一路径既作图又作视频时会互相串味——拿到错类型的张量，
    且形状可能恰好兼容而不报错。"""
    Image = pytest.importorskip("PIL.Image")
    p = tmp_path / "a.png"
    Image.new("RGB", (4, 4), (7, 8, 9)).save(p)
    路径 = str(p)

    解码 = []
    真读 = 执行核心._读图像

    def spy_读图像(path):
        解码.append(path)
        return 真读(path)

    monkeypatch.setattr(执行核心, "_读图像", spy_读图像)

    # 作用域外（未启用缓存）：每次现解码——从调用侧再验一次 _取缓存 的降级分支
    执行核心._加载图像(路径)
    执行核心._加载图像(路径)
    assert len(解码) == 2, f"作用域外应每次现解码，实际 {len(解码)} 次"

    解码.clear()
    with 执行核心._参考缓存作用域(启用=True) as 缓:
        a = 执行核心._加载图像(路径)
        b = 执行核心._加载图像(路径)
        assert len(解码) == 1, \
            f"作用域内 2 次只应解码 1 次（B 项收益），实际 {len(解码)} 次——缓存没接上"
        assert a is b, "命中缓存须返回同一对象，不是等值副本"
        assert len(缓) == 1, f"应只有 1 条缓存，实际 {len(缓)}"
        键 = next(iter(缓))
        assert 键[0] == "图", f"图像缓存的种类键应为 '图'，实际 {键[0]!r}"
        assert 键[1] == 路径, f"键应含原始路径，实际 {键[1]!r}"
        assert 键[4] is None, f"图像无额外键（视频才有 fps/上限秒），实际 {键[4]!r}"

        # 同一路径按「视频」加载：不得误命中上面的图条目
        视频解码 = []
        monkeypatch.setattr(执行核心, "_读视频帧",
                            lambda path, fps=24, 上限秒=15: (视频解码.append(path),
                                                             torch.zeros((1, 2, 2, 3)))[1])
        执行核心._加载视频帧(路径, 24, 15)
        assert len(视频解码) == 1, "同路径的视频加载须真解码，不得命中 '图' 条目"
        assert len(缓) == 2, f"图/视频应各占一条，实际 {len(缓)} 条"
        assert {k[0] for k in 缓} == {"图", "视"}, \
            f"两类素材的种类键须可区分，实际 {[k[0] for k in 缓]}"

    解码.clear()
    执行核心._加载图像(路径)
    assert len(解码) == 1, "退出作用域后缓存须失效，不得跨轮复用陈旧素材"


def test_确保图像_三分支与绝对路径前置(monkeypatch):
    """首/尾帧的双入口契约：既可能是 widget 里的文件名，也可能是已连入的 IMAGE 张量。
    三分支各自的可观察后果都锁住，尤其**张量分支须原样返回同一对象且不触发加载**——
    isinstance 判断写反时，连入的张量会被当路径送进 _加载图像（PIL 打开张量 → 崩），
    str 分支写反则下游拿裸文件名当张量用。故 mock 除返回值外还要**记录调用**，
    才能断言「该分支根本没走到加载」（只比返回值抓不到）。
    顺带锁 _绝对路径：它是本函数与 _解析参考张量 的共用前置，此前零覆盖。"""
    调用 = []
    monkeypatch.setattr(执行核心, "_加载图像",
                        lambda p: (调用.append(p), "LOADED::" + p)[1])

    # ① None → None，且不得调用加载（None 不是合法路径）
    assert 执行核心._确保图像(None, "/media") is None
    assert 调用 == [], "None 分支不得触发 _加载图像"

    # ② 文件名 → 先 _绝对路径 再 _加载图像（顺序由 spy 收到的入参反证：应是拼好的绝对路径）
    期望路径 = os.path.join("/media", "a.png")
    assert 执行核心._确保图像("a.png", "/media") == "LOADED::" + 期望路径
    assert 调用 == [期望路径], f"应把绝对化后的路径交给 _加载图像，实际 {调用}"

    # ③ 已连入的张量 → 原样同一对象，不得触发加载
    调用.clear()
    张 = torch.zeros((1, 4, 4, 3))
    assert 执行核心._确保图像(张, "/media") is 张, "张量分支须原样返回同一对象（不复制）"
    assert 调用 == [], "张量分支不得触发 _加载图像（张量不是路径）"

    # _绝对路径 自身契约：相对名拼根（存在意义）、绝对名原样（不重复拼）
    assert 执行核心._绝对路径("a.png", "/media") == os.path.join("/media", "a.png")
    assert 执行核心._绝对路径("sub/a.png", "/media") == os.path.join("/media", "sub/a.png")
    绝 = os.path.abspath("x.png")        # abspath 在任何平台都被 isabs 认定为绝对
    assert 执行核心._绝对路径(绝, "/media") == 绝, "绝对路径不得再拼媒体根"
    # Windows 盘符路径（用户常填 D:\素材\a.png）：仅在认它为绝对的平台上验原样。
    # 注意 win32 的 isabs 对**无盘符**的 "/x" 返回 False，故此处不可硬编码期望。
    盘符 = "C:\\素材\\a.png"
    if os.path.isabs(盘符):
        assert 执行核心._绝对路径(盘符, "/media") == 盘符, "盘符绝对路径须原样，不得拼根"


def test_解析参考张量_位置参数不错位(monkeypatch):
    """_解析参考张量 末行 `组装参考入参(图片, 视频, None, 音频)` 是 **4 个位置参数**，
    极易错位成 (图片, 视频, 音频, None)。错位后果是**静默**的：独立参考音频会被塞进
    ref_video_audios 并按序号与 ref_video_N 配对，同时 ref_audios 消失——素材类型全错
    但张量形状兼容，不报错，只有产物的画面/听感对不上，用户无从定位。
    现有两条 _解析参考张量 测试分别只碰校验标签与音频窗，都抓不到这个错位。
    本锁用可区分哨兵钉死三类素材各自的落点、键名与顺序（顺序=官方 <Picture i> 序号契约）。
    路径哨兵带 媒体根，故同时证明三类素材都过了 _绝对路径。"""
    拼 = lambda n: os.path.join("/m", n)   # noqa: E731  与 _绝对路径 在 win32/posix 上一致
    monkeypatch.setattr(执行核心, "_加载图像", lambda p: "IMG::" + p)
    monkeypatch.setattr(执行核心, "_加载视频帧", lambda p, fps=24, 上限秒=15: "VID::" + p)
    monkeypatch.setattr(执行核心, "_加载音频", lambda p, 起=None, 止=None: "AUD::" + p)

    kw = 执行核心._解析参考张量(
        {"图片": ["a.png", "b.png"], "视频": ["v.mp4"], "音频": ["x.mp3"]}, "/m", prompt="")

    assert set(kw) == {"ref_images", "ref_videos", "ref_audios"}, \
        f"三类素材应各落其位，实际键 {sorted(kw)}（错位时会冒出 ref_video_audios）"
    assert "ref_video_audios" not in kw, \
        "ref_video_audios 是「参考视频自带音轨」（v2 未实现，恒传 None），出现即说明位置参数错位"
    assert dict(kw["ref_images"]) == {"ref_image_0": "IMG::" + 拼("a.png"),
                                      "ref_image_1": "IMG::" + 拼("b.png")}, \
        "图片须按 refs 顺序映射到 ref_image_N 且路径已绝对化（官方按插入顺序赋 <Picture i>）"
    assert dict(kw["ref_videos"]) == {"ref_video_0": "VID::" + 拼("v.mp4")}
    assert dict(kw["ref_audios"]) == {"ref_audio_0": "AUD::" + 拼("x.mp3")}

    # 空切片音频的既有行为（实测确认）：加载返回 None → 被过滤，但键仍在且为空 dict；
    # 且图片序号不受影响（_解析参考张量 docstring 承诺「不影响图片/视频序号」）
    monkeypatch.setattr(执行核心, "_加载音频", lambda p, 起=None, 止=None: None)
    kw2 = 执行核心._解析参考张量({"图片": ["a.png", "b.png"], "音频": ["x.mp3"]}, "/m", prompt="")
    assert dict(kw2["ref_audios"]) == {}, "全为 None 时 ref_audios 应是空 dict（键在、无张量）"
    assert dict(kw2["ref_images"]) == {"ref_image_0": "IMG::" + 拼("a.png"),
                                       "ref_image_1": "IMG::" + 拼("b.png")}, \
        "音频被丢弃不得挤动图片序号"
