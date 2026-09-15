# -*- coding: utf-8 -*-
"""长视频规划师插件入口：V3 comfy_entrypoint 注册节点 + 网页资源 + 媒体/预设路由。"""
import logging

from comfy_api.latest import ComfyExtension, io
from typing_extensions import override

WEB_DIRECTORY = "./网页资源"

节点列表 = []


class 长视频规划师扩展(ComfyExtension):
    @override
    async def on_load(self) -> None:
        # 全局资源初始化：节点导入 + 媒体/预设路由注册（保持模块导入纯净）
        try:
            from .节点.长视频规划师 import 长视频规划师
            节点列表.append(长视频规划师)
        except ImportError as _e:  # 节点尚未就绪时仍可加载插件
            logging.warning(f"[长视频规划师] 节点导入跳过: {_e}")

        try:
            from .后端路由 import 媒体路由
            媒体路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 媒体路由跳过: {_e}")

        try:
            from .后端路由 import 预设路由
            预设路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 预设路由跳过: {_e}")

        try:
            from .后端路由 import 计划路由
            计划路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 计划路由跳过: {_e}")

    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return list(节点列表)


async def comfy_entrypoint() -> 长视频规划师扩展:
    return 长视频规划师扩展()
