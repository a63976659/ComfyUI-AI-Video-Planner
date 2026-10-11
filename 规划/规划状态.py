"""由程序绑定原文、内容和镜头身份；状态仅记录已有字段，不推测实际画面。"""
import copy
import re
from .规划契约 import 指纹


def 原文索引(scopes):
    result = []
    for scope in scopes:
        raw = scope["正文"]
        file_id = 指纹({"来源": scope.get("来源", scope["id"]), "正文": raw,
                       "起": scope.get("起", 0)})
        for match in re.finditer(r"[^。！？\r\n]+[。！？]?", raw):
            text = match.group().strip()
            if not text:
                continue
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            for offset in range(0, len(text), 1000):
                a, b = start + offset, start + min(offset + 1000, len(text))
                result.append({"稳定标识": "原文-" + 指纹([file_id, a, b])[:24],
                               "范围": scope["id"], "起": a, "止": b, "引文": raw[a:b]})
    return result


def 绑定内容身份(units, scopes):
    indices = 原文索引(scopes)
    lookup = {s["id"]: s for s in scopes}
    seen, locations = {}, {}
    for unit in units:
        spans = []
        for source in unit["来源"]:
            scope = lookup[source["范围"]]
            quote = source["引文"]
            location_key = (source["范围"], quote)
            if location_key not in locations:
                locations[location_key] = [m.start() for m in re.finditer("(?=" + re.escape(quote) + ")", scope["正文"])]
            positions = locations[location_key]
            spans.append({"范围": source["范围"], "来源": scope.get("来源", source["范围"]),
                          "范围版本": 指纹(scope["正文"]), "位置": positions[:24], "长度": len(quote),
                          "匹配数": len(positions), "位置摘要": 指纹(positions)})
        key = 指纹({"来源位置": spans, "内容": unit["内容"], "必留台词": unit.get("必留台词", [])})
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        unit["稳定标识"] = "事件-" + 指纹([key, ordinal])[:24]
        unit["来源位置"] = spans
        unique_spans = [span for span in spans if span["匹配数"] == 1]
        unit["原文单元"] = [item["稳定标识"] for item in indices if any(
            item["范围"] == span["范围"] and span["位置"][0] < item["止"] and span["位置"][0] + span["长度"] > item["起"]
            for span in unique_spans)]
        unit["来源歧义"] = any(span["匹配数"] > 1 for span in spans)
    return indices


def 绑定镜头身份(shots, units):
    lookup = {u["id"]: u.get("稳定标识", u["id"]) for u in units}
    counts = {}
    for shot in shots:
        sources = [lookup[ident] for ident in shot["内容单元"]]
        key = tuple(sources)
        counts[key] = counts.get(key, 0) + 1
        shot["稳定标识"] = "镜头-" + 指纹([sources, counts[key]])[:24]
        shot["内容事件"] = sources


def 实体索引(entities):
    result, seen = [], set()
    for entity in entities:
        name = entity.get("名称") if isinstance(entity, dict) else entity
        kind = entity.get("类型", "未分类") if isinstance(entity, dict) else "未分类"
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        identity = "实体-" + 指纹([kind, name])[:24]
        if identity not in seen:
            seen.add(identity)
            result.append({"稳定标识": identity, "类型": kind, "名称": name})
    return result


def 连续性账本(shots, entities=()):
    """给跨批任务已定稿的最近声明；不以文字账本宣称视觉验收通过。"""
    latest = {}
    for shot in shots:
        subject = shot.get("主体", "")
        if not subject:
            continue
        record = {k: copy.deepcopy(shot[k]) for k in
                           ("主体", "结束状态", "连续性", "使用素材", "素材职责") if k in shot}
        matches = [e["稳定标识"] for e in entities if e["名称"] == subject]
        if len(matches) == 1:
            record["实体标识"] = matches[0]
        latest[subject] = record
    return {"已记录主体": list(latest.values()),
            "证据边界": "这些是已定稿分镜中的声明，不是实际图像、视频或音轨验收。主体名称未经实体消歧时不能据此断言是同一人物。"}


def 定位修订问题(issues, segments):
    result = copy.deepcopy(issues)
    for issue in result:
        numbers = issue.get("镜号", [])
        if numbers:
            issue["关联单元"] = list(dict.fromkeys(ident for number in numbers
                if 1 <= number <= len(segments)
                for ident in segments[number - 1].get("镜头资料", {}).get("内容单元", [])))
            linked = list(dict.fromkeys(ident for number in numbers
                if 1 <= number <= len(segments)
                for ident in segments[number - 1].get("镜头资料", {}).get("内容事件", [])))
            if linked:
                issue["关联事件"] = linked
    return result
