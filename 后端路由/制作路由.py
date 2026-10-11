"""模型无关视频制作 HTTP 入口。长时合成走持久任务，媒体只接受库内文件名。"""
import asyncio
import importlib.util
import json
import math
import os
import re
import tempfile
import subprocess
import zipfile
import uuid
from pathlib import Path
from functools import wraps

from aiohttp import web
from .媒体路由 import 媒体根
try:
    from ..制作.工程 import 标准化工程
    from ..制作.预检 import 校验制作输入
    from ..制作.工具 import 安全媒体路径, 定位ffmpeg, 定位ffprobe, 可取消子进程运行
    from ..制作.合成 import 探测信息
    from ..制作.任务 import 制作任务管理, 可分享草稿
    from ..制作.扩展 import 生成配音, 转写音频, 导出工程包, 导入工程包
except ImportError:
    from 制作.工程 import 标准化工程
    from 制作.预检 import 校验制作输入
    from 制作.工具 import 安全媒体路径, 定位ffmpeg, 定位ffprobe, 可取消子进程运行
    from 制作.合成 import 探测信息
    from 制作.任务 import 制作任务管理, 可分享草稿
    from 制作.扩展 import 生成配音, 转写音频, 导出工程包, 导入工程包

_已注册 = False
_管理 = None
_辅助锁 = None


def 管理器():
    global _管理
    if _管理 is None:
        from server import PromptServer
        port = getattr(PromptServer.instance, "port", 8188) or 8188
        if not isinstance(port, int) or not 1 <= port <= 65535:
            port = 8188
        root = Path(__file__).resolve().parent.parent / "制作产物"
        _管理 = 制作任务管理(root, 媒体根(), f"http://127.0.0.1:{port}")
    return _管理


async def _正文(request):
    data = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        data.extend(chunk)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("制作工程请求超过8MB，请精简工程")
    body = json.loads(data)
    if not isinstance(body, dict):
        raise ValueError("请求体须为对象")
    return body


def _边界(handler):
    @wraps(handler)
    async def run(request):
        try:
            return await handler(request)
        except PermissionError as exc:
            return web.json_response({"error": str(exc)}, status=403)
        except FileNotFoundError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except (ValueError, KeyError, TypeError, AssertionError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except zipfile.BadZipFile as exc:
            return web.json_response({"error": "工程 ZIP 文件损坏或格式不正确：" + str(exc)}, status=400)
        except subprocess.TimeoutExpired:
            return web.json_response({"error": "媒体处理超过时间上限，请稍后重试或缩短素材"}, status=503)
        except (OSError, RuntimeError, TimeoutError) as exc:
            return web.json_response({"error": str(exc)}, status=503)
    return run


def _模型列表():
    import folder_paths
    result = {}
    for folder in ("whisper", "faster-whisper"):
        root = Path(folder_paths.models_dir) / folder
        if root.is_dir():
            for path in sorted(root.iterdir()):
                if path.is_dir() and not path.is_symlink() and (path / "model.bin").is_file():
                    result[folder+"/"+path.name] = str(path)
    return result


def _媒体列表():
    root = 媒体根()
    result = []
    for name in sorted(os.listdir(root)):
        if name.endswith(".part"):
            continue
        try:
            path = 安全媒体路径(root, name)
        except ValueError:
            continue
        if not os.path.isfile(path):
            continue
        ext = Path(name).suffix.lower()
        typ = "图像" if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp") else "视频" if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi") else "音频" if ext in (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac") else "文本"
        result.append({"name": name, "type": typ, "size": os.path.getsize(path)})
    return result


def _探测场景(path):
    args = [定位ffmpeg(), "-hide_banner", "-nostdin", "-i", path, "-t", "600", "-an",
            "-vf", "scale=320:-2,select='gt(scene,0.35)',showinfo", "-f", "null", "-"]
    result = 可取消子进程运行(args, timeout=180)
    if result.returncode:
        raise ValueError("镜头切点分析失败")
    return sorted(set(float(x) for x in re.findall(r"pts_time:([0-9.]+)", result.stderr.decode("utf-8", "replace"))))[:1000]


def 注册路由():
    global _已注册, _辅助锁
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes
    _辅助锁 = asyncio.Semaphore(1)

    @routes.get("/lvp/production/meta")
    @_边界
    async def meta(request):
        try:
            定位ffmpeg()
            定位ffprobe()
            ffmpeg = True
        except RuntimeError:
            ffmpeg = False
        models = _模型列表()
        return web.json_response({"capabilities": {"ffmpeg": ffmpeg, "workflow": True,
            "tts": importlib.util.find_spec("edge_tts") is not None,
            "asr": bool(models) and importlib.util.find_spec("faster_whisper") is not None},
            "media": await asyncio.to_thread(_媒体列表),
            "asr_models": [{"id": k, "name": k} for k in models],
            "jobs": [管理器().摘要(j) for j in sorted(管理器().jobs.values(), key=lambda j: j.get("updated", 0), reverse=True)[:40]]})

    @routes.post("/lvp/production/validate")
    @_边界
    async def validate(request):
        body = await _正文(request)
        project = 标准化工程(body.get("草稿"))
        checked = await asyncio.to_thread(校验制作输入, project, 媒体根())
        return web.json_response({"工程": project, "warnings": project["warnings"], "时长": project["时长"], **checked})

    @routes.post("/lvp/production/receive")
    @_边界
    async def receive(request):
        body = await _正文(request)
        ident, source = body.get("prompt_id"), body.get("来源节点")
        if not isinstance(ident, str) or not ident or len(ident) > 128 or not isinstance(source, (str, int)) or isinstance(source, bool):
            raise ValueError("接收结果需要本轮工作流ID和来源节点")
        from server import PromptServer
        queue = PromptServer.instance.prompt_queue
        # 普通工作流接收不启动交接协调器；只读已经存在的交接归属。
        coordinator = getattr(PromptServer.instance, "_lvp_handoff_coordinator", None)
        reader = getattr(coordinator, "取制作交接上下文", None)
        context = reader(ident, source) if reader else None
        if context:
            ident = context["b_prompt_id"]
            history = queue.get_history(prompt_id=ident)
            if ident not in history:
                if context["state"] in ("FAILED", "CANCELLED", "PAUSED"):
                    raise ValueError("交接精修未完成，尚无最终视频可接收")
                return web.json_response({"结果": [], "待完成": True, "prompt_id": ident})
        else:
            history = queue.get_history(prompt_id=ident)
        record = history.get(ident) if isinstance(history, dict) else None
        for _ in range(8):
            if record is not None:
                break
            # 宿主可能先发 execution_success，随后才把同轮结果写入 history。
            await asyncio.sleep(0.1)
            history = queue.get_history(prompt_id=ident)
            record = history.get(ident) if isinstance(history, dict) else None
        if record is None:
            raise FileNotFoundError("本轮工作流结果尚未写入历史，请稍后重试")
        if context:
            record = dict(record, prompt=[0, ident, context["graph"]],
                          outputs={context["dynamic_ids"].get(str(k), str(k)): v for k, v in record.get("outputs", {}).items()})
        if "." in __package__:
            from ..制作.结果接收 import 接收工作流结果
        else:
            from 制作.结果接收 import 接收工作流结果
        async with _辅助锁:
            result = await asyncio.to_thread(接收工作流结果, record, ident, str(source), 媒体根())
        return web.json_response(result)

    @routes.post("/lvp/production/jobs")
    @_边界
    async def create(request):
        body = await _正文(request)
        return web.json_response(管理器().新建(body.get("草稿"), body.get("模式", "预览"), body.get("样板段")), status=202)

    @routes.get("/lvp/production/jobs/{id}")
    @_边界
    async def status(request):
        return web.json_response(管理器().摘要(管理器().获取(request.match_info["id"], request.headers.get("X-LVP-Production-Token"))))

    @routes.post("/lvp/production/jobs/{id}/cancel")
    @_边界
    async def cancel(request):
        return web.json_response(管理器().停止(request.match_info["id"], request.headers.get("X-LVP-Production-Token")))

    @routes.post("/lvp/production/jobs/{id}/resume")
    @_边界
    async def resume(request):
        return web.json_response(管理器().恢复(request.match_info["id"], request.headers.get("X-LVP-Production-Token")))

    @routes.get("/lvp/production/file")
    @_边界
    async def file(request):
        path = 管理器().产物(request.query.get("job"), request.query.get("name"), request.query.get("token"))
        return web.FileResponse(path, headers={"Referrer-Policy": "no-referrer", "Cache-Control": "private, no-store"})

    @routes.post("/lvp/production/export")
    @_边界
    async def export(request):
        body = await _正文(request)
        manager = 管理器()
        response = manager.新建(body.get("草稿"), "导出", start=False)
        job = manager.jobs[response["id"]]
        try:
            async with _辅助锁:
                await asyncio.to_thread(导出工程包, 可分享草稿(job["草稿"]), 媒体根(), manager.root / job["id"] / "project.zip")
            if job["status"] != "cancelled":
                job.update(status="completed", 阶段="工程包已生成", result={"package": "project.zip"})
        except Exception as exc:
            if job["status"] != "cancelled":
                job.update(status="failed", error=str(exc))
            raise
        finally:
            manager._保存(job)
        return web.json_response({**manager.摘要(job), "token": response["token"]})

    @routes.post("/lvp/production/import")
    @_边界
    async def import_project(request):
        if not request.content_type.startswith("multipart/"):
            raise ValueError("工程导入需要 multipart ZIP 文件")
        reader = await request.multipart()
        field = await reader.next()
        if field is None or not field.filename:
            raise ValueError("工程导入缺少 ZIP 文件")
        with tempfile.TemporaryDirectory(prefix="lvp-import-") as tmp:
            path, size = Path(tmp) / "project.zip", 0
            with path.open("wb") as stream:
                while chunk := await field.read_chunk():
                    size += len(chunk)
                    if size > 2 * 1024**3:
                        raise ValueError("工程包不得超过2GB")
                    stream.write(chunk)
            async with _辅助锁:
                draft = await asyncio.to_thread(导入工程包, path, 媒体根(), 校验草稿=标准化工程)
            标准化工程(draft)
            return web.json_response({"草稿": draft, "素材": await asyncio.to_thread(_媒体列表)})

    @routes.post("/lvp/production/tts")
    @_边界
    async def tts(request):
        body = await _正文(request)
        name = "voice-"+uuid.uuid4().hex+".mp3"
        async with _辅助锁:
            path = 安全媒体路径(媒体根(), name)
            await 生成配音(body.get("文本"), body.get("声音", "zh-CN-XiaoxiaoNeural"), path, body.get("语速", "+0%"))
            info = await asyncio.to_thread(探测信息, path)
            duration = info.get("duration")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                raise ValueError("生成配音未能探测到有效时长，请检查音频文件")
        return web.json_response({"name": name, "duration": duration})

    @routes.post("/lvp/production/asr")
    @_边界
    async def asr(request):
        body = await _正文(request)
        models = _模型列表()
        if body.get("模型") not in models:
            raise ValueError("请选择已安装的本地 faster-whisper 模型")
        path = 安全媒体路径(媒体根(), body.get("文件名"))
        if not os.path.isfile(path):
            raise FileNotFoundError("待转写的媒体文件不存在")
        async with _辅助锁:
            entries = await asyncio.to_thread(转写音频, path, models[body["模型"]])
        if not isinstance(entries, list) or len(entries) > 10000:
            raise ValueError("转写结果须为不超过10000条的字幕数组")
        captions = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("转写字幕条目格式无效")
            start, end, text = entry.get("start"), entry.get("end"), entry.get("text")
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end))
                    or start < 0 or end <= start):
                raise ValueError("转写字幕时间须为非负且结束大于开始的有限秒数")
            if not isinstance(text, str) or len(text) > 4000 or "\x00" in text:
                raise ValueError("转写字幕文本须为不超过4000字的字符串")
            if text.strip():
                captions.append({"开始": start, "结束": end, "文本": text.strip()})
        return web.json_response({"条目": captions})

    @routes.post("/lvp/production/analyze")
    @_边界
    async def analyze(request):
        body = await _正文(request)
        path = 安全媒体路径(媒体根(), body.get("文件名"))
        if not os.path.isfile(path):
            raise FileNotFoundError("待分析的媒体文件不存在")
        async with _辅助锁:
            info = await asyncio.to_thread(探测信息, path)
            fps, duration = info.get("fps"), info.get("duration")
            has_video_time = (not isinstance(fps, bool) and isinstance(fps, (int, float)) and math.isfinite(fps) and fps > 0
                              and not isinstance(duration, bool) and isinstance(duration, (int, float))
                              and math.isfinite(duration) and duration > 0)
            for key in ("fps", "duration"):
                value = info.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    info[key] = None
            if body.get("切点", True) and has_video_time:
                info["scenes"] = await asyncio.to_thread(_探测场景, path)
                info["分析时长上限"] = 600
            if body.get("语义") is True:
                try:
                    from ..制作.素材分析 import 理解素材
                except ImportError:
                    from 制作.素材分析 import 理解素材
                from .规划路由 import _解析模型覆盖
                info["理解"] = await 理解素材(path, _解析模型覆盖(body))
        return web.json_response(info)

    _已注册 = True
