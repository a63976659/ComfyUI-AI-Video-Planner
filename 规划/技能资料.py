import json
from pathlib import Path, PurePosixPath, PureWindowsPath


技能根 = Path(__file__).resolve().parents[1] / "Skills"


def 本地路径(root, value, suffixes=(".md", ".txt"), 根文件=False):
    root = Path(root).resolve()
    if not isinstance(value, str) or not value or ":" in value:
        raise ValueError("技能资料必须是本地正文路径")
    relative = PurePosixPath(value.replace("\\", "/"))
    if (relative.is_absolute() or PureWindowsPath(value).drive or ".." in relative.parts
            or (not 根文件 and len(relative.parts) < 2) or relative.suffix.lower() not in suffixes):
        raise ValueError("技能资料路径无效")
    path = (root / relative).resolve()
    if (not path.is_relative_to(root) or (not 根文件 and path.parent == root)
            or path.suffix.lower() not in suffixes or not path.is_file()):
        raise ValueError(f"技能资料路径无效或文件缺失：{value}")
    return path


def _资料路径(root, value):
    return 本地路径(root, value)


def 读取正文(root, value):
    text = _资料路径(root, value).read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError(f"必需技能资料正文为空：{value}")
    return text


def 读取目录(root, value):
    data = json.loads(本地路径(root, value, (".json",), True).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("格式版本") != 1:
        raise ValueError(f"技能目录格式不支持：{value}")
    return data


def 共用目录(root=None):
    root = Path(root or 技能根).resolve()
    data = 读取目录(root, "共用规则/共用目录.json")
    rows = data.get("资料")
    if not isinstance(rows, list):
        raise ValueError("共用资料目录格式无效")
    entries, paths = {}, set()
    for row in rows:
        key = row.get("资料标识") if isinstance(row, dict) else None
        if not isinstance(key, str) or not key.startswith("共用:") or key in entries:
            raise ValueError("共用资料标识无效或重复")
        path = _资料路径(root, row.get("路径"))
        if path in paths:
            raise ValueError("共用资料正文路径重复")
        entries[key] = row
        paths.add(path)
    def visit(key, stack):
        if key in stack:
            raise ValueError("共用资料依赖存在循环")
        if key not in entries:
            raise ValueError(f"缺少共用依赖资料：{key}")
        deps = entries[key].get("依赖资料", [])
        if not isinstance(deps, list):
            raise ValueError("共用资料依赖须为数组")
        for dep in deps:
            visit(dep, stack + [key])
    for key in entries:
        visit(key, [])
    for deps in data.get("正文依赖", {}).values():
        for dep in deps:
            visit(dep, [])
    return data, entries


def 读取共用(keys, 阶段=None, root=None, _目录=None, _正文=None):
    root = Path(root or 技能根).resolve()
    _, entries = 共用目录(root) if _目录 is None else _目录
    selected = []
    def add(key):
        if key not in entries:
            raise ValueError(f"缺少共用依赖资料：{key}")
        row = entries[key]
        if 阶段 is not None and row.get("适用阶段") and 阶段 not in row["适用阶段"]:
            return
        if key in selected:
            return
        for dep in row.get("依赖资料", []):
            add(dep)
        selected.append(key)
    for key in keys:
        add(key)
    texts = {} if _正文 is None else _正文
    for key in selected:
        if key not in texts:
            texts[key] = 读取正文(root, entries[key]["路径"])
    return [{"技能": key, "资料": texts[key]} for key in selected]


def 资料依赖(paths, keys=(), 阶段=None, root=None, _目录=None, _正文=None):
    root = Path(root or 技能根).resolve()
    catalog = 共用目录(root) if _目录 is None else _目录
    data, _ = catalog
    needed = list(keys)
    for value in paths:
        needed.extend(data.get("正文依赖", {}).get(value, []))
    return 读取共用(needed, 阶段, root, catalog, _正文)


def 合并资料(docs, 预算=None, 系统正文=""):
    if 预算 is not None and (isinstance(预算, bool) or not isinstance(预算, int) or 预算 < 0):
        raise ValueError("技能正文预算须为非负整数")
    result, seen, used = [], set(), 0
    for doc in docs:
        text = doc["资料"]
        if text in seen or text in 系统正文:
            continue
        seen.add(text)
        used += len(text)
        if 预算 is not None and used > 预算:
            raise ValueError("本阶段必要技能正文超过安全预算；不能截断细则或静默遗漏技能，请按内容单元分批")
        result.append(doc)
    return result


def 请求资料去重(payload, system):
    payload = dict(payload)
    seen = system
    for key in ("技能资料", "专项设计资料", "模型编译规则"):
        if isinstance(payload.get(key), list):
            docs = 合并资料(payload[key], 系统正文=seen)
            payload[key] = docs
            seen += "\n" + "\n".join(doc["资料"] for doc in docs)
    return payload
