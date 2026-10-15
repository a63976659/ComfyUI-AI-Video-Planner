# -*- coding: utf-8 -*-
"""含凭据的配置存放在操作系统用户目录。"""
import contextlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path

_锁 = threading.RLock()


def 用户配置目录():
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "ComfyUI-AI-Video-Planner"


def 本地配置路径(文件名):
    return 用户配置目录() / 文件名


@contextlib.contextmanager
def 配置写入锁(路径):
    path = Path(路径)
    with _锁:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(path) + ".lock", "a+b") as lock:
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b"\0")
                lock.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("模型配置正在保存，请稍后重试") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def 写本地配置(路径, 内容):
    path = Path(路径)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(内容, f, ensure_ascii=False, allow_nan=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
