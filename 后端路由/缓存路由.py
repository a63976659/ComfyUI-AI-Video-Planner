# -*- coding: utf-8 -*-
"""缓存路由：/lvp/cache/* 提供段产物磁盘缓存的「可观测性 + 手动清理」后端入口（规格 §二·B §B-7）。

- GET  /lvp/cache/stats → 当前版本段缓存快照 {版本, 根目录, 条目数, 大小字节}。
- POST /lvp/cache/clear → 手动清空当前版本段缓存，返回 {版本, 删除数, 释放字节}。

真源在 执行/段缓存（缓存统计 / 清空段缓存，均磁盘 IO、CPU 可测、自身不抛）；本模块只是把它们
包成 aiohttp handler，供前端状态栏的「段缓存 N 项 / M｜清理」控件调用。HTTP 边界错误契约与
媒体路由/计划路由/预设路由 同源：handler **不抛**未捕获异常（aiohttp 会吞成 text/plain，前端
resp.json() 读不到 message），一律收敛为 JSON {error}；IO 失败 → 500。

⚠️ 保护活动任务：清空只删**当前版本目录**内本模块产出的 .pt/.part（白名单正则，model.pt 等免伤），
不碰旧版本目录（由 段缓存._淘汰旧版本 负责）与其它文件；且是用户主动、跨轮操作——正在跑的生成轮次
不经这条路。§B-7 首版刻意不自动淘汰同版本可复用结果，手动清空是唯一收缩手段（详 段缓存.清空段缓存）。
"""
from aiohttp import web

_已注册 = False


def _缓存层():
    """惰性取 执行.段缓存 的两个可观测性函数（与 执行核心/节点 同款相对→顶层双 import，
    兼容 ComfyUI 包加载与 pytest 裸插件根两条导入路径）。"""
    try:
        from ..执行.段缓存 import 缓存统计, 清空段缓存
    except ImportError:
        from 执行.段缓存 import 缓存统计, 清空段缓存
    return 缓存统计, 清空段缓存


def 注册路由():
    """幂等注册 aiohttp 路由（供 __init__.py 调用）。"""
    global _已注册
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes

    @routes.get("/lvp/cache/stats")
    async def 缓存查询(request):
        """返回当前版本段缓存快照。缓存层自身不抛，此 except 仅兜极端意外（如导入失败）→ 500 JSON。"""
        try:
            缓存统计, _清空 = _缓存层()
            统计 = 缓存统计()
        except Exception as e:  # noqa: BLE001 - HTTP 边界：任何意外都转 500 JSON，不外抛
            return web.json_response({"error": f"段缓存统计失败：{e}"}, status=500)
        return web.json_response(统计)

    @routes.post("/lvp/cache/clear")
    async def 缓存清理(request):
        """清空当前版本段缓存，返回 {版本, 删除数, 释放字节}。同上：边界不抛。"""
        try:
            _统计, 清空段缓存 = _缓存层()
            结果 = 清空段缓存()
        except Exception as e:  # noqa: BLE001 - HTTP 边界：任何意外都转 500 JSON，不外抛
            return web.json_response({"error": f"段缓存清理失败：{e}"}, status=500)
        return web.json_response(结果)

    _已注册 = True
