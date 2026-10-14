"""实际生成视频的独立后期时间线；不写回生成分镜。"""
import copy
import math


def _秒(v, name, default=None):
    if v is None and default is not None:
        v = default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 86400:
        raise ValueError(f"{name}须为有效非负秒数")
    return v


def 转换后期草稿(draft):
    """绑定字幕/文字/配音依据源段坐标，随裁切、禁用和排序一起变化。"""
    result = copy.deepcopy(draft)
    raw = result["制作"]
    if not isinstance(raw.get("画布", {}), dict) or not isinstance(raw.get("字幕", {}), dict):
        raise ValueError("后期画布和字幕设置须为对象")
    if not isinstance(raw.get("字幕", {}).get("条目", []), list):
        raise ValueError("额外字幕须为数组")
    clips = raw.get("片段", [])
    if not isinstance(clips, list) or len(clips) > 720:
        raise ValueError("后期片段须为不超过720项的数组")
    fps = raw.get("画布", {}).get("帧率", 24)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("后期帧率须在1至120之间")
    segments, shots, captions, bound = [], {}, [], {}
    cursor, ids = 0, set()
    for i, item in enumerate(clips):
        if not isinstance(item, dict):
            raise ValueError("后期片段须为对象")
        ident = item.get("id")
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError("后期片段id须非空且唯一")
        ids.add(ident)
        if item.get("启用", True) is False:
            continue
        source_start = _秒(item.get("源开始"), "源段开始", 0)
        seek = _秒(item.get("起点"), "视频入点", source_start)
        length = _秒(item.get("时长"), "片段时长")
        if length <= 0 or seek < source_start:
            raise ValueError("后期片段时长须为正数且入点不早于源段")
        frames = max(1, math.floor(length * fps + 0.5))
        length = frames / fps
        offset, start = seek - source_start, cursor / fps
        source_length = item.get("素材时长")
        if source_length is not None and seek + length > _秒(source_length, "素材时长") + 1 / fps + 1e-6:
            raise ValueError(f"片段{i+1}裁切超出实际视频长度")
        # 源段结束约束避免延长镜头时悄悄吃到下一段的画面与配音。
        if item.get("源结束") is not None and seek + length > _秒(item["源结束"], "源段结束") + 1 / fps + 1e-6:
            raise ValueError(f"片段{i+1}超出对应源段，请调整裁切范围")
        voice = copy.deepcopy(item.get("配音"))
        sound = item.get("声音", "配音" if voice else "原声")
        if sound not in ("原声", "配音", "静音"):
            raise ValueError("片段声音须为原声、配音或静音")
        refs = {}
        if sound == "配音":
            if not isinstance(voice, dict):
                raise ValueError(f"片段{i+1}没有对应配音")
            a, b = _秒(voice.get("起"), "配音起"), _秒(voice.get("末"), "配音末")
            local = _秒(voice.get("段内开始"), "配音段内开始", 0)
            if b <= a:
                raise ValueError("配音末须大于起")
            overlap_start, overlap_end = max(local, offset), min(local+b-a, offset+length)
            if overlap_end > overlap_start:
                refs["台词配音"] = {"文件名": voice.get("文件名"), "起": a+overlap_start-local,
                                   "末": a+overlap_end-local, "段内开始": overlap_start-offset}
        segment = {"segment_id": ident, "start": start, "end": start+length,
                   "台词": item.get("台词", ""), "refs": refs, "标题": item.get("名称", "")}
        segments.append(segment)
        shots[ident] = {"来源": "视频", "文件名": item.get("文件名", ""), "起点": seek,
                        "声音": "原声" if sound == "原声" else "静音", "音量": item.get("音量", 1),
                        "转场": item.get("转场", "硬切"), "适配": item.get("适配", "完整显示")}
        bound[ident] = {"开始": start, "时长": length, "偏移": offset}
        entries = item.get("字幕")
        if entries is None:
            entries = [{"开始": 0, "结束": offset+length, "文本": item.get("台词", "")}] if item.get("台词") else []
        if not isinstance(entries, list) or len(entries) > 10000:
            raise ValueError("片段字幕须为数组")
        for entry in entries:
            caption = _重定位(entry, bound[ident])
            if caption is not None:
                captions.append(caption)
        cursor += frames
    raw["实体"], raw["工作流"], raw["镜头"] = [], [], shots
    raw["字幕"] = {**raw.get("字幕", {}), "条目": captions + copy.deepcopy(raw.get("字幕", {}).get("条目", []))}
    # 向通用标准化器明确“空字幕”为用户选择，不能回退成整段台词。
    raw["字幕"]["自动回退"] = False
    for key in ("文字", "音轨"):
        entries = raw.get(key, [])
        if not isinstance(entries, list):
            raise ValueError(f"{key}须为数组")
        relocated = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"{key}须为对象数组")
            ident = entry.get("片段id")
            if not ident:
                relocated.append(copy.deepcopy(entry))
                continue
            if ident not in bound:
                continue
            if key == "文字":
                updated = _重定位(entry, bound[ident])
            else:
                local = _秒(entry.get("开始"), "绑定音轨开始", 0)
                length = _秒(entry.get("时长"), "绑定音轨时长")
                b = bound[ident]
                a, z = max(local, b["偏移"]), min(local+length, b["偏移"]+b["时长"])
                updated = dict(entry, 开始=b["开始"]+a-b["偏移"], 起点=_秒(entry.get("起点"), "音轨入点", 0)+a-local,
                               时长=z-a) if z > a else None
            if updated is not None:
                relocated.append(updated)
        raw[key] = relocated
    result["segments"] = segments
    return result


def _重定位(entry, binding):
    if not isinstance(entry, dict):
        raise ValueError("字幕或文字须为对象")
    a, z = _秒(entry.get("开始"), "文字开始"), _秒(entry.get("结束"), "文字结束")
    if z <= a:
        raise ValueError("文字结束须大于开始")
    delta, duration, start = binding["偏移"], binding["时长"], binding["开始"]
    left, right = max(a, delta), min(z, delta+duration)
    return dict(entry, 开始=start+left-delta, 结束=start+right-delta) if right > left else None
