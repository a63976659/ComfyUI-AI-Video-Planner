# -*- coding: utf-8 -*-
"""含凭据的配置存放在操作系统用户目录。"""
import json
import os
import tempfile
import threading
from pathlib import Path

_锁 = threading.RLock()


def 用户配置目录():
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "ComfyUI-AI-Video-Planner"


def 本地配置路径(文件名):
    target = 用户配置目录() / 文件名
    legacy = Path(__file__).with_name(文件名)
    with _锁:
        target.parent.mkdir(parents=True, exist_ok=True)
        if legacy.exists():
            raw = legacy.read_bytes()
            if not isinstance(json.loads(raw), dict):
                raise ValueError("旧模型配置须为JSON对象，请检查配置文件")
            if target.exists():
                if target.read_bytes() != raw:
                    raise ValueError(f"本地与插件目录同时存在不同的{文件名}，请先确定保留哪份配置")
            else:
                fd, temp = tempfile.mkstemp(dir=target.parent, prefix=文件名 + ".", suffix=".part")
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(raw)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(temp, target)
                finally:
                    if os.path.exists(temp):
                        os.remove(temp)
            if target.read_bytes() != raw:
                raise OSError("模型配置迁移校验失败，旧文件已保留")
            legacy.unlink()
    return target
