# -*- coding: utf-8 -*-
"""中文卡片注册和阶段装配；只读资料，不执行 Skills 中的程序。"""
import json
from pathlib import Path

from .技能资料 import (_资料路径, 本地路径, 读取目录, 读取正文, 资料依赖, 合并资料, 共用目录)

技能根 = Path(__file__).resolve().parents[1] / "Skills"
适配根 = Path(__file__).resolve().parent / "技能适配"


def 注册技能(root=None):
    root = Path(root or 技能根).resolve()
    cards = {}
    common = 共用目录(root) if ((root / "技能目录.json").is_file()
                              or (root / "共用规则/共用目录.json").is_file()) else None
    if (root / "技能目录.json").is_file():
        entries = 读取目录(root, "技能目录.json").get("技能")
        if not isinstance(entries, list):
            raise ValueError("技能目录须包含技能数组")
        records = [(本地路径(root, item["卡片"], (".json",)), item) for item in entries]
    elif root != 技能根.resolve():
        records = [(p, {}) for p in sorted(root.glob("*/技能卡片.json"))]
    else:
        raise ValueError("缺少技能目录.json")
    for p, entry in records:
        card = json.loads(p.read_text(encoding="utf-8-sig"))
        name = p.parent.name
        if card.get("技能标识") != "技能:" + name or card.get("适用范围") != "仅限AI规划":
            raise ValueError(f"技能卡片不合法：{name}")
        if card.get("格式版本") != 1 or not isinstance(card.get("资料文件"), list):
            raise ValueError(f"技能格式不支持：{name}")
        for doc in card["资料文件"]:
            _资料路径(root, doc["路径"])
            if common is not None:
                for dep in [*doc.get("依赖资料", []), *common[0].get("正文依赖", {}).get(doc["路径"], [])]:
                    if dep not in common[1]:
                        raise ValueError(f"缺少共用依赖资料：{dep}")
        if entry and entry.get("技能标识") != card["技能标识"]:
            raise ValueError(f"技能目录与卡片标识不一致：{name}")
        if card["技能标识"] in cards:
            raise ValueError(f"技能标识重复：{name}")
        card = {**card, "旧名称": entry.get("旧名称", [])}
        cards[card["技能标识"]] = card
    def visit(key, stack):
        if key in stack:
            raise ValueError("技能依赖存在循环")
        if key not in cards:
            raise ValueError(f"缺少依赖技能：{key}")
        for dep in cards[key].get("依赖技能", []):
            visit(dep["技能标识"], stack + [key])
    for key in cards:
        visit(key, [])
    return cards


def 解析技能(cards, name):
    if name in cards:
        return cards[name]
    label = name.removeprefix("技能:")
    for card in cards.values():
        if label in (card["显示名称"], *card.get("旧名称", [])):
            return card
    raise ValueError(f"未知的 Skills 技能: {name}")


def 装配技能(cards, 阶段, 输入类型, 体裁, 改写, root=None, 预算=None):
    if 预算 is not None and (isinstance(预算, bool) or not isinstance(预算, int) or 预算 < 0):
        raise ValueError("技能正文预算须为非负整数")
    root = Path(root or 技能根).resolve()
    common = 共用目录(root) if ((root / "技能目录.json").is_file()
                              or (root / "共用规则/共用目录.json").is_file()) else None
    common_texts = {}
    selected = []
    def add(key):
        if key in selected:
            return
        card = cards[key]
        if 阶段 not in card.get("适用阶段", []):
            return
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
        target = {"技能:产品卖点到展示分镜": "产品广告", "技能:资料与科普讲解分镜": "科普讲解"}.get(key)
        if target is not None and 体裁 != target:
            continue
        if 输入类型 not in card.get("输入类型", []):
            continue
        if 体裁 not in card.get("目标体裁", []) or 改写 not in card.get("改写方式", []):
            continue
        add(key)
    docs, used, receipt = [], 0, {"included": [], "truncated": [], "skipped": [], "missing": []}
    for key in selected:
        card = cards[key]
        parts, paths, dependencies = [], [], []
        for doc in sorted(card["资料文件"], key=lambda d: -d.get("优先级", 0)):
            if doc.get("用途") == "技能入口" or 阶段 not in doc.get("适用阶段", [阶段]):
                continue
            paths.append(doc["路径"])
            dependencies.extend(doc.get("依赖资料", []))
            parts.append(读取正文(root, doc["路径"]))
        text = "\n".join(parts)
        name = card["显示名称"]
        if not text:
            continue
        used += len(text)
        if 预算 is not None and used > 预算:
            raise ValueError("本阶段必要技能正文超过安全预算；不能截断细则或静默遗漏技能，请按内容单元分批")
        receipt["included"].append(name)
        docs.append({"技能": name, "资料": text})
        if common is not None:
            docs.extend(资料依赖(paths, dependencies, 阶段, root, common, common_texts))
    docs = 合并资料(docs, 预算)
    receipt["included"] = [doc["技能"] for doc in docs]
    return docs, receipt
