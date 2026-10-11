# -*- coding: utf-8 -*-
"""本地专项规则检索与按阶段装配；不执行资料，不发模型请求。"""
import json
import re
from pathlib import Path

from .技能注册 import 技能根, _资料路径, 装配资料

目录位置 = "专项目录.json"
阶段集合 = frozenset(("输入归一", "内容规划", "镜头编排", "实体设计", "辅助图设计", "参考图验收", "规划验收", "模型适配"))


def 注册专项(root=None):
    root = Path(root or 技能根).resolve()
    path = _资料路径(root, 目录位置, (".json",))
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data["专项"]


def _取文本(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_取文本(x) for x in value)
    if isinstance(value, dict):
        text = "\n".join(_取文本(v) for k, v in value.items()
                         if k not in ("详细内容", "api_key", "token", "目录", "路径", "编码", "image_url"))
        if any(value.get(k) for k in ("对白", "旁白", "必留台词", "台词")):
            text += "\n口语对白与倾听"
        if re.search(r"(?:说|问|答|喊|低语)[：:]", text):
            text += "\n口语对白与倾听"
        return text
    return ""


def _命中(text, word, 模式=False):
    for match in re.finditer(word if 模式 else re.escape(word), text, re.I):
        prefix = text[max(0, match.start() - 16):match.start()]
        if not re.search(r"(?:不(?:要|用|需|需要|加|加入|添加|引入|含|包含|安排|生成|涉及|允许|应|得|出现)?|未(?:加|加入|添加|引入|安排|涉及|出现)?|没有|禁止(?:加|加入|添加|引入|安排|生成)?|无需(?:加|加入|添加|引入|安排|生成)?|无|勿)(?:任何|新增|新的)?[\s：:、]*$", prefix):
            return True
    return False


def 装配专项(阶段, 需求, 当前内容=None, root=None, 预算=None):
    if 阶段 not in 阶段集合:
        raise ValueError("未知专项装配阶段")
    if 预算 is not None and (isinstance(预算, bool) or not isinstance(预算, int) or 预算 < 0):
        raise ValueError("专项正文预算须为非负整数")
    root = Path(root or 技能根).resolve()
    context = _取文本(当前内容)
    requirement = _取文本(需求)
    candidates = []
    for item in 注册专项(root):
        if 阶段 not in item["适用阶段"]:
            continue
        matches = [word for word in item["触发词"] if _命中(context, word) or _命中(requirement, word)]
        contexts = item.get("触发上下文", [])
        keyword_hit = matches and (not contexts or any(_命中(context, word) or _命中(requirement, word) for word in contexts))
        patterns = [pattern for pattern in item.get("触发模式", [])
                    if _命中(context, pattern, True) or _命中(requirement, pattern, True)]
        if not item["基础"] and not keyword_hit and not patterns:
            continue
        score = int(item["基础"]) + sum(3 if _命中(context, word) else 1 for word in matches) + len(patterns)
        candidates.append((score, item))
    candidates.sort(key=lambda pair: (-pair[0], pair[1]["名称"]))
    items = []
    for _, item in candidates:
        name = "专项:" + item["名称"]
        items.append({**item, "技能": name})
        for reference in item.get("条件参考", []):
            if 阶段 not in reference.get("适用阶段", [阶段]):
                continue
            if any(_命中(context, word) or _命中(requirement, word) for word in reference["触发词"]):
                items.append({**reference, "技能": name + "/" + Path(reference["路径"]).stem,
                              "依赖资料": reference.get("依赖资料", item.get("依赖资料", []))})
    return 装配资料(items, 阶段, root, 预算)
