"""仅为已核实的规划模型启用结构化返回，不改变其他提供商与时间轴策略。"""
import json
from urllib.parse import urlparse
from .文本话语 import 内容话语候选, 台词项上限, 原文引文候选, 台词来源契约
from .规划契约 import 来源字段模式
from .镜头创作 import 创作字段, 发声文案约定
from .项目设计 import 设计字段
from .规划默认规则 import 声音字段


def _对象(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _数组(item):
    return {"type": "array", "items": item}


def _项目设计模式():
    text = {"type": "string"}
    properties = {key: {**_数组(text), "description": "具体定稿的设计，区分原文事实与规划补全，无关时用空数组；待证事项仅记录证据限制"} for key in 设计字段}
    properties["声音方案"] = {**_数组(_对象({key: {**text, "minLength": 1} for key in 声音字段})),
                          "description": "主要角色的共享声音，一位说话人一个七项对象；临时说话人在首次发声分镜中确定，无共享声音用[]。"}
    properties["声景方案"] = {**_数组(_对象({key: {**text, "minLength": 1} for key in ("范围", "环境音", "音乐")})),
        "minItems": 1, "description": "范围全片确定唯一音乐安排和持续背景环境声；具体场景按实体名另列。动作触发的短音留给本镜音效，未使用声音明确填写不使用。"}
    return _对象(properties)


def _内容模式(data):
    text = {"type": "string"}
    limits = data.get("内容数量约束", {})
    if not isinstance(limits, dict):
        limits = {}
    maximum = limits.get("最多单元", 60)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 60:
        maximum = 60
    shot_limit = limits.get("镜头合计上限")
    ids = [s["id"] for s in data.get("原文", []) if isinstance(s, dict) and isinstance(s.get("id"), str)]
    quotes = []
    for scope in data.get("原文", []):
        raw = scope.get("正文", "") if isinstance(scope, dict) else ""
        if not isinstance(raw, str):
            continue
        quotes.extend(原文引文候选(raw))
    for block in data.get("分块理解", []):
        if isinstance(block, dict):
            for item in block.get("内容单元", []):
                if isinstance(item, dict):
                    for source in item.get("来源", []):
                        if isinstance(source, dict):
                            if isinstance(source.get("范围"), str):
                                ids.append(source["范围"])
                            if isinstance(source.get("引文"), str) and source["引文"].strip():
                                quotes.append(source["引文"])
    origin = {"type": "string", "enum": list(dict.fromkeys(ids))} if ids else text
    quote = {"type": "string", "enum": list(dict.fromkeys(quotes))} if quotes else text
    candidates = 内容话语候选(data)
    locked = {**text, "minLength": 1, "pattern": r"[\s\S]*\S[\s\S]*"}
    locks = {**_数组(locked), "maxItems": 台词项上限, "description": "非空原文字符串数组，每单元最多16项，每项是逐字连续原文；禁止对象、空字符串或仅空白。只保留原文已有的具体台词或歌词；制作要求、素材说明与摄影约束不是台词。原文没有具体话语时必须用[]。跨镜原话可按自然语句拆成连续原文片段，各片段分别分配，合起来完整保留原话，不改字、不重复、不遗漏。创作新增对白不得标为必留台词。超量时按事件和歌词结构划分内容单元，保留全部话语，不删原文。"}
    if not candidates:
        locks["maxItems"] = 0
    locks["description"] += 台词来源契约
    shot_count = {"type": "integer", "minimum": 1}
    if isinstance(shot_limit, int) and not isinstance(shot_limit, bool) and shot_limit > 0:
        shot_count["maximum"] = shot_limit
    table = data.get("来源引用表")
    unit = _对象({"内容": {**text, "minLength": 1}, "来源": 来源字段模式(table, _对象({"范围": origin, "引文": quote})),
        "必留台词": locks,
        "建议镜头数": shot_count, "时长预算说明": {**text}})
    if data.get("分镜生成方式") == "按场次":
        unit["properties"]["建议镜头数"] = {"type": "integer", "minimum": 1, "description": "场次节奏参考，不冻结实际镜头数。"}
        unit["properties"].update(涉及实体=_数组(text), 衔接方式={"type": "string", "enum": ["连续", "独立"],
            "description": "连续承接前场；仅无前场状态、话语和新声音身份依赖时选独立。"})
        unit["required"].extend(("涉及实体", "衔接方式"))
    elif data.get("内容阶段职责") != "原文分析":
        del unit["properties"]["建议镜头数"]
        unit["required"].remove("建议镜头数")
        unit["properties"]["镜头任务"] = {**_数组(_对象({"任务": {**text, "minLength": 1},
            "对白": {**text, "description": 发声文案约定}, "旁白": {**text, "description": 发声文案约定},
            "发声秒": {"type": ["number", "null"], "exclusiveMinimum": 0},
            "中文每秒字数": {"type": ["number", "null"], "exclusiveMinimum": 0, "maximum": 120,
                "description": "中文新配音在内容阶段按本次Skills、本镜文案与表演确定具体语速，用户指定优先；不填区间，不为压缩文案临时加速。无发声、非中文或保留原音填null。"},
            "建议秒数": {"type": "number", "exclusiveMinimum": 0},
            "涉及实体": _数组(text), "发声角色": _数组(text),
            "衔接方式": {"type": "string", "enum": ["连续", "时空跳转", "用户锁定"], "description": "同场时间连续选连续，由程序沿用前镜结束；只有实际时空变化或原有镜头明确锁定起始才选择另两项。全片首镜用连续并填写初始状态。"},
            "起始要求": {**text, "description": "全片首镜、时空跳转或用户锁定起始时填写动作发生前的实际状态；同场连续任务填空字符串，由程序承接前镜结束状态。"},
            "结束要求": {**text, "description": "本镜全部行动与话语完成后的物理状态，记录全部参与者位置、各只手的持物或接触状态、物品数量与结果；作为下一连续任务的唯一起始依据。"},
            "原镜号": _数组(text),
            "保留要求": text, "锁定秒数": {"type": ["number", "null"], "exclusiveMinimum": 0}})),
            "minItems": 0 if data.get("内容阶段职责") == "局部内容规划" else 1, "maxItems": shot_limit or 720,
            "description": "每项对应一个执行段，定稿完整对白和旁白及发声角色，无发声用空字符串。完整文案按事件与信息推进分配，不在后续镜头重复创作；制作说明融入项目设计及实际任务。"}
        unit["required"].append("镜头任务")
    if (isinstance(table, dict) and len(table) == 1
            and data.get("内容来源归属") == {"由程序绑定": True, "固定值": list(table)}):
        del unit["properties"]["来源"]
        unit["required"].remove("来源")
    entity = _对象({"类型": {"type": "string", "enum": ["角色", "场景", "道具"]}, "名称": text,
        "外观": {**text, "description": "角色和道具定稿稳定外形；场景定稿地标相对位置、光源世界位置与朝向，使用明确唯一安排供各镜沿用。缺省制作细节标规划补全。"}, "原文依据": text})
    schema = _对象({"内容单元": {**_数组(unit), "maxItems": maximum,
        "description": f"无真实需求冲突时返回1至{maximum}项；相关事件可组织为同一单元，保留全部必留内容。"
                       + ("当前局部范围仅含需求说明时记录约束单元及来源，汇总融入正文。" if data.get("内容阶段职责") in ("原文分析", "局部内容规划") else
                          "每个单元承载实际镜头；主题、钩子、风格等制作说明融入项目设计及实际任务，不单列说明单元。")},
        "人物场景": {**_数组(entity), "maxItems": 40}, "保真说明": {**text},
        "项目设计": _项目设计模式(), "冲突": {**_数组(text), "description": "仅报告输入资料确实缺失或真实需求矛盾。自己的来源、编号和JSON字段错误应按要求修正，不能作为用户需求冲突。"}})
    if data.get("内容阶段职责") == "原文分析":
        del schema["properties"]["项目设计"]
        schema["required"].remove("项目设计")
    return schema


def _全剧模式(data):
    text = {"type": "string"}
    ids = data["范围顺序"]
    ranges = {**_数组({"type": "string", "enum": ids}), "minItems": 1, "maxItems": 4,
              "description": "仅引用范围顺序中的连续真实ID；所有集依次拼接须完整匹配范围顺序，不重复、不遗漏。"}
    episode = _对象({"名称": text, "范围": ranges, "衔接": text})
    entity = _对象({"类型": {"type": "string", "enum": ["角色", "场景", "道具"]}, "名称": text,
        "外观": {**text, "description": "角色和道具定稿稳定外形；场景定稿地标相对位置、光源世界位置与朝向，使用明确唯一安排供各镜沿用。缺省制作细节标规划补全。"}, "原文依据": text})
    episode_limits = data.get("分集范围约束", {}).get("分集数量", [(len(ids) + 3) // 4, min(len(ids), 120)])
    return _对象({"主线": text, "人物场景": {**_数组(entity), "maxItems": 40},
        "分集": {**_数组(episode), "minItems": episode_limits[0], "maxItems": episode_limits[1],
            "description": "剧集不是镜头或歌词段落；每个真实范围只分配一次，范围内的多个事件在本集内拆镜头。"},
        "项目设计": _项目设计模式(), "冲突": _数组(text)})


def _镜头模式(data):
    text = {"type": "string"}
    brief = data.get("需求")
    materials = brief.get("素材", []) if isinstance(brief, dict) else []
    names = list(dict.fromkeys(m["名"] for m in materials
                              if isinstance(m, dict) and isinstance(m.get("名"), str)))
    file = {"type": "string", "enum": names} if names else text
    materials = {**_数组(file), **({} if names else {"maxItems": 0})}
    ids = list(dict.fromkeys(u["id"] for u in data["内容单元"] if isinstance(u, dict) and isinstance(u.get("id"), str)))
    props = {key: text for key in ("标题", "主体", "动作", "景别", "机位", "画面", "对白", "旁白", "职能", "情绪", "镜头目的", "起始状态", "结束状态", "切镜理由")}
    for key in ("对白", "旁白"):
        props[key] = {**text, "description": 发声文案约定}
    props.update(建议秒数={"type": "number"}, 内容单元={**_数组({"type": "string", "enum": ids} if ids else text), "minItems": 1}, 使用素材=materials)
    assignment = data.get("镜头内容单元归属")
    if (len(ids) == 1 and isinstance(assignment, dict) and assignment.get("由程序绑定") is True
            and assignment.get("固定值") == ids):
        del props["内容单元"]
    from .镜头设计 import 对象字段
    for key, fields in 对象字段.items():
        props[key] = _对象({field: text for field in fields})
    if data.get("本镜声景方案"):
        props["声景设计"] = _对象({field: text for field in 对象字段["声景设计"] if field not in data["本镜声景方案"]})
    props["声音设计"] = {"anyOf": [_对象({field: {**text, "minLength": 1} for field in 声音字段}), _对象({})],
                         "description": "本镜说话人的声音字段；无实际发声用空对象，已定身份字段由程序继承。"}
    content = data.get("本镜内容定稿")
    if isinstance(content, dict) and content.get("由程序绑定") is True and any(
            isinstance(content.get(key), str) and content[key].strip() for key in ("对白", "旁白")):
        props["声音设计"]["anyOf"].pop()
    props["声音设计"]["anyOf"][0]["properties"]["语速"]["description"] = "按本镜文案和表演确定每秒N字的具体语速，用户指定优先，与本镜计时和最终提示词一致；保留原音时注明原音保留。"
    if data.get("已定声音身份"):
        props["声音设计"]["anyOf"].append(_对象({
            "说话人": {**text, "enum": list(data["已定声音身份"])},
            "语速": {**text, "minLength": 1}, "情绪": {**text, "minLength": 1}, "停顿重音": {**text, "minLength": 1}}))
    if data.get("本镜声音身份"):
        props["声音设计"] = _对象({key: {**text, "minLength": 1} for key in ("情绪", "停顿重音")})
    props["时长依据"] = _对象({**{key: {"type": "number"} for key in ("动作秒", "停顿秒", "反应秒")},
        "动作与台词": {"type": "string", "enum": ["同时", "先后"]},
        "计时主导": {"type": "string", "enum": ["声音", "动作"],
            "description": "本镜计时采用的主导轨道。"}, "说明": text})
    props["时长依据"]["properties"]["发声秒"] = {"type": "number", "description": "非中文、混合语言或有实测原音时填写完整发声秒数，不含独立停顿与反应；纯中文合成人声省略，由程序按已定声音语速计算。"}
    if data.get("本镜文案定稿"):
        props["时长依据"]["properties"].pop("发声秒")
        script = data["本镜文案定稿"]
        if not (script.get("对白", "") + script.get("旁白", "")).strip():
            props["时长依据"]["properties"].pop("动作与台词")
            props["时长依据"]["required"].remove("动作与台词")
    props["素材职责"] = {**_数组(_对象({"文件": file, "职责": {"type": "string", "enum": ["身份", "场景", "道具", "风格", "构图", "首帧", "尾帧", "动作", "声音"]}, "限制": text})),
                        **({} if names else {"maxItems": 0})}
    if data.get("镜头创作约定"):
        fields = 创作字段(data)
        props = {key: value for key, value in props.items() if key in fields}
    shot = _对象(props)
    if isinstance(content, dict) and content.get("由程序绑定") is True:
        shot["required"] = [key for key in shot["required"] if key not in ("对白", "旁白", "建议秒数", "时长依据")]
    if data.get("单镜创作"):
        return shot
    shots = _数组(shot)
    if data.get("分镜生成方式") == "按场次":
        shots.update(minItems=1, maxItems=data.get("场次任务", {}).get("最多段数", 720))
    counts = [u.get("本批镜头数") for u in data["内容单元"] if isinstance(u, dict)]
    if counts and len(counts) == len(data["内容单元"]) and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in counts):
        shots.update(minItems=sum(counts), maxItems=sum(counts))
    return _对象({"镜头": shots} if data.get("镜头创作约定") else {"镜头": shots, "冲突": _数组(text)})


def 规划结构选项(cfg, system, user):
    host = (urlparse(str(cfg.get("base_url") or "")).hostname or "").lower()
    if host == "api.deepseek.com" and "你是视频内容规划师" in system:
        return {"response_format": {"type": "json_object"}}
    model = str(cfg.get("model", "")).lower()
    qwen = host in ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com") and model == "qwen3.8-flash"
    kimi = host in ("api.moonshot.cn", "api.moonshot.ai") and model == "kimi-k3"
    if not (qwen or kimi) or "你是视频内容规划师" not in system:
        return {}
    options = {"response_format": {"type": "json_object"}, **({"enable_thinking": False} if qwen else {})}
    try:
        data = json.loads(user) if isinstance(user, str) else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return options
    choices = data.get("识别要求")
    if data.get("规划阶段") == "准备实体绘图":
        names = [item["名"] for item in data.get("可用参考图片", []) if isinstance(item, dict) and isinstance(item.get("名"), str)]
        schema = _对象({"绘图提示词": {"type": "string", "minLength": 1},
            "参考图片": {**_数组({"type": "string", **({"enum": names} if names else {})}), **({} if names else {"maxItems": 0})}})
        name = "planning_reference_drawing"
    elif data.get("规划阶段") == "识别需求" and isinstance(choices, dict) and all(
            isinstance(choices.get(key), list) and choices[key] and all(isinstance(value, str) for value in choices[key])
            for key in ("输入类型", "目标体裁", "改写方式")):
        schema = _对象({key: {"type": "string", "enum": choices[key]} for key in ("输入类型", "目标体裁", "改写方式")})
        name = "planning_classification"
    elif isinstance(data.get("范围顺序"), list) and data["范围顺序"] and all(isinstance(sid, str) for sid in data["范围顺序"]):
        schema, name = _全剧模式(data), "planning_series"
    elif isinstance(data.get("原文"), list) or isinstance(data.get("分块理解"), list):
        schema, name = _内容模式(data), "planning_content"
        if qwen:
            options.update(stream=True, stream_options={"include_usage": True})
    elif isinstance(data.get("内容单元"), list):
        schema, name = _镜头模式(data), "planning_shots"
        if qwen:
            options.update(stream=True, stream_options={"include_usage": True})
    else:
        return options
    if qwen and name in ("planning_content", "planning_series", "planning_shots"):
        options.update(enable_thinking=True, reasoning_effort="medium", stream=True,
                       stream_options={"include_usage": True})
    options.update(response_format={"type": "json_schema", "json_schema": {
        "name": name, "strict": True, "schema": schema}})
    return options
