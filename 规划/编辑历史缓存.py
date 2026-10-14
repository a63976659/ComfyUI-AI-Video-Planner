"""撤销历史的本机文件缓存，不进入工作流与计划数据。"""
import json
import os
import re
import tempfile
import threading
from pathlib import Path

缓存目录 = Path(__file__).resolve().parents[1] / "缓存" / "编辑历史"
_锁 = threading.Lock()


def _路径(缓存id):
    if not isinstance(缓存id, str) or not re.fullmatch(r"[a-f0-9]{32}", 缓存id):
        raise ValueError("编辑历史缓存编号无效")
    return 缓存目录 / (缓存id + ".json")


def _规范(data):
    if not isinstance(data, dict) or not isinstance(data.get("当前草稿"), str):
        raise ValueError("编辑历史缓存内容无效")
    result = {"当前草稿": data["当前草稿"]}
    remaining = 20
    for key in ("草稿编辑历史", "草稿前进历史"):
        entries = data.get(key, [])
        if not isinstance(entries, list):
            raise ValueError("编辑历史须为列表")
        if any(not isinstance(x, dict) or not isinstance(x.get("草稿"), dict)
               or not isinstance(x["草稿"].get("segments"), list) for x in entries):
            raise ValueError("编辑历史记录无效")
        kept = entries[-remaining:] if remaining else []
        result[key] = kept
        remaining -= len(kept)
    return result


def 读取编辑历史(缓存id):
    path = _路径(缓存id)
    with _锁:
        if not path.is_file():
            return None
        try:
            return _规范(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, UnicodeError):
            return None


def 保存编辑历史(缓存id, data):
    path = _路径(缓存id)
    normalized = _规范(data)
    with _锁:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=缓存id + "-", suffix=".part", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(normalized, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
    return sum(len(normalized[key]) for key in ("草稿编辑历史", "草稿前进历史"))
