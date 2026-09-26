"""带取消语义的初采产物持久化存储。"""
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path

import torch

from .初采产物 import 校验初采产物, 校验磁盘初采引用, _容器
from .路径守卫 import 真实路径 as _真实路径


_最大段数 = 10000
_最大清单字节 = 16 * 1024 * 1024
_最大文件字节 = 64 * 1024 ** 3
_已发布 = {}
_登记锁 = threading.Lock()


def _交接根():
    import folder_paths
    return Path(_真实路径(folder_paths.get_output_directory())) / "长视频规划师_交接" / "v1"


def _安全路径(path):
    root = os.path.abspath(_交接根())
    absolute = os.path.abspath(path)
    real = _真实路径(absolute)
    if (os.path.normcase(root) != os.path.normcase(_真实路径(root))
            or os.path.normcase(absolute) != os.path.normcase(real)
            or os.path.commonpath([os.path.normcase(root), os.path.normcase(real)]) != os.path.normcase(root)):
        raise ValueError("交接路径越界或包含链接")
    return Path(absolute)


def _JSON(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _描述(value):
    if type(value) is torch.Tensor:
        if value.dtype not in (torch.float16, torch.bfloat16, torch.float32, torch.float64):
            raise ValueError("交接 Tensor 精度不支持")
        return {"shape": list(value.shape), "dtype": str(value.dtype), "bytes": value.numel() * value.element_size()}
    if type(value) is dict:
        return {k: _描述(v) for k, v in value.items()}
    if type(value) in (list, tuple):
        return [_描述(v) for v in value]
    return value


def _数据字节(value):
    if type(value) is torch.Tensor:
        return value.numel() * value.element_size()
    if type(value) is dict:
        return sum(_数据字节(v) for v in value.values())
    if type(value) in (list, tuple):
        return sum(_数据字节(v) for v in value)
    return 0


def _紧凑副本(value):
    if type(value) is torch.Tensor:
        return value.detach().cpu().clone(memory_format=torch.contiguous_format)
    if type(value) is dict:
        return {k: _紧凑副本(v) for k, v in value.items()}
    if type(value) in (list, tuple):
        return type(value)(_紧凑副本(v) for v in value)
    return value


def _摘要(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _原子写(path, value, *, json_data=False):
    path = _安全路径(path)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if json_data:
                stream.write(value)
            else:
                torch.save(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        _安全路径(path)
        os.replace(name, path)
    finally:
        try:
            if os.path.exists(name):
                os.unlink(name)
        except OSError:
            # 删不掉只会在目录里留一个永不命中的 .part；在这里抛会顶掉本轮真正的写入/取消异常。
            pass


def _读取数据(path, record):
    data = None
    try:
        with _安全路径(path).open("rb") as stream:
            if os.fstat(stream.fileno()).st_size != record["size"] or _摘要(stream) != record["sha256"]:
                raise ValueError("交接文件大小或摘要不符")
            stream.seek(0)
            try:
                data = torch.load(stream, map_location="cpu", weights_only=True)
            except (MemoryError, torch.OutOfMemoryError, OSError):
                raise
            except Exception as exc:
                interrupt = getattr(sys.modules.get("comfy.model_management"), "InterruptProcessingException", ())
                if isinstance(exc, interrupt):
                    raise
                raise ValueError("交接文件反序列化失败，源文件已保留") from exc
            _容器(data)
            if _描述(data) != record["data"]:
                raise ValueError("交接 Tensor 或元信息不符")
            stream.seek(0)
            if _摘要(stream) != record["sha256"]:
                raise ValueError("交接文件在读取时发生变化")
            return data
    except OSError as exc:
        raise ValueError(f"交接文件读取失败：{exc}") from exc
    finally:
        data = None


def _写数据(directory, relative, value):
    stored = None
    try:
        stored = _紧凑副本(value)
        path = _安全路径(directory / relative)
        _原子写(path, stored)
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if not 0 < size <= _最大文件字节:
                raise ValueError("交接文件超过大小限制")
            record = {"path": relative, "size": size, "sha256": _摘要(stream), "data": _描述(stored)}
        stored = None
        _读取数据(path, record)
        return record
    finally:
        stored = None


def 保存初采交接(package, *, 检查取消=None):
    校验初采产物(package)
    if len(package["segments"]) > _最大段数:
        raise ValueError("交接段数超过限制")
    root = _安全路径(_交接根())
    metadata = _描述(package)
    estimated = _数据字节(package) + len(_JSON(metadata)) + (len(package["segments"]) + 2) * 65536
    if len(_JSON(metadata)) > _最大清单字节:
        raise ValueError("交接清单超过大小限制")
    if any(_数据字节(s) > _最大文件字节 for s in package["segments"]) or _数据字节(package["audio"]) > _最大文件字节:
        raise ValueError("交接文件超过大小限制")
    existing = root
    while not existing.exists():
        existing = existing.parent
    半成品 = None
    try:
        if shutil.disk_usage(existing)[2] < estimated:
            raise ValueError("交接磁盘空间不足")
        if 检查取消 is not None:
            检查取消()
        artifact = str(uuid.uuid4())
        directory = _安全路径(root / artifact)
        root.mkdir(parents=True, exist_ok=True)
        directory.mkdir()
        半成品 = directory
        _安全路径(directory / "segments").mkdir()
        manifest = {"type": "LVP_HANDOFF", "version": 1, "artifact_id": artifact,
                    "package": {k: v for k, v in metadata.items() if k not in ("segments", "audio")},
                    "segments": [], "audio": None}
        for i, segment in enumerate(package["segments"]):
            if 检查取消 is not None:
                检查取消()
            manifest["segments"].append(_写数据(directory, f"segments/{i:06d}.pt", segment))
        if package["audio"] is not None:
            if 检查取消 is not None:
                检查取消()
            manifest["audio"] = _写数据(directory, "audio.pt", package["audio"])
        content = _JSON(manifest)
        if len(content) > _最大清单字节:
            raise ValueError("交接清单超过大小限制")
        if 检查取消 is not None:
            检查取消()
        _原子写(directory / "manifest.json", content, json_data=True)
        ref = {"type": "LVP_FIRST_PASS_DISK", "version": 1, "artifact_id": artifact,
               "manifest_sha256": hashlib.sha256(content).hexdigest(),
               **{k: package[k] for k in ("source_node_id", "source_run_id", "frame_count", "output_fps")}}
        校验磁盘初采引用(ref)
        with _登记锁:
            _已发布[artifact] = copy.deepcopy(ref)
        return ref
    except OSError as exc:
        _提示半成品(半成品)
        raise ValueError(f"交接文件写入失败：{exc}") from exc
    except BaseException:
        _提示半成品(半成品)
        raise


def _校验记录(record, relative):
    if (type(record) is not dict or set(record) != {"path", "size", "sha256", "data"}
            or record["path"] != relative or type(record["size"]) is not int
            or not 0 < record["size"] <= _最大文件字节 or type(record["sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None or type(record["data"]) is not dict):
        raise ValueError("交接文件记录不合法")


def 读交接清单(ref):
    校验磁盘初采引用(ref)
    with _登记锁:
        if _已发布.get(ref["artifact_id"]) != ref:
            raise ValueError("交接产物未登记或引用与登记不符")
    path = _安全路径(_交接根() / ref["artifact_id"] / "manifest.json")
    try:
        with path.open("rb") as stream:
            content = stream.read(_最大清单字节 + 1)
        if len(content) > _最大清单字节 or hashlib.sha256(content).hexdigest() != ref["manifest_sha256"]:
            raise ValueError("交接清单大小或摘要不符")
        manifest = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"交接清单读取失败：{exc}") from exc
    if (type(manifest) is not dict or set(manifest) != {"type", "version", "artifact_id", "package", "segments", "audio"}
            or manifest["type"] != "LVP_HANDOFF" or type(manifest["version"]) is not int or manifest["version"] != 1
            or manifest["artifact_id"] != ref["artifact_id"] or type(manifest["package"]) is not dict
            or any(manifest["package"].get(k) != ref[k] for k in ("source_node_id", "source_run_id", "frame_count", "output_fps"))
            or type(manifest["segments"]) is not list or not 0 < len(manifest["segments"]) <= _最大段数):
        raise ValueError("交接清单合同不符")
    for i, record in enumerate(manifest["segments"]):
        _校验记录(record, f"segments/{i:06d}.pt")
    if manifest["audio"] is not None:
        _校验记录(manifest["audio"], "audio.pt")
    return manifest


def 读源段(ref, ordinal):
    manifest = 读交接清单(ref)
    if type(ordinal) is not int or not 0 <= ordinal < len(manifest["segments"]):
        raise ValueError("交接段序号越界")
    record = manifest["segments"][ordinal]
    return _读取数据(_交接根() / ref["artifact_id"] / record["path"], record)


def 读原音轨(ref):
    record = 读交接清单(ref)["audio"]
    if record is None:
        return None
    return _读取数据(_交接根() / ref["artifact_id"] / record["path"], record)


def _提示半成品(半成品):
    # 半截目录没有 manifest.json、也不在 _已发布 里，任何清理入口都找不到它；但「未登记」不等于「可删」——
    # 重启后上一轮的完整产物同样未登记。所以按既定的「失败保留现场」只把位置报进日志供人工处置，绝不自动删。
    # UUID 撞车时 mkdir 先抛，半成品 仍是 None，不会把别人的既有产物报成可删。
    if 半成品 is None:
        return
    import logging
    logging.getLogger("长视频规划师.初采产物存储").warning(
        "交接未发布，半成品目录保留在 %s（人工确认后可整目录删除）", 半成品)
