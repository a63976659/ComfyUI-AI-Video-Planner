# -*- coding: utf-8 -*-
"""模型缓存单测：取模型（命中/未命中/失败不写缓存/None 值哨兵）+ 清缓存（单键/全清/删不存在）。

模型缓存 持进程级 dict 状态（_已加载），用 autouse fixture 每例前后清空，避免用例间串味，
也避免本模块的引用把测试进程内的假模型钉住。契约来源：计划 Task 7 Step 1 的 取模型/清缓存 docstring。
"""
import pytest

from 执行.模型缓存 import 取模型, 清缓存


@pytest.fixture(autouse=True)
def _清空模型缓存():
    清缓存()          # 前置：防御其它模块/用例遗留
    yield
    清缓存()          # 后置：保持进程级 dict 干净


def test_取模型_未命中时调用加载函数并返回其值():
    调用次数 = 0

    def 加载():
        nonlocal 调用次数
        调用次数 += 1
        return "模型实例"

    assert 取模型("k1", 加载) == "模型实例"
    assert 调用次数 == 1


def test_取模型_命中时复用同一实例不再加载():
    调用次数 = 0

    def 加载():
        nonlocal 调用次数
        调用次数 += 1
        return object()

    首次 = 取模型("k2", 加载)
    再次 = 取模型("k2", 加载)
    assert 首次 is 再次          # 返回共享实例
    assert 调用次数 == 1          # 第二次命中，未触发加载


def test_取模型_不同键各自独立加载():
    assert 取模型("a", lambda: "A") == "A"
    assert 取模型("b", lambda: "B") == "B"
    # a 已缓存 → 下面的 lambda 不应被执行
    assert 取模型("a", lambda: "不该被调用") == "A"


def test_取模型_缓存值为None时命中不重复加载():
    """哨兵 _缺 的意义：区分「键不存在」与「缓存值本身是 None」——后者仍算命中。"""
    调用次数 = 0

    def 加载():
        nonlocal 调用次数
        调用次数 += 1
        return None

    assert 取模型("kn", 加载) is None
    assert 取模型("kn", 加载) is None
    assert 调用次数 == 1          # 第二次命中已缓存的 None，未再加载


def test_取模型_加载失败不写缓存可安全重试():
    """契约 3：加载函数抛错时异常原样上抛、dict 不留占位，同键可安全重试。"""
    尝试 = {"n": 0}

    def 加载():
        尝试["n"] += 1
        if 尝试["n"] == 1:
            raise RuntimeError("首次加载失败")
        return "恢复的模型"

    with pytest.raises(RuntimeError):
        取模型("kf", 加载)
    # 失败未写缓存 → 同键重试会真正再次执行加载函数并缓存成功值
    assert 取模型("kf", 加载) == "恢复的模型"
    assert 尝试["n"] == 2


def test_清缓存_给定键只删该键():
    取模型("x", lambda: "X")
    取模型("y", lambda: "Y")
    清缓存("x")
    # x 已删 → 再取会重新加载拿到新值；y 仍在 → 复用旧值（lambda 不执行）
    assert 取模型("x", lambda: "X2") == "X2"
    assert 取模型("y", lambda: "不该被调用") == "Y"


def test_清缓存_None清空全部():
    取模型("x", lambda: "X")
    取模型("y", lambda: "Y")
    清缓存()
    assert 取模型("x", lambda: "X2") == "X2"
    assert 取模型("y", lambda: "Y2") == "Y2"


def test_清缓存_删不存在的键不报错():
    清缓存("从不存在的键")           # 不应抛
    取模型("z", lambda: "Z")
    清缓存("另一个不存在的键")       # 不应抛，且不影响已缓存的 z
    assert 取模型("z", lambda: "不该被调用") == "Z"
