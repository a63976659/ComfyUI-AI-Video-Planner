from pathlib import Path
from .技能资料 import 共用目录, 读取共用

中文发音字数 = 4
声音字段 = ("说话人", "声源", "声线", "语言", "语速", "情绪", "停顿重音")


def 读取规划规则():
    catalog = 共用目录()
    directory, _ = catalog
    texts = {}
    interface = (Path(__file__).resolve().parent / "技能适配/接口规则.md").read_text(encoding="utf-8-sig")
    rules = {}
    for _section in interface.split("\n## ")[1:]:
        _name, _, _body = _section.partition("\n")
        rules[_name.strip()] = "".join(_body.splitlines()).strip()
    rules["共用阶段"] = {}
    for stage in ("输入归一", "原文分析", "内容规划", "镜头编排", "动作专项", "实体设计", "辅助图设计", "模型适配"):
        keys = [*directory.get("系统规则", []), *directory.get("阶段系统规则", {}).get(stage, [])]
        sections = ["生成核对规则", "规划处理规则"]
        if stage in ("内容规划", "镜头编排", "动作专项", "模型适配"):
            sections.append("规划默认规则")
        if stage == "内容规划":
            sections.append("内容理解规则")
        elif stage == "镜头编排":
            sections.extend(("镜头编排规则", "声音输出要求"))
        for section in sections:
            keys.extend(directory.get("程序规则", {}).get(section, []))
        rules["共用阶段"][stage] = "\n".join(doc["资料"] for doc in 读取共用(keys, stage, _目录=catalog, _正文=texts))
    rules["默认接口"] = "\n".join(rules[name] for name in (
        "缺省决策与声音定稿", "段落与声景规则", "规划处理规则", "生成核对规则", "技能适用边界"))
    rules["默认"] = rules["共用阶段"]["内容规划"] + "\n" + rules["默认接口"]
    return rules


_规则 = 读取规划规则()

段落与声景规则 = _规则["段落与声景规则"]
规划处理规则 = _规则["规划处理规则"]
内容理解规则 = _规则["内容理解规则"]
镜头编排规则 = _规则["镜头编排规则"]
生成核对规则 = _规则["生成核对规则"]
声音输出要求 = _规则["声音输出要求"]
规划默认规则 = _规则["默认"]


def 规划阶段规则(stage, 规则=None):
    rules = _规则 if 规则 is None else 规则
    if stage in ("分析输入", "识别需求", "章节理解", "全剧分层理解"):
        original = stage in ("章节理解", "全剧分层理解")
        names = ["原文分析规则" if original else "输入分析规则", "生成核对规则", "技能适用边界"]
        phase = "原文分析" if original else "输入归一"
        return rules["共用阶段"][phase] + "\n" + "\n".join(rules[name] for name in names)
    if stage in ("理解内容", "汇总内容"):
        return rules["默认"] + rules["内容理解规则"]
    if stage == "编排镜头":
        return rules["共用阶段"]["镜头编排"] + rules["默认接口"] + rules["镜头编排规则"] + rules["声音输出要求"]
    if stage in ("设计实体参考", "准备实体绘图"):
        return rules["共用阶段"]["实体设计"] + rules["规划处理规则"] + rules["生成核对规则"]
    return rules["默认"]
