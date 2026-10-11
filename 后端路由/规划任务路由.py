# -*- coding: utf-8 -*-
"""AI 规划任务通道；H3 提示词流式接口不经过此模块。"""
import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
import copy
import re
from dataclasses import dataclass, field

from aiohttp import web

try:
    from ..规划.内容规划 import 准备输入, 范围预览, 选定范围
    from ..规划.异步请求 import 异步模型请求
    from ..规划.配置 import LLM错误
    from ..规划.配置 import 读配置
    from ..规划.自动规划 import 生成自动规划
    from ..规划.项目存储 import 项目存储, 读JSON, 指纹, 阶段名称
    from ..规划.图像配置 import 选中图像模型
    from ..规划.文本话语 import 来源协议版本
    from ..规划.原件输入 import 原件协议版本
    from ..规划.规划定稿 import 校验确定交付
except ImportError:
    from 规划.内容规划 import 准备输入, 范围预览, 选定范围
    from 规划.异步请求 import 异步模型请求
    from 规划.配置 import LLM错误
    from 规划.配置 import 读配置
    from 规划.自动规划 import 生成自动规划
    from 规划.项目存储 import 项目存储, 读JSON, 指纹, 阶段名称
    from 规划.图像配置 import 选中图像模型
    from 规划.文本话语 import 来源协议版本
    from 规划.原件输入 import 原件协议版本
    from 规划.规划定稿 import 校验确定交付

_终态 = {"completed", "cancelled", "failed"}


@dataclass
class 规划任务:
    id: str
    凭据摘要: bytes
    输入: dict
    预览: dict
    覆盖: dict = field(default_factory=dict)
    状态: str = "queued"
    序号: int = 0
    进度: dict = field(default_factory=lambda: {"阶段": "等待开始", "已完成": 0, "总数": 0, "调用次数": 0, "调用上限": 600})
    结果: dict = None
    错误: str = ""
    协程: object = None
    订阅: object = None
    定时器: object = None
    创建时间: float = field(default_factory=time.monotonic)
    结束时间: float = 0
    项目: object = None
    关机续跑: bool = False

    def 快照(self):
        return {"id": self.id, "seq": self.序号, "status": self.状态, "progress": self.进度,
                "result": self.结果, "error": self.错误, "preview": self.预览,
                "stages": self.项目.阶段快照() if self.项目 else []}

    def 发进度(self, payload):
        if self.状态 in _终态:
            return
        self.进度 = dict(payload)
        self.序号 += 1
        if self.项目:
            self.项目.写任务(self)
        self._发布("progress")

    def _发布(self, name):
        if self.订阅 is not None:
            # 慢客户端只需要最新状态；终态不得因队列已满而丢失。
            if self.订阅.full():
                self.订阅.get_nowait()
            self.订阅.put_nowait((name, self.快照()))

    def 结束(self, status, result=None, error=""):
        if self.状态 in _终态:
            return
        self.状态, self.结果, self.错误 = status, result, error
        self.结束时间 = time.monotonic()
        self.序号 += 1
        if self.项目:
            if status in ("failed", "cancelled"):
                self.项目.暂停阶段("任务已停止，已保存的阶段成果仍可查看" if status == "cancelled" else "任务未完成，已保存的阶段成果仍可查看")
            self.项目.写任务(self, shutdown=self.关机续跑)
        self.输入, self.覆盖 = None, None
        if self.定时器:
            self.定时器.cancel()
            self.定时器 = None
        self._发布("terminal")

    async def 停止(self):
        if self.状态 in _终态:
            return
        if self.协程 is not None:
            self.协程.cancel()
            try:
                await self.协程
            except asyncio.CancelledError:
                pass
        self.结束("cancelled")


class 规划任务管理:
    def __init__(self, 模型工厂=异步模型请求, 容量=8, 存储目录=None):
        self.任务 = {}
        self.模型工厂 = 模型工厂
        self.容量 = 容量
        self.存储 = 项目存储(存储目录)
        self.解析覆盖 = lambda _: None

    def _版本(self, override):
        cfg = {**读配置(), **(override or {})}
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        code = {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in (root / "规划").glob("*.py")}
        try:
            from ..规划.专项能力配置 import 读专项配置
        except ImportError:
            from 规划.专项能力配置 import 读专项配置
        return {"运行格式": 1, "来源协议": 来源协议版本, "原件协议": 原件协议版本, "代码指纹": 指纹(code),
                "专项配置指纹": 指纹(读专项配置()),
                **({"图像模型指纹": 指纹({k: cfg["图像模型"][k] for k in ("id", "base_url", "model")})} if cfg.get("图像模型") else {}),
                "模型指纹": 指纹({k: cfg.get(k, "") for k in ("base_url", "model")})}

    def 清理(self, 预留=0):
        now = time.monotonic()
        for key, job in list(self.任务.items()):
            if job.状态 in _终态 and now - job.结束时间 > 300:
                del self.任务[key]
        done = sorted((j for j in self.任务.values() if j.状态 in _终态), key=lambda j: j.结束时间)
        for job in done[:max(0, len(self.任务) + 预留 - self.容量)]:
            del self.任务[job.id]

    def 创建(self, prepared, override=None):
        override = dict(override or {})
        if prepared["brief"].get("生成参考图"):
            override["图像模型"] = 选中图像模型()
        self.清理(预留=1)
        if sum(j.状态 not in _终态 for j in self.任务.values()) >= self.容量:
            raise web.HTTPServiceUnavailable(text="规划任务已满，请稍后重试")
        long = prepared["需选范围"] or len(prepared["范围"]) > 1
        if long:
            preview = {"范围": [], "调用上限": 600, "需选范围": False, "自动流程": True,
                       "范围数": len(prepared["范围"]), "输入类型": prepared["输入类型"]}
        else:
            preview = {**范围预览(prepared), "需选范围": False, "自动流程": True, "调用上限": 600}
        identity = self._版本(override)
        key = self.存储.标识(prepared, identity)
        if any(j.项目 and j.项目.记录.get("输入标识", j.项目.id) == key and j.状态 not in _终态 for j in self.任务.values()):
            raise ValueError("相同规划已有活动任务，正在自动继续；不能重复启动收费任务")
        # 每次点击新建独立存档；历史成果只在配置页经二次确认后清理。
        project = self.存储.打开(prepared, identity, 新建=True)
        project.更新(调用上限=600)
        token = secrets.token_urlsafe(32)
        job = 规划任务(secrets.token_hex(16), hashlib.sha256(token.encode()).digest(), prepared, preview, override or {})
        job.项目 = project
        job.项目.写任务(job)
        self.任务[job.id] = job
        job.定时器 = asyncio.get_running_loop().call_later(120, lambda: job.结束(
            "cancelled", error="进度连接超过 120 秒仍未建立，任务已取消") if job.状态 == "queued" else None)
        return job, token

    def 查找(self, job_id, token):
        job = self.任务.get(job_id)
        if job is None and re.fullmatch(r"[a-f0-9]{32}", job_id):
            record = next((r for r in self.存储.任务记录() if r.get("任务") == job_id), None)
            if record and hmac.compare_digest(record.get("凭据摘要", ""), hashlib.sha256(token.encode()).hexdigest()):
                job = self._读任务(record)
        if not job or not hmac.compare_digest(job.凭据摘要, hashlib.sha256(token.encode()).digest()):
            raise web.HTTPNotFound()
        return job

    def 只读查找(self, job_id, token):
        job = self.任务.get(job_id)
        if job is not None:
            if hmac.compare_digest(job.凭据摘要, hashlib.sha256(token.encode()).digest()):
                return job
            raise web.HTTPNotFound()
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise web.HTTPNotFound()
        record = next((r for r in self.存储.任务记录() if r.get("任务") == job_id), None)
        if not record or not hmac.compare_digest(record.get("凭据摘要", ""), hashlib.sha256(token.encode()).hexdigest()):
            raise web.HTTPNotFound()
        # 只读成果不恢复任务，不解析模型，也不越过继续生成的版本门禁。
        project = self.存储.项目(record["项目"])
        job = 规划任务(record["任务"], bytes.fromhex(record["凭据摘要"]), None, record.get("预览", {}))
        job.项目, job.状态, job.序号 = project, record["状态"], record.get("序号", 0)
        job.结果, job.错误, job.进度 = record.get("结果"), record.get("错误", ""), record.get("进度", {})
        return job

    def 开始(self, job, ids=None, 自动恢复=False):
        if job.状态 != "queued":
            return
        if any(j is not job and j.项目 and j.项目.id == job.项目.id and j.状态 == "running" for j in self.任务.values()):
            raise ValueError("相同项目已有运行任务，不重复调用模型")
        if job.订阅 is None and not 自动恢复:
            raise ValueError("请先连接规划进度通道，再开始任务")
        if ids is not None:
            scopes, _, _ = 选定范围(job.输入, ids)
            if [s["id"] for s in scopes] != [s["id"] for s in job.输入["范围"]]:
                raise ValueError("新版规划自动处理全文，不支持中途缩减范围")
        scopes = job.输入["范围"]
        job.预览.update({"已选范围": [s["id"] for s in scopes]})
        job.状态 = "running"
        if job.定时器:
            job.定时器.cancel()
        job.定时器 = None
        job.项目.写任务(job)
        job.协程 = asyncio.create_task(self._运行(job))

    async def _运行(self, job):
        async def perform():
            model = None
            manifest_accepted = False
            try:
                async with self.模型工厂(job.覆盖) as model:
                    if hasattr(model, "绑定规划原件"):
                        job.输入["brief"]["仅发送选入素材"] = True
                        job.发进度({"阶段": "准备规划素材原件" if job.输入["brief"].get("素材") else "纯文本规划，无素材需要发送"})
                        await model.绑定规划原件(job.输入)
                        manifest = getattr(model, "原件记录", None)
                        if manifest:
                            previous = job.项目.记录.get("原件传输", {}).get("文件")
                            # 临时文件ID不进入请求指纹，原件字节变化则拒绝恢复旧理解。
                            stable = lambda rows: [{k: v for k, v in r.items() if k not in ("文件ID", "上传状态")} for r in rows]
                            if previous and stable(previous) != stable(manifest["文件"]):
                                raise ValueError("规划原件已变化，旧任务不能恢复；请重新生成规划")
                            job.项目.更新(原件传输=manifest)
                            manifest_accepted = True
                            job.输入["brief"]["原件输入记录"] = stable(manifest["文件"])
                    result = await 生成自动规划(job.输入, job.项目, model, job.发进度,
                        **({"图像模型": job.覆盖["图像模型"]} if job.覆盖.get("图像模型") else {}))
                    result["规划资料"]["模型用量"] = getattr(model, "用量", [])
                    result["规划资料"]["任务"] = job.id
                    if getattr(model, "原件记录", None):
                        result["规划资料"]["原件传输"] = model.原件记录
                return result
            finally:
                if getattr(model, "原件记录", None):
                    if manifest_accepted or not job.项目.记录.get("原件传输"):
                        job.项目.更新(原件传输=model.原件记录)
                    else:
                        job.项目.更新(未采纳原件传输=model.原件记录)
        try:
            # 全文规划可包含很多次请求；网络等待超时由模型适配器逐次处理。
            # 任务通过累计请求上限及用户停止保持有界，不按总耗时截断。
            result = await perform()
            校验确定交付(result)
            job.结束("completed", result)
        except asyncio.CancelledError:
            job.结束("cancelled")
            raise
        except (ValueError, LLM错误) as e:
            job.项目.更新(状态="失败", 错误=str(e))
            job.结束("failed", error=str(e))
        except Exception:
            logging.exception("[长视频规划师] 分阶段规划失败")
            job.结束("failed", error="规划服务异常，原草稿未改变，请检查服务端日志")

    def _读任务(self, record):
        project = self.存储.项目(record["项目"])
        state = record["状态"]
        prepared, override = None, None
        # 完成存档只读，不依赖当前模型配置；兼容性门禁只保护继续生成。
        if state not in _终态:
            if sum(j.状态 not in _终态 for j in self.任务.values()) >= self.容量:
                raise web.HTTPServiceUnavailable(text="规划任务已满，请稍后重试")
            prepared = 读JSON(project.路径("原始资料", "输入.json"))
            override = self.解析覆盖(copy.deepcopy(prepared["brief"]))
            if prepared["brief"].get("生成参考图"):
                override = {**(override or {}), "图像模型": 选中图像模型()}
            if project.记录.get("运行版本") != self._版本(override):
                raise ValueError("规划程序或模型配置已变化，不能自动复用旧任务；旧项目保留，请重新生成")
        job = 规划任务(record["任务"], bytes.fromhex(record["凭据摘要"]), prepared, record["预览"], override or {})
        job.项目, job.序号, job.进度 = project, record.get("序号", 0), record.get("进度", {})
        if state in _终态:
            job.状态, job.结果, job.错误 = state, record.get("结果"), record.get("错误", "")
            job.输入 = job.覆盖 = None
            job.结束时间 = time.monotonic()
        self.任务[job.id] = job
        self.清理()
        return job

    async def 恢复运行(self, app=None):
        for record in self.存储.任务记录():
            if record.get("状态") not in ("running", "queued", "interrupted") or record.get("任务") in self.任务:
                continue
            if sum(j.状态 not in _终态 for j in self.任务.values()) >= self.容量:
                break
            try:
                if any(j.项目 and j.项目.id == record.get("项目") and j.状态 not in _终态 for j in self.任务.values()):
                    continue
                job = self._读任务(record)
                self.开始(job, 自动恢复=True)
            except (ValueError, OSError, KeyError, TypeError):
                logging.exception("[长视频规划师] 规划检查点恢复失败，项目仍保留")

    async def 关闭(self, app=None):
        for job in list(self.任务.values()):
            if job.状态 not in _终态:
                job.关机续跑 = True
                await job.停止()


def _帧(name, data):
    return f"id: {data['seq']}\nevent: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def 注册规划任务路由(routes, 解析模型覆盖, manager=None, app=None):
    from .图像配置路由 import 注册图像配置路由
    注册图像配置路由(routes)
    manager = manager or 规划任务管理()
    manager.解析覆盖 = 解析模型覆盖
    from .数据管理路由 import 注册数据管理路由
    注册数据管理路由(routes, manager)
    if app is not None:
        app.on_startup.append(manager.恢复运行)
        app.on_cleanup.append(manager.关闭)

    def lookup(request):
        try:
            return manager.查找(request.match_info["id"], request.headers.get("X-LVP-Plan-Token", ""))
        except web.HTTPNotFound:
            raise web.HTTPNotFound(text=json.dumps({"error": "规划记录不存在、已清理或无权访问，请重新生成"}, ensure_ascii=False),
                                   content_type="application/json")
        except (ValueError, OSError, KeyError, TypeError):
            raise web.HTTPConflict(text=json.dumps({"error": "规划存档不能恢复；检查点仍保留，请重新生成"}, ensure_ascii=False),
                                   content_type="application/json")

    @routes.post("/lvp/plan/jobs")
    async def 创建(request):
        try:
            body = await request.json()
            # 文件读取有严格规模边界，移到线程避免阻塞进度/取消处理。
            prepared = await asyncio.to_thread(准备输入, body)
            override = 解析模型覆盖(copy.deepcopy(prepared["brief"]))
            job, token = manager.创建(prepared, override)
            return web.json_response({**job.快照(), "token": token}, status=201)
        except (ValueError, TypeError, KeyError) as e:
            return web.json_response({"error": str(e)}, status=400)
        except OSError:
            return web.json_response({"error": "无法读取文本素材，请检查文件及权限"}, status=400)
        except web.HTTPServiceUnavailable:
            return web.json_response({"error": "规划任务已满，请稍后重试"}, status=503)

    @routes.get("/lvp/plan/jobs/{id}")
    async def 状态(request):
        try:
            job = lookup(request)
            if job.状态 == "queued" and job.定时器 is None:
                manager.开始(job, 自动恢复=True)
            return web.json_response(job.快照())
        except (ValueError, OSError):
            return web.json_response({"error": "规划存档不能恢复；检查点仍保留，请重新生成"}, status=409)

    @routes.get("/lvp/plan/jobs/{id}/episodes/{number}")
    async def 分集结果(request):
        job = lookup(request)
        try:
            if job.状态 != "completed" or not job.结果.get("分集"):
                raise ValueError("全剧尚未生成完成")
            number = int(request.match_info["number"])
            if not 1 <= number <= len(job.结果["分集"]):
                raise ValueError("分集不存在")
            return web.json_response(await asyncio.to_thread(job.项目.读分集, number))
        except (ValueError, OSError):
            return web.json_response({"error": "分集暂不可读取"}, status=404)

    @routes.get("/lvp/plan/jobs/{id}/stages")
    async def 阶段状态(request):
        try:
            job = manager.只读查找(request.match_info["id"], request.headers.get("X-LVP-Plan-Token", ""))
            return web.json_response({"id": job.id, "status": job.状态, "stages": job.项目.阶段快照()},
                                     headers={"Cache-Control": "no-store"})
        except (ValueError, OSError, KeyError, TypeError):
            return web.json_response({"error": "阶段状态暂不可读取"}, status=404)
        except web.HTTPNotFound:
            return web.json_response({"error": "任务不存在或无权查看成果"}, status=404)

    @routes.get("/lvp/plan/jobs/{id}/stages/{stage}")
    async def 阶段成果(request):
        stage = request.match_info["stage"]
        if stage not in 阶段名称:
            return web.json_response({"error": "规划成果阶段不存在"}, status=404)
        try:
            job = manager.只读查找(request.match_info["id"], request.headers.get("X-LVP-Plan-Token", ""))
            episode_text, offset_text = request.query.get("episode"), request.query.get("offset", "0")
            if episode_text is not None and (stage != "storyboards" or not re.fullmatch(r"[1-9]\d{0,2}", episode_text)):
                raise ValueError("分集参数不合法")
            if not re.fullmatch(r"\d{1,3}", offset_text) or stage != "analysis" and offset_text != "0":
                raise ValueError("内容页参数不合法")
            result = await asyncio.to_thread(job.项目.读阶段, stage, int(episode_text) if episode_text else None, int(offset_text))
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except (ValueError, OSError, KeyError, TypeError):
            return web.json_response({"error": "此阶段成果暂不可读取"}, status=404)
        except web.HTTPNotFound:
            return web.json_response({"error": "任务不存在或无权查看成果"}, status=404)

    @routes.post("/lvp/plan/jobs/{id}/start")
    async def 开始(request):
        job = lookup(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("开始参数必须是对象")
            manager.开始(job, body.get("范围"), 自动恢复=job.预览.get("自动流程", False))
            return web.json_response(job.快照())
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)

    @routes.post("/lvp/plan/jobs/{id}/cancel")
    async def 停止(request):
        job = lookup(request)
        await job.停止()
        return web.json_response(job.快照())

    @routes.get("/lvp/plan/jobs/{id}/events")
    async def 事件(request):
        job = lookup(request)
        if job.订阅 is not None:
            return web.json_response({"error": "此任务已有进度连接"}, status=409)
        queue = asyncio.Queue(maxsize=64)
        job.订阅 = queue
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store",
                                               "X-Accel-Buffering": "no"})
        try:
            await response.prepare(request)
            snapshot = job.快照()
            await response.write(_帧("snapshot", snapshot))
            if snapshot["status"] not in _终态:
                while True:
                    try:
                        name, data = await asyncio.wait_for(queue.get(), timeout=10)
                    except asyncio.TimeoutError:
                        if request.transport is None or request.transport.is_closing():
                            break
                        await response.write(b": heartbeat\n\n")
                        continue
                    await response.write(_帧(name, data))
                    if data["status"] in _终态:
                        break
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            job.订阅 = None
            if job.状态 not in _终态 and job.项目 is None:
                await job.停止()
        return response

    return manager
