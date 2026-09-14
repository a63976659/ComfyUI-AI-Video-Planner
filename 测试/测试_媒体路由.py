# -*- coding: utf-8 -*-
"""Task 12 媒体路由：去重键（文件名+size → 16 位 sha256 前缀）纯函数单测。

只测 去重键 纯函数；媒体根() 依赖 folder_paths、注册路由() 依赖 server.PromptServer，
均为 ComfyUI 运行时内部 API，静态单测不触发（路由集成验证留 Task 20）。
"""
from 后端路由.媒体路由 import 去重键


def test_去重键_稳定():
    assert 去重键("cat.png", 100) == 去重键("cat.png", 100)


def test_去重键_区分大小():
    assert 去重键("cat.png", 100) != 去重键("cat.png", 101)


def test_去重键_长度():
    assert len(去重键("a.mp4", 1)) == 16
