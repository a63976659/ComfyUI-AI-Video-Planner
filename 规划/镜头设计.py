# -*- coding: utf-8 -*-
"""中性镜头资料的有界契约和表演估时，不调用模型或生成媒体。"""
import math
import re
from .规划默认规则 import 声音字段, 中文发音字数, 统一配音语速

设计版本 = 4
文字字段 = ("镜头目的", "切镜理由", "起始状态", "结束状态")
对象字段 = {
    "表演设计": ("目标", "阻力", "策略", "可见行为", "倾听反应"),
    "运镜设计": ("方式", "动机", "起点", "路径", "终点"),
    "连续性": ("场景", "时间关系", "空间锚点", "人物站位", "视线", "持物状态", "光线", "轴线说明", "证据限制"),
}
素材角色 = {"身份", "场景", "道具", "风格", "构图", "首帧", "尾帧", "动作", "声音"}


def _文本(value, name, limit=1000, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{name}须为{'非空' if required else ''}文本")
    return value.strip()


def _数(value, name, lo=0, hi=120):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name}须为{lo}..{hi}的有限秒数或速率")
    return float(value)


def 校验镜头设计(shot, 强制=False, 强制声音=False):
    clean = {}
    fallback = {"镜头目的": shot.get("职能")}
    movement = shot.get("运镜设计")
    if isinstance(movement, dict):
        fallback.update({"起始状态": movement.get("起点"), "结束状态": movement.get("终点")})
    for key in 文字字段:
        value = shot.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            value = fallback.get(key, value)
        if key in shot or value is not None or (强制 and key != "切镜理由"):
            clean[key] = _文本(value, key, required=强制 and key != "切镜理由")
    for key, fields in 对象字段.items():
        if key not in shot:
            continue
        value = shot[key]
        if not isinstance(value, dict):
            raise ValueError(f"{key}须为对象")
        clean[key] = {k: _文本(value[k], f"{key}.{k}") for k in fields if k in value}
    speech = any(isinstance(shot.get(k), str) and shot[k].strip() for k in ("对白", "旁白", "台词"))
    chinese = bool(re.search(r"[\u3400-\u9fff]", "".join(shot[k] for k in ("对白", "旁白", "台词") if isinstance(shot.get(k), str))))
    if "声音设计" in shot or (强制声音 and speech):
        voice = shot.get("声音设计")
        if not isinstance(voice, dict) or set(voice) - set(声音字段):
            raise ValueError("声音设计须为包含说话人、声源、声线、语言、语速、情绪、停顿重音的对象")
        if voice or speech:
            clean["声音设计"] = {k: _文本(voice.get(k), f"声音设计.{k}", required=True) for k in 声音字段}
            if not re.search(r"原(?:声|音)|(?:保留|沿用).{0,8}音轨", clean["声音设计"]["声源"]):
                clean["声音设计"]["语速"] = 统一配音语速
        else:
            clean["声音设计"] = {}
    if "时长依据" in shot:
        value = shot["时长依据"]
        if not isinstance(value, dict):
            raise ValueError("时长依据须为对象")
        timing = {k: _数(value[k], k) for k in ("动作秒", "停顿秒", "反应秒") if k in value}
        if "中文每秒字数" in value:
            timing["中文每秒字数"] = 中文发音字数 if chinese else 0
        relation = value.get("动作与台词", "同时")
        if relation == "无台词" and not (shot.get("对白", "") + shot.get("旁白", "")).strip():
            relation = "同时"
        if not isinstance(relation, str) or relation not in ("同时", "先后"):
            raise ValueError("动作与台词须为同时或先后")
        timing["动作与台词"] = relation
        if "说明" in value:
            timing["说明"] = _文本(value["说明"], "估时说明")
        clean["时长依据"] = timing
    if chinese:
        clean.setdefault("时长依据", {})["中文每秒字数"] = 中文发音字数
    if "素材职责" in shot:
        values = shot["素材职责"]
        names = shot.get("使用素材", [])
        if not isinstance(values, list) or len(values) > 40:
            raise ValueError("素材职责须为最多40项的数组")
        roles = []
        for value in values:
            if (not isinstance(value, dict) or not isinstance(value.get("文件"), str)
                    or not isinstance(value.get("职责"), str) or value["文件"] not in names or value["职责"] not in 素材角色):
                raise ValueError("素材职责须引用本镜头使用的真实素材及合法职责")
            roles.append({"文件": value["文件"], "职责": value["职责"],
                          "限制": _文本(value.get("限制", ""), "素材限制", 500)})
        clean["素材职责"] = roles
    return clean


def 最低表演秒数(shot):
    timing = 校验镜头设计(shot).get("时长依据", {})
    speech = shot.get("对白", "") + shot.get("旁白", "")
    if not speech:
        speech = shot.get("台词", "")
    # 全部发声文字统一4字/秒；标点与空白不占发音字数，停顿另计。
    voice = sum(char.isalnum() for char in speech) / 中文发音字数
    action = timing.get("动作秒", 0)
    # 停顿、倾听反应是未包含在动作/发音中的独立留白，不能重复记账。
    body = voice + action if timing.get("动作与台词") == "先后" else max(voice, action)
    return body + timing.get("停顿秒", 0) + timing.get("反应秒", 0)


def 动作专项适用(units):
    text = "\n".join(u.get("内容", "") for u in units)
    return bool(re.search(r"搏斗|格斗|打斗|交战|追逐|追击|挥拳|踢击|挥剑|劈砍|挡住.*(?:拳|刀|剑)|(?:拳|刀|剑).*(?:击中|命中)", text))
