# -*- coding: utf-8 -*-
"""制作流程扩展：ComfyUI API 工作流、可选语音服务、本地 ASR 与工程包。"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import math
import os
import re
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from .工具 import 安全媒体路径, 文件摘要, 可取消子进程运行

_视频后缀 = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".mpeg", ".mpg"}
_引用键 = {"首帧", "尾帧", "中间帧", "图片", "音频", "视频"}
_最大工程清单 = 1000
_最大工程单文件 = 16 * 1024**3
_最大工程总量 = 50 * 1024**3
_最大元数据 = 32 * 1024**2
_PROMPT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _路径状态(取消):
    if 取消 is None:
        return False
    if callable(取消):
        return bool(取消())
    状态 = getattr(取消, "is_set", None)
    return bool(状态()) if callable(状态) else bool(取消)


def _安全相对路径(root, relative, *, 必须存在=True):
    """解析允许子目录的根内路径，禁止绝对路径、越界、链接和设备名。"""
    if not isinstance(relative, str) or not relative or "\0" in relative or "\\" in relative:
        raise ValueError("素材路径无效")
    win = PureWindowsPath(relative)
    rel = PurePosixPath(relative)
    if win.drive or win.root or rel.is_absolute() or any(x in ("", ".", "..") for x in rel.parts):
        raise ValueError("素材路径必须是根目录内的相对路径")
    if any(any(ord(c) < 32 or c in '<>:\"|?*' for c in part) for part in rel.parts):
        raise ValueError("素材路径包含非法字符")
    root_abs = os.path.abspath(os.fspath(root))
    root_real = os.path.realpath(root_abs)
    if os.path.normcase(root_abs) != os.path.normcase(root_real):
        raise ValueError("素材根目录包含符号链接")
    path = os.path.join(root_abs, *rel.parts)
    real = os.path.realpath(path)
    try:
        inside = os.path.commonpath([os.path.normcase(root_real), os.path.normcase(real)]) == os.path.normcase(root_real)
    except ValueError:
        inside = False
    if not inside or os.path.normcase(path) != os.path.normcase(real):
        raise ValueError("素材路径越界或包含符号链接")
    if 必须存在 and not os.path.isfile(path):
        raise FileNotFoundError(f"素材文件不存在：{relative}")
    return path


def _工作流检查(配置):
    if not isinstance(配置, dict):
        raise ValueError("配置必须是对象")
    图 = 配置.get("图")
    if not isinstance(图, dict) or not 图:
        raise ValueError("配置.图必须是非空 ComfyUI API prompt 对象")
    for node_id, node in 图.items():
        if not isinstance(node_id, str) or not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise ValueError(f"工作流节点格式无效：{node_id!r}")
    能力 = 配置.get("能力")
    if not isinstance(能力, dict):
        raise ValueError("配置.能力必须包含最短秒和最长秒")
    最短, 最长 = 能力.get("最短秒"), 能力.get("最长秒")
    if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (最短, 最长))
            or 最短 <= 0 or 最长 < 最短):
        raise ValueError("工作流时长能力范围无效")
    帧步长, 帧偏移 = 能力.get("帧步长", 1), 能力.get("帧偏移", 0)
    if (isinstance(帧步长, bool) or not isinstance(帧步长, int) or not 1 <= 帧步长 <= 64
            or isinstance(帧偏移, bool) or not isinstance(帧偏移, int) or not 0 <= 帧偏移 <= 63
            or 帧偏移 >= 帧步长):
        raise ValueError("工作流帧数能力须满足帧步长1..64、帧偏移0..63且偏移小于步长")
    映射 = 配置.get("映射", 配置.get("映射数组"))
    if not isinstance(映射, list):
        raise ValueError("配置.映射必须是数组")
    targets = set()
    for item in 映射:
        if not isinstance(item, dict) or not isinstance(item.get("节点"), str) or not isinstance(item.get("输入"), str):
            raise ValueError("每条映射都必须包含字符串节点和输入")
        node, key, source = item["节点"], item["输入"], item.get("值")
        if node not in 图 or not key or not isinstance(source, str) or source not in {"提示词", "秒数", "帧数", "种子", "宽", "高", "帧率", "参考图", "参考视频"}:
            raise ValueError(f"工作流映射无效：{item!r}")
        if key not in 图[node]["inputs"]:
            raise ValueError(f"映射输入不存在于工作流节点：{node}.{key}")
        target = (node, key)
        if target in targets:
            raise ValueError(f"工作流映射目标重复：{node}.{key}")
        seq = item.get("序号", 0)
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise ValueError("工作流参考映射序号须为非负整数")
        if "多项" in item and not isinstance(item["多项"], bool):
            raise ValueError("工作流映射多项须为布尔值")
        targets.add(target)
    return 图, 能力, 映射


def _检查镜头(镜头, 能力):
    if not isinstance(镜头, dict):
        raise ValueError("镜头必须是对象")
    prompt = 镜头.get("提示词")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("镜头提示词不能为空")
    秒 = 镜头.get("时长")
    fps = 镜头.get("帧率")
    宽, 高, 种子 = 镜头.get("宽"), 镜头.get("高"), 镜头.get("种子")
    if isinstance(秒, bool) or not isinstance(秒, (int, float)) or not 能力["最短秒"] <= 秒 <= 能力["最长秒"]:
        raise ValueError(f"镜头时长须在 {能力['最短秒']} 至 {能力['最长秒']} 秒之间")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0 or fps > 240:
        raise ValueError("镜头帧率无效")
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (宽, 高)):
        raise ValueError("镜头宽高必须是正整数")
    if isinstance(种子, bool) or not isinstance(种子, int) or 种子 < 0:
        raise ValueError("镜头种子必须是非负整数")
    return int(round(秒 * fps))


def _Comfy路径引用(path):
    import folder_paths
    if not isinstance(path, str) or not path:
        raise ValueError("参考图/视频必须是媒体文件名")
    input_root = folder_paths.get_input_directory()
    # 插件媒体池的素材要以 ComfyUI input 相对路径交给 LoadImage/LoadVideo。
    media_root = os.path.join(input_root, "长视频规划师_媒体")
    if os.path.basename(path) == path:
        try:
            if os.path.isfile(安全媒体路径(media_root, path)):
                return os.path.relpath(os.path.join(media_root, path), input_root).replace(os.sep, "/")
        except ValueError:
            pass
    resolved = _安全相对路径(input_root, path)
    return os.path.relpath(resolved, input_root).replace(os.sep, "/")


def _工作流实例(配置, 镜头):
    图, 能力, 映射 = _工作流检查(配置)
    计划帧数 = _检查镜头(镜头, 能力)
    帧步长, 帧偏移 = 能力.get("帧步长", 1), 能力.get("帧偏移", 0)
    帧数 = math.ceil(max(0, 计划帧数 - 帧偏移) / 帧步长) * 帧步长 + 帧偏移
    帧数 = max(计划帧数, 帧数)
    result = copy.deepcopy(图)
    for item in 映射:
        source = item["值"]
        value = {
            "提示词": 镜头["提示词"], "秒数": 镜头["时长"], "帧数": 帧数,
            "种子": 镜头["种子"], "宽": 镜头["宽"], "高": 镜头["高"], "帧率": 镜头["帧率"],
        }.get(source)
        if source in ("参考图", "参考视频"):
            value = 镜头.get(source)
            values = value if isinstance(value, list) else ([value] if value else [])
            if not values:
                raise ValueError(f"此工作流映射了{source}，但镜头未提供素材")
            if item.get("多项", False):
                value = [_Comfy路径引用(x) for x in values]
            else:
                seq = item.get("序号", 0)
                if seq >= len(values):
                    raise ValueError(f"镜头{source}只有{len(values)}项，映射请求序号{seq}")
                value = _Comfy路径引用(values[seq])
        result[item["节点"]]["inputs"][item["输入"]] = value
    return result, 帧数, 计划帧数


def _默认输出根():
    import folder_paths
    return folder_paths.get_output_directory()


def _提取输出文件(history):
    outputs = history.get("outputs") if isinstance(history, dict) else None
    videos, images = [], []
    if not isinstance(outputs, dict):
        return videos, images
    def scan(value):
        if isinstance(value, dict):
            if isinstance(value.get("filename"), str):
                yield value
            else:
                for child in value.values():
                    yield from scan(child)
        elif isinstance(value, list):
            for child in value:
                yield from scan(child)
    seen = set()
    for entry in scan(outputs):
        filename = entry["filename"]
        key = (filename, entry.get("subfolder", ""), entry.get("type", "output"))
        if key in seen:
            continue
        seen.add(key)
        (videos if Path(filename).suffix.lower() in _视频后缀 else images).append(entry)
    return videos, images


def _执行错误(history):
    status = history.get("status") or {}
    messages = status.get("messages") or []
    for event in messages:
        if isinstance(event, (list, tuple)) and event and event[0] == "execution_error":
            data = event[1] if len(event) > 1 and isinstance(event[1], dict) else {}
            return str(data.get("exception_message") or data.get("exception_type") or "ComfyUI 工作流执行失败")
    if status.get("status_str") == "error":
        return "ComfyUI 工作流执行失败"
    return None


def _队列包含(queue_data, prompt_id):
    if not isinstance(queue_data, dict):
        return None
    found = False
    for key in ("queue_running", "queue_pending"):
        values = queue_data.get(key)
        if not isinstance(values, list):
            continue
        found = True
        for entry in values:
            if isinstance(entry, (list, tuple)) and len(entry) > 1 and entry[1] == prompt_id:
                return True
            if isinstance(entry, dict) and entry.get("prompt_id") == prompt_id:
                return True
    return False if found else None


def _分块复制视频(source, output_dir, filename, cancel):
    """以有界块复制独立视频，生成摘要并以临时文件原子发布。"""
    os.makedirs(output_dir, exist_ok=True)
    target = 安全媒体路径(output_dir, filename)
    fd, tmp = tempfile.mkstemp(prefix=".lvp-copy-", suffix=".part", dir=output_dir)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as dst, open(source, "rb") as src:
            while True:
                if _路径状态(cancel):
                    raise InterruptedError("视频复制已取消")
                chunk = src.read(4 * 1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                digest.update(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        hexdigest = digest.hexdigest()
        if os.path.isfile(target) and 文件摘要(target) == hexdigest:
            os.remove(tmp)
            return target
        if os.path.exists(target):
            stem, ext = os.path.splitext(filename)
            filename = f"{stem}.{hexdigest[:8]}{ext}"
            suffix = 2
            target = 安全媒体路径(output_dir, filename)
            while os.path.exists(target):
                if os.path.isfile(target) and 文件摘要(target) == hexdigest:
                    os.remove(tmp)
                    return target
                filename = f"{stem}.{hexdigest[:8]}.{suffix}{ext}"
                suffix += 1
                target = 安全媒体路径(output_dir, filename)
        os.replace(tmp, target)
        return target
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


async def _通知(回调, payload, value=None):
    if 回调 is None:
        return
    if value is not None:
        # 两参数回调可直接持久化状态与 prompt_id；单参数回调继续收到结构化事件。
        try:
            signature = inspect.signature(回调)
            accepts_two = any(p.kind == p.VAR_POSITIONAL for p in signature.parameters.values()) or sum(
                p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                for p in signature.parameters.values()) >= 2
        except (TypeError, ValueError):
            accepts_two = False
        result = 回调(payload, value) if accepts_two else 回调({"状态": payload, "prompt_id": value})
    else:
        result = 回调(payload)
    if asyncio.iscoroutine(result):
        await result


async def 执行工作流(配置, 镜头, 输出目录, 进度=None, 取消=None, 服务地址="http://127.0.0.1:8188"):
    """提交 ComfyUI API prompt，等待该 prompt 完成，只下载/复制它自己的视频结果。"""
    import aiohttp
    prompt, 帧数, 计划帧数 = _工作流实例(配置, 镜头)
    os.makedirs(输出目录, exist_ok=True)
    job_id = f"lvp-{os.getpid()}-{time.time_ns()}"
    base = 服务地址.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=60)
    prompt_id = 配置.get("_已有prompt_id")
    恢复 = prompt_id is not None
    if 恢复 and (not isinstance(prompt_id, str) or not _PROMPT_ID.fullmatch(prompt_id)):
        raise ValueError("配置._已有prompt_id 必须是非空字符串")
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if not 恢复:
            async with session.post(base + "/prompt", json={
                "prompt": prompt,
                "extra_data": {"job_id": job_id, "plugin": "ComfyUI-AI-Video-Planner"},
            }) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"ComfyUI 拒绝工作流：{data}")
                prompt_id = data.get("prompt_id")
                if not isinstance(prompt_id, str) or not _PROMPT_ID.fullmatch(prompt_id):
                    raise RuntimeError(f"ComfyUI 响应缺少 prompt_id：{data}")
                if data.get("node_errors"):
                    raise ValueError(f"工作流节点校验失败：{data['node_errors']}")
            # 先让调用方持久化 ID，再做第一次 history 轮询，崩溃后可用 _已有prompt_id 恢复。
            await _通知(进度, "已提交", prompt_id)
        else:
            job_id = 配置.get("_已有job_id") or job_id
            await _通知(进度, "已恢复", prompt_id)
        等待上限 = 配置.get("超时秒", 7200)
        if isinstance(等待上限, bool) or not isinstance(等待上限, (int, float)) or not math.isfinite(等待上限) or 等待上限 <= 0:
            raise ValueError("配置.超时秒必须是有限正数")
        start = time.monotonic()
        polls = 0
        missing_since = None
        while True:
            if _路径状态(取消):
                # 只从队列删除自己的 ID，不发送 /interrupt，避免干扰其他工作流。
                async with session.post(base + "/queue", json={"delete": [prompt_id]}) as response:
                    await response.read()
                raise asyncio.CancelledError("ComfyUI 工作流已请求取消")
            if time.monotonic() - start > 等待上限:
                async with session.post(base + "/queue", json={"delete": [prompt_id]}) as response:
                    await response.read()
                raise TimeoutError("ComfyUI 工作流等待超时，已从排队列表删除该任务")
            async with session.get(base + "/history/" + prompt_id) as response:
                if response.status >= 400:
                    await asyncio.sleep(0.5)
                    continue
                history_data = await response.json(content_type=None)
            history = history_data.get(prompt_id) if isinstance(history_data, dict) else None
            if isinstance(history, dict):
                missing_since = None
                error = _执行错误(history)
                if error:
                    raise RuntimeError(error)
                status = history.get("status") or {}
                if status.get("completed"):
                    break
            elif 恢复:
                polls += 1
                if polls % 4 == 0:
                    async with session.get(base + "/queue") as response:
                        if response.status < 400:
                            queue_data = await response.json(content_type=None)
                            is_queued = _队列包含(queue_data, prompt_id)
                            if is_queued:
                                missing_since = None
                            elif is_queued is False:
                                missing_since = missing_since or time.monotonic()
                                if time.monotonic() - missing_since >= 5:
                                    raise ValueError("队列/历史已无该任务，请新建试制")
            await asyncio.sleep(0.5)
    videos, images = _提取输出文件(history)
    if not videos:
        raise ValueError("工作流已完成，但 outputs 中没有视频文件；图像结果不会作为视频返回")
    import folder_paths
    roots = {
        "input": folder_paths.get_input_directory(),
        "output": folder_paths.get_output_directory(),
        "temp": folder_paths.get_temp_directory(),
    }
    output_dir = os.path.abspath(os.fspath(输出目录))
    copied = []
    for index, entry in enumerate(videos, 1):
        kind = entry.get("type", "output")
        root = roots.get(kind)
        if not root:
            raise ValueError(f"ComfyUI 返回了不支持的输出类型：{kind}")
        subfolder, filename = entry.get("subfolder", ""), entry["filename"]
        relative = "/".join(x for x in (subfolder.replace("\\", "/"), filename) if x)
        source = _安全相对路径(root, relative)
        if not os.path.isfile(source):
            raise FileNotFoundError(f"ComfyUI 视频输出不存在：{relative}")
        name = os.path.basename(filename)
        stop_copy = threading.Event()
        async def copy_one():
            copy_task = asyncio.create_task(asyncio.to_thread(
                _分块复制视频, source, output_dir, name, lambda: _路径状态(取消) or stop_copy.is_set()))
            try:
                return await copy_task
            except asyncio.CancelledError:
                stop_copy.set()
                try:
                    await asyncio.shield(copy_task)
                except (InterruptedError, asyncio.CancelledError):
                    pass
                raise
        try:
            destination = await copy_one()
        except InterruptedError as exc:
            raise asyncio.CancelledError("ComfyUI 视频复制已取消") from exc
        copied.append(destination)
    result = {"prompt_id": prompt_id, "job_id": job_id, "状态": "completed", "视频": copied,
              "帧数": 帧数, "计划帧数": 计划帧数, "图片输出": images}
    await _通知(进度, "已完成", prompt_id)
    return result


async def 生成配音(text, voice, out, rate="+0%", 取消=None):
    """使用可选 edge-tts 生成语音。未安装依赖时给出安装提示，不在导入模块时联网。"""
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ValueError("配音文本不能为空且不得超过 10000 字符")
    if not isinstance(voice, str) or not voice.strip() or len(voice) > 128:
        raise ValueError("voice 必须是有效的 Edge TTS 声线名称")
    if not isinstance(rate, str) or not re.fullmatch(r"[+-]\d{1,3}%", rate):
        raise ValueError("rate 格式应为 +0% 或 -10%")
    if _路径状态(取消):
        raise asyncio.CancelledError()
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("Edge TTS 未安装；可在 ComfyUI Python 环境安装 edge-tts 后启用") from exc
    target = os.path.abspath(os.fspath(out))
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=Path(target).stem + ".", suffix=Path(target).suffix or ".mp3", dir=os.path.dirname(target) or ".")
    os.close(fd)
    try:
        task = asyncio.create_task(edge_tts.Communicate(text, voice, rate=rate).save(tmp))
        while not task.done():
            if _路径状态(取消):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise asyncio.CancelledError("配音任务已取消")
            await asyncio.sleep(0.1)
        await task
        if not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
            raise RuntimeError("Edge TTS 未生成有效音频")
        os.replace(tmp, target)
        return target
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def 转写音频(path, 模型目录):
    """用本地 faster-whisper 模型转写；local_files_only=True，绝不自动下载模型。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("本地 ASR 需要 faster-whisper；请先安装依赖并准备本地模型目录") from exc
    model_dir = os.path.abspath(os.fspath(模型目录))
    if not os.path.isdir(model_dir):
        raise FileNotFoundError(f"本地 ASR 模型目录不存在：{model_dir}")
    model = WhisperModel(model_dir, device="cpu", compute_type="int8", local_files_only=True)
    segments, _info = model.transcribe(os.fspath(path), vad_filter=True)
    result, group = [], None
    for segment in segments:
        text = str(segment.text or "").strip()
        if not text:
            continue
        if group is None:
            group = {"start": float(segment.start), "end": float(segment.end), "text": text}
        else:
            group["end"] = float(segment.end)
            group["text"] += text
        if re.search(r"[。！？!?…]$", group["text"].rstrip()):
            result.append(group)
            group = None
    if group is not None:
        result.append(group)
    return result


def _媒体引用字段(container, on_ref, keys):
    if not isinstance(container, dict):
        return
    for key in keys:
        child = container.get(key)
        if isinstance(child, str) and child:
            on_ref(container, key, child)
        elif isinstance(child, list):
            for index, name in enumerate(child):
                if isinstance(name, str) and name:
                    on_ref(child, index, name)
    voice = container.get("台词配音")
    if isinstance(voice, dict) and isinstance(voice.get("文件名"), str) and voice["文件名"]:
        on_ref(voice, "文件名", voice["文件名"])


def _制作引用(制作, on_ref):
    if not isinstance(制作, dict):
        return
    for clip in 制作.get("片段", []) if isinstance(制作.get("片段", []), list) else []:
        if not isinstance(clip, dict):
            continue
        if isinstance(clip.get("文件名"), str) and clip["文件名"]:
            on_ref(clip, "文件名", clip["文件名"])
        voice = clip.get("配音")
        if isinstance(voice, dict) and isinstance(voice.get("文件名"), str) and voice["文件名"]:
            on_ref(voice, "文件名", voice["文件名"])
    镜头组 = 制作.get("镜头", {})
    镜头项 = 镜头组.values() if isinstance(镜头组, dict) else 镜头组 if isinstance(镜头组, list) else []
    for shot in 镜头项:
        if not isinstance(shot, dict):
            continue
        # 镜头主素材只从制作.镜头记录识别，绝不递归扫描工作流图输入或提示词正文。
        if shot.get("来源") in ("图片", "视频") and isinstance(shot.get("文件名"), str) and shot["文件名"]:
            on_ref(shot, "文件名", shot["文件名"])
        _媒体引用字段(shot, on_ref, ("参考图", "参考视频"))
    for track in 制作.get("音轨", []) if isinstance(制作.get("音轨", []), list) else []:
        if isinstance(track, dict) and isinstance(track.get("文件名"), str) and track["文件名"]:
            on_ref(track, "文件名", track["文件名"])
    for entity in 制作.get("实体", []) if isinstance(制作.get("实体", []), list) else []:
        if isinstance(entity, dict) and isinstance(entity.get("参考图"), str) and entity["参考图"]:
            on_ref(entity, "参考图", entity["参考图"])


def _规划素材引用(container, on_ref):
    """扫描规范化规划字段中的媒体名，不触碰描述、提示词或任意 graph inputs。"""
    if not isinstance(container, dict):
        return
    materials = container.get("素材")
    if isinstance(materials, list):
        for material in materials:
            if isinstance(material, dict) and isinstance(material.get("名"), str) and material["名"]:
                on_ref(material, "名", material["名"])
    for key in ("全局素材", "使用素材"):
        names = container.get(key)
        if isinstance(names, list):
            for index, name in enumerate(names):
                if isinstance(name, str) and name:
                    on_ref(names, index, name)
    understanding = container.get("素材理解")
    if isinstance(understanding, dict):
        # 素材理解以媒体文件名为 key。None parent 是精确的 key 引用回调；
        # 收集器可忽略返回值，导入器则返回已改名的媒体名。
        rewritten = {}
        for name, value in understanding.items():
            new_name = on_ref(None, None, name) if isinstance(name, str) else None
            key = new_name if isinstance(new_name, str) else name
            if key in rewritten:
                raise ValueError("导入后的素材理解文件名重复")
            rewritten[key] = value
        if rewritten != understanding:
            container["素材理解"] = rewritten


def _引用遍历(value, on_ref):
    """仅识别约定的真实引用位置；忽略工作流图内任意 filename 与描述文字。"""
    if isinstance(value, dict):
        _规划素材引用(value, on_ref)
        for key, child in value.items():
            if key == "refs":
                _媒体引用字段(child, on_ref, _引用键)
            elif key == "参考素材":
                _媒体引用字段(child, on_ref, ("图片", "音频", "视频"))
            elif key == "制作":
                _制作引用(child, on_ref)
            else:
                _引用遍历(child, on_ref)
    elif isinstance(value, list):
        for child in value:
            _引用遍历(child, on_ref)


def _收集引用(草稿):
    names = []
    def collect(_parent, _key, name):
        if name not in names:
            names.append(name)
    _引用遍历(草稿, collect)
    return names


def 导出工程包(草稿, 媒体根, 目标):
    """导出 project.json、带摘要的 manifest.json 和草稿实际引用的媒体资产。"""
    if not isinstance(草稿, (dict, list)):
        raise ValueError("草稿必须是 JSON 对象或数组")
    try:
        project = json.dumps({"格式版本": 1, "草稿": 草稿}, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"草稿不能编码为 JSON：{exc}") from exc
    names = _收集引用(草稿)
    if len(names) > _最大工程清单:
        raise ValueError("工程引用素材数量超过上限")
    records = []
    sources = []
    for name in names:
        source = 安全媒体路径(媒体根, name)
        if not os.path.isfile(source):
            raise FileNotFoundError(f"工程引用的素材不存在：{name}")
        size = os.path.getsize(source)
        if size > _最大工程单文件:
            raise ValueError(f"素材文件超过工程包单文件上限：{name}")
        digest = 文件摘要(source)
        records.append({"name": name, "path": f"assets/{name}", "size": size, "sha256": digest})
        sources.append(source)
    manifest = json.dumps({"格式版本": 1, "素材": records}, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    target = Path(目标).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
            archive.writestr("project.json", project)
            archive.writestr("manifest.json", manifest)
            for source, record in zip(sources, records):
                archive.write(source, record["path"])
                if os.path.getsize(source) != record["size"] or 文件摘要(source) != record["sha256"]:
                    raise ValueError(f"打包期间素材发生变化：{record['name']}")
        os.replace(tmp, target)
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
    return {"路径": str(target), "素材数": len(records), "摘要": hashlib.sha256(manifest).hexdigest()}


def _zip成员名(name):
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("ZIP 成员路径无效")
    path = PurePosixPath(name)
    if path.is_absolute() or PureWindowsPath(name).drive or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"ZIP 成员路径越界：{name}")
    return path.as_posix()


def _可用导入名(root, original, digest):
    try:
        original = os.path.basename(安全媒体路径(root, original))
    except ValueError:
        raise
    candidate = original
    suffix = 1
    while True:
        path = 安全媒体路径(root, candidate)
        if not os.path.exists(path):
            return candidate, False
        if os.path.isfile(path) and 文件摘要(path) == digest:
            return candidate, True
        stem, ext = os.path.splitext(original)
        candidate = f"{stem}.{digest[:8]}" + (f".{suffix}" if suffix > 1 else "") + ext
        suffix += 1


def 导入工程包(zip_path, 媒体根, 校验草稿=None):
    """校验 ZIP、摘要和路径后导入媒体；同名异内容安全改名并重写草稿引用。"""
    os.makedirs(媒体根, exist_ok=True)
    root = os.path.abspath(os.fspath(媒体根))
    安全媒体路径(root, "__lvp_root_check__")
    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > _最大工程清单 + 2:
            raise ValueError("工程包文件数量超过上限")
        total = 0
        members = {}
        for info in infos:
            name = _zip成员名(info.filename)
            if info.is_dir():
                raise ValueError("工程包不允许目录条目")
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and (mode & 0o170000) == 0o120000:
                raise ValueError("工程包不允许符号链接")
            if info.file_size > _最大工程单文件:
                raise ValueError("工程包单文件超过上限")
            total += info.file_size
            if total > _最大工程总量:
                raise ValueError("工程包解压总量超过上限")
            if info.file_size > 100 * 1024**2 and info.compress_size and info.file_size / info.compress_size > 1000:
                raise ValueError("工程包压缩比过高，疑似 ZIP bomb")
            if name in members:
                raise ValueError("工程包包含重复路径")
            members[name] = info
        if "project.json" not in members or "manifest.json" not in members:
            raise ValueError("工程包缺少 project.json 或 manifest.json")
        if members["project.json"].file_size > _最大元数据 or members["manifest.json"].file_size > _最大元数据:
            raise ValueError("工程包元数据超过上限")
        project = json.loads(archive.read("project.json").decode("utf-8"))
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if not isinstance(project, dict) or project.get("格式版本") != 1 or not isinstance(project.get("草稿"), (dict, list)):
            raise ValueError("project.json 格式不支持")
        records = manifest.get("素材") if isinstance(manifest, dict) else None
        if manifest.get("格式版本") != 1 or not isinstance(records, list) or len(records) > _最大工程清单:
            raise ValueError("manifest.json 格式无效")
        actual = set(members)
        expected = {"project.json", "manifest.json"}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("manifest 素材记录无效")
            name, member = record.get("name"), _zip成员名(record.get("path"))
            if not isinstance(name, str) or os.path.basename(name) != name or member != f"assets/{name}":
                raise ValueError("manifest 素材路径不匹配")
            if member not in members or member in expected:
                raise ValueError(f"工程素材缺失或重复：{member}")
            expected.add(member)
            info = members[member]
            if info.file_size != record.get("size"):
                raise ValueError(f"工程素材大小不匹配：{name}")
        if actual != expected:
            raise ValueError("工程包含 manifest 未登记的文件")
        草稿 = project["草稿"]
        预期引用 = set(_收集引用(草稿))
        if 预期引用 != {item["name"] for item in records}:
            raise ValueError("manifest 素材清单与草稿引用不一致")
        imported = {}
        staged = []
        reserved = set()
        actual_total = 0
        # staging 目录确保校验中途失败时不会留下半成品；验证全部通过后才发布媒体文件。
        with tempfile.TemporaryDirectory(prefix=".lvp-import-stage-", dir=root) as stage_dir:
            for record in records:
                name, member = record["name"], record["path"]
                fd, tmp = tempfile.mkstemp(prefix="asset-", suffix=".part", dir=stage_dir)
                digest = hashlib.sha256()
                written = 0
                try:
                    with os.fdopen(fd, "wb") as output, archive.open(member, "r") as source:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > _最大工程单文件:
                                raise ValueError("工程素材解压后超过上限")
                            actual_total += len(chunk)
                            if actual_total > _最大工程总量:
                                raise ValueError("工程包实际解压总量超过上限")
                            output.write(chunk)
                            digest.update(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if written != record["size"] or digest.hexdigest() != record["sha256"]:
                        raise ValueError(f"工程素材摘要校验失败：{name}")
                    new_name, dedup = _可用导入名(root, name, record["sha256"])
                    if new_name in reserved:
                        stem, ext = os.path.splitext(name)
                        base = f"{stem}.{record['sha256'][:8]}"
                        new_name = base + ext
                        suffix = 2
                        while new_name in reserved or os.path.exists(安全媒体路径(root, new_name)):
                            new_name = f"{base}.{suffix}{ext}"
                            suffix += 1
                        dedup = False
                    reserved.add(new_name)
                    if dedup:
                        os.remove(tmp)
                    else:
                        staged.append((tmp, new_name, record["sha256"]))
                    imported[name] = new_name
                except BaseException:
                    try:
                        os.remove(tmp)
                    except FileNotFoundError:
                        pass
                    raise
            result = copy.deepcopy(草稿)
            def rewrite(parent, key, old):
                if old not in imported:
                    raise ValueError(f"草稿引用了 manifest 未包含的素材：{old}")
                if parent is None:
                    return imported[old]
                parent[key] = imported[old]
                return imported[old]
            _引用遍历(result, rewrite)
            if 校验草稿 is not None:
                校验草稿(result)  # 可在任何素材发布前用制作标准化器验证完整结构。
            # 先完整校验全部素材与草稿，再开始发布，避免失败留下已导入的部分资产。
            for tmp, name, digest_value in staged:
                target = 安全媒体路径(root, name)
                if os.path.exists(target):
                    if 文件摘要(target) == digest_value:
                        continue
                    raise FileExistsError(f"导入期间目标素材发生冲突：{name}")
                os.replace(tmp, target)
    return result

