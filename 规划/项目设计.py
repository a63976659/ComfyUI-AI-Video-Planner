# -*- coding: utf-8 -*-
"""中性项目设计契约，跨章节、图像与镜头保存同一组创作约束。"""
import math

设计字段 = ("作者约束", "题材主次", "世界规则", "人物语气", "声音方案", "场次任务", "动作边界", "视觉母题", "待证事项")
设计契约 = "另提供项目设计对象，字段包括作者约束、题材主次、世界规则、人物语气、声音方案、场次任务、动作边界、视觉母题、待证事项。每个字段的值必须是数组，数组元素为文本或简单对象；即使只有一项也使用数组，不直接填写单段文本或单个对象。例如\"作者约束\":[\"保留原文\"],\"声音方案\":[{\"说话人\":\"旁白\",\"声源\":\"画外旁白\"}]，实际内容按本次要求完整填写。未指定的创作与制作要求直接确定具体方案，标明规划确定或创作补充；无关事项用空数组或省略字段。声音方案逐说话人写明声源、性别、年龄感、音色、语言、固定每秒4字的发音语速、情绪及独立停顿重音，未指定角色的朗读、旁白和解说统一采用成年女性配音；明确角色声音、原音轨与静音要求优先。无朗读则明确无朗读。待证事项只记录事实或素材证据限制，不能承载尚未决定的制作方案。保真时区分原文事实与创作补充，不凭空添加能力。跨章节合并保持原规则、声音身份与状态变化；后续镜头直接逐字继承已有声线。中文发音秒数=汉字数/4，独立停顿和动作另计，内容阶段即确定足够镜头及逐镜台词分配，不等待检查返修才决定。原音轨保留实际原音。"


def 校验项目设计(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - set(设计字段):
        raise ValueError("项目设计字段无效")
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
        result[key] = items
    return result
