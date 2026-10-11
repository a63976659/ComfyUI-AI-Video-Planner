# -*- coding: utf-8 -*-
"""中文卡片注册和阶段装配；只读资料，不执行 Skills 中的程序。"""
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

技能根 = Path(__file__).resolve().parents[1] / "Skills"


def _资料路径(root, value, 后缀=(".md", ".txt")):
    if not isinstance(value, str) or not value or ":" in value:
        raise ValueError("技能资料必须是本地正文路径")
    relative = PurePosixPath(value.replace("\\", "/"))
    if (relative.is_absolute() or PureWindowsPath(value).drive
            or ".." in relative.parts or relative.suffix.lower() not in 后缀):
        raise ValueError("技能资料必须是目录内的本地文件")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in 后缀:
        raise ValueError("技能资料路径无效或越过 Skills 目录")
    return path


def 注册技能(root=None):
    root = Path(root or 技能根).resolve()
    cards = {}
    catalog = json.loads(_资料路径(root, "技能目录.json", (".json",)).read_text(encoding="utf-8-sig"))
    for item in catalog["技能"]:
        path = _资料路径(root, item["卡片"], (".json",))
        card = json.loads(path.read_text(encoding="utf-8-sig"))
        cards[item["技能标识"]] = {**card, "旧名称": item.get("旧名称", [])}
    return cards


def 装配资料(items, 阶段, root=None, 预算=None):
    root = Path(root or 技能根).resolve()
    catalog = json.loads(_资料路径(root, "共用规则/共用目录.json", (".json",)).read_text(encoding="utf-8-sig"))
    common = {item["资料标识"]: item for item in catalog["资料"]}
    files, seen, selected = [], set(), set()
    def add_file(name, value):
        path = _资料路径(root, value)
        if path not in seen:
            seen.add(path)
            files.append((name, path))
    def add_common(key):
        if key in selected:
            return
        selected.add(key)
        item = common[key]
        if 阶段 is not None and 阶段 not in item.get("适用阶段", [阶段]):
            return
        for dep in item.get("依赖资料", []):
            add_common(dep)
        add_file(key, item["路径"])
    for key in [*catalog.get("系统规则", []), *catalog.get("阶段系统规则", {}).get(阶段, [])]:
        add_common(key)
    for item in items:
        if 阶段 is not None and 阶段 not in item.get("适用阶段", [阶段]):
            continue
        for dep in [*catalog.get("正文依赖", {}).get(item["路径"], []), *item.get("依赖资料", [])]:
            add_common(dep)
        add_file(item["技能"], item["路径"])
    docs, used = [], 0
    receipt = {"included": [], "truncated": [], "skipped": [], "missing": []}
    for name, path in files:
        text = path.read_text(encoding="utf-8-sig")
        used += len(text)
        if 预算 is not None and used > 预算:
            raise ValueError("本阶段必要技能资料超过安全预算；请按内容单元分批")
        docs.append({"技能": name, "资料": text})
        receipt["included"].append(name)
    return docs, receipt


def 合并技能资料(*groups):
    return list({doc["技能"]: doc for group in groups for doc in group}.values())


def 装配技能(cards, 阶段, 输入类型, 体裁, 改写, root=None, 预算=None):
    root = Path(root or 技能根).resolve()
    selected, seen = [], set()
    def add(key):
        if key in seen:
            return
        seen.add(key)
        card = cards[key]
        for dep in card.get("依赖技能", []):
            add(dep["技能标识"])
        selected.append(key)
    for key, card in cards.items():
        if 阶段 not in card.get("适用阶段", []):
            continue
        if 阶段 == "输入归一" and card.get("处理方式") == "规则路由":
            add(key)
            continue
        if card.get("处理方式") != "模型内容处理":
            continue
        if 输入类型 != "混合输入" and 输入类型 not in card.get("输入类型", []):
            continue
        if 体裁 not in card.get("目标体裁", []) or 改写 not in card.get("改写方式", []):
            continue
        add(key)
    items = []
    for key in selected:
        card = cards[key]
        for doc in sorted(card["资料文件"], key=lambda d: -d.get("优先级", 0)):
            name = card["显示名称"]
            if Path(doc["路径"]).stem != "技能说明":
                name += "/" + Path(doc["路径"]).stem
            items.append({**doc, "技能": name})
    return 装配资料(items, 阶段, root, 预算)
