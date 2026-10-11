# -*- coding: utf-8 -*-
"""多视图、空间草图和分镜预览；独立图片，不改变原分镜或素材槽位。"""
import asyncio
import hashlib
import json

from .规划器 import 提取JSON
from .项目存储 import 指纹, 写JSON
from .专项技能 import 装配专项


def 验图报告(data):
    """仅兼容独立报告读取；辅助图生成流程不调用AI验收或自动重画。"""
    if not isinstance(data, dict) or not isinstance(data.get("通过"), bool):
        raise ValueError("辅助图验收缺少布尔结论")
    issues, advice = data.get("问题"), data.get("建议")
    if not isinstance(issues, list) or len(issues) > 12 or any(not isinstance(x, str) or not x.strip() or len(x) > 800 for x in issues):
        raise ValueError("辅助图问题格式无效")
    if not isinstance(advice, str) or len(advice) > 2000 or (not data["通过"] and not advice.strip()) or data["通过"] == bool(issues):
        raise ValueError("辅助图结论、问题与建议矛盾")
    return {"通过": data["通过"], "问题": issues, "建议": advice, "证据范围": "真实静态缩图，不能证明完整视频动作与声音"}


class 辅助图流程:
    def __init__(self, reference, 配置):
        self.reference, self.cfg = reference, 配置
        self.flow, self.root = reference.flow, reference.root
        self.分集素材 = {}

    async def _生成(self, kind, design, style, baseline=()):
        from .参考图规划 import 保存图片, 保存已收到结果
        project = self.flow.project
        payload = {"生成流程版本": 2, "类型": kind, "设计": design, "画风": style,
                   "模型": {k: self.reference.entry[k] for k in ("id", "base_url", "model")},
                   "参考摘要": {name: hashlib.sha256((self.root/name).read_bytes()).hexdigest() for name in baseline}}
        cached = await project.读取("辅助图成果", payload)
        if isinstance(cached, dict):
            path = self.root / cached.get("名", "")
            if not path.is_symlink() and path.is_file() and path.resolve().is_relative_to(self.root) and path.stat().st_size <= 32*1024*1024 and hashlib.sha256(path.read_bytes()).hexdigest() == cached.get("摘要"):
                return cached
        docs = 装配专项("辅助图设计", {"主题": kind}, design)[0]
        prompt = (f"生成单张{kind}。画风：{style}。不绘制文字、水印、拼图。保持原角色服装、道具与空间关系。\n"
                  + json.dumps(design, ensure_ascii=False) + "\n" + "\n".join(x["资料"] for x in docs))
        self.flow.进度({"阶段": "生成" + kind})
        prompt += "\n在本次生成中核对主体完整、服装道具、站位遮挡、视图方向与原定事件，正确后提交唯一图片。白模只表达空间，不替换真实角色外观；只按已定设计生成，不添加无据细节。"
        name = kind + "_" + project.id[:10] + "_" + 指纹(payload)[:16] + ".png"
        path = self.root / name
        file_state = await project.读取("辅助图文件", payload)
        valid = (isinstance(file_state, dict) and file_state.get("名") == name and not path.is_symlink()
                 and path.is_file() and path.stat().st_size <= 32*1024*1024
                 and hashlib.sha256(path.read_bytes()).hexdigest() == file_state.get("摘要"))
        if not valid:
            def counted():
                project.计次()
                project.更新(图像请求=project.记录.get("图像请求", 0)+1)
            raw = await self.reference.生图(self.reference.entry, prompt, 请求回调=counted)
            async def persist():
                await asyncio.to_thread(保存图片, self.root, name, raw)
                await project.保存("辅助图文件", payload, {"名": name, "摘要": hashlib.sha256(raw).hexdigest()})
            await 保存已收到结果(persist())
        material = {"名": name, "摘要": hashlib.sha256(path.read_bytes()).hexdigest(), "类型": "图像", "生成参考图": True,
                    "辅助图类型": kind, "设计": design, "画风": style, "生成完成": True,
                    "参考职责": "空间" if kind == "空间草图" else "构图" if kind == "分镜预览" else "身份" if kind == "角色多视图" else "场景",
                    "职责限制": "辅助设计资料，未执行AI验收；不自动作为首尾帧，不把白模外观或草图笔触带入成片"}
        await project.保存("辅助图成果", payload, material)
        return material

    async def 实体多视图(self, brief, result):
        if self.cfg["辅助图"] == "关闭":
            return
        text = json.dumps({k: v for k, v in brief.items() if k not in ("详细内容", "素材理解", "本地美术参考")}, ensure_ascii=False)
        detailed = brief.get("详细内容", "")
        all_ = self.cfg["辅助图"] == "全部"
        requests = []
        for entity in result["实体"]:
            if entity["类型"] == "角色" and (all_ or any(x in text+detailed for x in ("多视图", "三视图", "角色侧面", "角色背面"))):
                requests.extend(("角色多视图", {**entity, "方向": view}) for view in ("侧面全身", "背面全身"))
            if entity["类型"] == "场景" and (all_ or any(x in text+detailed for x in ("多方向", "四方向", "场景多视图"))):
                requests.extend(("场景多方向", {**entity, "方向": view, "要求": "改变观察方向，保持同一房间地标与结构"}) for view in ("向左观察", "向右观察", "反向观察"))
        capacity = min(self.cfg["辅助图上限"], 40-len(brief.get("素材", []))-len(result["素材"]))
        if len(requests) > capacity:
            from .参考图规划 import 参考图错误
            raise 参考图错误("完整多视图超过辅助图或素材容量上限；已保留实体图，不擅自遗漏视图")
        for kind, design in requests:
            baseline = [m["名"] for m in result["素材"] if m.get("实体id") == design["id"]][:1]
            item = await self._生成(kind, design, result["画风"], baseline)
            item["实体id"] = design["id"]
            result["素材"].append(item)
            result["素材理解"][item["名"]] = {"描述": "已生成辅助多视图；设计是制作依据，不代表已观察实际图像或通过AI验收。", "限制": [item["职责限制"]], "取样说明": "静态辅助图，未执行AI验收"}
            result.setdefault("辅助图", []).append(item)
            self.reference._发布(result, "实体多视图", len(result["辅助图"]), len(requests))

    async def 分镜辅助图(self, brief, result):
        if self.cfg["辅助图"] == "关闭":
            return []
        all_ = self.cfg["辅助图"] == "全部"
        selected = []
        for i, shot in enumerate(result["segments"]):
            text = json.dumps(shot.get("镜头资料", {}), ensure_ascii=False)
            if all_ or any(x in text for x in ("打斗", "攻防", "追逐", "多人", "群体", "绕行", "环绕", "空间草图", "分镜预览")):
                selected.append((i, shot))
        if not all_:
            selected = selected[:2]
        reference = self.reference.结果
        others = [x for episode, items in self.分集素材.items() if episode != (self.flow.集号 or 1) for x in items]
        used = len(reference.get("辅助图", [])) + len(others)
        capacity = min(self.cfg["辅助图上限"]-used, 40-len(brief.get("素材", []))-len(reference["素材"])-len(others))
        if len(selected)*2 > capacity:
            if all_:
                from .参考图规划 import 参考图错误
                raise 参考图错误("全部分镜预览及空间草图超过本次辅助图容量；已保存分镜，不自动扩大发图预算")
            selected = selected[:max(0, capacity//2)]
        items = []
        for i, shot in selected:
            names = [m["名"] for m in reference["素材"] if not m.get("辅助图类型") and m["名"] in shot.get("使用素材", [])][:2]
            design = {"镜号": i+1, "画面": shot.get("分镜原稿") or shot["prompt"], "镜头资料": shot.get("镜头资料", {}),
                      "实体": reference["实体"], "项目设计": result["规划资料"]["内容计划"].get("项目设计", {})}
            for kind in ("空间草图", "分镜预览"):
                style = "灰白白模俯视空间预演，无材质；人物用无文字的简洁体块" if kind == "空间草图" else reference["画风"]
                item = await self._生成(kind, design, style, names)
                items.append(item)
        result["辅助图资料"] = {"素材": items, "覆盖镜号": [i+1 for i, _ in selected], "覆盖说明": "按需选取最多两个复杂镜头；全部模式覆盖每镜，均受明确容量限制。辅助图不是视频质量认证。"}
        result["辅助图资料"]["剩余容量"] = max(0, capacity-len(items))
        self.分集素材[self.flow.集号 or 1] = items
        写JSON(self.flow.project.路径("辅助图", f"第{self.flow.集号 or 1:03d}集索引.json"), result["辅助图资料"])
        if others or items:
            self.flow.参考图结果 = {**reference, "素材": [*reference["素材"], *others, *items], "辅助图": [*reference.get("辅助图", []), *others, *items]}
            total = len(self.flow.参考图结果["素材"])
            self.flow.project.写阶段("references", self.flow.参考图结果, status="completed", completed=total, total=total,
                                      reason="实体参考已观察，辅助图已生成；未执行AI验收")
            写JSON(self.flow.project.路径("参考图", "参考图索引.json"), {**self.flow.参考图结果, "媒体目录": str(self.root)})
        else:
            self.flow.参考图结果 = reference
        self.flow.进度({"阶段": "分镜辅助图完成", "已完成": len(items), "总数": len(items)})
        return items
