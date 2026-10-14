"""提交前的真实媒体与工作流检查，不加载生成模型。"""
import os
from .工具 import 安全媒体路径, 定位ffmpeg, 定位ffprobe
from .合成 import 探测信息
from .扩展 import _工作流检查


def 校验制作输入(project, media_root):
    定位ffmpeg(); 定位ffprobe()
    probes = {}
    def media(name, kind=None):
        path = 安全媒体路径(media_root, name)
        if not os.path.isfile(path):
            raise ValueError(f"素材不存在：{name}，请重新上传或选择")
        if name not in probes:
            probes[name] = 探测信息(path)
        info = probes[name]
        if kind == "图像" and not info["width"]:
            raise ValueError(f"素材没有图像画面：{name}")
        if kind == "声音" and not info["has_audio"]:
            raise ValueError(f"素材没有音轨：{name}")
        return info
    for config in project["工作流"]:
        _工作流检查(config)
    for shot in project["镜头"]:
        if shot["来源"] in ("视频", "图片"):
            info = media(shot["文件名"], "图像")
            if shot["来源"] == "视频" and info["duration"] + 0.08 < shot["起点"] + shot["时长"]:
                raise ValueError(f"镜头{shot['id']}视频长度不足，请调整入点或时长")
        if shot["来源"] == "工作流":
            for name in shot["参考图"]:
                media(name, "图像")
            for name in shot["参考视频"]:
                media(name, "图像")
        if shot.get("配音"):
            voice = shot["配音"]
            if not isinstance(voice, dict):
                raise ValueError("镜头配音须为对象")
            try:
                from ..执行.台词配音 import 校验配音引用
            except ImportError:
                from 执行.台词配音 import 校验配音引用
            校验配音引用({"台词配音": voice}, shot["时长"])
            from .工程 import 数值
            delay = 数值(voice.get("段内开始"), "配音段内开始", 0, shot["时长"], 0)
            if delay + voice["末"] - voice["起"] > shot["时长"] + 1e-6:
                raise ValueError("配音时间超出对应片段")
            if media(voice["文件名"], "声音")["duration"] + 0.04 < voice["末"]:
                raise ValueError("镜头配音结束时间超过实际声音长度")
    for track in project["音轨"]:
        info = media(track["文件名"], "声音")
        if track["起点"] >= info["duration"]:
            raise ValueError(f"音轨{track['文件名']}入点超过实际长度")
        if not track["循环"] and info["duration"] + 0.05 < track["起点"] + track["时长"]:
            raise ValueError(f"音轨{track['文件名']}长度不足，请用真实配音时长调整")
    return {"已检查素材": len(probes)}
