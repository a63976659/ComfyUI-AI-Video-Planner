"""生成视频的片段记录及库内视频清理。"""
import hashlib
import re
import threading
from pathlib import Path

from .工具 import 安全媒体路径
try:
    from ..规划.项目存储 import 读JSON, 写JSON, _是链接
except ImportError:
    from 规划.项目存储 import 读JSON, 写JSON, _是链接


_锁 = threading.RLock()
_旧文件 = re.compile(r"(?:生成结果_\d{8}_\d{6}_[a-f0-9]{6}\.mp4|结果_[a-f0-9]{24}\.(?:mp4|mov|mkv|webm|avi))", re.I)


class 片段记录:
    def __init__(self, media_root):
        self.root = Path(media_root)

    def 目录(self):
        path = Path(安全媒体路径(self.root, ".视频片段记录"))
        if path.exists() and _是链接(path):
            raise ValueError("视频片段记录目录不能是链接")
        return path

    def 媒体(self, name):
        path = Path(安全媒体路径(self.root, name))
        if _是链接(path) or not path.is_file():
            raise ValueError("视频片段文件不存在或不安全")
        stat = path.stat()
        key = hashlib.sha256(f"{name}\0{stat.st_mtime_ns}\0{stat.st_size}".encode()).hexdigest()
        return {"id": key, "文件名": name, "名称": path.stem, "大小": stat.st_size,
                "更新时间": stat.st_mtime, "修改时间": stat.st_mtime_ns, "运行中": False}

    def 保存(self, bundles):
        with _锁:
            for bundle in bundles:
                item = self.媒体(bundle["文件名"])
                path = self.目录() / (item["id"] + ".json")
                if path.exists():
                    previous = 读JSON(path)
                    if previous.get("结果id") == bundle.get("结果id"):
                        continue
                clips = bundle.get("片段") or []
                names = [str(s.get("名称") or "") for s in clips if isinstance(s, dict)]
                title = next((name for name in names if name), item["名称"])
                item.update(名称=title, 片段数=max(1, len(clips)), 时长=bundle.get("时长", 0),
                            结果id=bundle.get("结果id"), 本轮工作流=bundle.get("本轮工作流"))
                写JSON(path, item)

    def 列表(self):
        with _锁:
            directory = self.目录()
            names = {p.name for p in self.root.iterdir() if _旧文件.fullmatch(p.name)} if self.root.is_dir() else set()
            records = {}
            for path in directory.glob("*.json"):
                if not re.fullmatch(r"[a-f0-9]{64}", path.stem) or _是链接(path):
                    continue
                try:
                    record = 读JSON(path)
                    name = record["文件名"]
                    current = self.媒体(name)
                    if current["id"] != path.stem or record.get("id") != path.stem:
                        continue
                    names.add(name)
                    records[name] = record
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            result = []
            for name in names:
                try:
                    item = self.媒体(name)
                    record = records.get(name, {})
                    item.update({k: record[k] for k in ("名称", "片段数", "时长") if k in record})
                    path = directory / (item["id"] + ".json")
                    item["记录版本"] = [item["修改时间"], item["大小"], path.stat().st_mtime_ns if path.exists() else 0]
                    result.append(item)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            return sorted(result, key=lambda x: x["更新时间"], reverse=True)

    def 清理(self, entries):
        with _锁:
            items = {item["id"]: item for item in self.列表()}
            resolved = []
            directory = self.目录()
            for key, version in entries:
                item = items.get(key)
                if item is None or item["记录版本"] != version:
                    raise ValueError("视频片段记录已变化，请重新确认")
                resolved.append((Path(安全媒体路径(self.root, item["文件名"])), directory / (key + ".json")))
            for media, record in resolved:
                media.unlink()
                if record.exists():
                    record.unlink()
