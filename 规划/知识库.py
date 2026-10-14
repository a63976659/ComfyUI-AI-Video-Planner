# -*- coding: utf-8 -*-
"""独立加载规划 Skills 与时间轴唯一的通用提示词改写技能。"""
import os
from pathlib import Path

from .技能注册 import 注册技能, 解析技能, _资料路径
from .技能资料 import 资料依赖, 读取正文

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KB_H3_ROOT = os.path.join(PLUGIN_ROOT, "AI生成提示词")
# AI规划使用 Skills；时间轴仅使用通用改写技能，两者职责独立。
SKILLS_ROOT = os.path.join(PLUGIN_ROOT, "Skills")

# 对外显示名与现有任务指南路径分开，避免改变执行协议。
通用改写技能 = "通用提示词改写"
H3_SKILL_FOLDERS = {通用改写技能: "."}
# 旧计划/旧浏览器的选择只迁移到通用改写，不再注入旧风格或制作流程。
_旧改写选择 = frozenset(("不指定", "通用H3提示词写作", "3D动画短片", "极简产品广告",
                     "纸艺定格科普", "品牌宣传", "MV歌词字幕", "双人游戏开场",
                     "纸质拼贴讲解", "手绘实拍融合"))


def 规范改写技能(技能=None):
    value = str(技能 or 通用改写技能).strip()
    if value == 通用改写技能 or value in _旧改写选择:
        return 通用改写技能
    raise ValueError(f"未知的提示词改写技能: {value}")

# 规划器任务码 -> 知识库任务类型（兼容已有请求字段）
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
    """兼容旧元数据接口，仅公布唯一改写技能。"""
    return [通用改写技能]


def 辅助风格选项() -> list:
    """兼容旧元数据接口；时间轴不再支持辅助技能。"""
    return ["无"]


def 技能选项() -> list:
    """按技能目录公布可选技能。"""
    if not os.path.isdir(SKILLS_ROOT):
        return ["不指定"]
    names = sorted(card["显示名称"] for card in 注册技能(Path(SKILLS_ROOT)).values())
    return ["不指定"] + names


def load_skills_docs(技能, 辅助风格="无"):
    if not os.path.isdir(SKILLS_ROOT):
        raise FileNotFoundError(f"未找到 Skills 目录: {SKILLS_ROOT}")
    if 技能 == "不指定":
        return "", [], {key: [] for key in ("included", "truncated", "skipped", "missing")}
    root = Path(SKILLS_ROOT).resolve()
    cards = 注册技能(root)
    selected = [技能]
    if 辅助风格 not in (None, "无", "不指定", 技能):
        selected.append(辅助风格)
    paths, dependencies, visited = [], [], set()
    def add(name):
        card = 解析技能(cards, name)
        if card["技能标识"] in visited:
            return
        visited.add(card["技能标识"])
        for dep in card.get("依赖技能", []):
            add(dep["技能标识"])
        for item in card["资料文件"]:
            if item.get("用途") == "技能入口":
                continue
            paths.append(item["路径"])
            dependencies.extend(item.get("依赖资料", []))
    for name in selected:
        add(name)
    docs = 资料依赖(paths, dependencies, root=root)
    from .技能资料 import 共用目录
    _, commons = 共用目录(root)
    files = [(_资料路径(root, commons[doc["技能"]]["路径"]), commons[doc["技能"]]["路径"]) for doc in docs]
    files.extend((_资料路径(root, value), value) for value in dict.fromkeys(paths))
    for _, value in files:
        读取正文(root, value)
    文档, 明细 = _assemble_docs(files, SKILLS_ROOT, None)
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
        room = None if budget is None else budget - used - len(header)
        if room is not None and room <= 0:
            parts.append(f"\n(知识库文档 {rel} 因超出字符预算未加载)\n")
            明细.append((rel, "skipped"))               # 预算耗尽 → 未进入请求
            continue
        if room is not None and len(content) > room:
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


# ================= 时间轴提示词改写资料加载 =================

def load_skill_docs(风格, 任务类型, 辅助风格="无", *, 精简=False):
    """完整加载共用提示词规则与参考，返回真实来源清单和读取回执。"""
    规范改写技能(风格)
    if not os.path.isdir(KB_H3_ROOT):
        raise FileNotFoundError(f"未找到 AI生成提示词 目录: {KB_H3_ROOT}")
    parts, details = [], []
    for rel in ("SKILL.md", "参考资料/完整提示词规则.md"):
        path = _check_in_root(os.path.join(KB_H3_ROOT, *rel.split("/")), KB_H3_ROOT)
        if not os.path.isfile(path):
            details.append((rel, "missing"))
            continue
        content = _read_text(path)
        if not content.strip():
            details.append((rel, "missing"))
            continue
        parts.append(_doc_header(rel) + content)
        details.append((rel, "full"))
    files, receipt = _来源与回执(details)
    return "".join(parts), files, receipt
