# -*- coding: utf-8 -*-
"""中性项目设计契约，跨章节、图像与镜头保存同一组创作约束。"""
import math

设计字段 = ("作者约束", "题材主次", "世界规则", "人物语气", "声音方案", "声景方案", "场次任务", "动作边界", "视觉母题", "待证事项")
实体资料契约 = "人物场景统一记录本片需要的角色、场景和重要道具，每项包含类型、名称、外观、原文依据，类型取角色、场景或道具。文字设定在内容规划完成，不依赖是否生成参考图；具体设定遵守人物场景与连续性技能。已给定的同名同类型实体沿用共享设定，缺少的必要设定在本阶段确定；不同外观状态分别命名，无相关实体才用空数组。"
设计契约 = "另提供项目设计对象：作者约束、题材主次、世界规则、人物语气、声音方案、声景方案、场次任务、动作边界、视觉母题、待证事项。声音方案记录主要角色的共享声音，每项包含说话人、声源、声线、语言、语速、情绪、停顿重音七个非空文本字段；语速与情绪是基准，具体表演由分镜决定。临时说话人在首次发声分镜中直接定稿，无共享声音填[]。声景方案为对象数组，每项填写范围、环境音、音乐三个非空文本字段，先用范围全片确定统一音乐与基础环境声，具体场景需要变化时按人物场景中的场景名称另列；未使用的声音明确写不使用。其余字段为文本数组。具体设计遵守本次技能资料，无关事项可省略。"


def 校验项目设计(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("项目设计须为文本字段名组成的对象")
    result = {}
    for key, items in value.items():
        if isinstance(items, (str, dict)):
            items = [items]
        if not isinstance(items, list) or len(items) > 40:
            raise ValueError(f"项目设计{key}须为最多40项的数组")
        for item in items:
            if not isinstance(item, (str, dict)):
                raise ValueError("项目设计单项格式错误")
            if isinstance(item, dict) and any(not isinstance(k, str) or not isinstance(v, (str, int, float, bool, type(None))) for k, v in item.items()):
                raise ValueError("项目设计单项只接受简单字段，不接受可执行或嵌套内容")
            if isinstance(item, dict) and any(isinstance(v, float) and not math.isfinite(v) for v in item.values()):
                raise ValueError("项目设计数值须为有限值")
        if key == "声景方案" and items:
            if any(not isinstance(item, dict) or any(not isinstance(item.get(field), str) or not item[field].strip()
                   for field in ("范围", "环境音", "音乐")) for item in items):
                raise ValueError("声景方案须提供范围、环境音、音乐三个具体文本字段")
            scopes = [item["范围"] for item in items]
            if "全片" not in scopes or len(set(scopes)) != len(scopes):
                raise ValueError("声景方案须有唯一全片基础方案，同一范围不能重复决定")
        result[key] = items
    return result


def 本镜声景(design, task):
    rows = design.get("声景方案", [])
    selected = [row for row in rows if isinstance(row, dict) and row.get("范围") == "全片"]
    scenes = [row for row in rows if isinstance(row, dict) and row.get("范围") in task.get("涉及实体", [])]
    if len(scenes) == 1:
        selected.extend(scenes)
    result = {}
    for row in selected:
        for key in ("环境音", "音乐"):
            if isinstance(row.get(key), str) and row[key].strip():
                result[key] = row[key]
    return result
