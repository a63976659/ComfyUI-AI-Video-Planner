# -*- coding: utf-8 -*-
"""MiniMax-H3 知识库加载与映射（供 H3 规划器按“风格技能”注入提示词）。

移植自 ComfyUI-Artificial-Intelligence 节点/知识库.py 的 H3 部分（该插件与本插件
共用同一套 MiniMax-H3知识库）；不跨插件 import（对方插件未必安装），改为读取本插件根下
已复制到位的 MiniMax-H3知识库/。下拉框确定性映射：风格选项直接定位技能文档，一次性加载
后交给规划器提示词，不做模型选文档。设计依据：文档/计划 规划器集成H3知识库。
"""
import os

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KB_H3_ROOT = os.path.join(PLUGIN_ROOT, "MiniMax-H3知识库")
# brief 区「技能/辅助」下拉的独立技能源：根目录 Skills/（与 MiniMax-H3知识库 分家）；
# 剪辑时间轴生成行的 技能/辅助 仍用 MiniMax-H3知识库，两者不共用文件夹
SKILLS_ROOT = os.path.join(PLUGIN_ROOT, "Skills")

# 字符预算（中文约 1 字符 ≈ 1 token）：H3 主技能最大约 73KB，留出辅助技能说明与术语表余量
H3_CHAR_BUDGET = 60000

# 风格显示名 -> 技能文件夹名（对齐 MiniMax-H3知识库/00-总览.md 技能清单）
H3_SKILL_FOLDERS = {
    "通用H3提示词写作": "H3提示词写作",
    "3D动画短片": "3D动画短片生成器",
    "极简产品广告": "极简产品广告生成器",
    "纸艺定格科普": "纸艺定格科普视频生成器",
    "品牌宣传": "品牌宣传视频生成器",
    "MV歌词字幕": "MV歌词字幕视频生成器",
    "双人游戏开场": "双人游戏开场视频生成器",
    "纸质拼贴讲解": "纸质拼贴讲解视频生成器",
    "手绘实拍融合": "手绘实拍融合视频生成器",
}

# 规划器任务码 -> 知识库任务类型（仅 H3提示词写作 技能据此二选一参考指南；其余技能忽略任务类型）
_任务码到KB任务类型 = {
    "rv2v": "全能参考生视频(Ref2VA)",
    "r2v": "全能参考生视频(Ref2VA)",
    "v2v": "全能参考生视频(Ref2VA)",
    "i2v": "图生视频(I2VA)",
    "fl2v": "首尾帧视频(FL2VA)",
}


def 任务类型映射(默认任务: str) -> str:
    """把规划器任务码（t2v/i2v/fl2v/r2v/v2v/rv2v）映射到知识库任务类型；未命中默认 T2VA。"""
    return _任务码到KB任务类型.get(str(默认任务 or "").strip(), "文生视频(T2VA)")


def 风格选项() -> list:
    """前端“风格技能”下拉枚举（后端下发，杜绝前端硬编码）：不指定 + 9 技能。"""
    return ["不指定"] + list(H3_SKILL_FOLDERS.keys())


def 辅助风格选项() -> list:
    """前端“辅助风格”下拉枚举（后端下发）：无 + 9 技能。"""
    return ["无"] + list(H3_SKILL_FOLDERS.keys())


def 技能选项() -> list:
    """前端 brief「技能」下拉枚举（后端下发）：不指定 + 根目录 Skills/ 各一级子文件夹（文件夹名＝技能名）。
    与 风格选项()（MiniMax-H3知识库，供剪辑时间轴生成行）相互独立；Skills/ 不存在或为空时仅「不指定」。"""
    if not os.path.isdir(SKILLS_ROOT):
        return ["不指定"]
    names = sorted(n for n in os.listdir(SKILLS_ROOT)
                   if os.path.isdir(os.path.join(SKILLS_ROOT, n)))
    return ["不指定"] + names


def load_skills_docs(技能, 辅助风格="无"):
    """按 brief 技能（Skills/ 子文件夹）加载技能文档：SKILL.md 或 技能说明.md 为主文档，
    再按排序拼接文件夹内其余 .md/.txt；辅助风格从 Skills/ 同名子文件夹追加主说明（仅说明）。
    返回 (文档文本, 实际进入请求的相对名清单, 回执 dict)（A5：清单排除因预算被跳过者；
    回执 = {included, truncated, skipped, missing}）。"""
    if not os.path.isdir(SKILLS_ROOT):
        raise FileNotFoundError(f"未找到 Skills 目录: {SKILLS_ROOT}")
    if 技能 not in 技能选项():
        raise ValueError(f"未知的 Skills 技能: {技能}")
    skill_dir = os.path.join(SKILLS_ROOT, 技能)
    files = []
    for 主名 in ("SKILL.md", "技能说明.md"):
        p = os.path.join(skill_dir, 主名)
        if os.path.isfile(p):
            files.append((p, f"{技能}/{主名}"))
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames.sort()                                  # 遍历序确定性（同名技能多次加载文档序一致）
        for name in sorted(filenames):
            if not name.lower().endswith((".md", ".txt")):
                continue
            p = os.path.join(dirpath, name)
            rel = f"{技能}/{os.path.relpath(p, skill_dir).replace(os.sep, '/')}"
            if rel not in [r for _, r in files]:         # 主文档已收过的不重复拼
                files.append((p, rel))
    文档, 明细 = _assemble_docs(files, SKILLS_ROOT, H3_CHAR_BUDGET)
    # 辅助与主技能同源 Skills/，仅取主说明；同一技能不重复追加，不回退到 H3 知识库。
    if 辅助风格 and 辅助风格 not in ("无", "不指定", 技能) and 辅助风格 in 技能选项():
        for 主名 in ("SKILL.md", "技能说明.md"):
            aux_说明 = os.path.join(SKILLS_ROOT, 辅助风格, 主名)
            if os.path.isfile(aux_说明):
                rel = f"{辅助风格}/{主名} (辅助风格)"
                # 总预算守恒：辅助文档只用主文档装配后的剩余预算，避免主+辅各给满额致总量翻倍
                # （对照 load_skill_docs：主/辅/术语表一次性共享同一 H3_CHAR_BUDGET 装配）。
                剩余 = max(0, H3_CHAR_BUDGET - len(文档))
                辅文, 辅明细 = _assemble_docs([(aux_说明, rel)], SKILLS_ROOT, 剩余)
                文档 += 辅文
                明细 += 辅明细                     # 辅助的装配状态（full/truncated/skipped）入同一明细
    实际, 回执 = _来源与回执(明细)
    return 文档, 实际, 回执


# ================= 通用辅助 =================

def _check_in_root(path, root):
    """路径 resolve 后校验仍在知识库根内（防穿越），合法时返回绝对路径。"""
    rp = os.path.realpath(path)
    root_r = os.path.realpath(root)
    if not (rp == root_r or rp.startswith(root_r + os.sep)):
        raise ValueError(f"非法的知识库文档路径: {path}")
    return rp


def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _doc_header(rel):
    return f"\n===== 知识库文档: {rel} =====\n"


def _assemble_docs(files, kb_root, budget):
    """按优先级顺序拼接文档：每份前加分隔头，超预算的文件尾部截断并标注，
    预算耗尽后剩余文件跳过。files 为 (绝对路径, 相对显示名) 列表。
    返回 (文本, 明细)：明细为 [(相对显示名, 状态)]，状态 ∈
    full/truncated/skipped/missing，供上层「来源清单只列实际进入请求的资料」与「截断/缺失回显」（A5）。"""
    parts = []
    明细 = []
    used = 0
    for path, rel in files:
        path = _check_in_root(path, kb_root)
        if not os.path.isfile(path):
            明细.append((rel, "missing"))            # 列出后消失/不可读 → 记为缺失（不静默丢）
            continue
        header = _doc_header(rel)
        content = _read_text(path)
        room = budget - used - len(header)
        if room <= 0:
            parts.append(f"\n(知识库文档 {rel} 因超出字符预算未加载)\n")
            明细.append((rel, "skipped"))               # 预算耗尽 → 未进入请求
            continue
        if len(content) > room:
            content = content[:room] + "\n（文档已截断）"
            明细.append((rel, "truncated"))
        else:
            明细.append((rel, "full"))
        parts.append(header + content)
        used += len(header) + len(content)
    return "".join(parts), 明细


def _来源与回执(明细):
    """由 _assemble_docs 的明细派生 (实际进入请求的清单, 回执 dict)：
    清单只含 full+truncated（真正进了 prompt 的资料），排除 skipped/missing；
    回执把四类分开，供界面回显「截断/缺失/未加载」（A5）。"""
    实际 = [rel for rel, 状态 in 明细 if 状态 in ("full", "truncated")]
    回执 = {
        "included": 实际,
        "truncated": [rel for rel, 状态 in 明细 if 状态 == "truncated"],
        "skipped": [rel for rel, 状态 in 明细 if 状态 == "skipped"],
        "missing": [rel for rel, 状态 in 明细 if 状态 == "missing"],
    }
    return 实际, 回执


# ================= H3 知识库加载 =================

def load_skill_docs(风格, 任务类型, 辅助风格="无"):
    """按风格下拉加载技能文件夹文档。
    加载优先级：主技能说明 > 主技能参考资料 > 辅助技能说明 > 术语表。
    风格=通用H3提示词写作 时参考资料按任务类型二选一（Ref2VA 用全参考指南）。
    返回 (文档文本, 实际进入请求的相对名清单, 回执 dict)（A5：清单排除因预算被跳过者；
    回执 = {included, truncated, skipped, missing}）。"""
    if not os.path.isdir(KB_H3_ROOT):
        raise FileNotFoundError(f"未找到 MiniMax-H3知识库 目录: {KB_H3_ROOT}")
    folder = H3_SKILL_FOLDERS.get(风格)
    if folder is None:
        raise ValueError(f"未知的 H3 风格: {风格}")
    skill_dir = os.path.join(KB_H3_ROOT, folder)
    if not os.path.isdir(skill_dir):
        raise FileNotFoundError(f"未找到技能文件夹: {skill_dir}")

    files = []
    说明 = os.path.join(skill_dir, "技能说明.md")
    if os.path.isfile(说明):
        files.append((说明, f"{folder}/技能说明.md"))

    ref_dir = os.path.join(skill_dir, "参考资料")
    if os.path.isdir(ref_dir):
        if folder == "H3提示词写作":
            # 按任务类型二选一指南，避免多份指南同时占预算；
            # Ref2VA 用精炼版；"音频对口型" 是 Ref2VA 的场景变体，共用同一份指南
            if 任务类型 in ("全能参考生视频(Ref2VA)", "音频对口型"):
                指南组 = ["全参考模式精炼版.txt"]
            else:
                指南组 = ["基础模式提示词指南.txt"]
            for 指南 in 指南组:
                p = os.path.join(ref_dir, 指南)
                if os.path.isfile(p):
                    files.append((p, f"{folder}/参考资料/{指南}"))
        else:
            for name in sorted(os.listdir(ref_dir)):
                if name.lower().endswith((".md", ".txt")):
                    files.append((os.path.join(ref_dir, name), f"{folder}/参考资料/{name}"))

    if 辅助风格 and 辅助风格 != "无":
        aux_folder = H3_SKILL_FOLDERS.get(辅助风格)
        if aux_folder:
            aux_说明 = os.path.join(KB_H3_ROOT, aux_folder, "技能说明.md")
            if os.path.isfile(aux_说明):
                # 辅助风格只取技能说明（不取参考资料），控制输入量
                files.append((aux_说明, f"{aux_folder}/技能说明.md (辅助风格)"))

    术语表 = os.path.join(KB_H3_ROOT, "翻译规范与术语表.md")
    if os.path.isfile(术语表):
        files.append((术语表, "翻译规范与术语表.md"))

    文本, 明细 = _assemble_docs(files, KB_H3_ROOT, H3_CHAR_BUDGET)
    实际, 回执 = _来源与回执(明细)
    return 文本, 实际, 回执
