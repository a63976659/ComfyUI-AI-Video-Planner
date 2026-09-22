# -*- coding: utf-8 -*-
"""H3 提示词生成纯逻辑：编辑定稿的分镜草稿 → LLM → 逐段生成提示词。

不 import ComfyUI、不打真实网络（opener 注入，签名同 规划器：(system,user)->str）。
知识库与 规划器 共用同一文件夹（规划/知识库.load_skill_docs）；JSON 提取复用 规划器.提取JSON。
设计依据：文档/计划/2026-09-17-剪辑时间轴与AI提示词生成-实现计划.md C2/任务1。
"""
import logging

from .知识库 import load_skill_docs, H3_SKILL_FOLDERS, 任务类型映射
from .规划器 import 提取JSON

# 知识库注入指令：知识库文档为交互式智能体而写；此处只取视觉/提示词规范，
# 并要求最终仍只输出与 segments 逐段对齐的 prompts JSON。
_KB注入指令 = (
    "\n\n以下是 MiniMax H3 知识库文档（附在用户消息中），请提取其中的视觉风格、镜头语言与提示词写法规范，"
    "用于撰写每段的生成提示词。务必忽略文档中面向交互式智能体的分步确认流程、选项卡、多轮问答与制作清单，"
    "不要输出这些流程或询问用户；最终仍严格只输出上述 prompts JSON，不要任何解释文字。"
)
_KB融合说明 = (
    "\n文档中标注「(辅助风格)」的技能说明仅供借鉴融合其手法与风格要素，"
    "各段提示词的主体风格、结构与规范仍按主风格技能输出。"
)


def 构建提示词生成prompt(brief: dict, segments: list, 技能: str = "不指定", 辅助: str = "无", 回执: dict = None) -> tuple:
    """返回 (system, user)。segments 为用户编辑定稿的草稿段数组（含 start/end/标题/字幕/prompt 画面草稿）。
    可选 回执 dict（A5）：选了知识库技能时把装配回执写入 回执["知识库"]，供界面回显实际来源/截断/缺失。"""
    brief = brief if isinstance(brief, dict) else {}
    主题 = str(brief.get("主题") or "").strip()
    平台 = str(brief.get("平台") or "通用").strip()
    风格 = str(brief.get("风格") or "").strip()
    受众 = str(brief.get("受众") or "").strip()
    语言 = str(brief.get("语言") or "中文").strip()
    默认任务 = str(brief.get("默认任务") or "t2v").strip()

    system = (
        "你是 MiniMax H3 视频提示词写作导演，精通主体/动作/镜头/光线/氛围五要素描写、段间叙事衔接与角色一致性。"
        "依据用户给的整体信息与逐段分镜草稿（已经用户编辑定稿），为每段撰写视频生成提示词。"
        "严格只输出 JSON，不要任何解释文字。"
        'JSON 结构固定为：{"prompts": ["第1段提示词", "第2段提示词", ...]}，'
        "数组长度与顺序必须与输入段编号一一对应，不得多段或少段。"
        "每段提示词须：覆盖该段时长内的画面节奏；与相邻段的动作、场景转换互相衔接；"
        "涉及角色时保持同一角色外貌描述在全片一致。"
        "提示词只写视觉内容，不要添加分辨率、像素尺寸或画幅比例等输出参数。"
    )
    段行 = []
    for i, raw in enumerate(segments or []):
        raw = raw if isinstance(raw, dict) else {}
        起 = float(raw.get("start") or 0)
        末 = float(raw.get("end") or 0)
        段行.append(
            f"段{i + 1}: 时长{max(0.0, 末 - 起):.1f}s | 职能 {raw.get('职能') or ''} | 标题 {raw.get('标题') or ''} | "
            f"字幕 {raw.get('字幕') or ''} | 情绪 {raw.get('情绪') or ''} | 钩子 {raw.get('钩子') or ''} | "
            f"画面草稿 {raw.get('prompt') or ''}"
        )
    user = (
        f"主题：{主题}\n平台：{平台}\n语言：{语言}\n"
        + (f"风格：{风格}\n" if 风格 else "")
        + (f"受众：{受众}\n" if 受众 else "")
        + f"共{len(段行)}段，按段编号顺序撰写提示词：\n" + "\n".join(段行)
        + f"\n请用{语言}输出每段提示词。严格输出 JSON，不要多余文字。"
    )

    技能 = str(技能 or "不指定").strip()
    辅助 = str(辅助 or "无").strip()
    if 技能 in H3_SKILL_FOLDERS:
        try:
            文档, _文件, 知识库回执 = load_skill_docs(技能, 任务类型映射(默认任务), 辅助)
        except (FileNotFoundError, ValueError, OSError) as e:
            logging.warning("[长视频规划师] 提示词生成知识库加载失败，按无知识库降级：%s", e)
            文档 = ""
            知识库回执 = {"error": str(e)}
        if isinstance(回执, dict):
            回执["知识库"] = 知识库回执
        if 文档:
            system += _KB注入指令
            if 辅助 != "无":
                system += _KB融合说明
            user += f"\n\n知识库文档（供撰写每段提示词参考）:\n{文档}"
    return system, user


def 归并提示词(segments: list, prompts, 状态: dict = None) -> tuple:
    """按索引把 prompts 对齐回 segments（替换 prompt 字段）。返回 (新段数组, 降级数)。

    降级＝该段保留原 prompt（画面草稿）：prompts 非 list / 索引越界 / 元素非串或空串。
    局部降级不整单失败——草稿是用户编辑资产，不得因 LLM 局部缺输出而丢失。
    可选 状态 dict（A1）：传入时按 **segment_id** 映射逐段状态（"ok"/"degraded"），
    不再只回一个整单降级数而掩盖具体哪段失败；无 segment_id 的旧段以 `#index-{i}` 回退键登记。"""
    def 记(i, s, 命中):
        if not isinstance(状态, dict):
            return
        sid = s.get("segment_id") if isinstance(s, dict) else None
        键 = str(sid) if sid not in (None, "") else f"#index-{i}"
        状态[键] = "ok" if 命中 else "degraded"

    out = [dict(s) if isinstance(s, dict) else {} for s in (segments or [])]
    if not isinstance(prompts, list):
        for i, s in enumerate(out):
            记(i, s, False)
        return out, len(out)
    降级 = 0
    for i, s in enumerate(out):
        p = prompts[i] if i < len(prompts) else None
        命中 = isinstance(p, str) and bool(p.strip())
        if 命中:
            s["prompt"] = p
        else:
            降级 += 1
        记(i, s, 命中)
    if 降级:
        logging.warning("[长视频规划师] 提示词生成降级：%d 段保留原画面草稿（LLM 输出缺失/空）", 降级)
    return out, 降级


def _调opener取文本(system, user, opener) -> str:
    """调 opener(system,user)，统一收敛异常：RuntimeError 透传，其余包为 RuntimeError。"""
    try:
        return opener(system, user)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"LLM 调用失败：{e}") from e


def _从输出取prompts(文本, 目标段=None):
    """提取 prompts；指定目标段时校验数量与 ID 归属并对齐，无法确定归属则抛 ValueError。"""
    数据 = 提取JSON(文本)
    prompts = None
    if isinstance(数据, dict):
        if isinstance(数据.get("prompts"), list):
            条目 = 数据["prompts"]
            prompts = 条目
        elif isinstance(数据.get("segments"), list):   # 兼容：模型把 prompt 包回 segments 形态
            条目 = 数据["segments"]
            prompts = [s.get("prompt") if isinstance(s, dict) else None for s in 条目]
    elif isinstance(数据, list):
        条目 = 数据
        prompts = [s.get("prompt") if isinstance(s, dict) else s for s in 条目]
    if prompts is None:
        raise ValueError("无法从 LLM 输出定位 prompts 数组")
    if 目标段 is not None:
        if len(prompts) > len(目标段):
            raise ValueError(f"提示词数量（{len(prompts)}）超出目标段数（{len(目标段)}），未修改草稿，请重试")
        if any(isinstance(s, dict) and "segment_id" in s for s in 条目):
            目标ids = [str(s["segment_id"]) for s in 目标段]
            目标集 = set(目标ids)
            if len(目标集) != len(目标ids):
                raise ValueError("目标段 segment_id 重复，无法确定提示词归属，未修改草稿，请重试")
            按ID = {}
            for s in 条目:
                sid = s.get("segment_id") if isinstance(s, dict) else None
                if not isinstance(sid, str) or sid not in 目标集 or sid in 按ID:
                    raise ValueError("提示词 segment_id 缺失、无效、重复或不属于目标段，未修改草稿，请重试")
                按ID[sid] = s.get("prompt")
            return [按ID.get(sid) for sid in 目标ids]
        if len(prompts) < len(目标段):
            raise ValueError(f"提示词数量（{len(prompts)}）少于目标段数（{len(目标段)}）且无 segment_id，无法确定归属，未修改草稿，请重试")
    return prompts


def 生成提示词(brief: dict, segments: list, opener, 技能: str = "不指定", 辅助: str = "无",
             回执: dict = None, 状态: dict = None) -> list:
    """编排：构建提示词 → opener → 提取JSON → 定位 prompts 数组 → 归并。返回新段数组。

    降级契约同 规划器.规划：任一失败抛带上下文 RuntimeError（路由转 400/502/500 + {error}）。
    可选 回执 dict（A5）：与 构建提示词生成prompt 同一机制，回填 回执["知识库"] 供路由回显。
    可选 状态 dict（A1）：回填逐段提示词状态（segment_id → "ok"/"degraded"），供路由按段回显。"""
    system, user = 构建提示词生成prompt(brief, segments, 技能, 辅助, 回执=回执)
    文本 = _调opener取文本(system, user, opener)
    try:
        prompts = _从输出取prompts(文本)
        结果, _降级 = 归并提示词(segments, prompts, 状态=状态)
    except ValueError as e:
        原文 = 文本.strip() if isinstance(文本, str) else str(文本)
        预览 = 原文[:200] + ("…" if len(原文) > 200 else "")
        logging.warning("[长视频规划师] 提示词生成解析失败：%s｜原始输出（前2000字）：%s", e, 原文[:2000])
        raise RuntimeError(f"LLM 输出解析失败：{e}｜原始输出预览：{预览}") from e
    return 结果


def 构建局部重试prompt(brief: dict, segments: list, 目标索引: list, 技能: str = "不指定",
                    辅助: str = "无", 回执: dict = None) -> tuple:
    """返回 (system, user)（A2 局部重试）。segments 为**完整故事只读上下文**（逐段编号），
    目标索引 标记其中哪几段【需重写】；模型只为目标段按序输出新提示词，不得输出非目标段。
    每段带自自己的 task，供“按各段任务选择适用 H3 指南”参考。知识库注入机制同 构建提示词生成prompt。"""
    brief = brief if isinstance(brief, dict) else {}
    主题 = str(brief.get("主题") or "").strip()
    平台 = str(brief.get("平台") or "通用").strip()
    风格 = str(brief.get("风格") or "").strip()
    受众 = str(brief.get("受众") or "").strip()
    语言 = str(brief.get("语言") or "中文").strip()
    默认任务 = str(brief.get("默认任务") or "t2v").strip()
    目标集 = set(目标索引)
    目标数 = len(目标索引)

    system = (
        "你是 MiniMax H3 视频提示词写作导演。下面给出完整分镜草稿作为只读上下文，并标注哪些是【需重写】的目标段。"
        "请严格只为标注【需重写】的镜头、按其出现顺序重新撰写视频生成提示词；不要输出非目标段；不要任何解释文字。"
        'JSON 结构固定为：{"prompts": ["目标1提示词", "目标2提示词", ...]}，'
        f"数组长度必须等于目标段数（{目标数}）且与其顺序一一对应，不得多或少。"
        "重写时须：保持与相邻非目标段的动作、场景转换衔接；涉及角色时保持同一角色外貌描述全片一致；"
        "提示词只写视觉内容，不添加分辨率、像素尺寸或画幅比例等输出参数。"
    )
    段行 = []
    for i, raw in enumerate(segments or []):
        raw = raw if isinstance(raw, dict) else {}
        起 = float(raw.get("start") or 0)
        末 = float(raw.get("end") or 0)
        标 = "【需重写】" if i in 目标集 else ""
        段行.append(
            f"段{i + 1}{标}: 任务 {raw.get('task') or 默认任务} | 时长{max(0.0, 末 - 起):.1f}s | "
            f"职能 {raw.get('职能') or ''} | 标题 {raw.get('标题') or ''} | 字幕 {raw.get('字幕') or ''} | "
            f"情绪 {raw.get('情绪') or ''} | 钩子 {raw.get('钩子') or ''} | "
            f"画面草稿 {raw.get('prompt') or ''}"
        )
    user = (
        f"主题：{主题}\n平台：{平台}\n语言：{语言}\n"
        + (f"风格：{风格}\n" if 风格 else "")
        + (f"受众：{受众}\n" if 受众 else "")
        + f"共{len(段行)}段（其中 {目标数} 段标【需重写】），只重写标【需重写】的段：\n" + "\n".join(段行)
        + f"\n请用{语言}输出目标段提示词。严格输出 JSON，不要多余文字。"
    )

    技能 = str(技能 or "不指定").strip()
    辅助 = str(辅助 or "无").strip()
    if 技能 in H3_SKILL_FOLDERS:
        try:
            文档, _文件, 知识库回执 = load_skill_docs(技能, 任务类型映射(默认任务), 辅助)
        except (FileNotFoundError, ValueError, OSError) as e:
            logging.warning("[长视频规划师] 局部重试知识库加载失败，按无知识库降级：%s", e)
            文档 = ""
            知识库回执 = {"error": str(e)}
        if isinstance(回执, dict):
            回执["知识库"] = 知识库回执
        if 文档:
            system += _KB注入指令
            if 辅助 != "无":
                system += _KB融合说明
            user += f"\n\n知识库文档（供撰写目标段提示词参考）:\n{文档}"
    return system, user


def 局部重试(brief: dict, segments: list, 目标ids, opener, 技能: str = "不指定", 辅助: str = "无",
          回执: dict = None, 状态: dict = None) -> list:
    """A2：局部重试。携带**完整故事只读上下文**，服务端**仅允许修改目标段**（按 segment_id 清单）。
    非目标段的 prompt 与其他字段一律不动；返回新全段数组。超量、无 ID 缺项或 ID 校验失败时拒绝写入；等长空/无效占位或有效 ID 对齐后的缺项逐段降级，异常契约同 生成提示词。
    可选 状态 dict（A1）：仅回填**目标段**的逐段状态。目标清单为空/与 segment_id 不匹配 → ValueError。"""
    全段 = [dict(s) if isinstance(s, dict) else {} for s in (segments or [])]
    目标集 = {str(x) for x in (目标ids or []) if x not in (None, "")}
    目标索引 = [i for i, s in enumerate(全段) if str(s.get("segment_id") or "") in 目标集]
    if not 目标索引:
        raise ValueError("局部重试：目标段清单为空或与 segments 的 segment_id 不匹配")
    目标段 = [全段[i] for i in 目标索引]
    system, user = 构建局部重试prompt(brief, 全段, 目标索引, 技能, 辅助, 回执=回执)
    文本 = _调opener取文本(system, user, opener)
    try:
        prompts = _从输出取prompts(文本, 目标段=目标段)
        新目标, _降级 = 归并提示词(目标段, prompts, 状态=状态)   # 仅对目标段归并（降级保留各自旧词）
    except ValueError as e:
        原文 = 文本.strip() if isinstance(文本, str) else str(文本)
        预览 = 原文[:200] + ("…" if len(原文) > 200 else "")
        logging.warning("[长视频规划师] 局部重试解析失败：%s｜原始输出（前2000字）：%s", e, 原文[:2000])
        raise RuntimeError(f"LLM 输出解析失败：{e}｜原始输出预览：{预览}") from e
    for k, i in enumerate(目标索引):                     # 仅回写目标段，非目标段不动
        全段[i] = 新目标[k]
    return 全段
