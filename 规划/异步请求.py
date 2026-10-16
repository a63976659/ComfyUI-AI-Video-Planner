# -*- coding: utf-8 -*-
"""可取消的异步模型请求；默认保留AI规划策略，可显式设置时间轴请求预算。"""
import asyncio
import json
import uuid
import re
import logging
from urllib.parse import urlsplit

import aiohttp

from .配置 import 读配置, LLM错误, _整数配置, _ssl上下文, _分类HTTP
from .规划结构请求 import 规划结构选项
from .并发任务 import 请求限流器, 并发收集
from .原件输入 import 读取规划原件, 拼接原件消息, 原件协议版本, 授权端点, DeepSeek端点, 原件输入方式, 绑定内联原件


class _原件流(aiohttp.payload.Payload):
    def __init__(self, record):
        super().__init__(record["原件"], content_type=record["MIME"], filename=record["记录"]["名"])
        self._size = record["记录"]["字节数"]

    async def write(self, writer):
        self._value.seek(0)
        while chunk := await asyncio.to_thread(self._value.read, 65536):
            await writer.write(chunk)

    def decode(self, encoding="utf-8", errors="strict"):
        raise TypeError("媒体原件流不能解码为文本")


class 异步模型请求:
    def __init__(self, 覆盖=None, *, 请求选项=None, 请求回调=None, 总超时=None, 仅正文=False):
        self.配置 = {**读配置(), **(覆盖 or {})}
        self.会话 = None
        self.用量 = []
        self.请求用量 = []
        self._用量索引 = {}
        self.请求选项 = 请求选项 or {}
        self.请求回调 = 请求回调
        self.总超时 = 总超时
        self.仅正文 = 仅正文
        self.规划原件 = []
        self.原件记录 = None
        self._远程原件 = []
        self._文件SSL = None

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
        if mode == "接口内联":
            await asyncio.to_thread(绑定内联原件, records)
            return
        if mode == "DeepSeek图片文件":
            await asyncio.to_thread(绑定内联原件, [r for r in records if r["记录"]["类型"] != "图像"])
            images = [r for r in records if r["记录"]["类型"] == "图像"]
            slots = asyncio.Semaphore(4)
            async def upload_image(index, record):
                async with slots:
                    await self._上传DeepSeek图片(record)
            await 并发收集(images, upload_image)
            return
        async def upload(index, record):
            if record["记录"]["类型"] != "文本":
                try:
                    await self._上传临时媒体(record)
                except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                    raise ValueError("媒体原件上传连接失败或超时，未开始规划；上传结果未知，不自动重复上传") from error
                return
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
        await 并发收集(records, upload)
        self.规划原件 = records

    async def _上传DeepSeek图片(self, record):
        info = record["记录"]
        info.update(发送方式="DeepSeek Files原件上传；规划请求复用文件ID（无裁剪、转码或抽样）", 上传状态="未确认")
        self.原件记录["图片上传次数"] = self.原件记录.get("图片上传次数", 0) + 1
        form = aiohttp.FormData(quote_fields=False)
        form.add_field("purpose", "user_data")
        form.add_field("expires_after[anchor]", "created_at")
        form.add_field("expires_after[seconds]", "604800")
        form.add_field("file", _原件流(record), filename=info["名"], content_type=record["MIME"])
        try:
            data = await self._文件请求("post", "/files", 上传=True, data=form)
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            raise ValueError("DeepSeek图片原件上传连接失败或超时，未开始规划；上传结果未知，不自动重复上传") from error
        ident = data.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"file-api-[A-Za-z0-9_-]+", ident):
            raise ValueError("DeepSeek图片上传接口未返回有效文件ID；未开始规划")
        self._远程原件.append(ident)
        info["文件ID"] = ident
        if (not isinstance(data.get("bytes"), int) or isinstance(data["bytes"], bool)
                or data["bytes"] != info["字节数"] or data.get("purpose") != "user_data"):
            raise ValueError("DeepSeek图片上传回执与原件不一致；未开始规划")
        info["上传状态"] = "已上传"
        record["消息"] = {"type": "file", "file_id": ident}

    async def _上传临时媒体(self, record):
        """使用百炼官方模型专属临时存储；仅上传当前任务原件。"""
        cfg = self.配置
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
        form = aiohttp.MultipartWriter("form-data")
        for field, value in {"OSSAccessKeyId": policy["oss_access_key_id"], "Signature": policy["signature"],
                "policy": policy["policy"], "x-oss-object-acl": policy["x_oss_object_acl"],
                "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"], "key": key, "success_action_status": "200"}.items():
            part = aiohttp.payload.StringPayload(str(value))
            part.headers.clear()
            part.set_content_disposition("form-data", quote_fields=False, name=field)
            form.append_payload(part)
        part = aiohttp.payload.get_payload(getattr(record["原件"], "file", record["原件"]))
        part.headers.clear()
        part.set_content_disposition("form-data", quote_fields=False, name="file", filename=record["记录"]["名"])
        part.headers["Content-Type"] = record["MIME"]
        form.append_payload(part)
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
        error = LLM错误(f"{action}：HTTP {response.status}；{detail}", 类别=kind, 可重试=retry,
                        状态码=status, 请求ID=uuid.uuid4().hex[:8])
        error.原始响应 = text.replace(str(self.配置.get("api_key") or "\0"), "[已隐藏]")
        raise error

    async def _文件请求(self, method, path, *, 上传=False, **kwargs):
        timeout = _整数配置(self.配置, "timeout", 120, 下限=1)
        headers = {"Authorization": f"Bearer {self.配置.get('api_key', '')}"}
        base = DeepSeek端点 if 原件输入方式(self.配置, []) == "DeepSeek图片文件" else 授权端点
        url = base + path
        if self._文件SSL is None:
            self._文件SSL = _ssl上下文(self.配置, url)
        budget = aiohttp.ClientTimeout(total=600, connect=min(timeout, 30), sock_read=timeout) if 上传 else aiohttp.ClientTimeout(total=timeout)
        async with getattr(self.会话, method)(url, headers=headers, allow_redirects=False,
                ssl=self._文件SSL, timeout=budget, **kwargs) as response:
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
        cleanup_key = "远程图片清理" if 原件输入方式(self.配置, []) == "DeepSeek图片文件" else "远程文档清理"
        async def clean():
            failed = []
            async def remove(ident):
                try:
                    result = await self._文件请求("delete", "/files/" + ident)
                    if result.get("id") != ident or result.get("deleted") is not True:
                        failed.append(ident)
                except Exception:
                    failed.append(ident)
            if cleanup_key == "远程图片清理":
                slots = asyncio.Semaphore(4)
                async def worker(index, ident):
                    async with slots:
                        await remove(ident)
                await 并发收集(self._远程原件, worker)
            else:
                for ident in self._远程原件:
                    await remove(ident)
            self.原件记录[cleanup_key] = {"已完成": not failed, "未清理文件ID": failed}
        task = asyncio.create_task(clean())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=15)
        except (asyncio.TimeoutError, asyncio.CancelledError) as error:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.原件记录[cleanup_key] = {"已完成": False, "未确认文件ID": list(self._远程原件)}
            logging.warning("[长视频规划师] 本任务上传的远程文件未全部确认清理，可按运行记录中的文件ID核查")
            if isinstance(error, asyncio.CancelledError):
                raise

    async def __call__(self, system, user):
        cfg = self.配置
        try:
            request_data = json.loads(user) if isinstance(user, str) else {}
        except ValueError:
            request_data = {}
        metadata = {"阶段": request_data.get("规划阶段", ""), "阶段任务标识": request_data.get("阶段任务标识", "")} if isinstance(request_data, dict) else {}
        planning = system.startswith("你是视频内容规划师")
        options = {**规划结构选项(cfg, system, user), **self.请求选项}
        omni = "omni" in str(cfg.get("model") or "").lower()
        if omni:
            options.update(modalities=["text"], stream=True, stream_options={"include_usage": True})
        if self.规划原件 and isinstance(user, str) and system.startswith("你是视频内容规划师"):
            response_format = options.get("response_format", {})
            if response_format.get("type") == "json_schema" and any(r["记录"]["类型"] != "文本" for r in self.规划原件):
                payload = json.loads(user)
                payload["输出JSON结构"] = response_format["json_schema"]["schema"]
                user = json.dumps(payload, ensure_ascii=False)
                options["response_format"] = {"type": "json_object"}
            user = 拼接原件消息(user, self.规划原件)
            system += "本次附有选入素材原件或同一文档的完整逐字正文，具体类型与发送方式已明确标注。媒体可依据实际画面和声音分析，不凭文件名猜测。未知时码或观察限制仍须如实报告。"
        structured = "response_format" in options
        base = str(cfg.get("base_url") or "").rstrip("/")
        model = str(cfg.get("model") or "").strip()
        rid = uuid.uuid4().hex[:8]
        if not base or not model:
            raise LLM错误("请先配置 API 模型", 类别="config", 状态码=400, 请求ID=rid)
        timeout = _整数配置(cfg, "timeout", 120, 下限=1)
        limiter = 请求限流器(cfg)
        if not await limiter.异步获取(timeout):
            raise LLM错误("LLM 请求繁忙，请稍后重试", 类别="busy", 可重试=True, 状态码=503, 请求ID=rid)
        raw = bytearray()
        try:
            headers = {"Content-Type": "application/json"}
            if cfg.get("api_key"):
                headers["Authorization"] = f"Bearer {cfg['api_key']}"
            if self.规划原件 and urlsplit(base).hostname == "dashscope.aliyuncs.com":
                headers["X-DashScope-OssResourceResolve"] = "enable"
            for parameter in ("temperature", "max_tokens", "max_completion_tokens", "max_output_tokens"):
                options.pop(parameter, None)
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
                if options.get("stream") is True:
                    return await self._读流式正文(resp, None, rid, 原始响应=raw, 请求资料=metadata)
                async for part in resp.content.iter_chunked(65536):
                    raw.extend(part)
                data = json.loads(raw.decode("utf-8"))
                self._记录用量(data.get("usage") if isinstance(data, dict) else None, rid, metadata)
                message = data["choices"][0]["message"]
                content = message.get("content")
                if not planning and not self.仅正文 and not structured:
                    content = content or message.get("reasoning_content")
                if (planning or self.仅正文 or structured) and data["choices"][0].get("finish_reason") == "length":
                    raise ValueError("模型正文被截断（finish_reason=length）；接口输出额度已用尽，未生成完整结果")
                if not isinstance(content, str) or not content.strip():
                    if message.get("reasoning_content"):
                        raise ValueError("接口只返回思考内容（reasoning_content），没有最终正文（content）；不能作为规划JSON解析")
                    raise ValueError("模型未返回正文")
                return content
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            error = LLM错误("模型连接失败或超时；已接收的响应保留供排查", 类别="network", 可重试=True, 请求ID=rid)
            error.原始响应 = raw.decode("utf-8", errors="replace").replace(str(cfg.get("api_key") or "\0"), "[已隐藏]")
            raise error from e
        except (ValueError, KeyError, IndexError, TypeError) as e:
            detail = str(e).replace(str(cfg.get("api_key") or "\0"), "[已隐藏]")
            error = LLM错误(f"模型响应格式无效：{detail}", 类别="parse", 请求ID=rid)
            error.原始响应 = raw.decode("utf-8", errors="replace").replace(str(cfg.get("api_key") or "\0"), "[已隐藏]")
            raise error from e
        finally:
            limiter.释放()

    def _记录用量(self, usage, rid, metadata=None):
        if not isinstance(usage, dict):
            return
        values = {key: value for key, value in usage.items() if key in (
            "prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
            and isinstance(value, int) and not isinstance(value, bool) and value >= 0}
        if rid not in self._用量索引:
            self._用量索引[rid] = len(self.用量)
            self.用量.append({})
            self.请求用量.append({"请求ID": rid, **(metadata or {})})
        index = self._用量索引[rid]
        self.用量[index].update(values)
        self.请求用量[index].update(values)

    async def _读流式正文(self, resp, limit, rid, *, 传输上限=None, 原始响应=None, 请求资料=None):
        """按SSE协议只收正文；旧容量参数忽略，完整结束检查保留。"""
        body, pending, finished, ended = [], bytearray(), False, False
        failure, reasoning = None, False
        async for chunk in resp.content.iter_chunked(65536):
            if 原始响应 is not None:
                原始响应.extend(chunk)
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
                try:
                    data = json.loads(payload.decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError("流式事件须为 JSON 对象")
                except ValueError as error:
                    failure = failure or str(error)
                    continue
                if data.get("error"):
                    error = data["error"]
                    detail = error.get("message") or error.get("code") or "未知服务错误" if isinstance(error, dict) else str(error)
                    failure = failure or f"模型流式请求返回错误：{detail}"
                    continue
                self._记录用量(data.get("usage"), rid, 请求资料)
                for choice in data.get("choices", []):
                    if choice.get("index", 0) != 0:
                        continue
                    reason = choice.get("finish_reason")
                    if reason == "length":
                        failure = failure or "模型正文被截断（finish_reason=length）；接口输出额度已用尽，未生成完整结果"
                    if reason is not None:
                        if reason not in ("stop", "length"):
                            failure = failure or f"模型没有正常完成规划正文（finish_reason={reason}）"
                        finished = True
                    reasoning = reasoning or bool(choice.get("delta", {}).get("reasoning_content"))
                    content = choice.get("delta", {}).get("content")
                    if isinstance(content, str):
                        body.append(content)
        result = "".join(body)
        if failure:
            raise ValueError(failure)
        if pending.strip() or not ended or not finished:
            raise ValueError("模型流式正文未完整结束")
        if not result.strip():
            if reasoning:
                raise ValueError("接口只返回思考内容（reasoning_content），没有最终正文（content）；不能作为规划JSON解析")
            raise ValueError("模型未返回正文")
        return result
