# -*- coding: utf-8 -*-
"""本地专项规则检索与按阶段装配；不执行资料，不发模型请求。"""
import re
from pathlib import Path

from .技能注册 import 技能根, _资料路径
from .技能资料 import 读取目录, 读取正文, 资料依赖, 合并资料, 共用目录

目录位置 = "专项目录.json"
阶段集合 = frozenset(("内容规划", "镜头编排", "实体设计", "辅助图设计", "参考图验收", "规划验收", "模型适配"))


def 注册专项(root=None):
    root = Path(root or 技能根).resolve()
    data = 读取目录(root, 目录位置)
    common = 共用目录(root)
    if not isinstance(data, dict) or data.get("格式版本") != 1 or not isinstance(data.get("专项"), list):
        raise ValueError("专项目录格式不支持")
    names, paths = set(), set()
    for item in data["专项"]:
        if not isinstance(item, dict) or not isinstance(item.get("名称"), str) or not item["名称"].strip():
            raise ValueError("专项名称无效")
        _资料路径(root, item.get("路径"))
        if item.get("入口"):
            _资料路径(root, item["入口"])
        for path in item.get("附加资料", []):
            _资料路径(root, path)
        for reference in item.get("条件参考", []):
            _资料路径(root, reference.get("路径"))
            if not isinstance(reference.get("触发词", []), list):
                raise ValueError("条件参考触发词须为数组")
        for pattern in item.get("触发模式", []):
            try:
                re.compile(pattern)
            except (re.error, TypeError) as error:
                raise ValueError("专项触发模式无效") from error
        dependencies = list(item.get("依赖资料", []))
        for value in [item["路径"], *(ref["路径"] for ref in item.get("条件参考", []))]:
            dependencies.extend(common[0].get("正文依赖", {}).get(value, []))
        for dep in dependencies:
            if dep not in common[1]:
                raise ValueError(f"缺少共用依赖资料：{dep}")
        if item["名称"] in names or item["路径"] in paths:
            raise ValueError("专项名称或正文路径重复")
        for key in ("触发词", "适用阶段"):
            if not isinstance(item.get(key), list) or any(not isinstance(v, str) or not v.strip() for v in item[key]):
                raise ValueError("专项阶段或触发词须为文本数组")
        if not item["适用阶段"] or set(item["适用阶段"]) - 阶段集合 or not isinstance(item.get("基础"), bool):
            raise ValueError("专项阶段或基础标记无效")
        names.add(item["名称"])
        paths.add(item["路径"])
    return data["专项"]


def _取文本(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_取文本(x) for x in value)
    if isinstance(value, dict):
        text = "\n".join((f"{k}：" if k in ("对白", "旁白", "必留台词", "台词") and v else "") + _取文本(v)
                         for k, v in value.items()
                         if k not in ("详细内容", "api_key", "token", "目录", "路径", "编码", "image_url"))
        return text
    return ""


def _命中(text, word):
    for match in re.finditer(re.escape(word), text, re.I):
        prefix = text[max(0, match.start() - 16):match.start()]
        if not re.search(r"(?:不(?:要|用|需|需要|加|加入|添加|引入|含|包含|安排|生成|涉及|允许|应|得|出现)?|未(?:加|加入|添加|引入|安排|涉及|出现)?|没有|禁止(?:加|加入|添加|引入|安排|生成)?|无需(?:加|加入|添加|引入|安排|生成)?|无|勿)(?:任何|新增|新的)?(?:刀|剑|长枪|棍|与|和|及|、)*[\s：:、]*$", prefix):
            return True
    return False


def _专项命中(item, text):
    words = [word for word in item.get("触发词", []) if _命中(text, word)]
    if any(_命中(text, match.group()) for pattern in item.get("触发模式", [])
           for match in re.finditer(pattern, text, re.I)):
        return True
    contexts = item.get("触发上下文", [])
    return bool(words) and (not contexts or any(_命中(text, word) for word in contexts))


def 装配专项(阶段, 需求, 当前内容=None, root=None, 预算=None):
    if 阶段 not in 阶段集合:
        raise ValueError("未知专项装配阶段")
    if 预算 is not None and (isinstance(预算, bool) or not isinstance(预算, int) or 预算 < 0):
        raise ValueError("专项正文预算须为非负整数")
    root = Path(root or 技能根).resolve()
    common, common_texts = 共用目录(root), {}
    context = _取文本(当前内容)
    requirement = _取文本(需求)
    candidates, receipt = [], {"included": [], "truncated": [], "skipped": [], "missing": []}
    for item in 注册专项(root):
        if 阶段 not in item["适用阶段"]:
            continue
        matches = [word for word in item["触发词"] if _命中(context, word) or _命中(requirement, word)]
        if not item["基础"] and not (_专项命中(item, context) or _专项命中(item, requirement)):
            continue
        score = int(item["基础"]) + sum(3 if _命中(context, word) else 1 for word in matches)
        candidates.append((score, item))
    candidates.sort(key=lambda pair: (-pair[0], pair[1]["名称"]))
    docs, used = [], 0
    for _, item in candidates:
        paths = list(dict.fromkeys([item["路径"], *item.get("附加资料", [])]))
        for reference in item.get("条件参考", []):
            if 阶段 not in reference.get("适用阶段", [阶段]):
                continue
            if any(_命中(text, word) for word in reference.get("触发词", []) for text in (context, requirement)):
                paths.append(reference["路径"])
        paths = list(dict.fromkeys(paths))
        text = "\n".join(读取正文(root, path) for path in paths)
        used += len(text)
        if 预算 is not None and used > 预算:
            raise ValueError("本阶段必要专项正文超过安全预算；不能截断细则或静默遗漏专项，请按内容单元分批")
        name = "专项:" + item["名称"]
        docs.append({"技能": name, "资料": text})
        receipt["included"].append(name)
        docs.extend(资料依赖(paths, item.get("依赖资料", []), 阶段, root, common, common_texts))
    docs = 合并资料(docs, 预算)
    receipt["included"] = [doc["技能"] for doc in docs]
    return docs, receipt
