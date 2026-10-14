# -*- coding: utf-8 -*-
"""对齐辅助（画布/帧数/秒↔帧）+ AV 音视频解码封装。

严格复刻 comfy_extras/nodes_minimax_h3.py 的常量（L26-30）与 adapt_canvas
（L50-61）；align_frame_count（L34-37）为本地增强版（多 int() 强转、
显式 min=5，语义与官方 temporal_shape L45 一致）。官方其余辅助函数
（REF_IMAGE_SHORT_EDGE/AUDIO_LATENT_FPS/video_latent_t/temporal_shape）
有意不复刻——Task 8/9 直接调官方节点，不需要自己造 latent。

职责边界：本模块无"采样"，采样在 Task 9 的 KSampler 链路（`执行核心.py`）。
FPS=24 是官方时间基座（模型训练帧率），唯一消费者是秒转帧数；用户 widget
的「帧率」只作输出封装元数据，不参与帧数换算。
"""
import math

CANVAS_MULTIPLE = 32
BASE_SHORT_EDGE = 768
MAX_PIXELS = 768 * 1344
FPS = 24


def 对齐帧数(n: int) -> int:
    """对齐到 17k+5 网格（官方 nodes_minimax_h3.py:34-37 align_frame_count）；
    本地先钳 max(5, int(n))——官方 min=5 语义在 temporal_shape L45 中由外层
    max(5, length) 提供，此处内联以匹配调用组合。int() 强转为本地增强：
    官方版本对浮点 n 会 while 死循环，本模块不会。最多上抬 16 帧
    （约 0.67s@24fps），跨度由 test_对齐帧数_跨度上界 锁定。
    """
    n = max(5, int(n))
    while n % 17 != 5:
        n += 1
    return n


def 对齐画布(width: int, height: int) -> "tuple[int, int]":
    """官方 adapt_canvas（逐行等同 comfy_extras/nodes_minimax_h3.py:50-61）：短边 768、
    面积上限 768*1344、每轴 32 倍数。**平局按官方 round() 取偶，勿改成半进位。**
    正数守卫为本地增补（官方靠节点 schema min=32 兜底）：非正数一律 ValueError。
    """
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError(f"画布宽高必须为正数，收到 宽={width} 高={height}")
    ratio = width / height
    if ratio >= 1.0:
        nom_w, nom_h = BASE_SHORT_EDGE * ratio, BASE_SHORT_EDGE
    else:
        nom_w, nom_h = BASE_SHORT_EDGE, BASE_SHORT_EDGE / ratio
    if nom_w * nom_h > MAX_PIXELS:
        s = math.sqrt(MAX_PIXELS / (nom_w * nom_h))
        nom_w, nom_h = nom_w * s, nom_h * s
    return (max(CANVAS_MULTIPLE, round(nom_w / CANVAS_MULTIPLE) * CANVAS_MULTIPLE),
            max(CANVAS_MULTIPLE, round(nom_h / CANVAS_MULTIPLE) * CANVAS_MULTIPLE))


def 秒转帧数(秒: float) -> int:
    """秒 → 帧数（已对齐 17k+5 网格）。**官方时间基座恒为 FPS=24**，与用户
    「帧率」widget 解耦——后者仅影响输出容器/封装的 fps 标签，不影响模型内部
    帧数换算。Task 9 只能经本函数拿帧数，禁止再散落魔法 24。
    """
    return 对齐帧数(round(秒 * FPS))


def 解码音视频(av_latent, video_vae, audio_vae) -> tuple:
    """同一个 AV 嵌套 latent 分别喂 VAEDecode(取视频流 unbind[0]) 与
    VAEDecodeAudio(取音频流 unbind[-1])；返回 (images, audio)。GPU 集成验证。"""
    from .官方管线适配 import 调用节点
    images = 调用节点("VAEDecode", vae=video_vae, samples=av_latent)[0]
    audio = None
    if audio_vae is not None:
        audio = 调用节点("VAEDecodeAudio", vae=audio_vae, samples=av_latent)[0]
    return images, audio
