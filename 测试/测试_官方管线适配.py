# -*- coding: utf-8 -*-
"""Task 8 官方管线适配：调用节点 的 NodeOutput→tuple 归一化 + 官方节点可用 的 True/False 路径。

纯 sys.modules 桩测，无 ComfyUI / GPU 依赖。模式沿用 测试_采样与解码.py：注入假 `nodes`
模块到 sys.modules，让被测函数 `import nodes` 命中桩。
"""
import sys
import types
from collections import namedtuple

import pytest

from 执行.官方管线适配 import 取节点, 调用节点, 官方节点可用


def _注入nodes(映射):
    """把带 NODE_CLASS_MAPPINGS 的假 nodes 模块塞进 sys.modules，返回旧值供还原。"""
    假 = types.ModuleType("nodes")
    假.NODE_CLASS_MAPPINGS = 映射
    旧 = sys.modules.get("nodes")
    sys.modules["nodes"] = 假
    return 旧


def _还原nodes(旧):
    if 旧 is None:
        sys.modules.pop("nodes", None)
    else:
        sys.modules["nodes"] = 旧


# ---------- 取节点 ----------

def test_取节点_命中返回类对象():
    class Dummy:
        pass
    旧 = _注入nodes({"Dummy": Dummy})
    try:
        assert 取节点("Dummy") is Dummy
    finally:
        _还原nodes(旧)


def test_取节点_缺失抛RuntimeError():
    旧 = _注入nodes({})
    try:
        with pytest.raises(RuntimeError, match="未找到官方节点"):
            取节点("Ghost")
    finally:
        _还原nodes(旧)


# ---------- 调用节点：V3 归一化（NodeOutput 有 .args、非 tuple 子类 → unwrap） ----------

def test_调用节点_V3NodeOutput归一化为tuple():
    """模拟 V3 官方 execute 返回 io.NodeOutput：带 .args 元组但不是 tuple 子类。
    归一化后调用侧应拿到普通 tuple，而非再判 isinstance(..., NodeOutput)。"""
    class 假NodeOutput:
        def __init__(self, *args):
            self.args = args
    class V3Node:
        @classmethod
        def execute(cls, a, b):
            return 假NodeOutput(a, b)
    旧 = _注入nodes({"V3Node": V3Node})
    try:
        结果 = 调用节点("V3Node", a=1, b=2)
        assert 结果 == (1, 2)
        assert isinstance(结果, tuple) and type(结果) is tuple
    finally:
        _还原nodes(旧)


# ---------- 调用节点：V1 直返 tuple（不带 .args 属性） ----------

def test_调用节点_V1实例方法直返tuple():
    """V1 官方节点：FUNCTION="gen"，实例方法 gen(self, x) 直接返回 tuple；无 .args。
    归一化守卫应不触发、原样透传，避免 V1 契约被误改。"""
    class V1Node:
        FUNCTION = "gen"
        def gen(self, x=None):
            return (x, (x or 0) + 1)
    旧 = _注入nodes({"V1Node": V1Node})
    try:
        assert 调用节点("V1Node", x=5) == (5, 6)
    finally:
        _还原nodes(旧)


# ---------- 调用节点：namedtuple 带 .args 字段（tuple 子类不 unwrap） ----------

def test_调用节点_tuple子类不被误unwrap():
    """具名元组是 tuple 子类且可带名为 args 的字段——若不检查 `not isinstance(结果, tuple)`，
    就会错误返回 结果.args 而丢失 namedtuple 类型。用此测把守卫钉死。"""
    NT = namedtuple("NT", ["args", "extra"])
    class NTNode:
        FUNCTION = "gen"
        def gen(self):
            return NT(args=(9, 9), extra=1)
    旧 = _注入nodes({"NTNode": NTNode})
    try:
        结果 = 调用节点("NTNode")
        assert isinstance(结果, NT)
        assert 结果.args == (9, 9) and 结果.extra == 1
    finally:
        _还原nodes(旧)


# ---------- 官方节点可用 ----------

def test_官方节点可用_已注册True():
    class Dummy:
        pass
    旧 = _注入nodes({"Dummy": Dummy})
    try:
        assert 官方节点可用("Dummy") is True
    finally:
        _还原nodes(旧)


def test_官方节点可用_未注册False():
    旧 = _注入nodes({})
    try:
        assert 官方节点可用("Ghost") is False
    finally:
        _还原nodes(旧)


def test_官方节点可用_nodes模块不可导入False():
    """裸 Python 环境（无 ComfyUI）下的启动期预检：import nodes 抛 ImportError，
    被 官方节点可用 收窄后的 except 捕获，返回 False 不崩。"""
    旧 = sys.modules.get("nodes")
    sys.modules["nodes"] = None  # 强制 import 抛 ImportError
    try:
        assert 官方节点可用("Whatever") is False
    finally:
        _还原nodes(旧)
