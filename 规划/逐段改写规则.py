# -*- coding: utf-8 -*-
"""单段改写共享边界：不把整篇需求或邻段当作生成上下文。"""
import re

独立描述规则 = (
    "每段提示词必须能独立使用。跨段关联仅依据主题和当前目标，不引用前段、后段或此前成稿。"
    "明确写出当前人物的姓名或主体称谓、已有固定特征、场景及动作起止；"
    "禁止用‘和前面一样’‘继续之前的’‘同一个女孩’‘同上’等替代具体描述。"
    "段内已经明确主体后的代词可以使用，锁定台词逐字保留。"
    "只用当前段原稿、绑定的人物资料和素材说明补清描述，缺少特征时使用已有主体称谓，不能猜测外貌或新增剧情。"
)
_依赖前文 = re.compile(
    r"(?:和|与|跟)(?:前面|之前|上一段|上一个镜头)(?:的)?(?:一样|相同)|"
    r"继续之前的|同(?:一个|一位|一名)(?:女孩|男孩|女人|男人|女子|男子|人物|角色|少女|青年)|"
    r"同上|如前所述|沿用(?:前段|上一段|上个镜头)|(?:承接|延续)(?:前段|上一段|上个镜头)"
)


def 精简关联(brief, shot=None, 资料=None):
    brief = brief if isinstance(brief, dict) else {}
    shot = shot if isinstance(shot, dict) else {}
    data = 资料 if isinstance(资料, dict) else {}
    return {"主题": brief.get("主题") or "",
            "当前目标": shot.get("职能") or shot.get("标题") or "优化当前已定稿分镜，保留人物、场景、动作及台词",
            "风格": brief.get("风格") or "", "作品语言偏好": brief.get("语言") or "中文",
            "禁止配乐": brief.get("禁止配乐") is True,
            "执行全局提示词": data.get("执行提示词") or ""}


def 独立描述问题(prompt, dialogue=""):
    # 对白属于冻结内容，不因为角色说出“同一个女孩”等原话而删改台词。
    text = re.sub(r"<d>.*?</d>", "", prompt, flags=re.S)
    if isinstance(dialogue, str):
        for line in dialogue.splitlines():
            if line.strip():
                text = text.replace(line.strip(), "")
    issues = []
    for m in _依赖前文.finditer(text):
        prefix = text[:m.start()].split("\n\n")[-1]
        if m[0].startswith("同") and re.search(r"女孩|男孩|女人|男人|女子|男子|少女|青年|小[\u4e00-\u9fff]{1,2}|[\u4e00-\u9fff]{2,3}(?:穿|站|走|坐|推|看|抬)", prefix):
            continue
        issues.append("提示词依赖前文，请依据当前段资料明确人物、场景和动作：" + m[0])
    return issues[:8]
