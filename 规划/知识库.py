# -*- coding: utf-8 -*-
"""独立加载规划 Skills 与时间轴唯一的通用提示词改写技能。"""
import os
from .技能注册 import 注册技能, 装配资料

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KB_H3_ROOT = os.path.join(PLUGIN_ROOT, "AI生成提示词")
# AI规划使用 Skills；时间轴仅使用通用改写技能，两者职责独立。
SKILLS_ROOT = os.path.join(PLUGIN_ROOT, "Skills")

# 手动选择规划技能时的资料预算。
H3_CHAR_BUDGET = 60000

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
    """从技能目录读取可选名称及已有名称映射。"""
    if not os.path.isdir(SKILLS_ROOT):
        return ["不指定"]
    cards = 注册技能(SKILLS_ROOT)
    names = sorted({name for card in cards.values() for name in [card["显示名称"], *card.get("旧名称", [])]})
    return ["不指定"] + names


def load_skills_docs(技能, 辅助风格="无"):
    """加载所选技能及依赖，返回正文、实际来源和回执。"""
    if 技能 == "不指定":
        return "", [], {"included": [], "truncated": [], "skipped": [], "missing": []}
    cards = 注册技能(SKILLS_ROOT)
    by_name = {name: key for key, card in cards.items() for name in [card["显示名称"], *card.get("旧名称", [])]}
    if 技能 not in by_name:
        raise ValueError(f"未知的 Skills 技能: {技能}")
    items, seen = [], set()
    def add(key):
        if key in seen:
            return
        seen.add(key)
        card = cards[key]
        for dep in card.get("依赖技能", []):
            add(dep["技能标识"])
        items.extend({**doc, "技能": doc["路径"]} for doc in sorted(card["资料文件"], key=lambda d: -d.get("优先级", 0)))
    add(by_name[技能])
    if 辅助风格 not in ("无", "不指定", 技能) and 辅助风格 in by_name:
        card = cards[by_name[辅助风格]]
        items.extend({**doc, "技能": doc["路径"] + " (辅助风格)"} for doc in card["资料文件"]
                     if doc["路径"].endswith("/技能说明.md"))
    docs, receipt = 装配资料(items, None, SKILLS_ROOT, H3_CHAR_BUDGET)
    text = "".join(_doc_header(doc["技能"]) + doc["资料"] for doc in docs)
    return text, receipt["included"], receipt


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


def _来源与回执(明细):
    """由读取明细派生 (实际进入请求的清单, 回执 dict)：
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
    """加载 H3 使用的主入口和格式参考，旧选择参数仅兼容，不遍历或截断资料。

    其他模型直接读取主入口，不加载 H3 格式；返回真实来源清单与缺失回执。
    """
    规范改写技能(风格)
    if not os.path.isdir(KB_H3_ROOT):
        raise FileNotFoundError(f"未找到 AI生成提示词 目录: {KB_H3_ROOT}")
    parts, details = [], []
    for rel in ("SKILL.md", "参考资料/H3格式.md"):
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
