# -*- coding: utf-8 -*-
"""可取消的异步模型请求；默认保留AI规划策略，可显式设置时间轴请求预算。"""
import asyncio
import json
import uuid
import re
import logging
from urllib.parse import urlsplit

import aiohttp

from .配置 import 读配置, LLM错误, _限流器, _整数配置, _ssl上下文, _分类HTTP
from .规划结构请求 import 规划结构选项
from .原件输入 import 读取规划原件, 拼接原件消息, 校验原件端点, 原件协议版本, 授权端点, 原件输入方式, 绑定内联原件


class 异步模型请求:
    def __init__(self, 覆盖=None, *, 请求选项=None, 请求回调=None, 总超时=None, 仅正文=False):
        self.配置 = {**读配置(), **(覆盖 or {})}
        self.会话 = None
        self.用量 = []
        self.请求选项 = 请求选项 or {}
        self.请求回调 = 请求回调
        self.总超时 = 总超时
        self.仅正文 = 仅正文
        self.规划原件 = []
        self.原件记录 = None
        self._远程原件 = []

    async def 绑定规划原件(self, prepared, *, 媒体目录=None):
        self.原件记录 = {"协议": 原件协议版本, "文件": [], "文档上传次数": 0}
        if not prepared["brief"].get("素材"):
            return
        mode = 原件输入方式(self.配置, prepared["brief"]["素材"])
        if 媒体目录 is None:
            try:
                from ..后端路由.媒体路由 import 媒体根
            except ImportError:
                from 后端路由.媒体路由 import 媒体根
            媒体目录 = 媒体根()
        reading = asyncio.create_task(asyncio.to_thread(读取规划原件, prepared, 媒体目录))
        try:
            records = await asyncio.shield(reading)
        except asyncio.CancelledError:
            def close_later(task):
                try:
                    for record in task.result():
                        record["原件"].close()
                except BaseException:
                    pass
            reading.add_done_callback(close_later)
            raise
        self.规划原件 = records
        self.原件记录 = {"协议": 原件协议版本, "文件": [r["记录"] for r in records], "文档上传次数": 0}
        if mode == "Moonshot内联":
            await asyncio.to_thread(绑定内联原件, records)
            return
        for record in records:
            if record["记录"]["类型"] != "文本":
                try:
                    await self._上传临时媒体(record)
                except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                    raise ValueError("媒体原件上传连接失败或超时，未开始规划；上传结果未知，不自动重复上传") from error
                continue
            form = aiohttp.FormData(quote_fields=False)
            form.add_field("purpose", "file-extract")
            form.add_field("file", getattr(record["原件"], "file", record["原件"]), filename=record["记录"]["名"], content_type=record["MIME"])
            # 不重试上传：响应丢失时不能确认是否已创建远程文件。
            self.原件记录["文档上传次数"] += 1
            record["记录"]["上传状态"] = "未确认"
            try:
                data = await self._文件请求("post", "/files", data=form)
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                raise ValueError("文档原件上传连接失败或超时，未开始规划；上传结果未知，不自动重复上传") from error
            ident = data.get("id")
            if not isinstance(ident, str) or not re.fullmatch(r"file-[A-Za-z0-9_-]+", ident):
                raise ValueError("文档上传接口未返回有效文件ID；未开始规划")
            self._远程原件.append(ident)
            record["记录"]["文件ID"] = ident
            if (not isinstance(data.get("bytes"), int) or isinstance(data["bytes"], bool) or
                    data["bytes"] != record["记录"]["字节数"] or data.get("purpose") != "file-extract"):
                raise ValueError("文档上传回执与原件不一致；未开始规划")
            record["记录"]["上传状态"] = data.get("status", "unknown")
        self.规划原件 = records

    async def _上传临时媒体(self, record):
        """使用百炼官方模型专属临时存储；仅上传当前任务原件。"""
        cfg = self.配置
        校验原件端点(cfg)
        timeout = aiohttp.ClientTimeout(total=None, sock_read=_整数配置(cfg, "timeout", 120, 下限=1))
        async with self.会话.get("https://dashscope.aliyuncs.com/api/v1/uploads",
                params={"action": "getPolicy", "model": cfg["model"]},
                headers={"Authorization": f"Bearer {cfg.get('api_key', '')}"}, allow_redirects=False,
                ssl=_ssl上下文(cfg, 授权端点), timeout=timeout) as response:
            if response.status != 200:
                await self._服务错误(response, "获取官方临时上传凭证")
            policy = (await response.json())["data"]
        host = policy.get("upload_host", "")
        parsed = urlsplit(host)
        if (parsed.scheme != "https" or not re.fullmatch(r"dashscope-file-[a-z0-9-]+\.oss-cn-beijing\.aliyuncs\.com", parsed.hostname or "")
                or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise ValueError("官方临时存储地址不符合百炼北京OSS范围，未上传原件")
        directory = policy.get("upload_dir")
        if not isinstance(directory, str) or not directory or ".." in directory.split("/") or any(c in directory for c in "\\?#"):
            raise ValueError("官方临时存储目录无效，未上传原件")
        key = directory.rstrip("/") + "/" + uuid.uuid4().hex + "-" + record["记录"]["名"]
        form = aiohttp.FormData(quote_fields=False)
        for field, value in {"OSSAccessKeyId": policy["oss_access_key_id"], "Signature": policy["signature"],
                "policy": policy["policy"], "x-oss-object-acl": policy["x_oss_object_acl"],
                "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"], "key": key, "success_action_status": "200"}.items():
            form.add_field(field, str(value))
        form.add_field("file", getattr(record["原件"], "file", record["原件"]), filename=record["记录"]["名"], content_type=record["MIME"])
        record["记录"]["临时上传状态"] = "未确认"
        # 大文件传输不套用整段120秒预算；连接受控，上传过程可由任务取消。
        upload_timeout = aiohttp.ClientTimeout(total=None, connect=_整数配置(cfg, "timeout", 120, 下限=1))
        async with self.会话.post(host, data=form, allow_redirects=False, timeout=upload_timeout,
                ssl=_ssl上下文(cfg, host)) as response:
            if response.status not in (200, 204):
                await self._服务错误(response, "官方临时素材上传")
            await response.read()
        url = "oss://" + key
        kind = record["记录"]["类型"]
        if kind == "图像":
            record["消息"] = {"type": "image_url", "image_url": {"url": url}}
        elif kind == "音频":
            suffix = record["记录"]["名"].rsplit(".", 1)[-1].lower()
            record["消息"] = {"type": "input_audio", "input_audio": {"data": url, "format": suffix}}
        else:
            record["消息"] = {"type": "video_url", "video_url": {"url": url}}
        record["记录"].update(临时上传状态="已上传", 临时清理="百炼自动过期清理")

    async def _服务错误(self, response, action):
        # 服务端限制原样说明，不把上传失败误写成模型未收到正文。
        text = await response.text()
        try:
            data = json.loads(text)
            error = data.get("error") or data
            detail = error.get("message") or error.get("code") or text if isinstance(error, dict) else str(error)
        except (ValueError, TypeError):
            detail = text
        detail = str(detail).replace(str(self.配置.get("api_key") or "\0"), "[已隐藏]")
        kind, retry, status = _分类HTTP(response.status)
        raise LLM错误(f"{action}：HTTP {response.status}；{detail}", 类别=kind, 可重试=retry,
                      状态码=status, 请求ID=uuid.uuid4().hex[:8])

    async def _文件请求(self, method, path, **kwargs):
        校验原件端点(self.配置)
        timeout = _整数配置(self.配置, "timeout", 120, 下限=1)
        headers = {"Authorization": f"Bearer {self.配置.get('api_key', '')}"}
        url = 授权端点 + path
        async with getattr(self.会话, method)(url, headers=headers, allow_redirects=False,
                ssl=_ssl上下文(self.配置, url), timeout=aiohttp.ClientTimeout(total=timeout), **kwargs) as response:
            if response.status not in (200, 201):
                await self._服务错误(response, "原件文件接口")
            raw = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                raw.extend(chunk)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("原件文件接口响应格式错误")
            return data

    async def __aenter__(self):
        self.会话 = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        try:
            if self._远程原件:
                await self._清理远程原件()
        finally:
            for record in self.规划原件:
                record["原件"].close()
            await self.会话.close()

    async def _清理远程原件(self):
        async def clean():
            failed = []
            for ident in self._远程原件:
                try:
                    result = await self._文件请求("delete", "/files/" + ident)
                    if result.get("id") != ident or result.get("deleted") is not True:
                        failed.append(ident)
                except Exception:
                    failed.append(ident)
            self.原件记录["远程文档清理"] = {"已完成": not failed, "未清理文件ID": failed}
        task = asyncio.create_task(clean())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=15)
        except (asyncio.TimeoutError, asyncio.CancelledError) as error:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.原件记录["远程文档清理"] = {"已完成": False, "未确认文件ID": list(self._远程原件)}
            logging.warning("[长视频规划师] 本任务上传的远程文档未全部确认清理，可按运行记录中的文件ID核查")
            if isinstance(error, asyncio.CancelledError):
                raise

    async def __call__(self, system, user):
        cfg = self.配置
        options = {**规划结构选项(cfg, system, user), **self.请求选项}
        omni = "omni" in str(cfg.get("model") or "").lower()
        if omni:
            options.update(modalities=["text"], stream=True, stream_options={"include_usage": True})
        if self.规划原件 and isinstance(user, str) and system.startswith("你是视频内容规划师"):
            原件输入方式(cfg, [r["记录"] for r in self.规划原件])
            user = 拼接原件消息(user, self.规划原件)
            system += "本次附有选入素材原件或同一文档的完整逐字正文，具体类型与发送方式已明确标注。媒体可依据实际画面和声音分析，不凭文件名猜测。未知时码或观察限制仍须如实报告。"
        structured = "response_format" in options
        base = str(cfg.get("base_url") or "").rstrip("/")
        model = str(cfg.get("model") or "").strip()
        rid = uuid.uuid4().hex[:8]
        if not base or not model:
            raise LLM错误("请先配置 API 模型", 类别="config", 状态码=400, 请求ID=rid)
        timeout = _整数配置(cfg, "timeout", 120, 下限=1)
        _限流器.设置上限(_整数配置(cfg, "llm_max_active", 2, 下限=1),
                     _整数配置(cfg, "llm_max_queued", 4, 下限=0))
        if not await _限流器.异步获取(timeout):
            raise LLM错误("LLM 请求繁忙，请稍后重试", 类别="busy", 可重试=True, 状态码=503, 请求ID=rid)
        try:
            headers = {"Content-Type": "application/json"}
            if cfg.get("api_key"):
                headers["Authorization"] = f"Bearer {cfg['api_key']}"
            if self.规划原件 and urlsplit(base).hostname == "dashscope.aliyuncs.com":
                headers["X-DashScope-OssResourceResolve"] = "enable"
            if system.startswith("你是视频内容规划师"):
                for output_limit in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                    options.pop(output_limit, None)
            url = base + "/chat/completions"
            # 不隐式重试：每一次收费请求都由上层任务预算计数。禁止携凭据跟随重定向。
            if self.请求回调:
                self.请求回调()
            async with self.会话.post(url, json={"model": model, "messages": [
                    {"role": "system", "content": system}, {"role": "user", "content": user}], **options},
                    headers=headers, allow_redirects=False, ssl=_ssl上下文(cfg, url),
                    # AI规划默认仅限制无数据等待；时间轴显式传入完整请求预算。
                    timeout=aiohttp.ClientTimeout(total=self.总超时,
                                                  connect=min(timeout, 30) if self.总超时 is not None else timeout,
                                                  sock_connect=min(timeout, 30) if self.总超时 is not None else timeout,
                                                  sock_read=timeout)) as resp:
                if resp.status != 200:
                    await self._服务错误(resp, "模型服务")
                if omni:
                    return await self._读流式正文(resp, None, rid)
                raw = bytearray()
                async for part in resp.content.iter_chunked(65536):
                    raw.extend(part)
                data = json.loads(raw.decode("utf-8"))
                message = data["choices"][0]["message"]
                content = message.get("content")
                if not self.仅正文 and not structured:
                    content = content or message.get("reasoning_content")
                if (self.仅正文 or structured) and data["choices"][0].get("finish_reason") == "length":
                    raise ValueError("模型正文被截断")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("模型未返回正文")
                usage = data.get("usage")
                if isinstance(usage, dict):
                    self.用量.append({k: v for k, v in usage.items()
                                    if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                                    and isinstance(v, int) and not isinstance(v, bool) and v >= 0})
                return content
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise LLM错误("模型连接失败或超时", 类别="network", 可重试=True, 请求ID=rid) from e
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLM错误("模型响应格式无效", 类别="parse", 请求ID=rid) from e
        finally:
            _限流器.释放()

    async def _读流式正文(self, resp, limit, rid, *, 传输上限=None):
        """按Omni官方SSE协议只收正文；旧容量参数忽略，完整结束检查保留。"""
        body, pending, finished, ended = [], bytearray(), False, False
        async for chunk in resp.content.iter_chunked(65536):
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, rest = pending.partition(b"\n")
                pending = bytearray(rest)
                line = line.rstrip(b"\r")
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    ended = True
                    continue
                if not payload:
                    continue
                data = json.loads(payload.decode("utf-8"))
                if data.get("error"):
                    raise ValueError("模型流式请求返回错误")
                usage = data.get("usage")
                if isinstance(usage, dict):
                    self.用量.append({k: v for k, v in usage.items() if k in
                        ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, int) and not isinstance(v, bool) and v >= 0})
                for choice in data.get("choices", []):
                    if choice.get("index", 0) != 0:
                        continue
                    reason = choice.get("finish_reason")
                    if reason == "length":
                        raise ValueError("模型正文被截断")
                    if reason is not None:
                        if reason != "stop":
                            raise ValueError("模型没有正常完成规划正文")
                        finished = True
                    content = choice.get("delta", {}).get("content")
                    if isinstance(content, str):
                        body.append(content)
        result = "".join(body)
        if pending.strip() or not ended or not finished or not result.strip():
            raise ValueError("模型流式正文未完整结束")
        return result
