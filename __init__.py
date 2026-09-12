# -*- coding: utf-8 -*-
"""H3 导演台插件入口：V3 comfy_entrypoint 注册节点 + 网页资源 + 媒体/预设路由。"""
import logging

from comfy_api.latest import ComfyExtension, io
from typing_extensions import override

WEB_DIRECTORY = "./网页资源"

节点列表 = []


class H3导演台扩展(ComfyExtension):
    @override
    async def on_load(self) -> None:
        # 全局资源初始化：节点导入 + 媒体/预设路由注册（保持模块导入纯净）
        try:
            from .节点.导演台 import H3导演台
            节点列表.append(H3导演台)
        except ImportError as _e:  # 节点尚未就绪时仍可加载插件
            logging.warning(f"[H3导演台] 节点导入跳过: {_e}")

        try:
            from .后端路由 import 媒体路由
            媒体路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[H3导演台] 媒体路由跳过: {_e}")

        try:
            from .后端路由 import 预设路由
            预设路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[H3导演台] 预设路由跳过: {_e}")

    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return list(节点列表)


async def comfy_entrypoint() -> H3导演台扩展:
    return H3导演台扩展()
