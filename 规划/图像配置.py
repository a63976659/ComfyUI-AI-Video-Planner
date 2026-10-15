# -*- coding: utf-8 -*-
"""独立生图模型清单；只选一个运行模型，不继承文本模型密钥。"""
from urllib.parse import urlsplit

from .配置 import _净化模型清单
from .本地配置 import 本地配置路径, 配置写入锁, 写本地配置
from .项目存储 import 读JSON


def 配置路径():
    return 本地配置路径("图像模型配置.json")


def 默认配置():
    return {"selected_id": "GPT-image2.5", "models": [{"id": "GPT-image2.5", "name": "GPT-image2.5",
        "base_url": "https://api.openai.com/v1", "model": "gpt-image-2.5-flare", "api_key": "", "builtin": True}]}


def 读图像配置():
    path = 配置路径()
    if not path.exists():
        return 默认配置()
    data = 读JSON(path)
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("图像模型配置损坏，请在设置中重新保存")
    return {"selected_id": data.get("selected_id", ""), "models": _净化模型清单(data["models"])}


def 脱敏图像配置(data=None):
    data = data if data is not None else 读图像配置()
    return {"selected_id": data["selected_id"], "models": [
        {**{k: v for k, v in m.items() if k != "api_key"}, "has_key": bool(m.get("api_key"))} for m in data["models"]]}


def 写图像配置(patch):
    if not isinstance(patch, dict) or not isinstance(patch.get("models"), list) or not 1 <= len(patch["models"]) <= 20:
        raise ValueError("图像模型清单须包含1到20项")
    if any(not isinstance(m, dict) for m in patch["models"]):
        raise ValueError("图像模型条目须为对象")
    with 配置写入锁(配置路径()):
        old = 读图像配置()
        models = _净化模型清单(patch["models"], old["models"])
        ids = [m["id"] for m in models]
        if len(set(ids)) != len(ids):
            raise ValueError("图像模型标识重复")
        for m in models:
            if any(not m[k] or len(m[k]) > limit for k, limit in (("name", 100), ("model", 200), ("base_url", 2000), ("id", 200))):
                raise ValueError("请填写图像模型名称、地址和模型名")
            p = urlsplit(m["base_url"])
            if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
                raise ValueError("图像API地址须为不含凭据和查询参数的http(s)地址")
        selected = patch.get("selected_id", "")
        if not isinstance(selected, str) or selected not in ids:
            raise ValueError("请选择一个图像模型；运行时不会自动切换其他API")
        result = {"selected_id": selected, "models": models}
        写本地配置(配置路径(), result)
        return 脱敏图像配置(result)


def 选中图像模型():
    data = 读图像配置()
    selected = next((m for m in data["models"] if m["id"] == data["selected_id"]), None)
    if not selected or not selected.get("base_url") or not selected.get("model"):
        raise ValueError("请在配置设置中勾选并配置一个图像模型")
    if not selected.get("api_key"):
        raise ValueError("选中的图像模型尚未配置API Key，请先保存图像配置")
    return dict(selected)
