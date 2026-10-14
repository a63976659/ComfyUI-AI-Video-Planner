# -*- coding: utf-8 -*-
"""图像API配置仅在服务器保存明文密钥。"""
import asyncio
from aiohttp import web

try:
    from ..规划.图像配置 import 脱敏图像配置, 写图像配置
except ImportError:
    from 规划.图像配置 import 脱敏图像配置, 写图像配置


def 注册图像配置路由(routes):
    @routes.get("/lvp/image_config")
    async def 读取(request):
        try:
            return web.json_response(await asyncio.to_thread(脱敏图像配置))
        except (OSError, ValueError):
            return web.json_response({"error": "图像配置读取失败，请检查配置文件"}, status=400)

    @routes.post("/lvp/image_config")
    async def 保存(request):
        try:
            body = await request.json()
            if len(str(body)) > 100000:
                raise ValueError("图像配置过大")
            return web.json_response(await asyncio.to_thread(写图像配置, body))
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except OSError:
            return web.json_response({"error": "图像配置写入失败"}, status=500)
