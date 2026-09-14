# -*- coding: utf-8 -*-
import ast
import math
import sys
import types
from pathlib import Path

import pytest

from 执行.采样与解码 import 对齐帧数, 对齐画布, 秒转帧数


def test_对齐帧数_120到124():
    assert 对齐帧数(120) == 124      # 官方 17k+5 网格


def test_对齐帧数_下限5():
    assert 对齐帧数(1) == 5          # 官方最小 length=5
    assert 对齐帧数(5) == 5


def test_对齐画布_官方默认():
    assert 对齐画布(1344, 768) == (1344, 768)


def test_对齐画布_横屏封顶():
    assert 对齐画布(1920, 1080) == (1344, 768)


def test_对齐画布_竖屏():
    assert 对齐画布(720, 1280) == (768, 1344)


# ---------- C-1：正数守卫 + ValueError-only 契约（Task 11 UI 只 catch ValueError） ----------

def test_对齐画布_非正数抛ValueError():
    """零/负数一律 ValueError：不得漏出 ZeroDivisionError，也不得静默反转成正数。"""
    for w, h in [(1344, 0), (0, 768), (1344, -768), (-1344, -768), (0, 0)]:
        with pytest.raises(ValueError):
            对齐画布(w, h)
    with pytest.raises(ValueError):
        对齐画布(1344, 0.0)          # 浮点 0 同样拦下


# ---------- I-1：秒↔帧换算入口（官方时间基座 FPS=24） ----------

def test_秒转帧数_走官方基座24():
    assert 秒转帧数(5.0) == 124      # 5*24=120 → 上抬 4 帧到 17*7+5
    assert 秒转帧数(15.0) == 362     # 15*24=360 → 上抬 2 帧到 17*21+5
    assert 秒转帧数(1) == 39         # 入参可为 int：24 → 17*2+5
    assert 秒转帧数(0) == 5          # 落到 min=5
    assert 秒转帧数(5.0) == 对齐帧数(round(5.0 * 24))


# ---------- M-3：幂等 / 不变量 ----------

def test_对齐帧数_幂等():
    for n in [5, 22, 39, 120, 124, 500]:
        一 = 对齐帧数(n)
        assert 对齐帧数(一) == 一


def test_对齐画布_网格与面积不变量():
    """合法输入域内：每轴 32 倍数 & 面积 ≤ 768*1344。"""
    from 执行.采样与解码 import MAX_PIXELS
    for w, h in [(1344, 768), (768, 1344), (1920, 1080), (720, 1280), (512, 512), (4096, 1024)]:
        宽, 高 = 对齐画布(w, h)
        assert 宽 % 32 == 0 and 高 % 32 == 0
        assert 宽 * 高 <= MAX_PIXELS + 32 * 32  # 舍入容差一格


# ---------- M-4：跨度上界 ----------

def test_对齐帧数_跨度上界():
    """官方语义：最多上抬 16 帧（0.67s@24fps）。"""
    跨度 = {对齐帧数(n) - n for n in range(5, 5000)}
    assert max(跨度) == 16
    assert min(跨度) == 0
    assert 对齐帧数(6) == 22
    assert 对齐帧数(21) == 22


# ---------- M-5：平局取偶（banker's rounding 锁定） ----------

def test_对齐画布_平局取偶():
    """官方 round() 是银行家舍入：(49,48) 的 nom_w/32 与 nom_h/32 都是 .5，
    官方 round 会给 768, 768；半进位会给 800, 768。此测锁定与官方一致。"""
    assert 对齐画布(49, 48) == (768, 768)


# ---------- I-2：解码音视频 桩测（sys.modules 注入，无需 GPU / Task 8 实体） ----------

def _注入适配桩(返回序列):
    """在 sys.modules 里塞一个假的 执行.官方管线适配，让 解码音视频 可以测试。"""
    假 = types.ModuleType("执行.官方管线适配")
    调用记录 = []

    def 调用节点(名, **kwargs):
        调用记录.append((名, kwargs))
        return 返回序列[len(调用记录) - 1]

    假.调用节点 = 调用节点
    sys.modules["执行.官方管线适配"] = 假
    return 调用记录


def _清理适配桩():
    sys.modules.pop("执行.官方管线适配", None)


def test_解码音视频_同latent双解码():
    """核心契约：视频流与音频流必须来自同一个 av_latent 对象。"""
    latent = object()  # 哨兵，锁 is 相等
    try:
        记录 = _注入适配桩([(["视频"],), (["音频"],)])
        from 执行.采样与解码 import 解码音视频
        images, audio = 解码音视频(latent, "vvae", "avae")
        assert [名 for 名, _ in 记录] == ["VAEDecode", "VAEDecodeAudio"]
        for _, kw in 记录:
            assert kw["samples"] is latent          # 同一对象
        assert images == ["视频"] and audio == ["音频"]
    finally:
        _清理适配桩()


def test_解码音视频_无audio_vae跳过音频解码():
    latent = object()
    try:
        记录 = _注入适配桩([(["视频"],)])
        from 执行.采样与解码 import 解码音视频
        images, audio = 解码音视频(latent, "vvae", None)
        assert [名 for 名, _ in 记录] == ["VAEDecode"]
        assert audio is None
    finally:
        _清理适配桩()


def test_解码音视频_返回取args元组第0项():
    """Task 8 归一化契约：调用节点(...) 返回 io.NodeOutput，[0] 是 .args[0]。"""
    latent = object()
    try:
        _注入适配桩([("视频帧", "额外"), ("音频波",)])
        from 执行.采样与解码 import 解码音视频
        images, audio = 解码音视频(latent, "vvae", "avae")
        assert images == "视频帧"
        assert audio == "音频波"
    finally:
        _清理适配桩()


# ---------- I-3：AST 差分测试防漂移（不触发 torch import） ----------

def _官方源码路径():
    """插件根 = parents[1]；ComfyUI 根 = 插件根.parents[1]（同 conftest 注入口径）。
    评审草案写的 parents[2] 会落到 custom_nodes/，此处按实际布局修正。"""
    插件根 = Path(__file__).resolve().parents[1]
    候选 = 插件根.parents[1] / "comfy_extras" / "nodes_minimax_h3.py"
    if not 候选.exists():
        候选 = 插件根.parent / "comfy_extras" / "nodes_minimax_h3.py"
    return 候选


def _加载官方函数():
    """从 comfy_extras/nodes_minimax_h3.py 抽 adapt_canvas/align_frame_count
    与相关常量（AST 静态解析，不触发 torch import）。返回 (函数dict, 常量dict)。"""
    路径 = _官方源码路径()
    if not 路径.exists():
        pytest.skip(f"未找到官方源码：{路径}")
    源 = 路径.read_text(encoding="utf-8")
    命名 = {"math": math}
    常量 = {}
    函数 = {}
    for 节 in ast.parse(源).body:
        if isinstance(节, ast.Assign) and len(节.targets) == 1 and isinstance(节.targets[0], ast.Name):
            try:
                常量[节.targets[0].id] = ast.literal_eval(节.value)
                命名[节.targets[0].id] = 常量[节.targets[0].id]
            except (ValueError, TypeError):
                # MAX_PIXELS = 768 * 1344 这类算术式：literal_eval 不支持乘法，
                # 退一步用只看得见已解析常量的受限 eval（无 builtins）补上，
                # 否则官方 adapt_canvas 执行时会 NameError。
                try:
                    常量[节.targets[0].id] = eval(  # noqa: S307
                        compile(ast.Expression(节.value), "<常量>", "eval"),
                        {"__builtins__": {}}, dict(命名))
                    命名[节.targets[0].id] = 常量[节.targets[0].id]
                except Exception:
                    pass
        elif isinstance(节, ast.FunctionDef) and 节.name in {"align_frame_count", "adapt_canvas"}:
            # 只把官方源文件中挑出的这两个纯算术函数装进临时命名空间执行，不 import 官方模块
            exec(ast.get_source_segment(源, 节), 命名)  # noqa: S102
            函数[节.name] = 命名[节.name]
    return 函数, 常量


def test_与官方源码数值差分():
    """锁漂移：官方 adapt_canvas 语义若变，本测试立刻红。"""
    官方函数, 官方常量 = _加载官方函数()
    assert 官方函数["adapt_canvas"](1344, 768) == 对齐画布(1344, 768)
    assert 官方函数["adapt_canvas"](1920, 1080) == 对齐画布(1920, 1080)
    assert 官方函数["adapt_canvas"](720, 1280) == 对齐画布(720, 1280)
    # 常量对齐（官方源码实测名：CANVAS_MULTIPLE / BASE_SHORT_EDGE / FPS，L26-30）
    from 执行.采样与解码 import BASE_SHORT_EDGE, CANVAS_MULTIPLE, FPS, MAX_PIXELS
    assert 官方常量.get("CANVAS_MULTIPLE", 32) == CANVAS_MULTIPLE
    assert 官方常量.get("BASE_SHORT_EDGE", 768) == BASE_SHORT_EDGE
    assert 官方常量.get("FPS", 24) == FPS
    assert 官方常量.get("MAX_PIXELS", 768 * 1344) == MAX_PIXELS
    assert MAX_PIXELS == BASE_SHORT_EDGE * 1344


def test_对齐帧数_与官方语义等价():
    """官方 align_frame_count 无 max(5) 与 int；本模块 temporal_shape 组合等价。
    官方 temporal_shape L45 定义：align_frame_count(max(5, length))。"""
    官方函数, _ = _加载官方函数()
    官方acf = 官方函数["align_frame_count"]
    for n in [5, 22, 39, 120, 124, 500]:
        assert 对齐帧数(n) == 官方acf(max(5, n))
