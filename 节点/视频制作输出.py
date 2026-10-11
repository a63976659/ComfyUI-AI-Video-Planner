# -*- coding: utf-8 -*-
"""将批量 IMAGE 帧与可选 AUDIO 编成媒体库 MP4，并提供可预览的视频输出。"""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
import time
import uuid
import wave

from comfy_api.latest import io, InputImpl, ui

try:
    from ..制作.工具 import 定位ffmpeg, 安全媒体路径
except ImportError:
    from 制作.工具 import 定位ffmpeg, 安全媒体路径

_最大帧数 = 432000
_最大像素 = 16_777_216
_音频块样本 = 262_144


def _校验图像(images, fps):
    import torch
    if not isinstance(images, torch.Tensor) or images.ndim != 4:
        raise ValueError("图像输入须为 [帧数, 高, 宽, 通道] Tensor")
    frames, height, width, channels = map(int, images.shape)
    if not 1 <= frames <= _最大帧数:
        raise ValueError(f"帧数须在 1 至 {_最大帧数} 之间")
    if height <= 0 or width <= 0 or width * height > _最大像素:
        raise ValueError(f"单帧像素不得超过 {_最大像素}")
    if width % 2 or height % 2:
        raise ValueError("H.264 MP4 要求偶数宽高，请先调整画布")
    if channels not in (3, 4):
        raise ValueError("图像通道数须为 RGB 或 RGBA")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("帧率须在 1 至 120 之间")
    if frames / float(fps) > 3600:
        raise ValueError("视频时长不得超过 3600 秒")
    return frames, height, width, channels


def _音频校验(audio, video_seconds):
    if audio is None:
        return None
    import torch
    if not isinstance(audio, dict) or not isinstance(audio.get("waveform"), torch.Tensor):
        raise ValueError("音频须为 ComfyUI AUDIO 对象")
    waveform, rate = audio["waveform"], audio.get("sample_rate")
    if waveform.ndim != 3 or waveform.shape[0] != 1 or waveform.shape[1] not in (1, 2) or waveform.shape[-1] <= 0:
        raise ValueError("音频 waveform 须为单批次、单/双声道 AUDIO 张量")
    if isinstance(rate, bool) or not isinstance(rate, int) or not 8000 <= rate <= 192000:
        raise ValueError("音频采样率须为 8000 至 192000 Hz 的整数")
    duration = waveform.shape[-1] / rate
    if duration > video_seconds + max(0.05, 1024 / rate):
        raise ValueError("音频长于视频；请在时间轴裁切音轨后再合成")
    return waveform, rate


def _前缀(name):
    if not isinstance(name, str):
        raise ValueError("文件名前缀须为文本")
    name = name.strip()
    if not name or len(name) > 80 or name in (".", ".."):
        raise ValueError("文件名前缀须为 1 至 80 个字符")
    if any(ord(c) < 32 or c in '<>:\"|?*/\\' for c in name) or name.rstrip(" .") != name:
        raise ValueError("文件名前缀不能包含路径或 Windows 非法字符")
    if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError("文件名前缀不能使用 Windows 保留设备名")
    return name


def _音频写wav(audio, path):
    if audio is None:
        return
    import torch
    waveform, rate = audio
    channels, samples = waveform.shape[1], waveform.shape[-1]
    with wave.open(path, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        for start in range(0, samples, _音频块样本):
            _检查中断()
            end = min(samples, start + _音频块样本)
            chunk = waveform[0, :, start:end].detach().to(device="cpu", dtype=torch.float32)
            if not bool(torch.isfinite(chunk).all()):
                raise ValueError("音频包含 NaN 或无穷值")
            pcm = (torch.clamp(chunk, -1, 1) * 32767).to(torch.int16).transpose(0, 1).contiguous()
            output.writeframesraw(pcm.numpy().tobytes())


def _帧rgb(frame, channels):
    import torch
    frame = frame[..., :3].detach().to(device="cpu", dtype=torch.float32)
    if not bool(torch.isfinite(frame).all()):
        raise ValueError("图像帧包含 NaN 或无穷值")
    return (torch.clamp(frame, 0, 1) * 255).to(torch.uint8).contiguous().numpy().tobytes()


def _检查中断():
    try:
        import comfy.model_management
        comfy.model_management.throw_exception_if_processing_interrupted()
    except ImportError:
        return


def _唯一目标(root, prefix):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for _ in range(10):
        name = f"{prefix}_{stamp}_{uuid.uuid4().hex[:6]}.mp4"
        path = 安全媒体路径(root, name)
        if not os.path.lexists(path):
            return name, path
    raise RuntimeError("无法为成片分配唯一文件名")


def _编码(images, audio, fps, media_root, prefix):
    frames, height, width, channels = _校验图像(images, fps)
    validated_audio = _音频校验(audio, frames / fps)
    os.makedirs(media_root, exist_ok=True)
    # 根路径及目标文件名均经过路径守卫；媒体库只接受直接子项。
    name, target = _唯一目标(media_root, prefix)
    fd, video_part = tempfile.mkstemp(prefix=".lvp-video-", suffix=".mp4.part", dir=media_root)
    os.close(fd)
    audio_part = None
    process = None
    try:
        audio_args = []
        if validated_audio is not None:
            fd, audio_part = tempfile.mkstemp(prefix=".lvp-audio-", suffix=".wav.part", dir=media_root)
            os.close(fd)
            _音频写wav(validated_audio, audio_part)
            audio_args = ["-f", "wav", "-i", audio_part]
        command = [定位ffmpeg(), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-video_size", f"{width}x{height}",
                   "-framerate", f"{float(fps):.10g}", "-i", "pipe:0", *audio_args,
                   "-map", "0:v:0"]
        if validated_audio is not None:
            command += ["-map", "1:a:0", "-af", "apad"]
        command += ["-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-pix_fmt", "yuv420p"]
        if validated_audio is not None:
            command += ["-c:a", "aac", "-b:a", "192k", "-ar", str(validated_audio[1])]
        command += ["-t", f"{frames / float(fps):.10g}", "-movflags", "+faststart", "-f", "mp4", video_part]
        with tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr)
            try:
                for index in range(frames):
                    _检查中断()
                    if process.poll() is not None:
                        raise RuntimeError("ffmpeg 提前退出，未能完成视频编码")
                    frame = images[index]
                    process.stdin.write(_帧rgb(frame, channels))
                process.stdin.close()
                deadline = time.monotonic() + 1800
                while True:
                    _检查中断()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        process.kill()
                        process.wait()
                        raise TimeoutError("MP4 编码超过 30 分钟，已终止")
                    try:
                        code = process.wait(timeout=min(0.1, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                raise
            if code != 0:
                stderr.seek(0)
                detail = stderr.read().decode("utf-8", "replace")[-3000:]
                raise RuntimeError(f"ffmpeg 编码失败（返回码 {code}）：{detail}")
        if not os.path.isfile(video_part) or os.path.getsize(video_part) < 256:
            raise RuntimeError("ffmpeg 未生成有效 MP4 文件")
        _检查中断()
        os.replace(video_part, target)
        return name, target
    finally:
        for path in (video_part, audio_part):
            if path:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass


class 视频制作输出(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="视频制作输出",
            display_name="视频制作输出",
            category="长视频规划师/制作",
            description="将 H3 或其他节点输出的 IMAGE 帧与可选 AUDIO 音轨编码为 MP4，存入制作媒体库。",
            inputs=[
                io.Image.Input("图像", tooltip="批量视频帧 [T,H,W,C]，可直接连接长视频规划师。"),
                io.Audio.Input("音频", optional=True, tooltip="可选 AUDIO 音轨；单/双声道，过长音轨会被拒绝。"),
                io.Float.Input("帧率", default=24.0, min=1.0, max=120.0, step=1.0),
                io.String.Input("文件名前缀", default="视频制作"),
            ],
            outputs=[
                io.String.Output("媒体名", tooltip="媒体库中的 MP4 文件名，可供制作时间线引用。"),
                io.Video.Output("视频", tooltip="可直接预览，也可连接到其他 ComfyUI 视频节点。"),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, 图像, 帧率, 文件名前缀, 音频=None) -> io.NodeOutput:
        try:
            from ..后端路由.媒体路由 import 媒体根
        except ImportError:
            from 后端路由.媒体路由 import 媒体根
        name, path = _编码(图像, 音频, 帧率, 媒体根(), _前缀(文件名前缀))
        video = InputImpl.VideoFromFile(path)
        preview = ui.PreviewVideo([ui.SavedResult(name, "长视频规划师_媒体", io.FolderType.input)])
        return io.NodeOutput(name, video, ui=preview)

