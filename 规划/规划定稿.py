# -*- coding: utf-8 -*-
"""声音身份供生成前规则直接沿用；自动交付只核对完整性与结构。"""
import re

from .规划默认规则 import 声音字段

定稿版本 = 3
class 规划未定稿(ValueError):
    pass


def 声音角色(voice):
    speaker = voice.get("说话人") if isinstance(voice, dict) else None
    if not isinstance(speaker, str):
        return []
    names = [s.strip() for s in re.split(r"[、,，；;\n]", speaker) if s.strip()]
    return [(name, "旁白" if name in ("旁白", "画外旁白", "解说", "解说员", "朗读者", "Narrator", "narrator") else name)
            for name in names]


def _声音身份(voice):
    names = 声音角色(voice)
    result = {}
    for name, key in names:
        line = voice.get("声线", "")
        if len(names) > 1:
            match = re.search(r"(?:^|[；;\n])\s*" + re.escape(name) + r"\s*[：:]\s*([^；;\n]+)", line)
            if not match:
                continue  # 只记录已明确映射的身份，不以字符串解析触发自动返修。
            line = match[1].strip()
        identity = {**voice, "说话人": key, "声线": line}
        if len(names) > 1:
            for field in ("声源", "语言", "语速"):
                match = re.search(r"(?:^|[；;\n])\s*" + re.escape(name) + r"\s*[：:]\s*([^；;\n]+)", voice.get(field, ""))
                if match:
                    identity[field] = match[1].strip()
        result[key] = identity
    return result


def 记录声音身份(shots, known):
    for shot in shots:
        for speaker, voice in _声音身份(shot.get("声音设计", {})).items():
            identity = known.setdefault(speaker, voice)
            for field, value in voice.items():
                if not identity.get(field) and isinstance(value, str) and value.strip():
                    identity[field] = value


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
        shot = {**segment.get("镜头资料", {}), "画面": segment.get("prompt", ""), "台词": segment.get("台词", ""),
                "使用素材": segment.get("使用素材", [])}
        校验镜头设计(shot, 强制=True, 强制声音=True)
