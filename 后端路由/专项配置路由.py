# -*- coding: utf-8 -*-
"""专项能力配置入口；检索不允许请求体临时扩大授权目录。"""
import asyncio
import json
from aiohttp import web
try:
    from ..规划.专项能力配置 import 读专项配置, 写专项配置
    from ..规划.本地参考 import 检索本地参考
except ImportError:
    from 规划.专项能力配置 import 读专项配置, 写专项配置
    from 规划.本地参考 import 检索本地参考


def 注册专项配置路由(routes):
    async def body(request):
        if request.content_type != "application/json":
            raise ValueError("请求须使用application/json格式")
        raw = bytearray()
        async for block in request.content.iter_chunked(4096):
            raw.extend(block)
            if len(raw) > 64000:
                raise ValueError("专项请求超过64KB")
        return json.loads(raw)
    @routes.get("/lvp/skill_config")
    async def read(request):
        try:
            return web.json_response(读专项配置())
        except (ValueError, OSError) as e:
            return web.json_response({"error": str(e)}, status=400)

    @routes.post("/lvp/skill_config")
    async def write(request):
        try:
            if request.content_length and request.content_length > 32000:
                raise ValueError("专项配置超过32KB")
            data = await body(request)
            if not isinstance(data, dict):
                raise ValueError("专项配置须为对象")
            return web.json_response(写专项配置(data))
        except (ValueError, OSError) as e:
            return web.json_response({"error": str(e)}, status=400)

    @routes.post("/lvp/local_reference/search")
    async def search(request):
        try:
            data = await body(request)
            if not isinstance(data, dict) or not isinstance(data.get("查询"), str) or len(data["查询"]) > 16000:
                raise ValueError("查询须为16000字以内的文本")
            result = await asyncio.to_thread(检索本地参考, data["查询"])
            return web.json_response(result)
        except (ValueError, OSError) as e:
            return web.json_response({"error": str(e)}, status=400)
