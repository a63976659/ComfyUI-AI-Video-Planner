"""文件式合成：镜头缓存、独立声音/字幕、准确文字与通用后处理。"""
import copy
import hashlib
import json
import os
from pathlib import Path

from .工具 import 定位ffmpeg, 媒体探测, 安全媒体路径, 文件摘要, 可取消子进程运行

渲染版本 = "production-2"


def _运行(args, cancel=None, cwd=None):
    result = 可取消子进程运行([定位ffmpeg(), "-hide_banner", "-nostdin", "-y", *args], cancel=cancel, cwd=cwd)
    if result.returncode:
        raise ValueError("合成失败：" + result.stderr.decode("utf-8", "replace")[-2500:])
    return result


def 探测信息(path):
    raw = 媒体探测(path)
    video = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
    rate = video.get("avg_frame_rate", "0/1")
    try:
        a, b = rate.split("/")
        fps = float(a) / float(b) if float(b) else 0
    except (ValueError, AttributeError):
        fps = 0
    return {"duration": float(raw.get("format", {}).get("duration", 0)), "width": video.get("width", 0),
            "height": video.get("height", 0), "fps": fps, "has_audio": any(s.get("codec_type") == "audio" for s in raw.get("streams", []))}


def _取消(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("制作已停止")


def 字体路径():
    candidates = [os.environ.get("LVP_VIDEO_FONT", ""),
                  "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    return next((p for p in candidates if p and os.path.isfile(p)), None)


def 制作标题图片(text, dest, width, height, 占位=False):
    from PIL import Image, ImageDraw, ImageFont
    font_path = 字体路径()
    if not font_path:
        raise ValueError("未找到可用字体，请设置 LVP_VIDEO_FONT 指向本地字体")
    image = Image.new("RGB", (width, height), (17, 22, 31))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, max(8 if 占位 else 18, int(min(width, height) * 0.073)))
    lines, line = [], ""
    for char in text:
        if char == "\n" or draw.textlength(line + char, font=font) > width * 0.82:
            lines.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    if line:
        lines.append(line)
    max_lines = max(1, int(height * 0.8 / (font.size * 1.4)))
    if len(lines) > max_lines:
        if 占位:
            font = ImageFont.truetype(font_path, max(8, int(min(width, height) * 0.045)))
            lines = ["待生成"]
        else:
            raise ValueError("标题过长，无法在画布安全区完整呈现，请缩短文字或增大画布")
    y = (height - len(lines) * font.size * 1.4) / 2
    for line in lines:
        draw.text(((width - draw.textlength(line, font=font)) / 2, y), line, font=font, fill=(242, 244, 248))
        y += font.size * 1.4
    image.save(dest)


def _ass时间(t):
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _srt时间(t):
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _ass文本(text):
    # ASS override/转义符永远不能作为用户可执行排版指令。
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\r", "").replace("\n", "\\N")


def 写字幕(工程, root):
    w, h = 工程["画布"]["宽"], 工程["画布"]["高"]
    caption = 工程["字幕"]
    rgb = caption["颜色"].lstrip("#")
    ass_color = "&H00" + rgb[4:6] + rgb[2:4] + rgb[0:2]
    styles = []
    aligns = {"顶部": 8, "中部": 5, "底部": 2}
    for name, size, color, alignment in [("Caption", caption["字号"], ass_color, aligns[caption["位置"]])]:
        styles.append(f"Style: {name},Microsoft YaHei,{size},{color},&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,1,{alignment},30,30,30,1")
    events = []
    for entry in caption["条目"] if caption["启用"] else []:
        events.append(f"Dialogue: 0,{_ass时间(entry['开始'])},{_ass时间(entry['结束'])},Caption,,0,0,0,,{_ass文本(entry['文本'])}")
    for i, entry in enumerate(工程["文字"]):
        name = f"Text{i}"
        styles.append(f"Style: {name},Microsoft YaHei,{entry['字号']},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,1,{aligns[entry.get('位置','中部')]},30,30,30,1")
        events.append(f"Dialogue: 1,{_ass时间(entry['开始'])},{_ass时间(entry['结束'])},{name},,0,0,0,,{_ass文本(entry['文本'])}")
    text = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            + "\n".join(styles) + "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + "\n".join(events) + "\n")
    Path(root, "captions.ass").write_text(text, encoding="utf-8-sig")
    Path(root, "captions.srt").write_text("\n\n".join(f"{i+1}\n{_srt时间(e['开始'])} --> {_srt时间(e['结束'])}\n{e['文本']}" for i, e in enumerate(caption["条目"])), encoding="utf-8-sig")
    return bool(events)


def 镜头指纹(shot, media_root):
    dependencies = []
    if shot["文件名"]:
        dependencies.append(文件摘要(安全媒体路径(media_root, shot["文件名"])))
    if shot.get("配音"):
        dependencies.append(文件摘要(安全媒体路径(media_root, shot["配音"]["文件名"])))
    font = 字体路径()
    if shot["来源"] == "标题" and font:
        dependencies.append(文件摘要(font))
    return hashlib.sha256(json.dumps([渲染版本, shot, dependencies], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def 渲染镜头(shot, media_root, cache_root, cancel=None):
    _取消(cancel)
    key = 镜头指纹(shot, media_root)
    root = Path(cache_root) / key
    root.mkdir(parents=True, exist_ok=True)
    out = root / "shot.mp4"
    if out.is_file():
        try:
            info = 探测信息(str(out))
        except (ValueError, RuntimeError):
            info = {}
        if info.get("width") == shot["宽"] and info.get("height") == shot["高"] and info.get("fps") == shot["帧率"] and info.get("has_audio") and abs(info.get("duration", 0) - shot["时长"]) <= 1 / shot["帧率"] + 0.04:
            return str(out), True
    w, h, fps, dur = shot["宽"], shot["高"], shot["帧率"], shot["时长"]
    source = shot["来源"]
    if source == "标题":
        path = str(root / "title.png")
        制作标题图片(shot["标题"], path, w, h, shot.get("_占位", False))
    else:
        path = 安全媒体路径(media_root, shot["文件名"])
    args = []
    if source in ("图片", "标题"):
        args += ["-loop", "1", "-framerate", str(fps), "-i", path]
        has_audio = False
    elif source in ("视频", "工作流"):
        info = 探测信息(path)
        if info["duration"] + 0.08 < shot["起点"] + dur:
            raise ValueError(f"镜头{shot['id']}视频长度不足，请调整入点或镜头时长")
        args += ["-ss", str(shot["起点"]), "-i", path]
        has_audio = info["has_audio"] and shot["声音"] != "静音"
    else:
        raise ValueError("镜头还未生成，请绑定实际素材")
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    if shot.get("适配") == "完整显示":
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if source == "图片" and shot["运镜"] != "静止":
        frames = shot["帧数"]
        zoom = f"1+0.15*on/{max(1,frames-1)}" if shot["运镜"] == "推进" else f"1.15-0.15*on/{max(1,frames-1)}"
        vf += f",zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps}"
    elif source == "视频" and shot.get("_插帧"):
        vf += f",tpad=stop_mode=clone:stop_duration={2/fps},minterpolate=fps={fps}:mi_mode=mci"
    else:
        vf += f",fps={fps}"
    if shot["转场"] == "淡入淡出":
        length = min(0.25, dur / 4)
        vf += f",fade=t=in:d={length},fade=t=out:st={dur-length}:d={length}"
    audio_index = 0
    dubbing = shot.get("配音")
    delay = 0
    if dubbing:
        try:
            from ..执行.台词配音 import 校验配音引用
        except ImportError:
            from 执行.台词配音 import 校验配音引用
        校验配音引用({"台词配音": dubbing}, dur)
        delay = dubbing.get("段内开始", 0)
        if not isinstance(delay, (int, float)) or isinstance(delay, bool) or not 0 <= delay <= dur or delay + dubbing["末"] - dubbing["起"] > dur + 1e-6:
            raise ValueError("配音在镜头中的时间范围不合法")
        apath = 安全媒体路径(media_root, dubbing["文件名"])
        if 探测信息(apath)["duration"] + 0.04 < dubbing["末"]:
            raise ValueError("配音时间窗超过音频实际长度")
        args += ["-ss", str(dubbing["起"]), "-t", str(dubbing["末"]-dubbing["起"]), "-i", apath]
        audio_index = 1
        has_audio = True
    if not has_audio:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_index = 1
    args += ["-map", "0:v:0", "-map", f"{audio_index}:a:0", "-vf", vf,
             "-af", f"aresample=48000,{f'adelay={round(delay*1000)}:all=1,' if delay else ''}apad,atrim=duration={dur},volume={shot['音量']}",
             "-t", str(dur), "-frames:v", str(shot["帧数"]), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(root / "shot.part.mp4")]
    _运行(args, cancel)
    _取消(cancel)
    os.replace(root / "shot.part.mp4", out)
    return str(out), False


def 合成成片(工程, files, media_root, root, cancel=None, progress=None):
    _取消(cancel)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    # 镜头路径为本模块生成的摘要目录；不把用户路径拼入 concat 脚本。
    clips = []
    for i, path in enumerate(files):
        target = root / f"clip-{i:04d}.mp4"
        same = target.exists() and os.path.samefile(path, target)
        if not same:
            temporary = root / f"clip-{i:04d}.part.mp4"
            if temporary.exists():
                temporary.unlink()
            try:
                os.link(path, temporary)
            except OSError:
                import shutil
                shutil.copyfile(path, temporary)
            _取消(cancel)
            os.replace(temporary, target)
        clips.append(target)
    Path(root, "concat.txt").write_text("\n".join(f"file '{p.name}'" for p in clips), encoding="ascii")
    _运行(["-f", "concat", "-safe", "1", "-i", "concat.txt", "-c", "copy", "joined.mp4"], cancel, str(root))
    if progress:
        progress("声音与字幕合成")
    has_text = 写字幕(工程, root)
    args = ["-i", "joined.mp4"]
    filters = ["[0:a]aresample=48000,asetpts=PTS-STARTPTS[base]"]
    voices, music, effects = ["[base]"], [], []
    for i, track in enumerate(工程["音轨"], 1):
        path = 安全媒体路径(media_root, track["文件名"])
        info = 探测信息(path)
        if not info["has_audio"]:
            raise ValueError(f"音轨没有声音：{track['文件名']}")
        if track["起点"] >= info["duration"]:
            raise ValueError(f"音轨{track['文件名']}入点超过实际长度")
        if not track["循环"] and info["duration"] + 0.05 < track["起点"] + track["时长"]:
            raise ValueError(f"音轨{track['文件名']}长度不足，不会静默截断")
        if track["循环"]:
            args += ["-stream_loop", "-1"]
        args += ["-ss", str(track["起点"]), "-i", path]
        chain = f"[{i}:a]aresample=48000,atrim=duration={track['时长']},asetpts=PTS-STARTPTS,volume={track['音量']}"
        if track["淡入"]:
            chain += f",afade=t=in:d={min(track['淡入'],track['时长'])}"
        if track["淡出"]:
            chain += f",afade=t=out:st={max(0,track['时长']-track['淡出'])}:d={min(track['淡出'],track['时长'])}"
        chain += f",adelay={round(track['开始']*1000)}:all=1,apad,atrim=duration={工程['时长']}[t{i}]"
        filters.append(chain)
        (voices if track["类型"] == "人声" else music if track["类型"] == "音乐" else effects).append(f"[t{i}]")
    filters.append("".join(voices) + f"amix=inputs={len(voices)}:normalize=0[voice]")
    mixed = ["[voice]"]
    if music:
        filters.append("".join(music) + f"amix=inputs={len(music)}:normalize=0[music]")
        if 工程["后处理"]["音乐压低"]:
            filters += ["[voice]asplit[voiceout][side]", "[music][side]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck]"]
            mixed = ["[voiceout]", "[duck]"]
        else:
            mixed.append("[music]")
    mixed += effects
    final = "".join(mixed) + f"amix=inputs={len(mixed)}:normalize=0,apad,atrim=duration={工程['时长']}"
    if 工程["后处理"]["响度标准化"]:
        final += ",loudnorm=I=-16:TP=-1.5:LRA=11"
        # 部分 FFmpeg 的响度滤镜对全静音产生 NaN，发布前恢复为真实静音。
        final += ",aeval=exprs='if(isnan(val(0))+isinf(val(0)),0,val(0))|if(isnan(val(1))+isinf(val(1)),0,val(1))':c=stereo"
    filters.append(final + "[audio]")
    post = 工程["后处理"]
    video = f"[0:v]eq=brightness={post['亮度']}:contrast={post['对比度']}:saturation={post['饱和度']}"
    if post["去闪烁"]:
        video += ",deflicker=size=5:mode=am"
    if post["防抖"]:
        video += ",deshake=rx=16:ry=16"
    if has_text:
        video += ",ass=captions.ass"
    filters.append(video + "[video]")
    Path(root, "filters.txt").write_text(";\n".join(filters), encoding="utf-8")
    args += ["-filter_complex_script", "filters.txt", "-map", "[video]", "-map", "[audio]", "-t", str(工程["时长"]),
             "-r", str(工程["画布"]["帧率"]), "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", "video.part.mp4"]
    _运行(args, cancel, str(root))
    _取消(cancel)
    os.replace(root / "video.part.mp4", root / "video.mp4")
    export = copy.deepcopy(工程)
    Path(root, "project.json").write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"video": "video.mp4", "subtitles": "captions.srt", "project": "project.json"}
