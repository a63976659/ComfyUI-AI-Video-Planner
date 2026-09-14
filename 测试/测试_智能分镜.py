# -*- coding: utf-8 -*-
"""Task 10 智能分镜：秒区间转段与依赖可用性探测的纯函数契约。"""
from 执行.智能分镜 import 秒区间转段, 依赖可用


def test_秒区间转段():
    段 = 秒区间转段([(0.0, 3.5), (3.5, 8.0)], 任务="v2v")
    assert len(段) == 2
    assert 段[0]["task"] == "v2v"
    assert 段[0]["start"] == 0.0 and 段[0]["end"] == 3.5
    assert 段[1]["start"] == 3.5


def test_依赖可用_返回布尔():
    assert isinstance(依赖可用(), bool)
