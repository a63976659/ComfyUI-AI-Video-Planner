"""持久制作任务：文件缓存、凭证隔离、取消和显式恢复。"""
import asyncio
import copy
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .工程 import 标准化工程
from .工具 import 原子JSON写, 安全媒体路径, 文件摘要
from .合成 import 渲染镜头, 合成成片, 探测信息
from .扩展 import 执行工作流, 导出工程包
from .质检 import 检查成片


def 可分享草稿(draft):
    value = copy.deepcopy(draft)
    def strip(item):
        if isinstance(item, dict):
            item.pop("规划任务引用", None)
            item.pop("规划任务缓存", None)
            planning = item.get("规划资料")
            if isinstance(planning, dict):
                planning.pop("任务引用", None)
            production = item.get("制作")
            if isinstance(production, dict):
                production.pop("最近任务", None)
                production.pop("任务历史", None)
            for child in item.values():
                strip(child)
        elif isinstance(item, list):
            for child in item:
                strip(child)
    strip(value)
    return value


class 制作任务管理:
    def __init__(self, root, media_root, service="http://127.0.0.1:8188"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.media_root = os.fspath(media_root)
        self.service = service
        self.jobs, self.tasks, self.cancel = {}, {}, {}
        self._已开始 = set()
        self.gate = asyncio.Semaphore(1)
        for path in self.root.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job.get("id") != path.parent.name or not self._合法id(job["id"]):
                    continue
                if job["status"] in ("queued", "running"):
                    job.update(status="interrupted", 阶段="服务重启，请恢复任务")
                    原子JSON写(path, job)
                self.jobs[job["id"]] = job
            except (OSError, ValueError, KeyError, TypeError):
                continue

    @staticmethod
    def _合法id(ident):
        return isinstance(ident, str) and len(ident) == 32 and all(c in "0123456789abcdef" for c in ident)

    def _保存(self, job):
        job["updated"] = time.time()
        原子JSON写(self.root / job["id"] / "job.json", job)

    def 获取(self, ident, token):
        job = self.jobs.get(ident) if self._合法id(ident) else None
        if not job or not isinstance(token, str) or not hmac.compare_digest(job["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
            raise PermissionError("制作任务不存在或凭证无效")
        return job

    @staticmethod
    def 摘要(job):
        keys = ("id", "status", "模式", "阶段", "已完成", "总数", "result", "error", "updated", "缓存命中", "warnings")
        return {k: copy.deepcopy(job[k]) for k in keys if k in job}

    def 新建(self, draft, mode="预览", pilot=None, start=True):
        if mode not in ("预览", "成片", "样板", "导出"):
            raise ValueError("制作模式不合法")
        if sum(j["status"] in ("queued", "running") for j in self.jobs.values()) >= 8:
            raise ValueError("制作队列已满，请等待已有任务")
        draft = 可分享草稿(draft)
        project = 标准化工程(draft, 严格=mode == "成片")
        if mode == "样板":
            shot = next((s for s in project["镜头"] if s["id"] == pilot), None)
            if shot is None:
                raise ValueError("请选择要试制的样板镜头")
            if shot["来源"] == "待生成":
                raise ValueError("样板镜头未绑定画面，请选择素材或通用工作流")
            offset = shot["开始"]
            project["镜头"] = [shot]
            project["时长"], project["帧数"] = shot["时长"], shot["帧数"]
            shot["开始"], shot["结束"] = 0, shot["时长"]
            project["音轨"] = [dict(t, 开始=max(0, t["开始"]-offset), 起点=t["起点"]+max(0, offset-t["开始"]),
                                      时长=min(t["开始"]+t["时长"], offset+shot["时长"])-max(t["开始"],offset))
                                  for t in project["音轨"] if t["开始"] < offset+shot["时长"] and t["开始"]+t["时长"] > offset]
            for entries in (project["字幕"]["条目"], project["文字"]):
                entries[:] = [dict(e, 开始=max(0, e["开始"]-offset), 结束=min(shot["时长"], e["结束"]-offset))
                              for e in entries if e["开始"] < offset+shot["时长"] and e["结束"] > offset]
        ident, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        job = {"id": ident, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "status": "queued",
               "模式": mode, "阶段": "等待制作", "已完成": 0, "总数": len(project["镜头"])+2,
               "草稿": draft, "工程": project, "工作流状态": {}, "缓存命中": 0, "warnings": list(project["warnings"])}
        self.jobs[ident] = job
        self._保存(job)
        if start:
            self._启动(job)
        return {**self.摘要(job), "token": token}

    def _启动(self, job):
        event = threading.Event()
        self.cancel[job["id"]] = event
        self.tasks[job["id"]] = asyncio.create_task(self._运行(job, event))

    def 停止(self, ident, token):
        job = self.获取(ident, token)
        if job["status"] in ("queued", "running"):
            event = self.cancel.get(ident)
            if event is not None:
                event.set()
            if job["status"] == "queued":
                job.update(status="cancelled", 阶段="已停止")
                # 已进入协程但仍等待单队列的任务可以立即退出；尚未进入协程的任务由入口取消检查处理。
                task = self.tasks.get(ident)
                if ident in self._已开始 and task is not None and not task.done():
                    task.cancel()
            else:
                job["阶段"] = "正在停止当前步骤"
            self._保存(job)
        return self.摘要(job)

    def 恢复(self, ident, token):
        job = self.获取(ident, token)
        if job["status"] not in ("failed", "cancelled", "interrupted"):
            raise ValueError("只有失败、停止或中断的任务可以恢复")
        if ident in self.tasks and not self.tasks[ident].done():
            raise ValueError("上一次制作尚未停止")
        if sum(j["status"] in ("queued", "running") for j in self.jobs.values()) >= 8:
            raise ValueError("制作队列已满，请等待已有任务")
        if any(s.get("提交中") and not s.get("prompt_id") for s in job["工作流状态"].values()):
            raise ValueError("工作流提交期间连接中断，无法确认是否已入队；请检查 ComfyUI 队列后新建任务，避免重复生成")
        job.update(status="queued", error="", 阶段="等待恢复", 已完成=0, 缓存命中=0)
        self._保存(job)
        self._启动(job)
        return self.摘要(job)

    def 产物(self, ident, name, token):
        job = self.获取(ident, token)
        if not isinstance(name, str) or name not in (job.get("result") or {}).values():
            raise PermissionError("产物尚未发布或文件名无效")
        path = 安全媒体路径(self.root / ident, name)
        if not os.path.isfile(path):
            raise FileNotFoundError("制作产物不存在")
        return path

    def _已存媒体(self, name, digest=None):
        if not name:
            return None
        path = 安全媒体路径(self.media_root, name)
        if not os.path.isfile(path):
            return None
        if digest is not None and 文件摘要(path) != digest:
            return None
        return path

    def _复制工作流媒体(self, source, name, digest, cancel):
        """校验完整副本后才发布，避免中断残片在下一次恢复时被文件存在检查复用。"""
        if cancel.is_set():
            raise InterruptedError("工作流媒体复制已停止")
        target = 安全媒体路径(self.media_root, name)
        if self._已存媒体(name, digest):
            return target
        fd, temporary = tempfile.mkstemp(prefix=name + ".", suffix=".part", dir=self.media_root)
        copied = hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as output, open(source, "rb") as incoming:
                while True:
                    if cancel.is_set():
                        raise InterruptedError("工作流媒体复制已停止")
                    chunk = incoming.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    copied.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            if copied.hexdigest() != digest:
                raise ValueError("工作流产物在复制期间发生变化，请重新获取")
            if cancel.is_set():
                raise InterruptedError("工作流媒体复制已停止")
            target = 安全媒体路径(self.media_root, name)
            os.replace(temporary, target)
            return target
        finally:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass

    async def _运行(self, job, cancel):
        try:
            self._已开始.add(job["id"])
            if cancel.is_set():
                raise InterruptedError("制作已停止")
            async with self.gate:
                if cancel.is_set():
                    raise InterruptedError("制作已停止")
                job["status"] = "running"
                self._保存(job)
                project = copy.deepcopy(job["工程"])
                root = self.root / job["id"]
                if job["模式"] == "导出":
                    job["阶段"] = "打包工程与素材"
                    self._保存(job)
                    await asyncio.to_thread(导出工程包, 可分享草稿(job["草稿"]), self.media_root, root / "project.zip")
                    if cancel.is_set():
                        raise InterruptedError("制作已停止")
                    job.update(status="completed", 阶段="工程包已生成", 已完成=job["总数"], result={"package": "project.zip"})
                    return
                result, report = await self._制作一次(job, project, root, cancel)
                job["result"] = {**result, "report": "quality.json", "render_manifest": "render-manifest.json"}
                if cancel.is_set():
                    raise InterruptedError("制作已停止")
                job.update(status="completed", 阶段="制作完成", 已完成=job["总数"])
        except (InterruptedError, asyncio.CancelledError):
            cancel.set()
            job.update(status="cancelled", 阶段="已停止")
        except Exception as exc:
            job.update(status="failed", 阶段="制作失败", error=str(exc)[:3000])
        finally:
            self._已开始.discard(job["id"])
            self._保存(job)

    async def _制作一次(self, job, project, root, cancel):
        files = []
        rendered = []
        for index, shot in enumerate(project["镜头"]):
            if cancel.is_set():
                raise InterruptedError("制作已停止")
            job.update(阶段=f"镜头 {index+1}/{len(project['镜头'])}", 已完成=index)
            self._保存(job)
            original_source = shot["来源"]
            original_title, original_prompt = shot["标题"], shot["提示词"]
            placeholder = False
            shot["_插帧"] = project["后处理"]["插帧"]
            if shot["来源"] in ("待生成", "工作流") and job["模式"] == "预览":
                state = job["工作流状态"].get(shot["id"], {})
                existing = state.get("文件名")
                if existing and await asyncio.to_thread(self._已存媒体, existing, state.get("摘要") or ""):
                    shot.update(来源="视频", 文件名=existing)
                else:
                    reference = next((name for name in shot.get("参考图", [])
                                      if self._已存媒体(name)), None)
                    if reference:
                        shot.update(来源="图片", 文件名=reference)
                    else:
                        shot.update(来源="标题", 文件名="", 标题="待生成镜头\n" + (original_title[:40] or f"镜头 {index+1}"), _占位=True)
                    placeholder = True
                    warning = f"镜头{shot['id']}尚未生成，预览使用{'参考图' if reference else '标题'}占位；成片或样板模式才提交生成。"
                    project["warnings"].append(warning)
                    job["warnings"] = list(project["warnings"])
                    job["阶段"] += "（未生成占位）"
                    self._保存(job)
            if shot["来源"] == "工作流":
                state = job["工作流状态"].setdefault(shot["id"], {})
                references = list(dict.fromkeys(shot["参考图"] + shot["参考视频"]))
                inputs = {name: await asyncio.to_thread(文件摘要, 安全媒体路径(self.media_root, name)) for name in references}
                if state.get("输入摘要") is not None and state["输入摘要"] != inputs:
                    raise ValueError("恢复任务的参考素材内容已变化，请新建任务，以免混用先前生成结果")
                state["输入摘要"] = inputs
                self._保存(job)
                existing = state.get("文件名")
                if existing and await asyncio.to_thread(self._已存媒体, existing, state.get("摘要") or ""):
                    shot["文件名"] = existing
                else:
                    config = copy.deepcopy(next(w for w in project["工作流"] if w["id"] == shot["工作流id"]))
                    if state.get("prompt_id"):
                        config["_已有prompt_id"] = state["prompt_id"]
                    state["提交中"] = True
                    self._保存(job)
                    def notified(data):
                        if data.get("prompt_id"):
                            state.update(prompt_id=data["prompt_id"], 提交中=False)
                            self._保存(job)
                    result = await 执行工作流(config, shot, root / ("workflow-"+str(index)), notified, cancel, self.service)
                    source = result["视频"][0]
                    digest = await asyncio.to_thread(文件摘要, source)
                    name = "workflow-"+digest[:24]+Path(source).suffix.lower()
                    await asyncio.to_thread(self._复制工作流媒体, source, name, digest, cancel)
                    state.update(文件名=name, 摘要=digest, 提交中=False)
                    self._保存(job)
                    shot["文件名"] = name
                shot["来源"] = "视频"
            path, hit = await asyncio.to_thread(渲染镜头, shot, self.media_root, self.root / "cache", cancel)
            files.append(path)
            rendered.append({"id": shot["id"], "原始来源": original_source, "实际来源": shot["来源"],
                             "原始标题": original_title, "原始提示词": original_prompt,
                             "占位": placeholder, "文件名": shot["文件名"], "缓存命中": bool(hit)})
            job["缓存命中"] += int(hit)
            job["已完成"] = index+1
            self._保存(job)
        job["阶段"] = "合成声音、字幕与画面"
        self._保存(job)
        result = await asyncio.to_thread(合成成片, project, files, self.media_root, root, cancel)
        await asyncio.to_thread(原子JSON写, root / "render-manifest.json",
                                {"模式": job["模式"], "镜头": rendered, "warnings": project["warnings"]})
        job.update(阶段="检查成片", 已完成=len(files)+1)
        self._保存(job)
        report = await asyncio.to_thread(检查成片, root / result["video"], project, cancel)
        await asyncio.to_thread(原子JSON写, root / "quality.json", report)
        return result, report

