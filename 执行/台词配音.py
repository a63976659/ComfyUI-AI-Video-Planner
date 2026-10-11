# -*- coding: utf-8 -*-
"""可选配音原声输出：只替换裁前缀后的输出音轨，不改采样或latent锚定。"""
import math
import os


def 校验配音引用(refs, 段长=None):
    配 = (refs or {}).get("台词配音")
    if 配 is None:
        return None
    if not isinstance(配, dict):
        raise ValueError("台词配音必须是包含文件名、起、末的对象")
    名 = 配.get("文件名")
    if not isinstance(名, str) or not 名 or 名 in (".", "..") or "/" in 名 or "\\" in 名 or os.path.basename(名) != 名:
        raise ValueError("台词配音必须是媒体池文件名")
    起, 末 = 配.get("起"), 配.get("末")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (起, 末)):
        raise ValueError("台词配音起止时间必须是有效秒数")
    if not 0 <= 起 < 末 <= 3600:
        raise ValueError("台词配音起止时间须在0至3600秒内且末大于起")
    if 段长 is not None and 末 - 起 > 段长 + 1e-6:
        raise ValueError("镜头时长无法容纳指定配音，请重新估时；不会截断原声")
    return 配


def 读取台词配音(refs, 段长, 媒体根, 加载音频):
    配 = 校验配音引用(refs, 段长)
    if 配 is None:
        return None
    路径 = os.path.join(媒体根, 配["文件名"])
    if not os.path.isfile(路径):
        raise ValueError(f"台词配音不存在：{配['文件名']}，请重新上传")
    全音 = 加载音频(路径)
    if 全音 is None or 全音["waveform"].shape[-1] / 全音["sample_rate"] + 0.05 < 配["末"]:
        raise ValueError(f"台词配音时间戳超过文件实际长度：{配['文件名']}")
    sr = 全音["sample_rate"]
    起点, 末点 = int(round(配["起"] * sr)), int(round(配["末"] * sr))
    波 = 全音["waveform"][..., 起点:末点]
    if 波.shape[-1] == 0:
        raise ValueError(f"台词配音切片为空：{配['文件名']}")
    return {**全音, "waveform": 波}


def 统一配音音轨(音频列表, 重采样=None):
    """启用原声时统一采样率与声道，再交既有累计帧边界拼接。"""
    有效 = [a for a in 音频列表 if a.get("waveform") is not None]
    if not 有效:
        return 音频列表
    for a in 有效:
        w, 率 = a["waveform"], a.get("sample_rate")
        if w.ndim != 3 or w.shape[0] != 1 or w.shape[1] not in (1, 2):
            raise ValueError("配音音轨须为单批次单声道或双声道")
        if isinstance(率, bool) or not isinstance(率, (int, float)) or not math.isfinite(率) or 率 <= 0:
            raise ValueError("配音采样率须为有效正数")
    sr = max(a["sample_rate"] for a in 有效)
    声道 = max(a["waveform"].shape[-2] for a in 有效)
    if 声道 not in (1, 2):
        raise ValueError("配音原声仅支持单声道或双声道，请先转换音频")
    结果 = []
    for a in 音频列表:
        if a.get("waveform") is None:
            结果.append(a)
            continue
        w = a["waveform"].cpu()
        if w.ndim != 3 or w.shape[0] != 1 or w.shape[1] not in (1, 2):
            raise ValueError("配音音轨须为单批次单声道或双声道")
        if a["sample_rate"] != sr:
            if 重采样 is None:
                from comfy.audio import resample
                重采样 = resample
            w = 重采样(w, a["sample_rate"], sr)
        if w.shape[1] == 1 and 声道 == 2:
            w = w.repeat(1, 2, 1)
        结果.append({**a, "waveform": w, "sample_rate": sr})
    return 结果
