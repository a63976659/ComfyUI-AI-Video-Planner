"""仅修复有原始摘要与设计记录的自动参考资产，保留用户文件。"""
import asyncio
import copy
from pathlib import Path

from .工具 import 安全媒体路径, 文件摘要
from .成片审查 import 可停止请求, 取审片模型
try:
    from ..规划.图像配置 import 选中图像模型
    from ..规划.异步请求 import 异步模型请求
    from ..规划.项目存储 import 项目存储
    from ..规划.自动规划 import 自动流程
    from ..规划.参考图规划 import 参考图流程
    from ..规划.专项能力配置 import 读专项配置
except ImportError:
    from 规划.图像配置 import 选中图像模型
    from 规划.异步请求 import 异步模型请求
    from 规划.项目存储 import 项目存储
    from 规划.自动规划 import 自动流程
    from 规划.参考图规划 import 参考图流程
    from 规划.专项能力配置 import 读专项配置


async def 修订参考资产(project, report, source, root, media_root, cancel, 模型id="", 模型=None, 图片生成=None, 图像模型=None, 进度=None):
    shots = {s["id"]: s for s in project["镜头"]}
    materials = {m["名"]: m for m in source.get("素材", [])}
    entities = {e["id"]: e for e in source.get("实体", [])}
    requests = {}
    for row in report["镜头验收"]:
        for issue in row["问题"]:
            if issue.get("层级") != "资产":
                continue
            name = issue["素材"]
            if name not in shots[row["id"]].get("参考图", []):
                raise ValueError("资产问题未对应实际绑定参考，不自动改图")
            material = materials.get(name, {})
            entity = entities.get(material.get("实体id"))
            if not material.get("生成参考图") or material.get("辅助图类型") or not entity or not material.get("摘要"):
                raise ValueError("资产缺少自动生成设计或原始摘要，保留用户素材，不擅自生图替换")
            if await asyncio.to_thread(文件摘要, 安全媒体路径(media_root, name)) != material["摘要"]:
                raise ValueError("参考图已被用户修改，保留修改，不自动覆盖")
            requests.setdefault(name, {"实体": entity, "问题": []})["问题"].append(issue)
    if not requests:
        return [], []
    if len(requests) > 8:
        raise ValueError("本轮资产返修超过8张安全上限，已保存问题，未自动扩大生图预算")
    affected = [s for s in project["镜头"] if any(name in requests for name in s.get("参考图", []))]
    if any(s["来源"] != "工作流" for s in affected):
        raise ValueError("资产返修影响用户绑定镜头，保留原资产和用户素材")
    entry = 图像模型 or 选中图像模型()
    original_api = source.get("模型", {})
    changed = entry["id"] != original_api.get("id")
    for key in ("model", "base_url"):
        if original_api.get(key):
            changed |= str(entry.get(key, "")).rstrip("/") != str(original_api[key]).rstrip("/")
    if changed:
        raise ValueError("选中生图API已变更，不自动用其他API修复原资产")
    if 模型 is None:
        async with 异步模型请求(取审片模型(模型id), 总超时=120, 仅正文=True) as model:
            return await 修订参考资产(project, report, source, root, media_root, cancel, 模型id, model, 图片生成, entry, 进度)
    async def cancellable(system, messages):
        return await 可停止请求(模型, system, messages, cancel)
    plan = {"brief": {"主题": "成片参考资产局部返修"}, "资产问题": requests, "原始模型": entry["id"]}
    checkpoint = 项目存储(Path(root)/"资产返修检查点").打开(plan, {"版本": 1})
    checkpoint.更新(调用上限=48)
    flow = 自动流程(checkpoint, cancellable, 进度 or (lambda _: None))
    if 图片生成 is None:
        try:
            from ..规划.图像请求 import 生成图像
        except ImportError:
            from 规划.图像请求 import 生成图像
        图片生成 = 生成图像
    async def generate(selected, prompt, 请求回调):
        async def request(*_):
            return await 图片生成(selected, prompt, 请求回调=请求回调)
        return await 可停止请求(request, "", "", cancel)
    reference = 参考图流程(flow, entry, generate, media_root)
    reference.辅助图.cfg = 读专项配置()
    replacements, records = {}, []
    for name, request in requests.items():
        if cancel.is_set():
            raise InterruptedError("资产返修已停止")
        material = await reference.辅助图._生成("实体参考修复", request, source.get("画风", "电影写实"))
        material.pop("辅助图类型", None)
        material.update(实体id=request["实体"]["id"], 原资产=name,
            名称=request["实体"]["名称"], 实体类型=request["实体"]["类型"],
            参考职责=materials[name].get("参考职责", "身份"),
            职责限制=materials[name].get("职责限制", "仅按冻结分镜的原参考职责使用"))
        replacements[name] = material["名"]
        records.append(material)
    if cancel.is_set():
        raise InterruptedError("资产返修已停止")
    for shot in affected:
        shot["参考图"] = [replacements.get(name, name) for name in shot["参考图"]]
    return [s["id"] for s in affected], copy.deepcopy(records)
