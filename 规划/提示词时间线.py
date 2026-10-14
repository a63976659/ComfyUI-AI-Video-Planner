# -*- coding: utf-8 -*-
"""逐段提示词的秒级时间线契约；H3与自然语言共用，不改变分镜。"""
import re

时间线版本 = 1
秒级时间线规则 = (
    "每段必须提供从本段零秒到实际结束的完整秒级时间线，允许毫秒级边界。"
    "每个时间节拍独占一行，统一写成‘从 MM:SS.mmm 到 MM:SS.mmm，具体描述’；每个区间最长1秒，连续覆盖全段，不重叠、不留缺口。"
    "连续保持的动作也明确本秒的位置、动作进展或保持状态，不能只列空时间戳。"
    "逐节拍交代已有主体与空间、动作起止及结果、表演变化、镜头状态、当前声音和实际参考生效点；适用内容具体充分，无关维度不凑模板。"
    "台词逐字保留且只出现一次，在起说节拍注明说话人及原话，后续秒只描述其持续发声与表演；"
    "跨多个节拍的长台词注明持续到哪个时间点，不把整句挤进1秒、不重复原话、不伪造词级音轨对齐。"
    "时间节拍不是切镜；只有既定切镜才使用目标模型的镜头标记，切点必须是节拍边界。"
    "在已有事实、动作和拍法内展开过程与视听细节，不新增剧情、人物、台词、素材、音乐或运镜；缺少依据时明确已知状态。"
    "时间精度表示执行意图，不能声称生成模型保证逐毫秒还原。"
)
_区间 = re.compile(r'^\s*从\s*(\d{2}):(\d{2})\.(\d{3})\s*到\s*(\d{2}):(\d{2})\.(\d{3})[，,:：]([^\n]*)', re.M)


def 时间线问题(text, duration, cuts=()):
    matches = list(_区间.finditer(text))
    if not matches:
        return ["缺少覆盖全段的秒级时间线，使用从 MM:SS.mmm 到 MM:SS.mmm 的逐行描述"]
    errors, previous = [], 0
    end_ms = round(duration * 1000)
    cut_ms = [round(c * 1000) for c in cuts]
    # 对白中出现时间格式只是原话，不当作摄影时间线。
    for m in matches:
        start = int(m[1]) * 60000 + int(m[2]) * 1000 + int(m[3])
        end = int(m[4]) * 60000 + int(m[5]) * 1000 + int(m[6])
        if int(m[2]) >= 60 or int(m[5]) >= 60:
            errors.append("时间线秒字段须小于60")
        if start != previous:
            errors.append("时间线必须从零秒开始连续覆盖，不能缺口、重叠或倒序")
            if start > previous:
                errors.append(f"缺少从 {previous//60000:02d}:{previous//1000%60:02d}.{previous%1000:03d} 到 {start//60000:02d}:{start//1000%60:02d}.{start%1000:03d} 的逐秒具体描述；切镜行本身不能替代时间区间。")
        if not 0 <= start < end <= end_ms:
            errors.append("时间线区间须为正时长且位于当前段内")
        if end - start > 1000:
            errors.append("时间线每个节拍不得超过1秒")
        if not m[7].strip():
            errors.append("时间线节拍缺少具体描述")
        if any(start < c < end for c in cut_ms):
            errors.append("切镜时间必须与秒级节拍边界对齐")
        previous = end
    if previous != end_ms:
        errors.append("时间线未覆盖到当前段结束")
    return list(dict.fromkeys(errors))


def 既定切点(shot):
    points = []
    values = shot.get("镜头资料", {}).get("切点", [])
    for value in values if isinstance(values, (list, tuple)) else []:
        value = value.get("秒") if isinstance(value, dict) else value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < shot["时长"]:
            points.append(value)
    original = shot.get("原始分镜", "")
    for match in re.finditer(r"(?:第|在)?(\d+(?:\.\d+)?)\s*秒[^，。；\n]{0,6}(?:切到|切为|切镜|切至|切换)", original):
        value = float(match[1])
        if 0 < value < shot["时长"]:
            points.append(value)
    for match in re.finditer(r"\[Shot\s+\d+\] At (\d{2}):(\d{2})\.(\d{3})", original):
        value = int(match[1])*60 + int(match[2]) + int(match[3])/1000
        if 0 < value < shot["时长"]:
            points.append(value)
    return sorted(set(points))


def 时间线骨架(duration, cuts=()):
    end = round(duration * 1000)
    def stamp(ms):
        return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"
    boundaries = sorted({0, end, *range(0, end, 1000), *(round(c*1000) for c in cuts if 0 < c < duration)})
    return [f"从 {stamp(start)} 到 {stamp(stop)}" for start, stop in zip(boundaries, boundaries[1:])]
