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
            # 主节点的可选配置产物（不连即单阶段采样），紧跟消费者注册以便分类面板相邻
            from .节点.SelfLift配置 import SelfLift配置
            节点列表.append(SelfLift配置)
        except ImportError as _e:
            logging.warning(f"[长视频规划师] SelfLift配置节点导入跳过: {_e}")

        try:
            from .节点.精修与放大 import 精修与放大
            节点列表.append(精修与放大)
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 精修与放大节点导入跳过: {_e}")

        try:
            from .节点.初采交接与清理 import 初采交接与清理
            from .节点.交接内部节点 import LVP_交接写入, LVP_阶段清理, LVP_二采入口, LVP_读取初采引用
            节点列表.extend([初采交接与清理, LVP_交接写入, LVP_阶段清理, LVP_二采入口, LVP_读取初采引用])
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 交接节点导入跳过: {_e}")

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

        try:
            from .后端路由 import 规划路由
            规划路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 规划路由跳过: {_e}")

        try:
            from .后端路由 import 缓存路由
            缓存路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 缓存路由跳过: {_e}")

        try:
            from .后端路由 import 交接路由
            交接路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 交接路由跳过: {_e}")

        try:
            from .后端路由 import 制作路由
            制作路由.注册路由()
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 制作路由跳过: {_e}")

        try:
            from .节点.视频制作输出 import 视频制作输出
            节点列表.append(视频制作输出)
        except ImportError as _e:
            logging.warning(f"[长视频规划师] 视频制作输出节点跳过: {_e}")

    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return list(dict.fromkeys(节点列表))   # 模块留在 sys.modules 时 on_load 会再跑一遍，去重保证幂等


async def comfy_entrypoint() -> 长视频规划师扩展:
    return 长视频规划师扩展()
