"""仅为已核实的规划模型启用结构化返回，不改变其他提供商与时间轴策略。"""
import json
import re
from urllib.parse import urlparse
from .文本话语 import 内容话语候选, 台词项上限, 原文引文候选, 台词来源契约
from .规划契约 import 来源字段模式, 缺陷类型, 验收问题上限


def _对象(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _数组(item):
    return {"type": "array", "items": item}


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
    locked = {**text, "minLength": 1,
              **({"enum": list(dict.fromkeys(candidates))} if candidates else {})}
    locks = {**_数组(locked), "maxItems": 台词项上限, "description": "非空原文字符串数组，每单元最多16项，每项完整保留原文；禁止对象、空字符串或仅空白。只保留原文已有的具体台词或歌词；制作要求、素材说明与摄影约束不是台词。原文没有具体话语时必须用[]。创作新增对白仅写在内容中，不得标为必留台词。超量时按事件和歌词结构划分内容单元，保留全部话语，不删原文。"}
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
    if (isinstance(table, dict) and len(table) == 1
            and data.get("内容来源归属") == {"由程序绑定": True, "固定值": list(table)}):
        del unit["properties"]["来源"]
        unit["required"].remove("来源")
    entity = _对象({"类型": {"type": "string", "enum": ["角色", "场景", "道具"]}, "名称": text,
        "外观": text, "原文依据": text})
    from .项目设计 import 设计字段
    design = _对象({key: {**_数组(text), "description": "具体定稿的设计，区分原文事实与规划补全，无关时用空数组；声音方案在内容阶段确定，未指定角色的朗读与旁白统一女性配音；待证事项仅记录证据限制"} for key in 设计字段})
    schema = _对象({"内容单元": {**_数组(unit), "maxItems": maximum,
        "description": f"无真实需求冲突时返回1至{maximum}项；仅含需求说明的范围也记录约束单元及来源，汇总融入正文，不另造剧情。单元不等于镜头，相关事件可组织为同一单元，保留全部必留内容。"},
        "人物场景": {**_数组(entity), "maxItems": 40}, "保真说明": {**text},
        "项目设计": design, "冲突": {**_数组(text), "description": "仅报告输入资料确实缺失或真实需求矛盾。自己的来源、编号和JSON字段错误应按要求修正，不能作为用户需求冲突。"}})
    # 成功结果不能无内容；有真实冲突时仍允许空数组，不能为了满足格式虚构剧情。
    schema["anyOf"] = [
        {"properties": {"内容单元": {"minItems": 1}, "冲突": {"maxItems": 0}}},
        {"properties": {"冲突": {"minItems": 1}}},
    ]
    return schema


def _全剧模式(data):
    text = {"type": "string"}
    ids = data["范围顺序"]
    ranges = {**_数组({"type": "string", "enum": ids}), "minItems": 1, "maxItems": 4,
              "description": "仅引用范围顺序中的连续真实ID；所有集依次拼接须完整匹配范围顺序，不重复、不遗漏。"}
    episode = _对象({"名称": text, "范围": ranges, "衔接": text})
    entity = _对象({"类型": {"type": "string", "enum": ["角色", "场景", "道具"]}, "名称": text,
        "外观": text, "原文依据": text})
    from .项目设计 import 设计字段
    design = _对象({key: {**_数组(text), "description": "具体定稿的设计，区分原文事实与规划补全，无关时用空数组；声音方案在内容阶段确定，未指定角色的朗读与旁白统一女性配音；待证事项仅记录证据限制"} for key in 设计字段})
    episode_limits = data.get("分集范围约束", {}).get("分集数量", [(len(ids) + 3) // 4, min(len(ids), 120)])
    return _对象({"主线": text, "人物场景": {**_数组(entity), "maxItems": 40},
        "分集": {**_数组(episode), "minItems": episode_limits[0], "maxItems": episode_limits[1],
            "description": "剧集不是镜头或歌词段落；每个真实范围只分配一次，范围内的多个事件在本集内拆镜头。"},
        "项目设计": design, "冲突": _数组(text)})


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
    props.update(建议秒数={"type": "number"}, 内容单元={**_数组({"type": "string", "enum": ids} if ids else text), "minItems": 1}, 使用素材=materials)
    assignment = data.get("镜头内容单元归属")
    if (len(ids) == 1 and isinstance(assignment, dict) and assignment.get("由程序绑定") is True
            and assignment.get("固定值") == ids):
        del props["内容单元"]
    from .镜头设计 import 对象字段
    for key, fields in 对象字段.items():
        props[key] = _对象({field: text for field in fields})
    from .规划默认规则 import 声音字段, 声音输出要求
    props["声音设计"] = {"anyOf": [_对象({field: {**text, "minLength": 1} for field in 声音字段}), _对象({})],
                         "description": 声音输出要求}
    props["声音设计"]["anyOf"][0]["properties"]["语速"]["description"] = "新配音固定填写每秒4字，不按情绪另选语速；原音轨写明保留原音。"
    props["时长依据"] = _对象({**{key: {"type": "number"} for key in ("动作秒", "停顿秒", "反应秒")},
        "中文每秒字数": {"type": "number", "enum": [0, 4],
            "description": "有中文台词固定为4，即每秒4字；无中文台词可填0或4，不产生额外发音时长。"},
        "动作与台词": {"type": "string", "enum": ["同时", "先后"]}, "说明": text})
    props["素材职责"] = {**_数组(_对象({"文件": file, "职责": {"type": "string", "enum": ["身份", "场景", "道具", "风格", "构图", "首帧", "尾帧", "动作", "声音"]}, "限制": text})),
                        **({} if names else {"maxItems": 0})}
    shots = _数组(_对象(props))
    counts = [u.get("本批镜头数") for u in data["内容单元"] if isinstance(u, dict)]
    if counts and len(counts) == len(data["内容单元"]) and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in counts):
        shots.update(minItems=sum(counts), maxItems=sum(counts))
    return _对象({"镜头": shots, "冲突": _数组(text)})


def _验收引文(data):
    """枚举本次实际字段的短引文，避免模型拼接章节或给不存在的内容造出处。"""
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from strings(v)
        elif isinstance(value, list):
            for v in value:
                yield from strings(v)
    keys = ("需求", "原文资料", "镜头", "前批结尾", "内容计划", "全剧资料", "分集结果",
            "程序时长核验", "程序素材核验", "素材执行契约", "规划规则")
    quotes = []
    for text in strings({key: data[key] for key in keys if key in data}):
        if text.strip():
            quotes.append(text)
        quotes.extend(s.strip() for s in re.findall(r"[^。！？\n]+[。！？]?", text) if s.strip())
    return list(dict.fromkeys(quotes))


def 规划结构选项(cfg, system, user):
    host = (urlparse(str(cfg.get("base_url") or "")).hostname or "").lower()
    if host not in ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com") or str(cfg.get("model", "")).lower() != "qwen3.8-flash" or "你是视频内容规划师" not in system:
        return {}
    options = {"enable_thinking": False, "response_format": {"type": "json_object"}}
    try:
        data = json.loads(user) if isinstance(user, str) else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return options
    if isinstance(data.get("范围顺序"), list) and data["范围顺序"] and all(isinstance(sid, str) for sid in data["范围顺序"]):
        schema, name = _全剧模式(data), "planning_series"
    elif isinstance(data.get("原文"), list) or isinstance(data.get("分块理解"), list):
        schema, name = _内容模式(data), "planning_content"
    elif isinstance(data.get("内容单元"), list):
        schema, name = _镜头模式(data), "planning_shots"
    elif data.get("验收任务") not in ("分集自动验收", "全剧自动验收"):
        return options
    else:
        schema, name = None, "planning_review"
    quotes = _验收引文(data) if name == "planning_review" else []
    evidence = {"type": "string", "minLength": 1, **({"enum": quotes} if quotes else {})}
    start = data.get("镜头起号")
    shots = data.get("镜头")
    numbers = {"type": "integer"}
    if isinstance(start, int) and not isinstance(start, bool) and isinstance(shots, list) and shots:
        numbers.update(minimum=start, maximum=start + len(shots) - 1)
    issue = {"type": "object", "properties": {
        "范围": {"type": "string", "enum": ["内容", "镜头"]},
        "镜号": {"type": "array", "items": numbers},
        "缺陷类型": {"type": "string", "enum": list(缺陷类型)},
        "证据": {"type": "array", "minItems": 2, "maxItems": 4,
                 "items": evidence,
                 "description": "每项只填原文或当前字段的一段连续原句，逐字照抄；不加text/title前缀，不用省略号或摘要。不引用自己的风险推测或偏好。"},
        "说明": {"type": "string", "minLength": 1, "description": "明确证据，不写思考过程或不成立的风险"},
        "建议": {"type": "string", "minLength": 1, "description": "针对实际缺陷的修复，必须非空"}},
        "required": ["范围", "镜号", "缺陷类型", "证据", "说明", "建议"], "additionalProperties": False}
    schema = schema or {"type": "object", "properties": {
        "通过": {"type": "boolean"}, "问题": {"type": "array", "items": issue, "maxItems": 验收问题上限},
        "处理": {"type": "string", "enum": ["优化", "重新规划"]}},
        "required": ["通过", "问题", "处理"], "additionalProperties": False}
    options.update(response_format={"type": "json_schema", "json_schema": {
        "name": name, "strict": True, "schema": schema}})
    return options
