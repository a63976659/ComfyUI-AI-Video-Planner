"""独立后处理内容缓存；不读取、淘汰或清理初采缓存。"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import uuid
import weakref

import torch

from .参考素材 import 解析槽位
from .条件组装 import 选模型槽, 需要首帧, 需要尾帧
from .精修条件 import _前驱尾, 精修前驱尾
from .路径守卫 import 真实路径 as _真实路径


class 缓存读写异常(ValueError):
    """只有磁盘/改名/反序列化这类 IO 侧失败；输入不合法仍抛普通 ValueError。"""


_格式版本 = 1
_精修算法 = "refine-v1-token-mask-promoted-tail"
_放大算法 = "h3-upscale-v1-fp32-full"
_摘要格式 = re.compile(r"[0-9a-f]{64}")
_进程标识 = uuid.uuid4().hex
_模型弱标识 = {}
_模型锁 = threading.RLock()
_块字节 = 1024 * 1024
_改名尝试 = 5
_改名间隔 = (0.05, 0.1, 0.2, 0.4)


def _原子改名(源, 目标):
    """Windows 上杀软/索引器会短暂独占刚落盘的目标文件，改名要等到句柄释放而非放弃整轮。"""
    for 次序 in range(_改名尝试):
        try:
            os.replace(源, 目标)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in (5, 32) or 次序 == _改名尝试 - 1:
                raise
            time.sleep(_改名间隔[次序])


def _规范值(value, active=None, *, tensor=True):
    if active is None:
        active = set()
    if type(value) is torch.Tensor and tensor:
        return ["tensor", 张量摘要(value)]
    if type(value) in (dict, tuple, list):
        if id(value) in active:
            raise ValueError("缓存元信息不允许循环容器")
        active.add(id(value))
        try:
            if type(value) is dict:
                if any(type(k) is not str for k in value):
                    raise ValueError("缓存元信息字典键须为字符串")
                return ["dict", [[k, _规范值(value[k], active, tensor=tensor)] for k in sorted(value)]]
            return [type(value).__name__, [_规范值(v, active, tensor=tensor) for v in value]]
        finally:
            active.remove(id(value))
    if value is None or type(value) in (str, bool, int):
        return [type(value).__name__, value]
    if type(value) is float and math.isfinite(value):
        return ["float", value]
    raise ValueError("缓存元信息只允许有限标量、内建容器与 CPU Tensor")


def _摘要(value):
    data = json.dumps(_规范值(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def 张量摘要(value):
    def feed(part):
        raw = None
        try:
            if part.numel() * part.element_size() <= _块字节:
                raw = part.detach().contiguous().reshape(-1).view(torch.uint8).numpy()
                digest.update(memoryview(raw))
                return
            axis = next(i for i, n in enumerate(part.shape) if n > 1)
            split = part.shape[axis] // 2
            feed(part.narrow(axis, 0, split))
            feed(part.narrow(axis, split, part.shape[axis] - split))
        finally:
            part = raw = None

    try:
        if type(value) is not torch.Tensor or value.device.type != "cpu" or value.layout != torch.strided:
            raise ValueError("内容摘要需要 CPU 稠密 Tensor")
        digest = hashlib.sha256(json.dumps([str(value.dtype), list(value.shape)]).encode("ascii"))
        feed(value)
        return digest.hexdigest()
    finally:
        value = None


def 文件摘要(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(_块字节):
            digest.update(chunk)
    return digest.hexdigest()


def 取模型身份(model):
    value = getattr(model, "lvp_模型身份", None)
    if type(value) in (str, dict) and value:
        return {"scope": "content", "value": _摘要(_规范值(value, tensor=False))}
    key = id(model)
    with _模型锁:
        old = _模型弱标识.get(key)
        if old is not None and old[0]() is model:
            return {"scope": "process", "value": _进程标识 + ":" + old[1]}

        def release(ref):
            with _模型锁:
                current = _模型弱标识.get(key)
                if current is not None and current[0] is ref:
                    del _模型弱标识[key]

        try:
            ref = weakref.ref(model, release)
        except TypeError:
            return None
        token = uuid.uuid4().hex
        _模型弱标识[key] = (ref, token)
        return {"scope": "process", "value": _进程标识 + ":" + token}


def 精修键(段快照, 生成记录, 精修参数, 模型身份, 前段精修结果=None):
    if not 模型身份 or any(v is None for v in 模型身份.values()):
        return None
    seg, generation, params = 段快照, 生成记录, 精修参数
    if 选模型槽(seg["task"]) == "ref2va":
        refs = 解析槽位(seg["refs"])
    else:
        refs = {slot: seg["refs"].get(slot) for slot, enabled in (
            ("首帧", 需要首帧(seg["task"])), ("尾帧", 需要尾帧(seg["task"])),
            ("中间帧", 需要尾帧(seg["task"]) and seg["middle_frame_index"] is not None),
        ) if enabled}
    predecessor = None
    if seg["predecessor_index"] is not None:
        tail_v, tail_a, anchor, tick = _前驱尾(seg, generation, 前段精修结果)
        digest = (前段精修结果.video_digest if isinstance(前段精修结果, 精修前驱尾)
                  else 张量摘要(前段精修结果["video_latent"]))
        predecessor = {"video": digest,
                       "tail_video": 张量摘要(tail_v), "tail_audio": tail_a,
                       "anchor_frames": anchor, "audio_end_tick": tick}
    return _摘要({
        "algorithm": _精修算法,
        "source": {k: seg[k] for k in (
            "video_latent", "audio_latent", "task", "prompt", "width", "height", "frame_count",
            "anchor_frames", "crop_prefix", "middle_frame_index", "reference_audio_window")},
        "refs": refs, "assets": [a for a in seg["assets"] if a["slot"] in refs],
        "generation": {k: generation.get(k) for k in (
            "shift_video", "shift_audio", "参考图尺寸", "audio_vae", "上下文帧数",
            "音频上下文帧数", "续拍算法标识")},
        "sampling": {k: params[k] for k in ("精修强度", "精修步数", "采样器", "调度器", "缓存失效版本")},
        "seed": (params["精修种子"] + seg["index"]) % 2**64, "cfg": 1.0,
        "models": 模型身份, "predecessor": predecessor,
    })


def _校验摘要(value):
    if type(value) is not str or _摘要格式.fullmatch(value) is None:
        raise ValueError("缓存摘要须为64位小写十六进制")


def 放大键(video, 目标宽, 目标高, 权重摘要, 缓存失效版本):
    _校验摘要(权重摘要)
    return _摘要({"algorithm": _放大算法, "source": 张量摘要(video),
                "width": 目标宽, "height": 目标高, "weights": 权重摘要,
                "invalidate": 缓存失效版本})


def _缓存根():
    # 仅规范化可信 TEMP 父目录（含 Windows 短名），缓存内部仍严格拒绝链接。
    return Path(_真实路径(tempfile.gettempdir())) / "长视频规划师_后处理缓存" / "v1"


def _安全路径(path):
    root = os.path.abspath(_缓存根())
    absolute = os.path.abspath(path)
    real = _真实路径(absolute)
    if (os.path.normcase(root) != os.path.normcase(_真实路径(root))
            or os.path.normcase(real) != os.path.normcase(absolute)
            or os.path.commonpath([os.path.normcase(root), os.path.normcase(real)]) != os.path.normcase(root)):
        raise ValueError("后处理缓存路径越界或包含链接")
    return Path(absolute)


def _节点目录(node_id):
    safe = hashlib.sha256(str(node_id).encode("utf-8")).hexdigest()
    return _安全路径(_缓存根() / safe)


def 后处理缓存路径(node_id, stage, key):
    if stage not in ("refine", "h3-upscale"):
        raise ValueError("未知后处理缓存阶段")
    _校验摘要(key)
    return _安全路径(_节点目录(node_id) / stage / (key + ".pt"))


def _合法视频(video, shape):
    try:
        return (type(video) is torch.Tensor and video.device.type == "cpu" and video.layout == torch.strided
                and video.ndim == 5 and tuple(video.shape[:2]) == (1, 24) and min(video.shape) > 0
                and tuple(video.shape) == tuple(shape) and video.is_floating_point()
                and bool(torch.isfinite(video).all()))
    finally:
        video = None


def _合法记录(data, stage, key, shape, source):
    video = None
    try:
        if type(data) is not dict or set(data) != {
            "version", "stage", "key", "source_digest", "result_digest", "shape", "dtype", "video_latent"
        }:
            return False
        if type(data["version"]) is not int or data["version"] != _格式版本:
            return False
        for name, expected in (("stage", stage), ("key", key), ("source_digest", source)):
            if type(data[name]) is not str or data[name] != expected:
                return False
        if (type(data["shape"]) is not list or any(type(n) is not int for n in data["shape"])
                or data["shape"] != list(shape) or type(data["dtype"]) is not str
                or type(data["result_digest"]) is not str):
            return False
        video = data["video_latent"]
        return (_合法视频(video, shape) and data["dtype"] == str(video.dtype)
                and data["result_digest"] == 张量摘要(video))
    finally:
        data = video = None


def 读后处理缓存(node_id, stage, key, shape, source_digest):
    _校验摘要(source_digest)
    path = 后处理缓存路径(node_id, stage, key)
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise 缓存读写异常(f"后处理缓存读取失败：{exc}") from exc
    data = None
    try:
        with stream:
            try:
                data = torch.load(stream, map_location="cpu", weights_only=True)
            except (MemoryError, torch.OutOfMemoryError):
                raise
            except OSError as exc:
                raise 缓存读写异常(f"后处理缓存读取失败：{exc}") from exc
            except Exception as exc:
                # 兼容继承 Exception 的官方取消；只查已加载模块，不触发 GPU 初始化。
                interrupt = getattr(sys.modules.get("comfy.model_management"), "InterruptProcessingException", ())
                if isinstance(exc, interrupt):
                    raise
                # 仅隔离第三方反序列化：损坏文件保留，成功重算才原子覆盖。
                return None
        return data["video_latent"] if _合法记录(data, stage, key, shape, source_digest) else None
    finally:
        data = None


def 写后处理缓存(node_id, stage, key, video, source_digest):
    part = stored = data = None
    try:
        _校验摘要(source_digest)
        path = 后处理缓存路径(node_id, stage, key)
        if not _合法视频(video, getattr(video, "shape", ())):
            raise ValueError("后处理缓存只接受非空有限 CPU 视频 latent")
        stored = video.detach().contiguous()
        if stored.untyped_storage().nbytes() != stored.numel() * stored.element_size():
            stored = stored.clone()
        data = {"version": _格式版本, "stage": stage, "key": key, "source_digest": source_digest,
                "result_digest": 张量摘要(stored), "shape": list(stored.shape),
                "dtype": str(stored.dtype), "video_latent": stored}
        path.parent.mkdir(parents=True, exist_ok=True)
        _安全路径(path)
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, suffix=".part", delete=False) as stream:
            part = Path(stream.name)
            torch.save(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        _安全路径(path)
        _原子改名(part, path)
        part = None
        return path
    except OSError as exc:
        raise 缓存读写异常(f"后处理缓存写入失败：{exc}") from exc
    finally:
        video = stored = data = None
        if part is not None:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                # 删不掉只会在目录里留一个永不命中的 .part；在这里抛会顶掉本轮真正的写入/取消异常。
                pass


def 后处理缓存统计(node_id):
    root = _节点目录(node_id)
    files, size = 0, 0
    try:
        for stage in ("refine", "h3-upscale"):
            directory = _安全路径(root / stage)
            if not directory.exists():
                continue
            for path in directory.iterdir():
                if path.suffix != ".pt" or _摘要格式.fullmatch(path.stem) is None:
                    continue
                _安全路径(path)
                info = path.stat()
                files += 1
                size += info.st_size
    except OSError as exc:
        raise ValueError(f"后处理缓存统计失败：{exc}") from exc
    return {"path": str(root), "files": files, "bytes": size}
