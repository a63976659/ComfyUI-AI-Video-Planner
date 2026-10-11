# -*- coding: utf-8 -*-
"""逐段提示词共用的输入检查及验收恢复；不修改图像分析。"""

约束优先规则 = (
    "只处理当前真实段ID，不推测邻段。当前段人物、场景、核心动作和原台词是锁定字段。"
    "禁用字幕表示禁止屏上文字，不禁止对白；禁止配乐及静音是明确禁令。"
    "禁止或不要出现字幕、标题或文字是禁令，不是生成屏上文字的要求；逐句区分肯定与否定，转折后的明确文字要求仍按真实要求处理。"
    "已在当前段明确姓名或主体后，同一个女孩等段内回指是合法表达；只有缺少当前主体或依赖前后段才能理解时才是跨段依赖。"
    "若原稿明确要求屏上文字而同时禁用屏上文字，这是输入冲突，不擅自替换为图标，也不要求模型违反禁令。"
    "正常的动作过程细化和持续状态不属于新增剧情，不能仅凭个人审美否定合法描述。"
)


def 校验验收依据(row, source, candidate):
    if row["通过"]:
        return
    evidence = row.get("依据")
    if not isinstance(evidence, list) or len(evidence) != len(row["问题"]):
        raise ValueError("验收拒绝缺少逐项原稿及候选引文依据")
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("验收依据须为对象")
        a, b = item.get("原稿引用"), item.get("候选引用")
        if not isinstance(a, str) or not a.strip() or a not in source or not isinstance(b, str) or not b.strip() or b not in candidate:
            raise ValueError("验收引文不属于当前原稿资料或候选，不能据此重写")


def 输入约束问题(shot, 禁用字幕=False, 全局提示词=""):

    errors = list(shot.get("输入问题") or [])
    dialogue = shot.get("台词", "").strip() or ("原稿对白" if "<d>" in shot.get("原始分镜", "") else "")
    if shot.get("声音") == "静音" and dialogue:
        errors.append("输入约束冲突：本段要求静音，同时存在锁定台词；请调整发声要求后重试")
    if dialogue and 全局提示词.strip() in {"静音", "无声", "无对白", "禁止对白", "禁止声音"}:
        errors.append("输入约束冲突：执行全局提示词禁止发声或对白，同时存在锁定台词")
    return list(dict.fromkeys(errors))


def 验收恢复(request, system, user, parse):
    """最多一次格式重试，候选保持原样；网络/鉴权/取消不隐式重发。"""
    for attempt in range(2):
        try:
            raw = request(system, user, "验收提示词" if attempt == 0 else "重试验收格式")
            return parse(raw)
        except (ValueError, RuntimeError) as exc:
            # 传输层会把非法或截断正文标为parse；不能误判为内容质量缺陷。
            kind = getattr(exc, "类别", "")
            if kind and kind != "parse":
                raise
            if attempt:
                raise
            system += f"上次验收结论未通过程序核对：{exc}。本次纠正上述问题，只返回要求的合法JSON，布尔值用true/false，逐字保留目标segment_id；不重写候选、不输出解释。"
