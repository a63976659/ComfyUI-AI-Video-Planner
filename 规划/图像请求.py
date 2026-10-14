# -*- coding: utf-8 -*-
"""OpenAI Images兼容接口；可取消、有界响应、不自动重试收费生图。"""
import asyncio
import base64
import io
import ipaddress
import json
from urllib.parse import urlsplit

import aiohttp
from PIL import Image

from .配置 import 读配置, _ssl上下文
from .并发任务 import 请求限流器

_上限 = 32 * 1024 * 1024


class 公网解析器(aiohttp.resolver.DefaultResolver):
    async def resolve(self, host, port=0, family=0):
        records = await super().resolve(host, port, family)
        if not records or any(not ipaddress.ip_address(r["host"]).is_global for r in records):
            raise ValueError("生图返回的下载地址不能指向本机或内网")
        return records


async def 限长读取(response):
    if response.content_length is not None and response.content_length > _上限:
        raise ValueError("图像响应超过32MiB")
    raw = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        raw.extend(chunk)
        if len(raw) > _上限:
            raise ValueError("图像响应超过32MiB")
    return bytes(raw)


def 验图(raw):
    if not raw or len(raw) > _上限:
        raise ValueError("生图没有返回有效图片或超过32MiB")
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > 32_000_000 or min(image.size) < 64 or image.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError("生图尺寸或格式不合法")
        image.load()
        output = io.BytesIO()
        image.convert("RGB").save(output, format="PNG")
        data = output.getvalue()
        if len(data) > _上限:
            raise ValueError("图像文件超过32MiB")
        return data


async def 生成图像(entry, prompt, 请求回调=None, 参考图片=()):
    cfg = 读配置()
    timeout = max(120, min(3600, int(cfg.get("timeout", 120))))
    limiter = 请求限流器(cfg, 图像=True)
    if not await limiter.异步获取(timeout):
        raise ValueError("图像API繁忙，请稍后重试；没有发起生图请求")
    try:
        url = entry["base_url"].rstrip("/")
        request = {"json": {"model": entry["model"], "prompt": prompt, "n": 1, "size": "1024x1024"}}
        if 参考图片:
            base = url.rsplit("/images/", 1)[0] if "/images/" in url else url
            if base != "https://api.openai.com/v1":
                raise ValueError("上传参考图片生图目前仅获授权至https://api.openai.com/v1；未发送图片，未降级为纯文字生图")
            url = base + "/images/edits"
            form = aiohttp.FormData(quote_fields=False)
            for key, value in {"model": entry["model"], "prompt": prompt, "n": "1", "size": "1024x1024"}.items():
                form.add_field(key, value)
            for image in 参考图片:
                form.add_field("image" if len(参考图片) == 1 else "image[]", image["字节"],
                               filename=image["名"], content_type=image["MIME"])
            request = {"data": form}
        elif not url.endswith("/images/generations"):
            url += "/images/generations"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            if 请求回调:
                请求回调()
            async with session.post(url, **request,
                headers={"Authorization": "Bearer " + entry["api_key"]}, allow_redirects=False,
                ssl=_ssl上下文(cfg, url)) as response:
                if response.status != 200:
                    raise ValueError(f"图像API返回HTTP {response.status}；未自动改用其他模型或移除参考图片重试")
                data = json.loads((await 限长读取(response)).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("图像API响应须为对象")
            rows = data.get("data")
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError("图像API须返回一张图片")
            item = rows[0]
            if isinstance(item.get("b64_json"), str) and item["b64_json"]:
                raw = base64.b64decode(item["b64_json"], validate=True)
            elif isinstance(item.get("url"), str):
                address = item["url"]
                parsed = urlsplit(address)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("图像下载地址须为公网HTTPS地址")
                try:
                    literal = ipaddress.ip_address(parsed.hostname)
                except ValueError:
                    literal = None
                if literal is not None and not literal.is_global:
                    raise ValueError("图像下载地址不能指向本机或内网")
                connector = aiohttp.TCPConnector(resolver=公网解析器())
                async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=timeout)) as download:
                    async with download.get(address, allow_redirects=False) as response:
                        if response.status != 200:
                            raise ValueError(f"参考图下载失败HTTP {response.status}")
                        raw = await 限长读取(response)
            else:
                raise ValueError("图像API没有返回b64_json或url")
        try:
            return await asyncio.to_thread(验图, raw)
        except (OSError, Image.DecompressionBombError) as e:
            raise ValueError("图像API返回的图片无法解码或像素过大") from e
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise ValueError("生图连接失败或超时，已完成图片保存在检查点；未自动重发收费请求") from e
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeError) as e:
        raise ValueError("图像API响应格式无效") from e
    finally:
        limiter.释放()
