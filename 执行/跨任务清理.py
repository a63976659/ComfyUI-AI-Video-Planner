"""本机单 worker 的 A/C/B 交接协议。history 观察不是清理屏障。

只在 B 的真实执行上下文确认 C→worker flags/unload/reset→get(B) 顺序。
不操作执行器私有缓存，不恢复旧进程任务，不删除交接文件。
"""
import asyncio
from contextlib import contextmanager
import copy
import hashlib
import hmac
import json
import logging
import math
import secrets
import sys
import threading
import time
import uuid


_终态 = frozenset({"FAILED", "CANCELLED", "PAUSED", "SUCCEEDED"})
# 协调器唯一可产出的状态全集；前端 交接提交.js 的 状态码 白名单是它的镜像
# （镜像锁 test_交接状态码白名单与协调器状态全集同步）。二采阶段不新增状态：
# B 图作为普通宿主提示词执行，精修/放大/输出的进度走 长视频规划师_后处理进度 独立通道。
_状态全集 = _终态 | frozenset({
    "VALIDATING",
    "A_QUEUED", "A_RUNNING", "A_WRITING", "ARTIFACT_READY", "A_SUCCEEDED",
    "C_QUEUED", "C_CHECKING", "C_REQUESTED",
    "B_QUEUED", "B_CHECKING", "B_GATE_PASSED",
})
_保留ID = frozenset({"_lvp_cleanup", "_lvp_gate"})
_最大JSON字节 = 8 * 1024 * 1024
# 与 交接分图._MAX_JSON_* 同值（镜像锁 test_JSON结构上限与分图模块同值）：同一份图在两处必须同判。
_最大JSON深度 = 64
_最大JSON项 = 262144
_单例锁 = threading.RLock()


class 交接错误(ValueError):
    """路由可用 status_code/code 转换错误；不携带底层异常或敏感输入。"""
    def __init__(self, code, message, status_code=409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _拒绝(code, message, status_code=409):
    raise 交接错误(code, message, status_code) from None


_最大原因字符 = 300


def _单行原因(value):
    # 分图合同的中文原因要进状态与响应：压成单行并限长，免得大段图内容顺着错误跑出去。
    text = " ".join(str(value).split()) or "未给出原因"
    return text[:_最大原因字符] + "…" if len(text) > _最大原因字符 else text


def _是取消异常(exc):
    # 与后处理缓存一致：只查已加载宿主，兼容 Exception/BaseException 及子类。
    interrupt = getattr(sys.modules.get("comfy.model_management"), "InterruptProcessingException", ())
    return isinstance(exc, asyncio.CancelledError) or isinstance(exc, interrupt)


def _需原样传播(exc):
    # 不为识别异常导入 torch/宿主；不按错误文本猜测，不吞进程级 BaseException。
    oom = getattr(sys.modules.get("torch"), "OutOfMemoryError", ())
    return (not isinstance(exc, Exception) or isinstance(exc, MemoryError)
            or isinstance(exc, oom) or _是取消异常(exc))


def _JSON副本(value, limit=_最大JSON字节):
    # 先限制深度、节点数和字符串总量，避免 dumps 前就遍历任意大对象。
    count, chars = 0, 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > _最大JSON深度 or count > _最大JSON项 or len(stack) > _最大JSON项:
            _拒绝("JSON_LIMIT", "交接 JSON 深度或节点数超限", 400)
        kind = type(item)
        if kind is dict:
            if len(item) > _最大JSON项:
                _拒绝("JSON_LIMIT", "交接 JSON 节点数超限", 400)
            for key, child in item.items():
                if type(key) is not str:
                    _拒绝("JSON_TYPE", "交接 JSON 键须为字符串", 400)
                chars += len(key)
                stack.append((child, depth + 1))
        elif kind is list:
            if len(item) > _最大JSON项:
                _拒绝("JSON_LIMIT", "交接 JSON 节点数超限", 400)
            stack.extend((child, depth + 1) for child in item)
        elif kind is str:
            chars += len(item)
        elif kind not in (int, float, bool, type(None)):
            _拒绝("JSON_TYPE", "交接只接受纯 JSON，不接受运行对象", 400)
        if chars > limit:
            _拒绝("JSON_LIMIT", "交接 JSON 大小超限", 400)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > limit:
            _拒绝("JSON_LIMIT", "交接 JSON 大小超限", 400)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError):
        _拒绝("JSON_TYPE", "交接 JSON 格式或大小无效", 400)


def _文本(value, name):
    if type(value) is not str or not value.strip() or len(value) > 256:
        _拒绝("INVALID_INPUT", name + "须为非空短字符串", 400)
    return value


def _选项(options):
    result = _JSON副本({} if options is None else options)
    if type(result) is not dict or set(result) - {"preview_method"}:
        _拒绝("UNSUPPORTED_OPTIONS", "首版不支持优先级、front、partial、批量或 extra_data", 400)
    if "preview_method" in result and result["preview_method"] not in ("default", "none", "auto", "latent2rgb", "taesd"):
        _拒绝("PREVIEW_METHOD", "未知 preview_method", 400)
    return result


# 所有宿主/业务依赖均懒加载；CPU 测试替换这些窄适配，不接触真实实例。
def _节点类():
    import nodes
    return nodes.NODE_CLASS_MAPPINGS


def _分析图(graph, node_classes):
    from .交接分图 import 分析交接图
    return 分析交接图(graph, node_classes)


def _构建图(analysis, **kwargs):
    from .交接分图 import 构建阶段图
    return 构建阶段图(analysis, **kwargs)


def _图摘要(graph):
    from .交接分图 import 图摘要
    return 图摘要(graph)


def _展开图(graph):
    from .交接分图 import 展开二采图
    return 展开二采图(graph)


async def _验证图(prompt_id, graph, targets):
    from execution import validate_prompt
    return await validate_prompt(prompt_id, graph, targets)


def _执行上下文():
    from comfy_execution.utils import get_executing_context
    return get_executing_context()


def _保存交接(package, *, 检查取消):
    from .初采产物存储 import 保存初采交接
    return 保存初采交接(package, 检查取消=检查取消)


def _读清单(ref):
    from .初采产物存储 import 读交接清单
    return 读交接清单(ref)


def _清插件模型缓存():
    from .模型缓存 import 清缓存
    清缓存()


def _空载回收():
    import gc
    from comfy.model_management import soft_empty_cache
    gc.collect()
    soft_empty_cache()


def _内存硬限制():
    from .执行核心 import _内存硬限额字节
    return _内存硬限额字节()


def _资源观测():
    result = {"ram_available_bytes": None, "rss_bytes": None, "vram_free_bytes": None}
    try:
        import psutil
        result.update(ram_available_bytes=int(psutil.virtual_memory().available),
                      rss_bytes=int(psutil.Process().memory_info().rss))
    except (ImportError, OSError):
        pass
    try:
        import torch
        if torch.cuda.is_initialized():
            result["vram_free_bytes"] = int(torch.cuda.mem_get_info()[0])
    except (ImportError, RuntimeError, OSError) as exc:
        if _需原样传播(exc):
            raise
    return result


def _元数据预算(manifest, graph, refiner_id):
    """仅已知数据下限；不读 Tensor，不把观测值或估算说成真实峰值。"""
    from .视频放大 import 计算目标尺寸

    segments = [record["data"] for record in manifest["segments"]]
    params = graph[refiner_id]["inputs"]
    first = segments[0]
    width, height = 计算目标尺寸(first["width"], first["height"], params.get("放大倍率", 2.0))
    mode = params.get("放大方式", "Lanczos")
    if mode not in ("Lanczos", "像素模型", "H3潜空间"):
        _拒绝("MEMORY_METADATA", "门控要求明确的放大方式", 400)
    strength = params.get("精修强度", 0.2)
    if type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 1:
        _拒绝("MEMORY_METADATA", "门控要求明确的精修强度", 400)

    def tensor_bytes(value):
        if type(value) is dict:
            if set(value) == {"shape", "dtype", "bytes"}:
                size = value["bytes"]
                if type(size) is not int or size < 0:
                    _拒绝("MEMORY_METADATA", "Tensor 字节记录无效", 400)
                return size
            return sum(tensor_bytes(v) for v in value.values())
        if type(value) is list:
            return sum(tensor_bytes(v) for v in value)
        return 0

    frame_count = manifest["package"]["frame_count"]
    if type(frame_count) is not int or frame_count <= 0:
        _拒绝("MEMORY_METADATA", "总帧数记录无效", 400)
    current_source, current_work, current_decode, h3_work = 0, 0, 0, 0
    for seg in segments:
        frames = seg["frame_count"]
        if type(frames) is not int or frames <= 0 or (seg["width"], seg["height"]) != (first["width"], first["height"]):
            _拒绝("MEMORY_METADATA", "源段画布或帧数记录无效", 400)
        source = tensor_bytes(seg)
        video = seg["video_latent"]
        shape = video["shape"]
        if type(shape) is not list or len(shape) != 5 or any(type(n) is not int or n <= 0 for n in shape):
            _拒绝("MEMORY_METADATA", "源 latent shape 无效", 400)
        fp32 = max(video["bytes"], math.prod(shape) * 4)
        work_audio = max(tensor_bytes(seg.get("audio_latent")), 32 * 2 * round(frames / 24 * 40) * 4)
        current_source = max(current_source, source)
        current_work = max(current_work, 5 * fp32 + 4 * work_audio + source if strength else 0)
        h3 = mode == "H3潜空间" and (width, height) != (first["width"], first["height"])
        dw, dh = (width, height) if h3 else (first["width"], first["height"])
        current_decode = max(current_decode, frames * dw * dh * 3 * 4 * 2 + fp32)
        if h3:
            enlarged = 24 * shape[2] * (height // 16) * (width // 16) * max(4, video["bytes"] // math.prod(shape))
            h3_work = max(h3_work, 3 * (fp32 + enlarged))
    parts = {"final_image_bytes": frame_count * width * height * 3 * 4,
             "current_source_bytes": current_source, "current_work_bytes": current_work,
             "current_decode_bytes": current_decode, "h3_current_bytes": h3_work,
             "image_batch_bytes": 3 * width * height * 3 * 4,
             "audio_bytes": tensor_bytes(manifest.get("audio"))}
    total = sum(parts.values())
    limit = _内存硬限制()
    observations = _JSON副本(_资源观测())
    available = observations.get("ram_available_bytes")
    if (limit and total > limit) or (type(available) is int and total > available):
        _拒绝("MEMORY_LIMIT", "二采最终 IMAGE 与当前段已知数据超过内存硬限制或当前可用 RAM", 400)
    return {"known_data_bytes": total, "parts": parts, "hard_limit_bytes": limit,
            "observations": observations,
            "limitations": "仅已知数据下限；未计模型、未知激活、像素模型原生倍率和外部引用，不保证峰值或不OOM"}


class 交接协调器:
    观察间隔 = 0.25
    清理等待上限 = 120.0
    清理核对上限 = 900.0

    def __init__(self, server):
        self.server = server
        self.q = server.prompt_queue
        for name in ("mutex", "queue", "currently_running", "history", "flags", "put",
                     "delete_queue_item", "interrupt_if_running", "set_flag"):
            if not hasattr(self.q, name):
                _拒绝("HOST_UNSUPPORTED", "当前宿主队列接口不支持交接", 503)
        if not hasattr(server, "number") or not hasattr(server, "node_replace_manager"):
            _拒绝("HOST_UNSUPPORTED", "当前宿主入队接口不支持交接", 503)
        self._lock = threading.RLock()
        # 三张表随进程累积、无淘汰：终态 job 仍要支撑幂等重发（_requests）、读取任务初采与门控
        # 核验（_jobs/_artifacts），删掉就会让已结束的 job 变成「不存在」。上限＝本机交接任务数。
        # 能力令牌 = HMAC(_secret, job_id)，无过期时间，只随进程结束（密钥消失）而失效。
        self._jobs = {}
        self._requests = {}
        self._artifacts = {}
        self._active = None
        self._observer = None
        self._closed = False
        self._secret = secrets.token_bytes(32)
        self._最后序号 = None

    @contextmanager
    def _临界区(self):
        # 唯一双锁入口；慢 IO/哈希/校验/模型操作均不能在此作用域内执行。
        with self.q.mutex:
            with self._lock:
                yield

    def _能力(self, job_id):
        # 可重发幂等响应，job 只存摘要；密钥只在当前协调器进程内。
        return hmac.new(self._secret, job_id.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _能力摘要(capability):
        if type(capability) is not str or len(capability) > 256:
            _拒绝("FORBIDDEN", "任务控制能力无效", 403)
        return hashlib.sha256(capability.encode()).hexdigest()

    def _授权(self, job_id, owner, cap_hash):
        job = self._jobs.get(job_id)
        if job is None or job["owner"] != owner or not hmac.compare_digest(job["capability_hash"], cap_hash):
            _拒绝("FORBIDDEN", "任务不存在或不属于当前控制者", 403)
        return job

    @staticmethod
    def _版本(job, attempt, version):
        if type(attempt) is not int or type(version) is not int or (attempt, version) != (job["attempt"], job["version"]):
            _拒绝("STALE_VERSION", "任务轮次或状态版本已改变")

    def _迁移(self, job, state, **values):
        if state not in _状态全集:
            # 编程错误，不走 交接错误 的 409 映射；未登记状态不得写入 job，免得 version 被顶高。
            raise RuntimeError(f"交接状态 {state!r} 未在 _状态全集 登记")
        job.update(values)
        job.update(state=state, version=job["version"] + 1, changed_at=time.time())
        if state in _终态 and self._active == job["job_id"]:
            self._active = None

    def _公开(self, job):
        phases = job.get("phases", {})
        a = phases.get("A", {})
        return copy.deepcopy({"job_id": job["job_id"], "attempt": job["attempt"], "version": job["version"],
                              "state": job["state"], "phase": job.get("phase"), "seq": job["version"],
                              "prompt_id": a.get("id"), "number": a.get("number"), "node_errors": {},
                              "a_prompt_id": a.get("id"), "c_prompt_id": phases.get("C", {}).get("id"),
                              "b_prompt_id": phases.get("B", {}).get("id"),
                              "artifact_id": (job.get("ref") or {}).get("artifact_id"),
                              "cleanup_requested": job.get("cleanup_requested", False),
                              "cleanup_confirmed": job.get("cleanup_confirmed", False),
                              "error": job.get("error"), "report": job.get("report", {})})

    def _带能力(self, response):
        return {**response, "capability": self._能力(response["job_id"])}

    def _空闲(self, *, flags=True):
        if self.q.queue or self.q.currently_running or (flags and self.q.flags):
            _拒绝("QUEUE_BUSY", "交接要求专用空闲队列且无待处理清理标志")

    def _启动观察(self):
        if self._observer is None or self._observer.done():
            self._observer = asyncio.get_running_loop().create_task(self._观察循环())

    @staticmethod
    def _记录(phase, graph, outputs, node, nonce, attempt):
        return {"id": str(uuid.uuid4()), "graph": graph, "outputs": list(outputs), "node": node,
                "nonce": nonce, "attempt": attempt, "digest": _图摘要(graph), "receipt": None,
                "number": None, "phase": phase}

    async def _准备(self, graph, workflow, options, job_id, attempt):
        bundle = _JSON副本({"graph": graph, "workflow": workflow})
        graph, workflow = bundle["graph"], bundle["workflow"]
        if type(graph) is not dict or not graph or type(workflow) is not dict or _保留ID.intersection(graph):
            _拒绝("INVALID_GRAPH", "图格式无效或占用交接保留节点 ID", 400)
        # 不让 API 凭据随任意图/画布元数据进入队列历史。
        stack = [bundle]
        while stack:
            item = stack.pop()
            if type(item) is dict:
                if {"capability", "auth_token_comfy_org", "api_key_comfy_org"}.intersection(item):
                    _拒绝("SENSITIVE_DATA", "交接图与工作流禁止携带控制能力或 API 凭据", 400)
                stack.extend(item.values())
            elif type(item) is list:
                stack.extend(item)
        self.server.node_replace_manager.apply_replacements(graph)
        graph = _JSON副本(graph)
        if _保留ID.intersection(graph):
            _拒绝("INVALID_GRAPH", "替换后的图占用交接保留节点 ID", 400)
        classes = _节点类()
        for node in graph.values():
            cls = classes.get(node.get("class_type")) if type(node) is dict else None
            if cls is None or getattr(cls, "API_NODE", False):
                _拒绝("UNSUPPORTED_NODE", "交接不支持未知或远程 API 节点", 400)
        analysis = _分析图(graph, classes)
        if analysis is None:
            _拒绝("NO_HANDOFF", "图中没有受支持的有效交接链", 400)
        a_nonce, c_nonce, b_nonce = (secrets.token_hex(32) for _ in range(3))
        stages = _构建图(analysis, job_id=job_id, attempt=attempt, a_nonce=a_nonce, b_nonce=b_nonce)
        stages = _JSON副本(stages)
        controls = {"job_id": job_id, "attempt": attempt}
        cg = {"_lvp_cleanup": {"class_type": "LVP_阶段清理", "inputs": {**controls, "nonce": c_nonce}}}
        bg = {"_lvp_gate": {"class_type": "LVP_二采入口", "inputs": {**controls, "nonce": b_nonce}}}
        phases = {"A": self._记录("A", stages["a_graph"], stages["a_outputs"], analysis["handoff_id"], a_nonce, attempt),
                  "C": self._记录("C", cg, ["_lvp_cleanup"], "_lvp_cleanup", c_nonce, attempt),
                  "B": self._记录("B", bg, ["_lvp_gate"], "_lvp_gate", b_nonce, attempt)}
        checks = [(phases["A"]["id"], phases["A"]["graph"], phases["A"]["outputs"]),
                  (phases["B"]["id"], stages["b_graph"], stages["b_outputs"]),
                  (phases["C"]["id"], cg, ["_lvp_cleanup"]), (phases["B"]["id"], bg, ["_lvp_gate"])]
        for pid, template, expected in checks:
            # 当前宿主会原位归一化 INT/FLOAT/STRING 输入。冻结真正校验过的图，
            # 而非丢弃归一化后再把未经校验的原值交给 execute。
            checked = copy.deepcopy(template)
            valid = await _验证图(pid, checked, list(expected))
            if (not isinstance(valid, (tuple, list)) or len(valid) != 4 or valid[0] is not True
                    or valid[3] != {} or not isinstance(valid[2], (list, tuple))
                    or len(valid[2]) != len(expected) or set(valid[2]) != set(expected)):
                _拒绝("VALIDATION_FAILED", "交接阶段未通过全部输出校验（不允许局部成功）", 400)
            template.clear()
            template.update(_JSON副本(checked))
        for record in phases.values():
            record["digest"] = _图摘要(record["graph"])
        return {"phases": phases, "workflow": workflow, "options": options,
                "b_graph": stages["b_graph"], "b_digest": _图摘要(stages["b_graph"]),
                "b_outputs": stages["b_outputs"], "dynamic_ids": {},
                **{key: analysis[key] for key in ("source_id", "handoff_id", "refiner_id", "source_digest")}}

    def _入队(self, job, phase):
        record = job["phases"][phase]
        number = self.server.number
        if type(number) not in (int, float) or not math.isfinite(number):
            _拒绝("HOST_UNSUPPORTED", "宿主队列序号无效", 503)
        # 宿主 /prompt 处理不设锁，可能与本协调器同时取号；这里只保证本协调器序号严格递增且写回宿主，
        # 无法证明全局唯一（阶段身份仍由 prompt_id 判定，序号只影响排队展示次序）。
        if self._最后序号 is not None and number <= self._最后序号:
            number = self._最后序号 + 1
        extra = {"client_id": job["client_id"], "create_time": int(time.time() * 1000),
                 "extra_pnginfo": {"workflow": copy.deepcopy(job["workflow"])}, **job["options"]}
        item = (number, record["id"], copy.deepcopy(record["graph"]), extra, list(record["outputs"]), {})
        self.server.number = number + 1
        self._最后序号 = number
        record["number"] = number
        self._迁移(job, phase + "_QUEUED", phase=phase, queued_at=time.monotonic())
        attempt, version = job["attempt"], job["version"]
        try:
            self.q.put(item)
        except BaseException as exc:
            self._失败CAS(job["job_id"], attempt, version,
                        "CANCELLED" if _是取消异常(exc) else "FAILED", "QUEUE_PUT_FAILED")
            if _需原样传播(exc):
                raise
            _拒绝("QUEUE_PUT_FAILED", "阶段入队失败", 503)

    async def 提交交接任务(self, graph, workflow, *, owner, client_id, request_id, options=None):
        _文本(owner, "owner")
        _文本(client_id, "client_id")
        _文本(request_id, "request_id")
        options = _选项(options)
        job_id = str(uuid.uuid4())
        cap_hash = self._能力摘要(self._能力(job_id))
        with self._临界区():
            if self._closed:
                _拒绝("CLOSED", "协调器已停止", 503)
            old = self._requests.get((owner, request_id))
            if old is not None:
                response = self._公开(self._jobs[old])
            else:
                if self._active is not None:
                    _拒绝("CHAIN_BUSY", "已有活动交接链（含验证预留）")
                self._空闲()
                job = {"job_id": job_id, "owner": owner, "client_id": client_id, "request_id": request_id,
                       "capability_hash": cap_hash, "attempt": 1, "version": 1, "state": "VALIDATING",
                       "ref": None, "a_succeeded": False, "cleanup_requested": False, "cleanup_confirmed": False,
                       "error": None, "report": {}}
                self._jobs[job_id] = job
                self._requests[(owner, request_id)] = job_id
                self._active = job_id
                response = None
                version = job["version"]
        if response is not None:
            return self._带能力(response)
        try:
            prepared = await self._准备(graph, workflow, options, job_id, 1)
            with self._临界区():
                self._版本(job, 1, version)
                if job["state"] != "VALIDATING":
                    _拒绝("STATE_CHANGED", "验证期间任务已停止")
                self._空闲()
                job.update(prepared)
                self._入队(job, "A")
                self._启动观察()
                response = self._公开(job)
        except BaseException as exc:
            # 状态里的 error 要与路由透出的 code 同源，否则查状态只剩笼统的 SUBMIT_FAILED。
            propagate = _需原样传播(exc) or isinstance(exc, 交接错误)
            code = (exc.code if isinstance(exc, 交接错误) else
                    "SUBMIT_FAILED" if propagate else
                    "GRAPH_REJECTED" if isinstance(exc, ValueError) else "SUBMIT_FAILED")
            self._失败CAS(job_id, 1, version, "CANCELLED" if _是取消异常(exc) else "FAILED", code)
            if propagate:
                raise
            logging.exception("[长视频规划师] 交接提交校验失败（job %s）", job_id)
            if code == "GRAPH_REJECTED":
                # 分图合同的中文原因只含节点 ID 与输入名；映射成带码错误后路由才透得出原因。
                _拒绝(code, "交接图校验失败：" + _单行原因(exc), 400)
            _拒绝(code, "交接提交校验失败", 400)
        return self._带能力(response)

    def 取交接状态(self, job_id, *, owner, capability):
        cap_hash = self._能力摘要(capability)
        with self._临界区():
            return self._公开(self._授权(job_id, owner, cap_hash))

    def _失败CAS(self, job_id, attempt, version, state, code):
        with self._临界区():
            job = self._jobs.get(job_id)
            if job and (job["attempt"], job["version"]) == (attempt, version) and job["state"] not in _终态:
                self._迁移(job, state, error=code)

    def _失败CAS当前(self, job_id, attempt, state, code):
        # 同轮控制节点会先推进版本；观察器只按当前版本落停，否则 job 卡在非终态并长期占用 _active。
        with self._临界区():
            job = self._jobs.get(job_id)
            if job and type(attempt) is int and job["attempt"] == attempt and job["state"] not in _终态:
                self._迁移(job, state, error=code)

    def 检查任务取消(self, job_id, attempt):
        with self._临界区():
            job = self._jobs.get(job_id)
            if job is None or type(attempt) is not int or job["attempt"] != attempt or job["state"] in _终态:
                _拒绝("CANCELLED", "任务已停止或轮次过期")

    def _控制上下文(self, job_id, attempt, nonce, phase, context, states, *, node=None):
        job = self._jobs.get(job_id)
        record = (job or {}).get("phases", {}).get(phase)
        if (job is None or record is None or type(attempt) is not int or job["attempt"] != attempt
                or type(nonce) is not str or len(nonce) != 64 or not nonce.isascii()
                or not hmac.compare_digest(nonce, record["nonce"])
                or job["state"] not in states or self._active != job_id
                or context is None or context.prompt_id != record["id"]
                or context.node_id != (record["node"] if node is None else node)
                or getattr(context, "list_index", None) not in (None, 0)
                or len(self.q.currently_running) != 1
                or next(iter(self.q.currently_running.values()))[1] != record["id"]):
            _拒绝("INVALID_CONTEXT", "控制节点不属于当前交接阶段或控制数据已过期")
        return job

    def _专用运行(self):
        if self.q.queue or self.q.flags:
            _拒绝("QUEUE_CONFLICT", "检测到外部等待任务或清理标志；已拒绝继续")

    @staticmethod
    def _回执(job, phase):
        record = job["phases"][phase]
        return {"job_id": job["job_id"], "attempt": record["attempt"], "phase": phase,
                "nonce": record["nonce"], "artifact_id": job["ref"]["artifact_id"]}

    def 保存任务初采(self, package, job_id, attempt, nonce):
        context = _执行上下文()
        with self._临界区():
            job = self._控制上下文(job_id, attempt, nonce, "A", context, {"A_QUEUED", "A_RUNNING"})
            self._迁移(job, "A_WRITING")
            version = job["version"]
        try:
            # callback 只捕获小控制标量，不存入 job，不持有 package。
            ref = _JSON副本(_保存交接(package, 检查取消=lambda: self.检查任务取消(job_id, attempt)))
            if ref.get("type") != "LVP_FIRST_PASS_DISK" or ref.get("source_node_id") != job["source_id"]:
                _拒绝("ARTIFACT_IDENTITY", "交接引用来源身份不匹配")
            with self._临界区():
                # 发布恰逢取消：仍登记自产文件，但不得复活/推进；文件保留。
                if ref["artifact_id"] in self._artifacts:
                    _拒绝("ARTIFACT_DUPLICATE", "禁止复用已登记交接产物")
                self._artifacts[ref["artifact_id"]] = {"job_id": job_id, "ref": copy.deepcopy(ref)}
                if job["attempt"] == attempt:
                    if job["version"] != version:
                        # 保留原终态，但元数据发布也是版本化更新，防旧状态覆盖。
                        self._迁移(job, job["state"], ref=copy.deepcopy(ref))
                    else:
                        job["ref"] = copy.deepcopy(ref)
                self._版本(job, attempt, version)
                if job["state"] != "A_WRITING":
                    _拒绝("STATE_CHANGED", "交接发布时任务已停止；文件已保留")
                receipt = self._回执(job, "A")
                job["phases"]["A"]["receipt"] = receipt
                self._迁移(job, "ARTIFACT_READY")
                return copy.deepcopy(ref), copy.deepcopy(receipt)
        except BaseException as exc:
            self._失败CAS(job_id, attempt, version, "CANCELLED" if _是取消异常(exc) else "FAILED", "ARTIFACT_WRITE_FAILED")
            if _需原样传播(exc):
                raise
            _拒绝("ARTIFACT_WRITE_FAILED", "交接写入失败或任务已停止；不申请清理")

    def _清单(self, job):
        ref = job.get("ref")
        if not ref:
            _拒绝("ARTIFACT_MISSING", "交接引用尚未发布")
        with self._临界区():
            registered = self._artifacts.get(ref["artifact_id"])
            if registered != {"job_id": job["job_id"], "ref": ref}:
                _拒绝("ARTIFACT_UNREGISTERED", "只允许本进程本任务自产交接引用")
        manifest = _读清单(copy.deepcopy(ref))
        if (manifest.get("artifact_id") != ref["artifact_id"] or manifest.get("type") != "LVP_HANDOFF"
                or any(manifest.get("package", {}).get(key) != ref.get(key)
                       for key in ("source_node_id", "source_run_id", "frame_count", "output_fps"))):
            _拒绝("ARTIFACT_IDENTITY", "交接清单身份不符；源文件保留")
        return manifest

    def _历史(self, record):
        """锁内只投影控制证据；不复制/持有业务 outputs 或错误 traceback。

        宿主承诺队列项不可变（get_current_queue_volatile 同一约定）；graph 的
        临时引用只在本次检查使用，哈希在锁外，绝不登记为 job 状态。
        """
        hist = self.q.history.get(record["id"])
        if type(hist) is not dict:
            return None
        prompt = hist.get("prompt")
        if type(prompt) not in (tuple, list) or len(prompt) != 5:
            return None
        status = hist.get("status")
        if type(status) is not dict:
            return None
        messages = status.get("messages")
        if type(messages) is not list:
            return None
        events = []
        for item in messages:
            if type(item) not in (tuple, list) or len(item) != 2 or type(item[1]) is not dict:
                return None
            events.append((item[0], item[1].get("prompt_id")))
        outputs = hist.get("outputs", {})
        ui = outputs.get(record["node"], {}) if type(outputs) is dict else {}
        receipts = ui.get("lvp_handoff") if type(ui) is dict else None
        receipt = None
        if type(receipts) is list and len(receipts) == 1 and type(receipts[0]) is dict:
            candidate = receipts[0]
            if (set(candidate) == {"job_id", "attempt", "phase", "nonce", "artifact_id"}
                    and all(type(v) in (str, int) for v in candidate.values())):
                receipt = candidate.copy()
        return {"id": prompt[1], "graph": prompt[2], "outputs": prompt[4],
                "status": status.get("status_str"), "completed": status.get("completed"),
                "events": events, "receipt": receipt}

    @staticmethod
    def _历史成功(history, record):
        if history is None or record["receipt"] is None:
            return False
        try:
            return (history["id"] == record["id"] and history["status"] == "success" and history["completed"] is True
                    and ("execution_success", record["id"]) in history["events"]
                    and not any("error" in event or "interrupt" in event for event, _ in history["events"])
                    and type(history["outputs"]) in (list, tuple)
                    and len(history["outputs"]) == len(record["outputs"])
                    and set(history["outputs"]) == set(record["outputs"])
                    and history["receipt"] == record["receipt"]
                    and _图摘要(history["graph"]) == record["digest"])
        except (TypeError, ValueError, KeyError):
            return False

    def 请求阶段清理(self, job_id, attempt, nonce):
        context = _执行上下文()
        with self._临界区():
            job = self._控制上下文(job_id, attempt, nonce, "C", context, {"C_QUEUED"})
            self._专用运行()
            self._迁移(job, "C_CHECKING")
            snapshot = copy.deepcopy(job)
            ah = self._历史(job["phases"]["A"])
        version = snapshot["version"]
        try:
            if not snapshot["a_succeeded"] or not self._历史成功(ah, snapshot["phases"]["A"]):
                _拒绝("A_HISTORY_INVALID", "初采完整成功证据已失效")
            self._清单(snapshot)
            # 慢校验后先 CAS 一次，取消或外部任务已发生时不清插件模型缓存。
            with self._临界区():
                self._版本(job, attempt, version)
                self._控制上下文(job_id, attempt, nonce, "C", context, {"C_CHECKING"})
                self._专用运行()
            _清插件模型缓存()
            with self._临界区():
                self._版本(job, attempt, version)
                self._控制上下文(job_id, attempt, nonce, "C", context, {"C_CHECKING"})
                self._专用运行()
                receipt = self._回执(job, "C")
                job["phases"]["C"]["receipt"] = receipt
                self._迁移(job, "C_REQUESTED", cleanup_requested=True)
                version = job["version"]
                # 与状态登记同一个短临界区；从不在图内调用 reset。
                self.q.set_flag("unload_models", True)
                self.q.set_flag("free_memory", True)
                return copy.deepcopy(receipt)
        except BaseException as exc:
            self._失败CAS(job_id, attempt, version, "CANCELLED" if _是取消异常(exc) else "PAUSED", "C_CHECK_FAILED")
            if _需原样传播(exc):
                raise
            _拒绝("C_CHECK_FAILED", "清理条件失效；禁止派发二采")

    def 核验二采门控(self, job_id, attempt, nonce):
        context = _执行上下文()
        with self._临界区():
            job = self._控制上下文(job_id, attempt, nonce, "B", context, {"B_QUEUED"})
            self._专用运行()
            self._迁移(job, "B_CHECKING")
            snapshot = copy.deepcopy(job)
            ch = self._历史(job["phases"]["C"])
            last = next(reversed(self.q.history), None)
        version = snapshot["version"]
        try:
            if last != snapshot["phases"]["C"]["id"] or not self._历史成功(ch, snapshot["phases"]["C"]):
                _拒绝("C_HISTORY_INVALID", "最近完成历史不是本轮完整成功的 C")
            if not snapshot["cleanup_requested"] or _图摘要(snapshot["b_graph"]) != snapshot["b_digest"]:
                _拒绝("TEMPLATE_CHANGED", "二采冻结模板或清理申请不匹配")
            manifest = self._清单(snapshot)
            with self._临界区():
                self._门控复核(job, attempt, version, nonce, context)
            _空载回收()
            report = _元数据预算(manifest, snapshot["b_graph"], snapshot["refiner_id"])
            with self._临界区():
                self._门控复核(job, attempt, version, nonce, context)
            # GraphBuilder 只生成定义，不执行模型/读取/保存。
            expanded = _JSON副本(_展开图(copy.deepcopy(snapshot["b_graph"])))
            ids = expanded["node_ids"]
            if (set(ids) != set(snapshot["b_graph"]) or len(set(ids.values())) != len(ids)
                    or set(ids.values()) != set(expanded["graph"])):
                _拒绝("EXPANSION_INVALID", "二采动态 ID 映射不完整")
            with self._临界区():
                self._门控复核(job, attempt, version, nonce, context)
                receipt = self._回执(job, "B")
                job["phases"]["B"]["receipt"] = receipt
                self._迁移(job, "B_GATE_PASSED", cleanup_confirmed=True, report=report,
                         dynamic_ids={dynamic: original for original, dynamic in ids.items()})
                return expanded["graph"], copy.deepcopy(receipt)
        except BaseException as exc:
            self._失败CAS(job_id, attempt, version, "CANCELLED" if _是取消异常(exc) else "PAUSED", "B_GATE_FAILED")
            if _需原样传播(exc):
                raise
            _拒绝("B_GATE_FAILED", "二采门控未通过；不加载二采模型或源 Tensor")

    def _门控复核(self, job, attempt, version, nonce, context):
        self._版本(job, attempt, version)
        self._控制上下文(job["job_id"], attempt, nonce, "B", context, {"B_CHECKING"})
        self._专用运行()
        if next(reversed(self.q.history), None) != job["phases"]["C"]["id"]:
            _拒绝("HISTORY_CHANGED", "门控期间插入外部完成历史")

    def 读取任务初采(self, job_id, attempt, nonce):
        context = _执行上下文()
        with self._临界区():
            job = self._jobs.get(job_id)
            ids = (job or {}).get("dynamic_ids", {})
            node = getattr(context, "node_id", None)
            if ids.get(node) != (job or {}).get("handoff_id") or node is None:
                _拒绝("INVALID_CONTEXT", "读取节点不是本轮展开的磁盘读取器")
            job = self._控制上下文(job_id, attempt, nonce, "B", context, {"B_GATE_PASSED"}, node=node)
            snapshot = copy.deepcopy(job)
        self._清单(snapshot)
        self.检查任务取消(job_id, attempt)
        return copy.deepcopy(snapshot["ref"])

    def 取磁盘执行上下文(self, ref):
        context = _执行上下文()
        safe_ref = _JSON副本(ref)
        with self._临界区():
            registered = self._artifacts.get(safe_ref.get("artifact_id"))
            if not registered or registered["ref"] != safe_ref:
                _拒绝("ARTIFACT_UNREGISTERED", "磁盘引用不属于本进程交接任务")
            job = self._jobs[registered["job_id"]]
            node = getattr(context, "node_id", None)
            if node is None or job.get("dynamic_ids", {}).get(node) != job["refiner_id"]:
                _拒绝("INVALID_CONTEXT", "只有本轮展开的原精修节点可消费磁盘产物")
            self._控制上下文(job["job_id"], job["attempt"], job["phases"]["B"]["nonce"], "B", context,
                         {"B_GATE_PASSED"}, node=node)
            return {"cache_node_id": job["refiner_id"], "job_id": job["job_id"], "attempt": job["attempt"]}

    def _清理超时(self, job):
        # 仍在阶段队列里按等待上限；worker 已取走进入核对说明慢 IO 正在跑，按更大的核对上限。
        等待 = job["state"] == job["phase"] + "_QUEUED"
        return time.monotonic() - job["queued_at"] > (self.清理等待上限 if 等待 else self.清理核对上限)

    @staticmethod
    def _清理超时码(job, 阶段):
        return (阶段 + "_TIMEOUT_UNCONFIRMED" if job["state"] == 阶段 + "_QUEUED"
                else 阶段 + "_CHECK_TIMEOUT")

    def _观察同步(self):
        with self._临界区():
            if self._active is None:
                return
            job = self._jobs[self._active]
            if job["state"] == "VALIDATING":
                return
            phase = job["phase"]
            record = job["phases"][phase]
            pid = record["id"]
            running = any(item[1] == pid for item in self.q.currently_running.values())
            queued = any(item[1] == pid for item in self.q.queue)
            if running or queued:
                if phase == "C" and self._清理超时(job):
                    self._迁移(job, "PAUSED", error=self._清理超时码(job, "C"))
                elif (phase == "B" and not job["cleanup_confirmed"] and self._清理超时(job)):
                    self._迁移(job, "PAUSED", error=self._清理超时码(job, "B"))
                    while self.q.delete_queue_item(lambda item: item[1] == pid):
                        pass
                elif phase == "A" and running and job["state"] == "A_QUEUED":
                    self._迁移(job, "A_RUNNING")
                return
            history = self._历史(record)
            snapshot = copy.deepcopy(job)
        jid, attempt, version = snapshot["job_id"], snapshot["attempt"], snapshot["version"]
        if history is None:
            self._失败CAS(jid, attempt, version, "PAUSED", "PROMPT_LOST_OR_HISTORY_MISSING")
            return
        try:
            if not self._历史成功(history, snapshot["phases"][phase]):
                self._失败CAS(jid, attempt, version, "FAILED", phase + "_HISTORY_FAILED")
                return
            if phase == "A":
                self._清单(snapshot)
            with self._临界区():
                if (job["attempt"], job["version"]) != (attempt, version) or job["state"] in _终态:
                    return
                if phase == "B":
                    if not job["cleanup_confirmed"] or job["state"] != "B_GATE_PASSED":
                        self._迁移(job, "FAILED", error="B_GATE_RECEIPT_MISSING")
                    else:
                        self._迁移(job, "SUCCEEDED")
                elif phase == "A":
                    self._迁移(job, "A_SUCCEEDED", a_succeeded=True)
                    advance_version = job["version"]
                    try:
                        self._空闲()
                        self._入队(job, "C")
                    except BaseException as exc:
                        self._失败CAS(jid, attempt, advance_version,
                                    "CANCELLED" if _是取消异常(exc) else "PAUSED", "C_QUEUE_CONFLICT")
                        if _需原样传播(exc):
                            raise
                else:
                    # C history 早于 worker.get_flags 是正常的；只允许本次两个 True 标志。
                    if job["state"] != "C_REQUESTED" or not job["cleanup_requested"]:
                        self._迁移(job, "FAILED", error="C_RECEIPT_MISSING")
                        return
                    if any(key not in ("unload_models", "free_memory") or value is not True
                           for key, value in self.q.flags.items()):
                        self._迁移(job, "PAUSED", error="C_FLAGS_CONFLICT")
                        return
                    self._空闲(flags=False)
                    self._入队(job, "B")
        except BaseException as exc:
            self._失败CAS(jid, attempt, version, "CANCELLED" if _是取消异常(exc) else "PAUSED", phase + "_ADVANCE_FAILED")
            if _需原样传播(exc):
                raise

    async def 观察一次(self):
        # 文件摘要/清单检查不能堵塞服务端事件循环；一个观察器最多一个在途检查。
        await asyncio.to_thread(self._观察同步)

    async def _观察循环(self):
        this_task = asyncio.current_task()
        token = None
        try:
            while True:
                with self._临界区():
                    if self._closed or self._active is None:
                        return
                    job = self._jobs[self._active]
                    token = (job["job_id"], job["attempt"], job["version"])
                await self.观察一次()
                with self._临界区():
                    if self._active is None:
                        return
                await asyncio.sleep(self.观察间隔)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if token is not None:
                if _是取消异常(exc):
                    self._失败CAS(*token, "CANCELLED", "OBSERVER_FAILED")
                else:
                    self._失败CAS当前(token[0], token[1], "PAUSED", "OBSERVER_FAILED")
            if _需原样传播(exc):
                raise
        finally:
            with self._临界区():
                if self._observer is this_task:
                    self._observer = None
                    if not self._closed and self._active is not None and token is not None:
                        active = self._jobs[self._active]
                        # 只接续复用本观察器的新 job/attempt，不重启被取消的同轮。
                        if (active["state"] not in _终态
                                and (active["job_id"], active["attempt"]) != token[:2]):
                            self._启动观察()

    async def 关闭(self):
        """供宿主生命周期适配调用；不撤销已请求 flags，不自动恢复。"""
        with self._临界区():
            self._closed = True
            if self._active is not None:
                self._迁移(self._jobs[self._active], "PAUSED", error="COORDINATOR_CLOSED")
            task = self._observer
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                # task 在首次调度前被取消时，协程自己的 finally 不会执行。
                with self._临界区():
                    if self._observer is task:
                        self._observer = None


def 取得协调器():
    from server import PromptServer
    server = getattr(PromptServer, "instance", None)
    if server is None:
        _拒绝("SERVER_UNAVAILABLE", "PromptServer 尚未就绪", 503)
    # 缓存在宿主对象，而不是模块全局：同一插件重复加载不产生第二个轮询器。
    with _单例锁:
        coordinator = getattr(server, "_lvp_handoff_coordinator", None)
        if coordinator is None:
            coordinator = 交接协调器(server)
            server._lvp_handoff_coordinator = coordinator
        return coordinator
