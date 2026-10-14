# -*- coding: utf-8 -*-
"""制作流程共用的本地媒体、进程与原子文件工具。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PureWindowsPath


_设备名 = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_FFMPEG = None
_FFPROBE = None


def _命令定位(名: str) -> str:
    命令 = shutil.which(名)
    if 命令:
        return 命令
    # imageio-ffmpeg 只提供 ffmpeg；同目录可能有 ffprobe，但不假设一定存在。
    if 名 == "ffmpeg":
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            raise RuntimeError("未找到 ffmpeg。请将 ffmpeg 加入 PATH，或安装 imageio-ffmpeg。") from exc
    ffmpeg = _命令定位("ffmpeg")
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if sibling.is_file():
        return str(sibling)
    raise RuntimeError("未找到 ffprobe。请安装包含 ffprobe 的 FFmpeg 并将其加入 PATH。")


def 定位ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = _命令定位("ffmpeg")
    return _FFMPEG


def 定位ffprobe() -> str:
    global _FFPROBE
    if _FFPROBE is None:
        _FFPROBE = _命令定位("ffprobe")
    return _FFPROBE


def 安全媒体路径(root, name) -> str:
    """解析媒体根下的单文件名；拒绝路径、设备名、链接和根目录外目标。"""
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise ValueError("媒体名必须是非空文件名")
    if any(ord(c) < 32 or c in '<>:\"|?*' for c in name) or "/" in name or "\\" in name:
        raise ValueError(f"媒体名不能包含路径或设备字符：{name!r}")
    win = PureWindowsPath(name)
    if win.drive or win.root or name.rstrip(" .") != name:
        raise ValueError("媒体名不能是绝对路径或以点/空格结尾")
    stem = name.split(".", 1)[0].upper()
    if stem in _设备名:
        raise ValueError(f"媒体名使用了 Windows 保留设备名：{name}")
    root_abs = os.path.abspath(os.fspath(root))
    root_real = os.path.realpath(root_abs)
    if os.path.normcase(root_abs) != os.path.normcase(root_real):
        raise ValueError("媒体根目录包含符号链接")
    candidate = os.path.join(root_abs, name)
    real = os.path.realpath(candidate)
    if os.path.normcase(candidate) != os.path.normcase(real):
        raise ValueError("媒体路径包含符号链接")
    try:
        if os.path.commonpath([os.path.normcase(root_real), os.path.normcase(real)]) != os.path.normcase(root_real):
            raise ValueError("媒体路径越出媒体根目录")
    except ValueError as exc:
        raise ValueError("媒体路径越出媒体根目录") from exc
    return candidate


def 文件摘要(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def 原子JSON写(path, value) -> None:
    """将 JSON 写入同目录唯一临时文件，再原子替换目标文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def _取消了(cancel) -> bool:
    if cancel is None:
        return False
    if callable(cancel):
        return bool(cancel())
    is_set = getattr(cancel, "is_set", None)
    return bool(is_set()) if callable(is_set) else bool(cancel)


def 可取消子进程运行(argv, cancel=None, timeout=900, cwd=None) -> subprocess.CompletedProcess:
    """运行参数数组形式的子进程；轮询取消信号，超时或取消时终止并回收子进程。"""
    if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(x, (str, os.PathLike)) for x in argv):
        raise ValueError("argv 必须是非空的参数数组")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout 必须是正数")
    start = time.monotonic()
    proc = subprocess.Popen([os.fspath(x) for x in argv], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while True:
        if _取消了(cancel):
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
            raise InterruptedError("子进程已取消")
        if time.monotonic() - start >= timeout:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr)
        try:
            # communicate 会并行排空 stdout/stderr，避免 FFmpeg 的统计日志填满管道后死锁。
            stdout, stderr = proc.communicate(timeout=0.1)
            return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def 媒体探测(path) -> dict:
    """使用 ffprobe 输出 JSON；非零退出码、空 JSON 和非法 JSON 均显式失败。"""
    path = os.fspath(path)
    result = 可取消子进程运行([
        定位ffprobe(), "-v", "error", "-show_format", "-show_streams", "-of", "json", path,
    ], timeout=120)
    if result.returncode:
        err = result.stderr.decode("utf-8", "replace")[-2000:]
        raise ValueError(f"ffprobe 探测失败：{err}")
    try:
        data = json.loads(result.stdout.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ffprobe 返回了无效 JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("streams", []), list):
        raise ValueError("ffprobe JSON 结构无效")
    return data

