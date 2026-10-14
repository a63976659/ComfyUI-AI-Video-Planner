"""提示词任务保存逐段结果，进度连接的断开不停止生成。"""
import asyncio
import hashlib
import hmac
import re
import threading
from pathlib import Path

from aiohttp import web

try:
    from ..规划.项目存储 import 写JSON, 读JSON
except ImportError:
    from 规划.项目存储 import 写JSON, 读JSON


class 提示词任务管理:
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).resolve().parents[1] / "计划数据" / "提示词任务")
        self.jobs = {}

    def 获取(self, identity):
        if not isinstance(identity, dict):
            raise web.HTTPBadRequest(reason="缺少提示词任务凭据")
        key, token = identity.get("id"), identity.get("token")
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key) or not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
            raise web.HTTPBadRequest(reason="提示词任务凭据格式错误")
        digest = hashlib.sha256(token.encode()).hexdigest()
        job = self.jobs.get(key)
        if job is None:
            path = self.root / f"{key}.json"
            if not path.is_file():
                return None
            saved = 读JSON(path)
            if not hmac.compare_digest(saved["digest"], digest):
                raise web.HTTPForbidden(reason="提示词任务凭据无效")
            job = {**saved, "停止": threading.Event(), "更新": asyncio.Event()}
            self.jobs[key] = job
            if not job["terminal"]:
                self.记录(job, "fatal", {"error": "服务已重启，已完成提示词保留，请重新生成剩余段。"})
        if not hmac.compare_digest(job["digest"], digest):
            raise web.HTTPForbidden(reason="提示词任务凭据无效")
        return job

    def 创建(self, identity, meta):
        job = self.获取(identity)
        if job is not None:
            return job, False
        if sum(not j["terminal"] for j in self.jobs.values()) >= 8:
            raise web.HTTPServiceUnavailable(reason="提示词任务繁忙，请稍后再试")
        # 已完成任务可从文件接回，内存只保留最近任务。
        for key, value in list(self.jobs.items()):
            if value["terminal"]:
                del self.jobs[key]
        job = {"id": identity["id"], "digest": hashlib.sha256(identity["token"].encode()).hexdigest(),
               "meta": meta, "events": [], "seq": 0, "terminal": False,
               "停止": threading.Event(), "更新": asyncio.Event()}
        self.jobs[job["id"]] = job
        self.保存(job)
        return job, True

    def 保存(self, job):
        写JSON(self.root / f"{job['id']}.json", {k: job[k] for k in ("id", "digest", "meta", "events", "seq", "terminal")})

    def 记录(self, job, name, data):
        if job["terminal"]:
            return
        job["seq"] += 1
        event = (name, {**data, "seq": job["seq"]})
        if name == "progress":
            job["progress"] = event
        else:
            job["events"].append(event)
            job["terminal"] = name in ("done", "fatal")
            self.保存(job)
        job["更新"].set()

    def 停止(self, job):
        job["停止"].set()
        self.记录(job, "done", {"stopped": True})

    async def 连接(self, request, job, sse, after=0):
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        try:
            await response.prepare(request)
            await response.write(sse("meta", job["meta"]))
            while True:
                job["更新"].clear()
                events = [e for e in job["events"] if e[1]["seq"] > after]
                if job.get("progress", (None, {"seq": 0}))[1]["seq"] > after:
                    events.append(job["progress"])
                for name, data in sorted(events, key=lambda e: e[1]["seq"]):
                    await response.write(sse(name, data))
                    after = data["seq"]
                if job["terminal"]:
                    break
                transport = getattr(request, "transport", None)
                if transport is not None and transport.is_closing():
                    break
                try:
                    await asyncio.wait_for(job["更新"].wait(), timeout=2)
                except asyncio.TimeoutError:
                    await response.write(sse("heartbeat", {}))
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass
        return response
