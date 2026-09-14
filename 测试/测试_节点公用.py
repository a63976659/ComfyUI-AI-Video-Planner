# -*- coding: utf-8 -*-
"""Task 11 节点公用：中文标签映射 + 画布校验助手（阈值走 采样与解码 单一真源）。

I4（Task 11 code review）：conftest.py 已把 插件根 加 sys.path，节点/__init__.py 仅注释，
故可正常 `from 节点.节点公用 import ...`；节点公用.py 内部通过 try 相对 / except 绝对
双通道 import 采样与解码 常量。不再走 spec_from_file_location 反包 hack。
"""
import pytest

节点公用 = pytest.importorskip("节点.节点公用")
from 节点.节点公用 import (  # noqa: E402
    任务标签,
    校验画布,
    解析任务,
)
from 执行.采样与解码 import CANVAS_MULTIPLE  # noqa: E402


# ---------- 任务标签往返 ----------

def test_解析任务_往返():
    for 码, 标签 in 任务标签.items():
        assert 解析任务(标签) == 码


def test_解析任务_未知回退():
    assert 解析任务("不存在") == "t2v"


# ---------- 画布校验（阈值走 采样与解码 单一真源）----------

def test_校验画布_合法与非法():
    assert 校验画布(1344, 768) is None
    assert 校验画布(10, 768) is not None           # <CANVAS_MULTIPLE
    assert 校验画布(20000, 768) is not None        # >_画布最大边


def test_校验画布_阈值与采样与解码常量同步():
    """C1 契约锁：校验画布 的下界阈值来自 采样与解码.CANVAS_MULTIPLE，禁散落魔法 32。
    若有人在 节点公用.py 里把 CANVAS_MULTIPLE 换回硬编码 32 或删除 import → 采样与解码
    里若改 CANVAS_MULTIPLE 就检不出漂移。"""
    边界 = CANVAS_MULTIPLE
    assert 校验画布(边界, 边界) is None, f"{边界}×{边界} 应合法"
    assert 校验画布(边界 - 1, 边界) is not None, f"{边界-1} 应被拒"
