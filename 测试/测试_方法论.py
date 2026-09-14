# -*- coding: utf-8 -*-
from 规划.方法论 import (
    角色配色, HOOK_TYPES, MIN_SEG, MAX_SEG,
    DEFAULT_COLOR, PLATFORM_HINTS, ROLE_COLORS,
)


def test_角色配色_已知角色():
    assert 角色配色("钩子") == "#ff4d4f"


def test_角色配色_未知回退():
    assert 角色配色("不存在") == "#8c8c8c"


def test_角色配色_前后空白容错():
    assert 角色配色(" 钩子 ") == "#ff4d4f"


def test_角色配色_None回退():
    assert 角色配色(None) == DEFAULT_COLOR


def test_时长约束原值():
    assert MIN_SEG == 5 and MAX_SEG == 15


def test_钩子类型():
    assert len(HOOK_TYPES) == 7


def test_平台提示覆盖():
    assert len(PLATFORM_HINTS) == 7
    assert "通用" in PLATFORM_HINTS


def test_色板是十六进制():
    assert all(v.startswith("#") and len(v) == 7 for v in ROLE_COLORS.values())
    assert DEFAULT_COLOR.startswith("#") and len(DEFAULT_COLOR) == 7
