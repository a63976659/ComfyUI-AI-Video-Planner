"""中性制作工程：严格类型、稳定镜头引用和实际媒体条件。"""
import copy
import math
import re

版本 = 1
来源选项 = ("视频", "图片", "标题", "工作流", "待生成")


def 数值(value, name, lo, hi, default=None):
    if value is None and default is not None:
        value = default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name}须为 {lo}..{hi} 的有限数值")
    return value


def 文字(value, name, limit=4000):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name}须为不超过 {limit} 字的文本")
    return value


def 颜色(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", value):
        raise ValueError("颜色须为六位十六进制颜色")
    return value


def _数组(value, name, limit):
    if not isinstance(value, list) or len(value) > limit or not all(isinstance(x, dict) for x in value):
        raise ValueError(f"{name}须为不超过 {limit} 项的对象数组")
    return value


def 标准化工程(草稿, 严格=False):
    if isinstance(草稿, dict) and isinstance(草稿.get("制作"), dict) and 草稿["制作"].get("模式") == "后期":
        from .后期工程 import 转换后期草稿
        草稿 = 转换后期草稿(草稿)
    if not isinstance(草稿, dict) or not isinstance(草稿.get("segments"), list):
        raise ValueError("制作需要有效的分镜草稿")
    raw = 草稿.get("制作", {})
    if not isinstance(raw, dict) or raw.get("版本", 1) != 1:
        raise ValueError("不支持的制作工程版本")
    if len(草稿["segments"]) > 720:
        raise ValueError("制作镜头不得超过720段")
    canvas = raw.get("画布", {})
    if not isinstance(canvas, dict):
        raise ValueError("画布须为对象")
    w = 数值(canvas.get("宽"), "画布宽", 64, 7680, 1280)
    h = 数值(canvas.get("高"), "画布高", 64, 7680, 720)
    fps = 数值(canvas.get("帧率"), "帧率", 1, 120, 24)
    if w * h > 16_777_216:
        raise ValueError("画布像素不得超过16777216")
    if int(w) != w or int(h) != h or w % 2 or h % 2:
        raise ValueError("画布宽高须为偶数整数")
    entities, entity_ids = [], set()
    for item in _数组(raw.get("实体", []), "人物场景卡", 100):
        ident = 文字(item.get("id", ""), "实体id", 100)
        if not ident or ident in entity_ids:
            raise ValueError("实体id须非空且唯一")
        entity_ids.add(ident)
        entity = {"id": ident, "名称": 文字(item.get("名称", ""), "实体名称", 100),
                  "类型": item.get("类型", "人物"), "描述": 文字(item.get("描述", ""), "实体描述"),
                  "参考图": 文字(item.get("参考图", ""), "实体参考图", 255), "锁定": bool(item.get("锁定", True))}
        if entity["类型"] not in ("人物", "场景", "产品", "道具"):
            raise ValueError("实体类型不合法")
        entities.append(entity)
    workflows = _数组(raw.get("工作流", []), "工作流", 20)
    if any(not isinstance(x.get("id"), str) or not x["id"] for x in workflows) or len({x["id"] for x in workflows}) != len(workflows):
        raise ValueError("工作流id須非空且唯一")
    by_workflow = {x["id"]: x for x in workflows}
    config = raw.get("镜头", {})
    if not isinstance(config, dict):
        raise ValueError("镜头制作配置须为对象")
    shots, warnings, seen, cursor = [], [], set(), 0
    for index, segment in enumerate(草稿["segments"]):
        if not isinstance(segment, dict):
            raise ValueError("镜头须为对象")
        ident = 文字(segment.get("segment_id", f"legacy-{index + 1}"), "镜头id", 100)
        if not ident or ident in seen:
            raise ValueError("镜头id须非空且唯一")
        seen.add(ident)
        if segment.get("启用", segment.get("run", True)) is False:
            continue
        start = 数值(segment.get("start", 0), "镜头开始", 0, 3600)
        end = 数值(segment.get("end", 0), "镜头结束", 0, 3600)
        if end <= start:
            raise ValueError(f"镜头{index+1}结束须大于开始")
        opts = config.get(ident, {})
        if not isinstance(opts, dict):
            raise ValueError("镜头配置须为对象")
        refs = segment.get("refs") or {}
        if not isinstance(refs, dict):
            raise ValueError("镜头参考须为对象")
        videos = refs.get("视频", [])
        if not isinstance(videos, list) or not all(isinstance(x, str) for x in videos) or not isinstance(refs.get("图片", []), list):
            raise ValueError("镜头视频和图片参考须为文件名数组")
        reference_images = list(refs.get("图片", []))
        for key in ("首帧", "尾帧"):
            if refs.get(key):
                reference_images.append(refs[key])
        if not all(isinstance(x, str) for x in reference_images):
            raise ValueError("图像参考须为文件名")
        image = refs.get("首帧") or next(iter(refs.get("图片", [])), "")
        file = opts.get("文件名", "")
        source = opts.get("来源") or ("视频" if videos else "图片" if image else "待生成")
        if source not in 来源选项:
            raise ValueError("未知镜头来源")
        if not file:
            file = videos[0] if source == "视频" and videos else image if source == "图片" else ""
        if source in ("视频", "图片") and not file:
            raise ValueError(f"镜头{index+1}需要选择{source}素材")
        if source == "待生成":
            warnings.append(f"镜头{index+1}还未绑定画面来源；预演仅显示分镜标题")
            if 严格:
                raise ValueError(f"镜头{index+1}未绑定画面，请选择素材或通用工作流")
        entity_refs = opts.get("实体引用", segment.get("实体引用", []))
        if not isinstance(entity_refs, list) or not all(isinstance(x, str) and x in entity_ids for x in entity_refs):
            raise ValueError(f"镜头{index+1}引用了不存在的人物场景卡")
        bound = [e for e in entities if e["id"] in entity_refs]
        prompt = 文字(segment.get("prompt", ""), "镜头提示词", 30000)
        details = "\n".join(f"{e['名称']}（{'保持身份、外观与风格一致' if e['锁定'] else '参考描述'}）：{e['描述']}" for e in bound)
        data = segment.get("镜头资料", {})
        if not isinstance(data, dict):
            raise ValueError("镜头资料须为对象")
        before = 文字(opts.get("起始状态", segment.get("起始状态", data.get("起始状态", ""))), "起始状态")
        after = 文字(opts.get("结束状态", segment.get("结束状态", data.get("结束状态", ""))), "结束状态")
        prompt = "\n".join(x for x in (prompt, details, f"开始状态：{before}" if before else "", f"结束状态：{after}" if after else "") if x)
        frames = max(1, round((end - start) * fps))
        speech = segment.get("台词") or (文字(data.get("对白", ""), "对白") + 文字(data.get("旁白", ""), "旁白"))
        shot = {"id": ident, "来源": source, "文件名": 文字(file, "镜头文件名", 255),
                "开始": cursor / fps, "结束": (cursor + frames) / fps, "时长": frames / fps, "帧数": frames,
                "提示词": prompt, "宽": int(w), "高": int(h), "帧率": fps,
                "标题": 文字(opts.get("标题", segment.get("标题", "") or segment.get("prompt", "")[:200]), "镜头标题", 2000),
                "起点": 数值(opts.get("起点"), "素材入点", 0, 86400, 0),
                "运镜": opts.get("运镜", "静止"), "声音": opts.get("声音", "原声"),
                "适配": opts.get("适配", "填满裁切"),
                "转场": opts.get("转场", "硬切"), "音量": 数值(opts.get("音量"), "镜头音量", 0, 4, 1),
                "种子": int(数值(opts.get("种子"), "种子", 0, 2**32-1, 0)),
                "实体引用": entity_refs, "参考图": list(dict.fromkeys([e["参考图"] for e in bound if e["参考图"]] + reference_images)),
                "参考视频": videos, "起始状态": before, "结束状态": after,
                "镜头资料": copy.deepcopy(data),
                "工作流id": 文字(opts.get("工作流id", ""), "工作流id", 100), "配音": copy.deepcopy(refs.get("台词配音")),
                "台词": 文字(speech, "台词")}
        if shot["运镜"] not in ("静止", "推进", "拉远") or shot["声音"] not in ("原声", "静音") or shot["转场"] not in ("硬切", "淡入淡出"):
            raise ValueError("运镜、声音或转场选项不合法")
        if shot["适配"] not in ("完整显示", "填满裁切"):
            raise ValueError("画面适配须为完整显示或填满裁切")
        if source == "工作流":
            if shot["工作流id"] not in by_workflow:
                raise ValueError(f"镜头{index+1}未选择有效工作流")
            capability = by_workflow[shot["工作流id"]].get("能力", {})
            if not isinstance(capability, dict):
                raise ValueError("工作流能力须为对象")
            lo = 数值(capability.get("最短秒"), "工作流最短秒", 0.1, 3600, 1)
            hi = 数值(capability.get("最长秒"), "工作流最长秒", lo, 3600, 60)
            if not lo <= shot["时长"] <= hi:
                raise ValueError(f"镜头{index+1}时长不在所选工作流的{lo}..{hi}秒范围")
        shots.append(shot)
        cursor += frames
    if not shots or cursor / fps > 3600:
        raise ValueError("制作须有启用镜头且总长不超过60分钟")
    duration = cursor / fps
    tracks = []
    for item in _数组(raw.get("音轨", []), "音轨", 40):
        track = {"id": 文字(item.get("id", ""), "音轨id", 100), "类型": item.get("类型", "音乐"),
                 "文件名": 文字(item.get("文件名", ""), "音轨文件名", 255),
                 "开始": 数值(item.get("开始"), "音轨开始", 0, duration, 0),
                 "起点": 数值(item.get("起点"), "音轨入点", 0, 86400, 0),
                 "音量": 数值(item.get("音量"), "音轨音量", 0, 4, 1), "循环": bool(item.get("循环", False)),
                 "淡入": 数值(item.get("淡入"), "淡入", 0, duration, 0), "淡出": 数值(item.get("淡出"), "淡出", 0, duration, 0)}
        track["时长"] = 数值(item.get("时长"), "音轨时长", 0.01, duration, max(0.01, duration - track["开始"]))
        if not track["文件名"] or track["类型"] not in ("人声", "音乐", "音效") or track["开始"] + track["时长"] > duration + 1e-6:
            raise ValueError("音轨文件、类型或结束时间不合法")
        tracks.append(track)
    captions = raw.get("字幕", {})
    if not isinstance(captions, dict):
        raise ValueError("字幕配置须为对象")
    entries = copy.deepcopy(_数组(captions.get("条目", []), "字幕条目", 10000))
    if not entries and captions.get("自动回退", True):
        entries = [{"开始": s["开始"], "结束": s["结束"], "文本": 草稿["segments"][[x.get("segment_id", f"legacy-{i+1}") for i, x in enumerate(草稿["segments"])].index(s["id"])].get("台词", "")} for s in shots]
        entries = [e for e in entries if e["文本"]]
    for entry in entries:
        _验文字区间(entry, duration)
    entries.sort(key=lambda x: x["开始"])
    text_layers = copy.deepcopy(_数组(raw.get("文字", []), "文字图层", 200))
    for entry in text_layers:
        _验文字区间(entry, duration)
        entry["字号"] = 数值(entry.get("字号"), "图层字号", 8, 160, 48)
        if entry.get("位置", "中部") not in ("顶部", "中部", "底部"):
            raise ValueError("文字图层位置不合法")
    post = raw.get("后处理", {})
    if not isinstance(post, dict):
        raise ValueError("后处理配置须为对象")
    processing = {"亮度": 数值(post.get("亮度"), "亮度", -1, 1, 0),
                  "对比度": 数值(post.get("对比度"), "对比度", 0.1, 3, 1),
                  "饱和度": 数值(post.get("饱和度"), "饱和度", 0, 3, 1)}
    for key in ("去闪烁", "防抖", "插帧", "响度标准化", "音乐压低"):
        processing[key] = bool(post.get(key, key in ("响度标准化", "音乐压低")))
    result = {"版本": 1, "画布": {"宽": int(w), "高": int(h), "帧率": fps}, "实体": entities,
              "镜头": shots, "音轨": tracks, "字幕": {"启用": bool(captions.get("启用", True)), "条目": entries,
              "字号": 数值(captions.get("字号"), "字幕字号", 8, 120, 36), "颜色": 颜色(captions.get("颜色", "#ffffff")),
              "位置": captions.get("位置", "底部")}, "文字": text_layers, "后处理": processing,
              "工作流": copy.deepcopy(workflows), "时长": duration, "帧数": cursor, "warnings": warnings}
    if result["字幕"]["位置"] not in ("顶部", "中部", "底部"):
        raise ValueError("字幕位置不合法")
    orphan = set(config) - seen
    if orphan:
        warnings.append(f"{len(orphan)}项制作镜头配置已无对应分镜，合成时忽略")
    return result


def _验文字区间(entry, duration):
    a = 数值(entry.get("开始"), "文字开始", 0, duration)
    b = 数值(entry.get("结束"), "文字结束", 0, duration)
    if b <= a:
        raise ValueError("文字结束须大于开始")
    文字(entry.get("文本"), "文字内容", 4000)
