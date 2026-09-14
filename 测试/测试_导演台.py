# -*- coding: utf-8 -*-
"""Task 11 导演台 V3 主节点：schema 冒烟 + I1/I2 契约回归锁。

覆盖：
  I1 契约锁（Task 11 code review）：本节点不覆写 validate_inputs，execution.py
    first_real_override 返回 None → 全节点原生 min/max/Combo 校验生效（带 **kwargs
    的覆写会令 validate_has_kwargs=True 而整体关闭原生校验）。
  I2 契约锁（Task 11 code review）：execute 收到 images=None 时抛 ValueError，
    不让 None 静默传给非 optional 输出。
  V3 schema 冒烟：18 inputs + 5 outputs + 1 hidden 全部通过 io.Schema.validate()。
  widget 边界与 ResolutionSelector/KSampler 常量同步（C1）。

不覆盖 GPU execute 集成（留 Task 19/20）。
"""
import pytest

comfy_api = pytest.importorskip("comfy_api")
节点导演台 = pytest.importorskip("节点.导演台")

from 节点.导演台 import H3导演台  # noqa: E402


def test_V3_schema_冒烟():
    s = H3导演台.GET_SCHEMA()
    s.validate()   # V3 schema 完整性检查：任一 io.Schema 参数非法都会抛
    assert s.node_id == "H3DYT_Director"
    assert len(s.inputs) == 18, "18 inputs：5 socket（fl2va模型/ref2va模型/CLIP编码器/视频VAE/音频VAE）+ 13 widget"
    assert len(s.outputs) == 5
    # 双模型改造：两个选填模型 socket 取代原单一「模型」；「模型标识」widget 已移除。
    输入名 = [i.id for i in s.inputs]
    assert "fl2va模型" in 输入名 and "ref2va模型" in 输入名, f"缺双模型输入：{输入名}"
    assert "模型" not in 输入名, f"旧单一「模型」输入应已移除：{输入名}"
    assert "模型标识" not in 输入名, f"「模型标识」widget 应已移除：{输入名}"
    选填 = {i.id: getattr(i, "optional", False) for i in s.inputs}
    assert 选填["fl2va模型"] and 选填["ref2va模型"], "两模型 socket 须为 optional（按需校验）"
    # V3 io.Schema 不直接暴露 return_names（属 V1 归一化产物），需从 INPUT_TYPES/OUTPUT 推。
    输出名 = [o.id for o in s.outputs]
    assert 输出名 == ["图像", "音频", "帧率", "帧数", "报告"], f"输出名漂移：{输出名}"


def test_不覆写_validate_inputs_I1_lock():
    """I1 契约锁：本节点不覆写 validate_inputs。execution.py:885 first_real_override
    找不到真实覆写 → 返回 None → validate_has_kwargs=False → L1019 原生 min/max/Combo
    校验对全部字段生效（任务类型/输出分辨率/采样器/调度器 Combo 与 帧率/百万像素/步数）。
    曾因带 **kwargs 的覆写会令 validate_has_kwargs=True 整体关闭原生校验，故锁死“不自定义”。"""
    assert "validate_inputs" not in H3导演台.__dict__, \
        "H3导演台 不得自定义 validate_inputs（含 **kwargs 会关闭全节点原生校验）"


def test_widget_边界走采样与解码常量_C1_lock():
    """C1 契约锁：百万像素/步数 widget 的 min/max/step 与 ResolutionSelector/KSampler
    常量同源，禁散落魔法。从 GET_SCHEMA 输出的 INPUT_TYPES（V3 归一化后的 dict）读取实际值。"""
    inputs = H3导演台.INPUT_TYPES()["required"]
    百万opts = inputs["百万像素"][1]
    assert 百万opts.get("min") == 0.1 and 百万opts.get("step") == 0.1, "百万像素 边界应=0.1/0.1"
    步数opts = inputs["步数"][1]
    assert 步数opts.get("min") == 1 and 步数opts.get("max") == 10000, "步数 边界应=1/10000"


def test_execute_空产物_抛ValueError_I2_lock(monkeypatch):
    """I2 契约锁：全段 skip+无缓存 → 执行核心 返 images=None。execute 不得把 None
    传给非 optional 输出（下游 SaveVideo 会抛无法定位的 TypeError）。此处 stub
    执行核心 直接返回 (None, None, 'report')，断言 execute 转抛 ValueError。"""
    假执行核心 = pytest.importorskip("执行.执行核心")
    monkeypatch.setattr(假执行核心, "执行时间轴",
                        lambda *a, **k: (None, None, "段1: 跳过（未选运行）"))
    假媒体路由 = pytest.importorskip("后端路由.媒体路由")
    monkeypatch.setattr(假媒体路由, "媒体根", lambda: "/tmp")

    with pytest.raises(ValueError, match="H3导演台 无有效产物"):
        H3导演台.execute(
            fl2va模型=None, ref2va模型=None, 视频VAE=None, 音频VAE=None, CLIP编码器=None,
            任务类型="文生视频 t2v", 全局提示词="", 时间轴数据='{"segments":[]}',
            参考素材="{}", 运行选择="{}", 帧率=24.0,
            输出分辨率="16:9 (宽屏)", 百万像素=1.0, 步数=25,
            采样器="res_multistep", 调度器="simple",
        )


def test_execute_双模型_写入模型输入(monkeypatch):
    """两个模型 socket 须按内部 ASCII 键写入 模型输入：fl2va模型→fl2va_model、ref2va模型→ref2va_model，
    供 执行核心 按段任务经 选模型槽 取 f"{槽}_model"；不再写 "model"/"模型标识"。stub 执行时间轴
    捕获 模型输入 实参后即抛哨兵中断，避免触达 GPU/NodeOutput 构造。"""
    假执行核心 = pytest.importorskip("执行.执行核心")
    假媒体路由 = pytest.importorskip("后端路由.媒体路由")
    捕获 = {}

    class _中断(Exception):
        pass

    def 假执行时间轴(时间轴数据, 全局参数, 模型输入, node_id, 媒体根, 进度回调=None):
        捕获["模型输入"] = 模型输入
        raise _中断()

    monkeypatch.setattr(假执行核心, "执行时间轴", 假执行时间轴)
    monkeypatch.setattr(假媒体路由, "媒体根", lambda: "/tmp")

    fl2va, ref2va = object(), object()
    with pytest.raises(_中断):
        H3导演台.execute(
            fl2va模型=fl2va, ref2va模型=ref2va, 视频VAE=None, 音频VAE=None, CLIP编码器=None,
            任务类型="文生视频 t2v", 全局提示词="", 时间轴数据='{"segments":[]}',
            参考素材="{}", 运行选择="{}", 帧率=24.0,
            输出分辨率="16:9 (宽屏)", 百万像素=1.0, 步数=25,
            采样器="res_multistep", 调度器="simple",
        )
    模型输入 = 捕获["模型输入"]
    assert 模型输入["fl2va_model"] is fl2va and 模型输入["ref2va_model"] is ref2va
    assert "model" not in 模型输入 and "模型标识" not in 模型输入


# ---------- P7 段级进度自有通道 ----------

def test_广播进度_发自有事件且失败吞掉(monkeypatch):
    """_广播进度 的接线锁：事件名 = _进度事件名、payload = {node,value,max}、sid = srv.client_id。

    另锁 best-effort：拿不到 PromptServer / instance 为 None / send_sync 抛错 都必须**静默返回**——
    进度上报失败绝不能把已跑了数小时的生成轮次拖成报错（try 体只有宿主调用，故宽 except 合规）。"""
    import sys
    import types

    发的 = []

    class 假Server:
        client_id = "cid-1"

        def send_sync(self, 事件, 数据, sid=None):
            发的.append((事件, 数据, sid))

    假模块 = types.ModuleType("server")
    假模块.PromptServer = type("PS", (), {"instance": 假Server()})
    monkeypatch.setitem(sys.modules, "server", 假模块)

    节点导演台._广播进度("n1", 3, 7)
    assert 发的 == [(节点导演台._进度事件名, {"node": "n1", "value": 3, "max": 7}, "cid-1")], \
        f"事件名/payload/sid 三项均须固定，实际 {发的}"

    # 三种失败形态都不得抛：instance 为 None、send_sync 报错、根本没有 server 模块
    发的.clear()
    假模块.PromptServer = type("PS", (), {"instance": None})          # .send_sync → AttributeError
    节点导演台._广播进度("n1", 4, 7)

    class 抛错Server:
        client_id = "cid-2"

        def send_sync(self, *a, **k):
            raise RuntimeError("websocket 已断")

    假模块.PromptServer = type("PS", (), {"instance": 抛错Server()})
    节点导演台._广播进度("n1", 5, 7)

    monkeypatch.setitem(sys.modules, "server", None)                  # from server import … → ImportError
    节点导演台._广播进度("n1", 6, 7)
    assert 发的 == [], "失败路径上一发也不得成功，且全程不得抛异常"


def test_execute_进度回调_宿主与自有双通道(monkeypatch):
    """进度回调的双通道接线锁：宿主 set_progress（供宿主自己的进度 UI/合并态）**与** 自有
    _广播进度（供自家状态栏面板）两者都要发。只发前者面板看不到（set_progress 不发 legacy
    "progress" 事件），只发后者宿主的进度 UI 不动。缘由详 _广播进度 docstring。"""
    假执行核心 = pytest.importorskip("执行.执行核心")
    假媒体路由 = pytest.importorskip("后端路由.媒体路由")
    收到 = {"回调": None, "序": []}

    class _中断(Exception):
        pass

    class 假execution:
        def set_progress(self, 值, 总, node_id=None):
            收到["序"].append(("宿主", 值, 总, node_id))

    class 假API:
        execution = 假execution()

    def 假执行时间轴(时间轴数据, 全局参数, 模型输入, node_id, 媒体根, 进度回调=None):
        收到["回调"] = 进度回调
        raise _中断()                              # 拿到回调就中断，不触达 NodeOutput

    monkeypatch.setattr(节点导演台, "ComfyAPISync", 假API)
    monkeypatch.setattr(假执行核心, "执行时间轴", 假执行时间轴)
    monkeypatch.setattr(假媒体路由, "媒体根", lambda: "/tmp")
    monkeypatch.setattr(节点导演台, "_广播进度",
                        lambda node_id, 当前, 总数: 收到["序"].append(("自有", 当前, 总数, node_id)))

    with pytest.raises(_中断):
        H3导演台.execute(
            fl2va模型=None, ref2va模型=None, 视频VAE=None, 音频VAE=None, CLIP编码器=None,
            任务类型="文生视频 t2v", 全局提示词="", 时间轴数据='{"segments":[]}',
            参考素材="{}", 运行选择="{}", 帧率=24.0,
            输出分辨率="16:9 (宽屏)", 百万像素=1.0, 步数=25,
            采样器="res_multistep", 调度器="simple",
        )
    assert callable(收到["回调"]), "execute 必须向 执行时间轴 传 进度回调"
    收到["回调"](3, 7)
    # 直调类时 cls.hidden 为 None → node_id 降级为 None（I2）；两通道均须带上同一 node_id
    assert 收到["序"] == [("宿主", 3, 7, None), ("自有", 3, 7, None)], \
        f"两通道须各发一次且同参，实际 {收到['序']}"
