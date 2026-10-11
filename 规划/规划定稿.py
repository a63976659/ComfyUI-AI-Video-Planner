# -*- coding: utf-8 -*-
"""声音身份供生成前规则直接沿用；自动交付只核对完整性与结构。"""
import re

from .规划默认规则 import 声音字段

定稿版本 = 3
_占位 = {"自动", "未知", "待定", "待补", "待证", "按需", "可选", "候选", "TBD", "待核实", "同上", "同前", "沿用前镜", "待完善", "未说明", "不确定"}
_搁置 = re.compile(
    r"待定|待确认|待补充|待解决|待核实|创作候选|候选方案|待用户|视情况|可以?考虑|按需(?:选择|添加|使用|安排|决定|调整)|"
    r"由用户(?:决定|选择|确认)|(?:后续|后期|制作阶段|制作时)再(?:确定|决定|选择|确认)"
)
_备选 = re.compile(
    r"(?:男声|女声|男性|女性)\s*[（(]?\s*(?:或|/|或者)\s*(?:男声|女声|男性|女性)|"
    r"(?:特写|近景|中景|全景|远景)\s*(?:或|/|或者)\s*(?:特写|近景|中景|全景|远景)|"
    r"(?:平视|俯视|仰视)\s*(?:或|/|或者)\s*(?:平视|俯视|仰视)"
)
_提议 = re.compile(r"(?:^|[。；\n])\s*(?:也许|或许|可能(?:采用|使用|选择|安排)|建议(?:采用|使用|安排)|可选[：:])")
class 规划未定稿(ValueError):
    pass


def 校验确定文本(value, field, 原话=()):
    """兼容手动诊断工具；自动规划与提示词生成流程不调用此关键词检查。"""
    if not isinstance(value, str) or not value.strip():
        return
    text = value
    for line in 原话:
        if isinstance(line, str) and line.strip():
            text = text.replace(line, "")
    if field in ("画面", "模型提示词", "H3提示词"):
        # 已确定要显示的字句属于画面内容，不是制作方案待定。
        text = re.sub(r'(写着|写有|印着|显示|字幕|标牌|标题文字|书名)\s*[：:]?\s*[“「『《"]([^”」』》"\n]+)[”」』》"]',
                      lambda m: m[1] + "[固定文字]", text)
    if text.strip() in _占位:
        raise 规划未定稿(f"规划未定稿：{field}不能使用占位值{value!r}，直接确定具体方案")
    for pattern in (_搁置, _备选, _提议):
        for match in pattern.finditer(text):
            # 规则中的“不使用待定方案”等禁令不是未决制作选择。
            before = text[max(0, match.start() - 16):match.start()]
            if re.search(r"(?:不|不得|禁止|不能|无需)[^。；，\n]{0,12}$", before):
                continue
            raise 规划未定稿(f"规划未定稿：{field}含{match.group()!r}，须在当前阶段确定唯一可执行方案；保留原话与事实证据限制")


def _声音身份(voice):
    if not isinstance(voice, dict) or not voice:
        return {}
    speaker = voice.get("说话人", "")
    if not speaker:
        return {}
    names = [s.strip() for s in re.split(r"[、,，；;\n]", speaker) if s.strip()]
    result = {}
    for name in names:
        key = "旁白" if name in ("旁白", "画外旁白", "解说", "解说员", "朗读者", "Narrator", "narrator") else name
        line = voice.get("声线", "")
        if len(names) > 1:
            match = re.search(r"(?:^|[；;\n])\s*" + re.escape(name) + r"\s*[：:]\s*([^；;\n]+)", line)
            if not match:
                continue  # 只记录已明确映射的身份，不以字符串解析触发自动返修。
            line = match[1].strip()
        result[key] = {**voice, "说话人": key, "声线": line}
    return result


def 记录声音身份(shots, known):
    for shot in shots:
        for speaker, voice in _声音身份(shot.get("声音设计", {})).items():
            known.setdefault(speaker, voice)


def 校验确定交付(result):
    if not isinstance(result, dict) or not isinstance(result.get("规划资料"), dict):
        raise 规划未定稿("规划尚未完整生成，阶段成果已保存，不作为确定成品交付")
    info = result["规划资料"]
    if "生成完成" in info:
        complete = info["生成完成"] is True and info.get("本地校验", {}).get("通过") is True
        series_complete = info.get("全剧生成完成") is True
    else:
        # 已有草稿与历史完整成果仍可导入；新流程不伪造AI验收记录。
        complete = info.get("自动验收", {}).get("通过") is True
        series_complete = info.get("全剧验收", {}).get("通过") is True
    if (not complete or info.get("未完成") or
            info.get("未完成单元") or info.get("未输出集号") or
            info.get("输出状态") in ("待完善", "部分输出") or
            (result.get("分集") and not series_complete)):
        reason = info.get("本地校验", {}).get("说明") or info.get("自动验收", {}).get("说明") or "内容尚未完整生成"
        raise 规划未定稿("未完成确定成品：" + reason + "；阶段成果已保存")
    segments = result.get("segments")
    if not isinstance(segments, list) or not segments:
        raise 规划未定稿("确定成品须包含完整分镜")
    from .镜头设计 import 校验镜头设计
    for segment in segments:
        shot = {**segment.get("镜头资料", {}), "画面": segment.get("prompt", ""), "台词": segment.get("台词", "")}
        校验镜头设计(shot, 强制=True, 强制声音=True)
