# -*- coding: utf-8 -*-
"""H3 规划器纯逻辑：brief → LLM → 规范化分镜时间轴段。

不 import ComfyUI、不打真实网络（网络由注入的 opener 承担，见 规划/配置.py 默认opener）。
消费 规划/方法论.py 常量（英文原名，见该文件命名例外注释）。设计依据：文档/规格/2026-09-10-H3规划器-设计.md §7.1 + §13。
"""
import json
import logging
import math
import re

from .方法论 import (
    MIN_SEG, MAX_SEG, HOOK_TYPES, PLATFORM_HINTS, 角色配色,
)
from .知识库 import load_skill_docs, load_skills_docs, H3_SKILL_FOLDERS, 技能选项, 任务类型映射

# ```json ... ``` 或 ``` ... ``` 代码块（非贪婪，DOTALL）
_代码块re = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _修复尾逗号(text: str) -> str:
    r"""字符串与转义态感知的尾逗号清理：仅删除「不在字符串内、其后首个非空白字符为 } 或 ]」的逗号。
    旧正则 `,\s*[}\]]` 不识别字符串，会把画面/字幕里合法的 ",}" ",]" 一并吃掉 → 破坏正文。"""
    出 = []
    in_str = False
    esc = False
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if in_str:                                   # 字符串内：原样拷贝，仅跟踪转义与结束引号
            出.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            出.append(c)
            i += 1
        elif c == ",":                                # 结构层逗号：向后探测是否为尾逗号
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":            # 紧跟 }/] → 尾逗号，丢弃（保留其前空白）
                i += 1
            else:
                出.append(c)
                i += 1
        else:
            出.append(c)
            i += 1
    return "".join(出)


def 提取JSON(text: str):
    """4 层策略提取 JSON（设计 §7.1）：① 直接 → ② ```json``` 块 → ③ 最外层 {} → ④ 最外层 []。
    每层先「直接解析」保留正文原样；失败才做字符串感知的有限尾逗号修复再解析；全部失败抛 ValueError。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("LLM 返回内容为空")
    for 候选 in _候选(text):
        try:
            return json.loads(候选)                    # 先直接解析：合法正文（含 ,} ,]）绝不经过修复
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            return json.loads(_修复尾逗号(候选))         # 仅失败时才修复尾逗号（不触碰字符串内容）
        except (json.JSONDecodeError, ValueError):
            continue
    raise ValueError("无法从 LLM 输出提取合法 JSON")


def _候选(text: str):
    yield text.strip()                                   # ① 直接
    m = _代码块re.search(text)                           # ② 代码块
    if m:
        yield m.group(1).strip()
    i, j = text.find("{"), text.rfind("}")               # ③ 最外层 {}
    if 0 <= i < j:
        yield text[i:j + 1]
    i, j = text.find("["), text.rfind("]")               # ④ 最外层 []
    if 0 <= i < j:
        yield text[i:j + 1]


# 知识库注入指令：知识库文档为交互式智能体而写（含分步确认/选项卡/多轮问答），规划器是一次性
# JSON 输出，故显式要求只取视觉/镜头/提示词规范，忽略交互流程，最终仍只输出 segments JSON。
_KB注入指令 = (
    "\n\n以下是 MiniMax H3 知识库文档（附在用户消息中），请提取其中的视觉风格、镜头语言、"
    "画面规范与提示词写法，用于撰写每段的「画面」字段，使各段画面贴合所选技能的风格。"
    "务必忽略文档中面向交互式智能体的分步确认流程、选项卡、多轮问答与制作清单，"
    "不要输出这些流程或询问用户；最终仍严格只输出上述 segments JSON，不要任何解释文字。"
)
_KB融合说明 = (
    "\n文档中标注「(辅助风格)」的技能说明仅供借鉴融合其手法与风格要素，"
    "各段画面的主体风格、结构与规范仍按主风格技能输出。"
)
# Skills 技能注入指令：措辞同 _KB注入指令 但不绑定 MiniMax H3 知识库名义（该支技能源为根目录 Skills/）
_技能注入指令 = (
    "\n\n以下是用户指定技能的技能文档（附在用户消息中），请提取其中的视觉风格、镜头语言、"
    "画面规范与提示词写法，用于撰写每段的「画面」字段，使各段画面贴合所选技能的风格。"
    "务必忽略文档中面向交互式智能体的分步确认流程、选项卡、多轮问答与制作清单，"
    "不要输出这些流程或询问用户；最终仍严格只输出上述 segments JSON，不要任何解释文字。"
)


def 构建提示词(brief: dict, 回执: dict = None) -> tuple:
    """返回 (system, user)（设计 §7.1）。brief 缺失字段用默认兜底；主题必填校验在路由侧。
    选了「风格技能」时把对应 MiniMax-H3知识库 文档注入，令每段「画面」按该技能视觉/镜头/提示词规范撰写。
    可选 回执 dict（A5）：传入时把知识库装配回执（included/truncated/skipped/missing）写入 回执["知识库"]，
    供上层回显「实际进入请求的来源 / 截断 / 缺失」；不传则行为与旧完全一致。"""
    brief = brief if isinstance(brief, dict) else {}
    主题 = str(brief.get("主题") or "").strip()
    平台 = str(brief.get("平台") or "通用").strip()
    风格 = str(brief.get("风格") or "").strip()
    受众 = str(brief.get("受众") or "").strip()
    语言 = str(brief.get("语言") or "中文").strip()
    总时长 = int(brief.get("总时长") or 30)
    段数上限 = int(brief.get("段数上限") or 0)
    钩子类型 = str(brief.get("钩子") or brief.get("钩子类型") or HOOK_TYPES[0]).strip()
    调性 = PLATFORM_HINTS.get(平台, PLATFORM_HINTS["通用"])
    风格技能 = str(brief.get("风格技能") or "不指定").strip()
    辅助风格 = str(brief.get("辅助风格") or "无").strip()
    默认任务 = str(brief.get("默认任务") or "t2v").strip()
    每段建议时长 = str(brief.get("每段建议时长") or "").strip()   # 范围字符串如 "5-8"，仅供 LLM 控制分镜节奏，不参与校验归一

    system = (
        "你是资深短视频分镜导演，精通黄金3秒、钩子设计、情绪曲线、节奏控制与完播率优化。"
        "依据用户 brief 产出多段分镜时间轴。严格只输出 JSON，不要任何解释文字。"
        'JSON 结构固定为：{"segments":[{"职能":"钩子|开场|建立|递进|冲突|高潮|反转|结尾|CTA",'
        '"标题":"段标题/章节名","画面":"画面描述（主体/动作/镜头/光线/氛围）",'
        '"字幕":"台词或字幕文案","情绪":"情绪曲线标注","钩子":"仅首段填钩子类型","时长":整数秒}]}。'
        "画面描述只写视觉内容，不要添加分辨率、像素尺寸或画幅比例等输出参数。"
        f"每段时长必须在 {MIN_SEG}-{MAX_SEG} 秒之间；首段职能必须是「钩子」；末段职能必须是「结尾」或「CTA」。"
    )
    user = (
        f"主题：{主题}\n平台：{平台}\n平台调性：{调性}\n"
        f"总时长：{总时长}秒\n语言：{语言}\n"
        + (f"风格：{风格}\n" if 风格 else "")
        + (f"受众：{受众}\n" if 受众 else "")
        + (f"段数上限：{段数上限}\n" if 段数上限 else "")
        + (f"每段建议时长：{每段建议时长}秒，各段时长在此范围内按需浮动，用于控制分镜节奏\n" if 每段建议时长 else "")
        + f"默认钩子类型：{钩子类型}\n"
        + f"请用{语言}产出每段的 标题/字幕/画面。严格输出 JSON，不要多余文字。"
    )

    # 知识库注入（仅当选中具体技能）：加载失败优雅降级为无知识库，不让整次规划失败
    是Skills技能 = 风格技能 != "不指定" and 风格技能 in 技能选项()
    if not 是Skills技能 and 风格技能 in H3_SKILL_FOLDERS:
        try:
            文档, _文件, 知识库回执 = load_skill_docs(风格技能, 任务类型映射(默认任务), 辅助风格)
        except (FileNotFoundError, ValueError, OSError) as e:
            logging.warning("[长视频规划师] 知识库加载失败，按无知识库降级：%s", e)
            文档 = ""
            知识库回执 = {"error": str(e)}
        if isinstance(回执, dict):
            回执["知识库"] = 知识库回执
        if 文档:
            system += _KB注入指令
            if 辅助风格 != "无":
                system += _KB融合说明
            user += f"\n\n知识库文档（供撰写每段画面参考）:\n{文档}"
    elif 是Skills技能:
        # brief「技能/辅助」源＝根目录 Skills/，同名时优先 Skills；仅未命中 Skills 的旧 KB 技能名走上支。
        # ⚠️ 技能选项() 恒含「不指定」（=不注入技能，走通用分镜），须先排除，否则「不指定」会误入本支
        #    去 load_skills_docs("不指定")，Skills/ 不存在时每次规划都打 WARNING 噪声。
        try:
            文档, _文件, 知识库回执 = load_skills_docs(风格技能, 辅助风格)
        except (FileNotFoundError, ValueError, OSError) as e:
            logging.warning("[长视频规划师] Skills 技能文档加载失败，按无知识库降级：%s", e)
            文档 = ""
            知识库回执 = {"error": str(e)}
        if isinstance(回执, dict):
            回执["知识库"] = 知识库回执
        if 文档:
            system += _技能注入指令
            if 辅助风格 != "无":
                system += _KB融合说明
            user += f"\n\n技能文档（供撰写每段画面参考）:\n{文档}"
    return system, user


def _分配时长(总时长: int, N: int) -> list:
    """最大余数法等额分配（设计 §6.3.4）：base=总时长//N，前 (总时长-base*N) 段各 +1。
    N 已钳到可行域时 base∈[MIN_SEG,MAX_SEG] 且 base+1≤MAX_SEG（见任务3 算法要点推导），
    故下方钳制在可行域内是 no-op；仅 总时长<MIN_SEG 等不可行场景才触发硬钳并产生最小偏差。

    ⚠️ 有意保留均分（第四阶段 A4 决策）：时长恒按段数等额铺满总时长，**不采纳** LLM 每段
    回传的「时长」建议值——LLM 的 时长/每段建议时长 仅作为分镜节奏提示进入提示词，不参与归一，
    以保证「时长和==总时长」且各段落在 [MIN_SEG,MAX_SEG] 硬边界的确定性契约（时长分配影响
    start/end，若跟随 LLM 相对权重会引入抖动与不可行解）。「按 LLM 相对时长比例分配」列为
    后续实验（见基线 §3.10 待登记与文档/技术实现 02），需先解决越界回退与可重现性再评估。"""
    base = 总时长 // N
    余 = 总时长 - base * N
    时长 = [base + (1 if i < 余 else 0) for i in range(N)]
    # 防御性硬钳（正常域内不改值）；钳后偏差在可行段上再平衡一次
    for i in range(N):
        时长[i] = max(MIN_SEG, min(MAX_SEG, 时长[i]))
    差 = 总时长 - sum(时长)
    i = 0
    while 差 > 0 and i < N * 2:                     # 和不足：给未达上限的段 +1
        j = i % N
        if 时长[j] < MAX_SEG:
            时长[j] += 1
            差 -= 1
        i += 1
    i = 0
    while 差 < 0 and i < N * 2:                     # 和超：给未达下限的段 -1
        j = i % N
        if 时长[j] > MIN_SEG:
            时长[j] -= 1
            差 += 1
        i += 1
    return 时长


# 段数组候选键（不同模型可能用不同键名，按优先级；含中英文常见变体）
_段数组键 = ("segments", "shots", "scenes", "clips", "分镜", "片段", "镜头", "结果",
             "result", "data", "plan", "时间轴", "timeline", "content", "items")
# 单个段对象的特征键（判断一个 dict 是否「本身就是一段」）
_段特征键 = ("画面", "prompt", "description", "职能", "role", "标题", "title", "字幕", "subtitle")


def _取(d: dict, *键):
    """按优先级返回 d 中第一个非空值（适配不同模型的字段别名）；全空返回 ""。"""
    for k in 键:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return ""


def _找段数组(数据):
    """从任意 LLM JSON 结构定位分镜段数组，适配不同模型的键名/嵌套/顶层数组/单段对象差异。
    策略：① 顶层就是数组 → 直接用；② 命中候选键（含一层嵌套递归）；③ 兜底任意「非空且首元素为
    dict 的数组」；④ dict 本身像单个段 → 包成单元素数组。找不到返回 None（由调用方抛 ValueError）。"""
    if isinstance(数据, list):
        return 数据 or None
    if not isinstance(数据, dict):
        return None
    for k in _段数组键:
        v = 数据.get(k)
        if isinstance(v, list) and v:
            return v
        if isinstance(v, dict):
            内 = _找段数组(v)
            if 内:
                return 内
    for v in 数据.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    if any(k in 数据 for k in _段特征键):
        return [数据]
    return None


def 校验归一(segments, brief: dict, 诊断: dict = None) -> list:
    """LLM 段数组（或含段数组的任意结构）→ 规范化段 dict 列表（含 §6.1 全字段），执行 §6.3 约束。
    超上限截断；**不再静默复制末段补齐**（第四阶段 A3）：不足时保留 LLM 实际返回的有效段，
    是否足以覆盖总时长写入 诊断（交由 规划() 决定定向修复/如何标注未完成）；无法定位段数组 → ValueError。
    可选 诊断 dict（A3）：传入时回填 {"期望段数","有效段数","不足段数","时长可行","不足"}，供上层判断故事是否完整。"""
    segs = _找段数组(segments)
    if not segs:
        raise ValueError("无法从 LLM 输出定位分镜段数组（segments）")
    brief = brief if isinstance(brief, dict) else {}

    总时长 = int(brief.get("总时长") or 30)
    默认任务 = str(brief.get("默认任务") or "t2v")
    用户上限 = int(brief.get("段数上限") or 0)

    # 段数约束（§6.3.5）：可行域 [下限, 上限]，下限=ceil(总/MAX_SEG) 保证时长能覆盖满，
    # 上限=min(总//MIN_SEG, 用户上限)。期望段数：用户设了上限→归一到该上限；否则尊重 LLM 自主分段。
    下限 = math.ceil(总时长 / MAX_SEG)
    硬上限 = 总时长 // MIN_SEG
    if 用户上限 > 0:
        上限 = min(硬上限, 用户上限)
        期望 = 用户上限                              # 用户显式要这么多段
    else:
        上限 = 硬上限
        期望 = len(segs)                             # 尊重模型自主分段
    if 上限 < 下限:                                  # 无解（用户上限过小/总时长<MIN_SEG）→ 收敛下限
        上限 = 下限
        期望 = 下限
    N = max(下限, min(期望, 上限))                   # clamp 期望到可行域

    if len(segs) > N:                                # 超上限：截断丢弃多余段
        segs = segs[:N]
    # 不足（len(segs) < N）不再复制末段冒充完整（A3）：原样保留有效段，由 规划() 尝试一次定向修复。
    有效段数 = len(segs)
    if isinstance(诊断, dict):
        诊断["期望段数"] = N
        诊断["有效段数"] = 有效段数
        诊断["不足段数"] = max(0, N - 有效段数)
        诊断["时长可行"] = 有效段数 >= 下限             # 是否多到足以按硬边界铺满总时长
        诊断["不足"] = 有效段数 < N

    时长 = _分配时长(总时长, 有效段数)                 # 有效段数≥下限时铺满总时长；不足则各段封顶 MAX、总和可能不满
    out = []
    起 = 0.0
    for i, raw in enumerate(segs):
        raw = raw if isinstance(raw, dict) else {}
        职能 = str(_取(raw, "职能", "role")).strip()
        if i == 0:                                   # §6.3.2 首段职能强制钩子（无条件覆盖，非「空才兜底」）
            职能 = "钩子"
        if i == 有效段数 - 1 and 职能 not in ("结尾", "CTA", "结尾CTA"):
            职能 = "结尾"                            # §6.3.2 末段 ∈ {结尾,CTA}
        钩子 = str(_取(raw, "钩子", "hook")).strip()
        if 钩子 not in HOOK_TYPES:
            钩子 = HOOK_TYPES[0] if i == 0 else ""   # 非法清空；仅首段兜底默认钩
        d = float(时长[i])
        out.append({
            "task": 默认任务,
            # 画面→prompt（§6.1）；兼容不同模型字段名（prompt/description/scene/画面描述/内容）
            "prompt": str(_取(raw, "画面", "prompt", "description", "scene", "画面描述", "内容")),
            "refs": {},
            "start": 起,
            "end": 起 + d,
            "run": True,
            "职能": 职能,
            "职能色": 角色配色(职能),                 # §6.3.6 后端查表写入
            "标题": str(_取(raw, "标题", "title", "name")),
            "字幕": str(_取(raw, "字幕", "subtitle", "caption", "台词", "text")),
            "情绪": str(_取(raw, "情绪", "emotion", "mood")),
            "钩子": 钩子,
        })
        起 += d
    return out


def _一次规划(system: str, user: str, opener, brief: dict, 诊断: dict) -> list:
    """单次编排：opener(system,user) → 提取JSON → 校验归一（回填 诊断）。失败抛带上下文 RuntimeError。
    错误契约（设计 §7.1）：不静默吞、不伪造 demo 段；解析/失败原始输出记服务端日志＋错误信息带 200 字预览。"""
    try:
        文本 = opener(system, user)
    except RuntimeError:
        raise                                        # opener 已带上下文，直接透传
    except Exception as e:                           # opener 抛任意异常统一收敛
        raise RuntimeError(f"LLM 调用失败：{e}") from e
    try:
        数据 = 提取JSON(文本)
        return 校验归一(数据, brief, 诊断=诊断)
    except ValueError as e:
        原文 = 文本.strip() if isinstance(文本, str) else str(文本)
        预览 = 原文[:200] + ("…" if len(原文) > 200 else "")
        logging.warning("[长视频规划师] LLM 输出解析/校验失败：%s｜原始输出（前2000字）：%s", e, 原文[:2000])
        raise RuntimeError(f"LLM 输出解析/校验失败：{e}｜原始输出预览：{预览}") from e


def _定向修复指令(诊断: dict) -> str:
    """A3：段数不足时的定向修复追加指令——要求把故事拆得更细、达到目标段数，严禁复制同一段冒充多段。"""
    期望 = 诊断.get("期望段数") or 0
    得到 = 诊断.get("有效段数") or 0
    return (
        f"\n\n⚠️ 上一次只得到 {得到} 段，不足以覆盖总时长/满足期望（需要约 {期望} 段）。"
        "请重新输出完整的 segments JSON：把故事拆成更细的镜头，确保段数达到 "
        f"{期望} 段左右，每段都是一个独立的新镜头（推进剧情），严禁把同一段画面复制成多段。"
        "仍严格只输出 JSON，不要解释文字。"
    )


def 规划(brief: dict, opener) -> dict:
    """编排：构建提示词 → opener(system,user) → 提取JSON → 校验归一，返回 {segments:[...]}。
    降级策略（设计 §7.1）：LLM 调用/解析/校验任一失败 → 不静默吞、不伪造 demo 段，
    抛带上下文的 RuntimeError（路由转 502/500 + {error}）。opener 签名 (system,user)->str。
    选了知识库时，结果附 `knowledge` 回执（A5：included/truncated/skipped/missing），供界面回显实际来源。
    A3：段数不足时最多进行一次定向修复（要求拆得更细、禁止复制）；仍不足则作为未完成草稿
    返回有效段与 `diagnostics`（不再静默复制末段冒充故事完整）。"""
    回执 = {}
    system, user = 构建提示词(brief, 回执=回执)
    诊断: dict = {}
    segments = _一次规划(system, user, opener, brief, 诊断)
    if 诊断.get("不足"):                                # A3：最多一次定向修复
        修复user = user + _定向修复指令(诊断)
        修复诊断: dict = {}
        try:
            修复段 = _一次规划(system, 修复user, opener, brief, 修复诊断)
        except RuntimeError as e:                        # 修复调用/解析失败：保留首轮有效段，不因修复失败而整单报错
            logging.warning("[长视频规划师] 段数定向修复失败，保留首轮结果：%s", e)
            修复段 = None
        if 修复段 is not None and len(修复段) > len(segments):   # 仅当修复确实带来更多有效段才采纳
            segments, 诊断 = 修复段, 修复诊断
    结果 = {"segments": segments}
    if 诊断.get("不足"):                                # 仍不足：未完成草稿标记 + 诊断（不伪造）
        结果["diagnostics"] = {
            "insufficient_segments": True,
            "expected": 诊断.get("期望段数"),
            "actual": 诊断.get("有效段数"),
            "duration_feasible": 诊断.get("时长可行"),
            "message": (f"故事未规划完整：期望约 {诊断.get('期望段数')} 段，实际得到 {诊断.get('有效段数')} 段"
                        + ("，且当前段数不足以覆盖总时长" if not 诊断.get("时长可行") else "")),
        }
    if 回执.get("知识库") is not None:            # A5：仅当确有知识库装配（选了技能）才附回执
        结果["knowledge"] = 回执["知识库"]
    return 结果
