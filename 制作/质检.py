"""文件式成片的可复核量测；不将信号量测冒充身份、口型或语义判断。"""
from __future__ import annotations

import math
import os
import re
from fractions import Fraction

from .工具 import 定位ffmpeg, 媒体探测, 可取消子进程运行


_数 = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_静态来源 = {"图片", "标题", "image", "title"}


def _有限数(value, default=None):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _帧率(value):
    try:
        result = float(Fraction(str(value)))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _取消检查(cancel):
    checker = getattr(cancel, "is_set", None)
    cancelled = cancel() if callable(cancel) else checker() if callable(checker) else bool(cancel)
    if cancelled:
        raise InterruptedError("成片质检已取消")


def 解析量测日志(text, duration):
    """读取 FFmpeg 的 blackdetect/freezedetect/astats 日志，闭合 EOF 静止区间。"""
    duration = max(0.0, _有限数(duration, 0.0))
    intervals = {"黑帧": [], "冻结": []}
    starts = {"black": None, "freeze": None}
    tokens = re.compile(rf"\b(black|freeze)_(start|end):\s*({_数})")
    for match in tokens.finditer(text):
        family, edge, raw = match.groups()
        point = min(duration, max(0.0, float(raw)))
        if edge == "start":
            starts[family] = point
        elif starts[family] is not None:
            start = starts[family]
            if point > start:
                intervals["黑帧" if family == "black" else "冻结"].append((start, point))
            starts[family] = None
    for family, start in starts.items():
        if start is not None and duration > start:
            intervals["黑帧" if family == "black" else "冻结"].append((start, duration))

    peaks = re.findall(r"Peak level dB:\s*([-+\w.]+)", text)
    finite = [_有限数(v) for v in peaks]
    finite = [v for v in finite if v is not None]
    silent = bool(peaks) and not finite and all(v.lower() == "-inf" for v in peaks)
    return {**intervals, "音峰值dB": max(finite) if finite else None,
            "音频静音": silent, "音频量测完成": bool(finite) or silent}


def _镜头区间(project):
    result = []
    for shot in project.get("镜头", []):
        if not isinstance(shot, dict):
            continue
        start = _有限数(shot.get("开始"), 0.0)
        end = _有限数(shot.get("结束"))
        if end is None:
            end = start + max(0.0, _有限数(shot.get("时长"), 0.0))
        if end > start:
            result.append((start, end, str(shot.get("id", shot.get("segment_id", ""))), shot))
    return sorted(result, key=lambda item: item[0])


def _区间问题(kind, start, end, shots, description, exempt_static=False):
    """将真实成片绝对时间切成逐镜头问题，不返回相对源素材的时间。"""
    problems = []
    covered = []
    for left, right, shot_id, shot in shots:
        overlap_start, overlap_end = max(start, left), min(end, right)
        if overlap_end <= overlap_start:
            continue
        covered.append((overlap_start, overlap_end))
        static = shot.get("来源") in _静态来源 or shot.get("允许静止") is True
        if exempt_static and static:
            continue
        problems.append({"类型": kind, "开始": round(overlap_start, 6), "结束": round(overlap_end, 6),
                         "镜头": shot_id, "说明": description})
    # 成片超出计划或镜头间有空洞，也必须报告该区间的缺陷。
    cursor = start
    for left, right in sorted(covered):
        if left > cursor:
            problems.append({"类型": kind, "开始": round(cursor, 6), "结束": round(left, 6),
                             "镜头": "", "说明": description})
        cursor = max(cursor, right)
    if cursor < end:
        problems.append({"类型": kind, "开始": round(cursor, 6), "结束": round(end, 6),
                         "镜头": "", "说明": description})
    return problems


def 检查成片(path, 工程, cancel=None):
    """返回基础质检报告。取消/探测失败/滤镜失败向上抛错，绝不返回虚假“通过”。"""
    if not isinstance(工程, dict):
        raise ValueError("质检工程必须是对象")
    _取消检查(cancel)
    probe = 媒体探测(path)
    _取消检查(cancel)
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise ValueError("成片没有视频轨，无法执行视频质检")
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    container_duration = _有限数(probe.get("format", {}).get("duration"))
    duration = _有限数(video.get("duration"), container_duration)
    if duration is None or duration <= 0:
        raise ValueError("无法取得成片的视频时长")
    fps = _帧率(video.get("avg_frame_rate")) or _帧率(video.get("r_frame_rate"))
    metrics = {"时长": duration, "容器时长": container_duration, "宽": video.get("width"),
               "高": video.get("height"), "帧率": fps, "音轨数": len(audio),
               "音频时长": [_有限数(s.get("duration"), container_duration) for s in audio]}
    shots = _镜头区间(工程)
    problems = []
    expected = _有限数(工程.get("时长"))
    canvas = 工程.get("画布", {})
    if not isinstance(canvas, dict):
        canvas = {}
    expected_fps = _帧率(canvas.get("帧率", 工程.get("帧率")))
    frame_tolerance = max(0.05, 1.5 / (expected_fps or fps or 24))

    def general(kind, description):
        problems.append({"类型": kind, "开始": 0.0, "结束": round(duration, 6), "镜头": "", "说明": description})

    if expected is not None and abs(duration - expected) > frame_tolerance:
        general("时长偏差", f"视频 {duration:.3f} 秒，计划 {expected:.3f} 秒；允许约 {frame_tolerance:.3f} 秒帧量化误差。")
    if expected_fps is not None and (fps is None or abs(fps - expected_fps) > 0.01):
        general("帧率偏差", f"成片帧率 {fps}，计划帧率 {expected_fps}。")
    for key in ("宽", "高"):
        wanted = canvas.get(key, 工程.get(key))
        if wanted is not None and metrics[key] != wanted:
            general("尺寸偏差", f"成片{key} {metrics[key]}，计划{key} {wanted}。")
    wants_audio = bool(工程.get("音轨")) or any(s.get("声音") == "原声" for *_, s in shots)
    if not audio and wants_audio:
        general("缺少音轨", "工程要求声音，但成片没有音轨。")
    if audio:
        first_duration = metrics["音频时长"][0]
        if first_duration is not None and abs(first_duration - duration) > max(0.15, frame_tolerance):
            general("音画时长偏差", f"首条音轨 {first_duration:.3f} 秒，视频 {duration:.3f} 秒。")

    video_map = f"0:{video['index']}" if isinstance(video.get("index"), int) else "0:v:0"
    command = [定位ffmpeg(), "-hide_banner", "-nostdin", "-nostats", "-v", "info", "-i", os.fspath(path),
               "-map", video_map, "-vf", "blackdetect=d=0.2:pix_th=0.10:pic_th=0.98,freezedetect=n=-50dB:d=0.75"]
    if audio:
        command += ["-map", "0:a:0", "-af", "astats=metadata=0:reset=0"]
    else:
        command += ["-an"]
    command += ["-f", "null", "-"]
    completed = 可取消子进程运行(command, cancel=cancel, timeout=max(120, min(7200, duration * 10)))
    _取消检查(cancel)
    log = completed.stderr.decode("utf-8", "replace") if isinstance(completed.stderr, bytes) else str(completed.stderr or "")
    if completed.returncode:
        raise ValueError(f"FFmpeg 成片量测失败：{log[-2000:]}")
    measurement = 解析量测日志(log, duration)
    metrics.update({k: measurement[k] for k in ("音峰值dB", "音频静音", "音频量测完成")})
    metrics["黑帧区间数"] = len(measurement["黑帧"])
    metrics["冻结候选区间数"] = len(measurement["冻结"])
    for left, right in measurement["黑帧"]:
        problems.extend(_区间问题("黑帧", left, right, shots, "超过 98% 画面像素持续接近黑色；请确认是否为预期黑场。"))
    for left, right in measurement["冻结"]:
        problems.extend(_区间问题("疑似冻结", left, right, shots,
                                  "画面变化低于阈值且持续至少 0.75 秒；请检查卡帧，也可能是有意静止镜头。", True))
    peak = measurement["音峰值dB"]
    if audio and not measurement["音频量测完成"]:
        general("音频量测缺失", "FFmpeg 未返回音峰值，不能确认音频峰值正常。")
    elif peak is not None and peak >= -0.1:
        general("音量峰值", f"音峰值 {peak:.2f} dBFS 接近满幅，存在削波风险；该指标不能证明实际爆音。")
    elif wants_audio and measurement["音频静音"]:
        general("音轨静音", "工程要求声音，但首条输出音轨量测为完全静音。")

    # 仅报告实际异常跨过切点的情况；这不是色光连续性、动作连续性或听觉接缝检测。
    for previous, following in zip(shots, shots[1:]):
        boundary = following[0]
        if abs(previous[1] - boundary) > frame_tolerance:
            continue
        kinds = [kind for kind in ("黑帧", "冻结") if any(left < boundary < right for left, right in measurement[kind])]
        if "冻结" in kinds and previous[3].get("来源") in _静态来源 and following[3].get("来源") in _静态来源:
            kinds.remove("冻结")
        if kinds:
            problems.append({"类型": "接缝疑点", "开始": round(max(0, boundary - frame_tolerance), 6),
                             "结束": round(min(duration, boundary + frame_tolerance), 6),
                             "镜头": f"{previous[2]} → {following[2]}",
                             "说明": f"{'、'.join(kinds)}候选区间跨过镜头切点；请人工检查，未验证动作、色光或声音连续性。"})
    return {"状态": "需检查" if problems else "通过", "指标": metrics,
            "问题": sorted(problems, key=lambda p: (p["开始"], p["结束"], p["类型"])),
            "未检测": ["身份漂移", "口型", "语义保真", "对白漏字", "色光与动作接缝", "音频接缝"]}
