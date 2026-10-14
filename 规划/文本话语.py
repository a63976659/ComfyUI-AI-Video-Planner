"""区分制作标题与角色话语；仅提取原文中的连续文字，不改写内容。"""
import re

台词项上限 = 16
来源协议版本 = "引用ID-v1"
台词来源契约 = (
    "必留台词表示用户已提供原文中的逐字话语，不表示视频里所有需要说出的内容。"
    "用户只给作品题目或创作主题、没有给具体诗句/对白时，必留台词必须为[]。"
    "创作补全的朗诵、讲解和对白完整写入内容，再由镜头对白/旁白承载，不能冒充用户原文；"
    "题目引用不等于已经提供作品全文。新增内容须说明依据与限制，不编造未核实的事实。"
    "必留台词字段逐字保留原有标点，包括句末句号；跨镜片段拼接后仍须保留全部原文标点。"
)


def 原文引文候选(text):
    """结构化枚举与字段示例共用真实连续引文，不另行截取不在枚举中的片段。"""
    if not isinstance(text, str):
        return []
    quotes = [s.strip() for s in re.findall(r"[^。！？\n]+[。！？]?", text)
              if s.strip()]
    quotes.extend(text[i:i + 1000].strip() for i in range(0, len(text), 1000)
                  if text[i:i + 1000].strip())
    return list(dict.fromkeys(s for s in quotes if s in text))


def 原文来源引用表(scopes):
    """模型选择编号，程序持有并恢复范围与逐字引文。编号仅在本次请求内有效。"""
    table = {}
    for scope in scopes:
        quotes = 原文引文候选(scope.get("正文"))
        if not quotes:
            raise ValueError(f"原文范围{scope.get('id', '')}为空，无法提供真实来源引文，不能发起内容理解")
        for quote in quotes:
            table[f"原文引文{len(table) + 1}"] = {"范围": scope["id"], "引文": quote}
    return table

需求标题 = re.compile(r"需求|要求|说明|想法|故事|目标|要点|资料|知识|科普|产品|卖点|品牌|备注|限制|歌词|旁白|字幕|时长|摘要|场景|人物|角色|分镜|镜头|音乐|音频|音轨|主题|标题|正文|内容|创意|任务|用途|MV", re.I)
行动标题 = re.compile(r"^(?:我|你|他|她|它|我们|你们|他们|她们|它们)(?:想|要|希望|需要|准备|决定|正在|将|会)|^(?:做|制作|生成|设计|讲解|解释|介绍|根据|请|保留)")


def 对白标签(text):
    return [(label, line.strip()) for label, line in
            re.findall(r"(?m)^[ \t]*([\w\u4e00-\u9fff]{1,6})[：:][ \t]*([^\n]+)", text)
            if line.strip() and not 需求标题.search(label) and not 行动标题.search(label)]


def 候选台词(text):
    quoted = re.findall(r'“([^”\n]+)”|‘([^’\n]+)’|「([^」\n]+)」|『([^』\n]+)』|"([^"\n]+)"', text)
    lines = [next(part for part in parts if part).strip() for parts in quoted]
    lines.extend(s.strip() for s in re.findall(
        r"(?:说|道|问|喊|叫|回答|回应|低语|旁白|对白|必留台词|保留台词|台词|歌词|演唱|音乐MV)[：:][ \t]*([^。！？\n]+[。！？]?)",
        text) if s.strip() and s.strip()[0] not in '“‘「『"')
    for label, line in 对白标签(text):
        if line[0] not in '“‘「『"':
            lines.append(line)
    # 保留完整话语，由镜头编排按实际发音时长分配，不设字符上限。
    return list(dict.fromkeys(line for line in lines if line.strip() and line in text))


def 内容话语候选(data):
    """生成请求与结构化返回共用原文话语候选，不从模型补全的内容提取。"""
    lines = []
    for scope in data.get("原文", []):
        raw = scope.get("正文", "") if isinstance(scope, dict) else ""
        if isinstance(raw, str):
            lines.extend(候选台词(raw))
    for block in data.get("分块理解", []):
        if isinstance(block, dict):
            for unit in block.get("内容单元", []):
                if isinstance(unit, dict):
                    lines.extend(line for line in unit.get("必留台词", [])
                                 if isinstance(line, str) and line.strip())
    return list(dict.fromkeys(lines))


def 恢复话语标点(line, candidates, 后续片段=""):
    if not line or re.search(r"[，。！？；：、,.!?;:…—]$", line):
        return line
    versions = set()
    for candidate in candidates:
        for match in re.finditer(re.escape(line), candidate):
            tail = re.match(r"[，。！？；：、,.!?;:…—]+", candidate[match.end():])
            versions.add(line + tail.group() if tail else line)
    if len(versions) > 1:
        raise ValueError("必留台词标点存在多个原文匹配，不能确定唯一原文片段；请保留对应原文的完整标点")
    restored = next(iter(versions)) if versions else line
    return line if 后续片段.startswith(restored[len(line):]) else restored


def 绑定文案原话(tasks, lines):
    pattern = r"[\u3400-\u9fff]|[^\W_\u3400-\u9fff]+(?:['’][^\W_\u3400-\u9fff]+)*"
    cursor = 0
    for line in lines:
        expected = list(re.finditer(pattern, line))
        if not expected:
            continue
        observed = [(task, field, match) for task in tasks for field in ("对白", "旁白")
                    for match in re.finditer(pattern, task.get(field, ""))]
        wanted = [match.group() for match in expected]
        positions = [index for index in range(cursor, len(observed) - len(expected) + 1)
                     if [match.group() for _, _, match in observed[index:index + len(expected)]] == wanted]
        if len(positions) != 1:
            continue
        start = positions[0]
        matched = observed[start:start + len(expected)]
        index = 0
        while index < len(matched):
            task, field, first = matched[index]
            stop = index + 1
            while stop < len(matched) and matched[stop][0] is task and matched[stop][1] == field:
                stop += 1
            last = matched[stop - 1][2]
            text = task[field]
            following = re.search(pattern, text[last.end():])
            right = last.end() + following.start() if following else len(text)
            origin_left = expected[index].start() if index else 0
            origin_right = expected[stop].start() if stop < len(expected) else len(line)
            task[field] = text[:first.start()] + line[origin_left:origin_right] + text[right:]
            index = stop
        cursor = start + len(expected)



def 编号演唱段落(text):
    """识别分镜的演唱段落及真实短引文；歌词用于定位，不自动成为必留话语。"""
    matches = []
    pattern = r'(?m)^[ \t]*(音频\d+|歌词\d*)[：:][ \t]*[“「"]([^”」"\n]+)[”」"]'
    for match in re.finditer(pattern, text):
        marker, _ = match.groups()
        if marker.startswith("音频") and not re.match(r"[ \t\r\n]*演唱分配[：:]", text[match.end():]):
            continue
        matches.append(match)
    return [{"标记": match.group(1), "参考引文": match.group().strip(), "起": match.start(),
             "止": matches[index + 1].start() if index + 1 < len(matches) else len(text)}
            for index, match in enumerate(matches)]
