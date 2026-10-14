import copy

from .镜头设计 import 对象字段, 估时字段, 素材角色
from .规划默认规则 import 声音字段
from .规划定稿 import 声音角色, _声音身份


文本字段 = ("标题", "主体", "动作", "景别", "机位", "画面", "职能", "情绪", "镜头目的", "起始状态", "结束状态", "切镜理由")
内容定稿字段 = ("对白", "旁白", "时长依据", "建议秒数")
声音身份字段 = ("声源", "声线", "语言")
发声文案约定 = (
    "对白和旁白承载全部实际发声文字，包括演唱、歌词、朗诵与对白。画内角色演唱的歌词填对白，"
    "画外歌词或解说填旁白；歌词不能只写在画面、动作、声景或声音设计中。无发声的对应字段填空字符串。")


def 独立镜头任务(units, finalized=None, 前镜=None, 待绑定前镜=False):
    tasks = []
    previous_end = (前镜 or {}).get("结束要求")
    for unit in units:
        unit = copy.deepcopy(unit)
        rows = unit.get("镜头任务") or unit.get("逐镜任务") or [
            {"任务": unit["内容"], "建议秒数": 8} for _ in range(unit.get("建议镜头数", 1))]
        for row in rows:
            if (row.get("衔接方式") == "连续" or ("衔接方式" not in row and row.get("起始要求") == "")) and previous_end:
                row["起始要求"] = previous_end
            if row.get("衔接方式") == "连续" and not row.get("起始要求", "").strip() and not 待绑定前镜:
                raise ValueError("首个连续镜头须提供初始状态，后续镜头由程序承接前镜结束")
            previous_end = row.get("结束要求")
        if unit.get("镜头任务") and all(all(key in row for key in ("对白", "旁白")) for row in rows):
            speech = [row["对白"] + row["旁白"] for row in rows]
            joined, cursor, quotes = "".join(speech), 0, []
            for row in rows:
                row["原文话语"] = []
            for line in unit.get("必留台词", []):
                start = joined.find(line, cursor)
                if start < 0:
                    raise ValueError(f"{unit['id']}的已定文案遗漏原文话语：{line}")
                stop, offset = start + len(line), 0
                for row, text in zip(rows, speech):
                    left, right = max(start, offset), min(stop, offset + len(text))
                    if left < right:
                        quotes.append(text[left-offset:right-offset])
                        row["原文话语"].append(len(quotes))
                    offset += len(text)
                cursor = stop
            unit["必留台词"] = quotes
        assigned = []
        for index, row in enumerate(rows):
            task = copy.deepcopy(row)
            quotes = unit.get("必留台词", [])
            indices = task.get("原文话语")
            if indices is None:
                if len(rows) == 1:
                    indices = list(range(1, len(quotes) + 1))
                else:
                    text = task.get("对白", "") + task.get("旁白", "") + task.get("任务", "")
                    indices = [i + 1 for i, quote in enumerate(quotes) if quote in text and i + 1 not in assigned]
            if any(i > len(quotes) for i in indices):
                raise ValueError(f"{unit['id']}镜头任务引用了不存在的原文话语")
            assigned.extend(indices)
            group = {key: copy.deepcopy(value) for key, value in unit.items() if key not in ("镜头任务", "逐镜任务")}
            group.update(必留台词=[quotes[i - 1] for i in indices], 本批镜头数=1,
                         单元镜头序号=index + 1, 单元总镜头数=len(rows), 本批结束单元=True)
            tasks.append({"单元": group, "任务": task, "单元任务": copy.deepcopy(rows)})
        if sorted(assigned) != list(range(1, len(unit.get("必留台词", [])) + 1)):
            raise ValueError(f"{unit['id']}的必留原文须在镜头任务中逐项分配；原文话语填写从1开始的编号")
    if finalized is not None:
        for item, task in zip(tasks, finalized):
            item["定稿"] = copy.deepcopy(task)
    return tasks


def 绑定字段(payload):
    bound = {}
    task = payload.get("本镜任务", {})
    for source, target in (("起始要求", "起始状态"), ("结束要求", "结束状态")):
        value = task.get(source)
        if isinstance(value, str) and value.strip():
            bound[target] = value
    units = payload.get("内容单元", [])
    if len(units) == 1:
        bound["内容单元"] = [units[0]["id"]]
    timing = payload.get("本镜时长预算") or payload.get("本镜时长定稿")
    if isinstance(timing, dict) and timing.get("由程序绑定") is True:
        bound["建议秒数"] = timing["建议秒数"]
    task = payload.get("本镜内容定稿")
    if isinstance(task, dict) and task.get("由程序绑定") is True:
        bound.update({key: copy.deepcopy(task[key]) for key in 内容定稿字段})
        if not task["对白"].strip() and not task["旁白"].strip():
            bound["声音设计"] = {}
    script = payload.get("本镜文案定稿")
    if isinstance(script, dict):
        bound.update({key: script[key] for key in ("对白", "旁白")})
        if not script["对白"].strip() and not script["旁白"].strip():
            bound["声音设计"] = {}
    return bound


def 创作字段(payload):
    fields = (*文本字段, *对象字段, "声音设计", "使用素材", "素材职责", *内容定稿字段, "内容单元")
    bound = 绑定字段(payload)
    automatic = payload.get("本镜文案定稿") and payload.get("需求", {}).get("总时长") == 0 and "建议秒数" not in bound
    return [key for key in fields if key not in bound and not (automatic and key == "建议秒数")]


def 准备镜头创作(payload):
    data = copy.deepcopy(payload)
    bound = 绑定字段(data)
    if "内容单元" in bound:
        data["镜头内容单元归属"] = {"由程序绑定": True, "固定值": bound["内容单元"]}
        data["本批覆盖要求"]["规则"] = ("程序绑定当前单元，输出镜头不填写内容单元字段；当前镜头任务见本镜任务。"
            + data["本批覆盖要求"].get("规则", "")
            + "当前镜只推进本单元的一部分是正常分工，后续镜头继续；不把未在本镜完成整单元报告为需求冲突。")
    known = data.setdefault("已定声音身份", {})
    for voice in data.get("项目设计", {}).get("声音方案", []):
        if isinstance(voice, dict) and all(isinstance(voice.get(key), str) for key in ("说话人", *声音身份字段)):
            for speaker, identity in _声音身份(voice).items():
                if all(isinstance(identity.get(key), str) and identity[key].strip() for key in 声音身份字段):
                    known.setdefault(speaker, identity)
    fields = 创作字段(data)
    data["镜头创作约定"] = {
        "输出字段": fields, "程序绑定字段": list(bound),
        "只读资料": ["本镜任务", "本镜文案定稿", "本镜内容定稿", "本镜时长预算", "本镜时长定稿", "本镜声景方案", "内容单元", "原文对照", "项目设计", "已定声音身份",
                     "人物场景", "实体索引", "相邻镜头计划", "内容任务分工", "时间预算"],
        "文本字段": [key for key in (*文本字段, "对白", "旁白") if key in fields],
        "对象字段": {key: list(value) for key, value in 对象字段.items() if key in fields},
        "数组字段": {"使用素材": "真实文件名字符串数组",
                     "素材职责": {"字段": ["文件", "职责", "限制"], "职责枚举": sorted(素材角色)}},
    }
    if "声音设计" in fields:
        data["镜头创作约定"]["声音设计"] = {"完整字段": list(声音字段)}
        task = data.get("本镜内容定稿")
        if isinstance(task, dict) and task.get("由程序绑定") is True:
            data["镜头创作约定"]["声音设计"]["本镜有发声"] = bool(task["对白"].strip() or task["旁白"].strip())
        if known:
            data["镜头创作约定"]["声音设计"]["引用已定身份时填写"] = ["说话人", "语速", "情绪", "停顿重音"]
            data["镜头创作约定"]["声音设计"]["可复用说话人"] = list(known)
        if data.get("本镜声音身份"):
            data["镜头创作约定"]["声音设计"]["本镜填写"] = ["情绪", "停顿重音"]
        data["镜头创作约定"]["声音设计"]["字段适用"] = "首次出现的说话人填写完整字段；只可省略当前可复用说话人的已定身份字段。"
        if data.get("本镜声音身份"):
            data["镜头创作约定"]["声音设计"] = {"本镜填写": ["情绪", "停顿重音"], "身份由程序绑定": True}
    if "时长依据" in fields:
        data["镜头创作约定"]["对象字段"]["时长依据"] = [key for key in 估时字段 if key != "中文每秒字数"]
        script = data.get("本镜文案定稿")
        if script and not (script.get("对白", "") + script.get("旁白", "")).strip():
            data["镜头创作约定"]["对象字段"]["时长依据"].remove("动作与台词")
        data["镜头创作约定"]["可选数值字段"] = [] if data.get("本镜文案定稿") else ["时长依据.发声秒"]
        data["镜头创作约定"]["数值字段"] = (["建议秒数"] if "建议秒数" in fields else []) + [
            f"时长依据.{key}" for key in ("动作秒", "停顿秒", "反应秒")]
    if data.get("本镜声景方案"):
        data["镜头创作约定"]["对象字段"]["声景设计"] = [key for key in 对象字段["声景设计"] if key not in data["本镜声景方案"]]
    single = data.get("本镜任务", {}).get("输出新镜头数") == 1
    data["单镜创作"] = single
    data["输出要求"] = ("直接返回当前镜头对象。" if single else "返回包含镜头数组的对象。") + "字段类型见镜头创作约定，创作方法由Skills提供。当前阶段不输出冲突、验收或诊断报告，将创作选择落实到镜头字段。"
    if data.get("本镜文案定稿"):
        data["输出要求"] += "本镜完整对白、旁白、发声时间与说话身份已经确定，由程序绑定；不重写、增删、重复输出或转移到其他镜头。时长依据只安排与已定发声对应的必要行动、停顿和反应，不重复填写发声秒。"
        if "建议秒数" not in fields and "建议秒数" not in bound:
            data["输出要求"] += "自动模式的执行秒数由程序按已定发声及本镜必要表演计算，不另填建议秒数，不把内容计划的建议值当作必须填满的预算。"
    if data.get("本镜声景方案"):
        data["输出要求"] += "环境音和音乐由本镜声景方案绑定，不重复选择；声景设计只创作当前音效、进入退出及与人声关系，沿用已有声音。"
    if "对白" in fields or "旁白" in fields:
        data["镜头创作约定"]["发声话语"] = 发声文案约定
        locked = [line for unit in data.get("内容单元", []) for line in unit.get("必留台词", [])]
        if locked:
            data["镜头创作约定"]["本镜必留话语"] = locked
            data["输出要求"] += "本镜必留话语须完整逐字写入对白或旁白字段，不得只在画面或声音设计中描述演唱，也不得两项同时留空。"
    if single:
        data["输出要求"] += "直接返回当前一个镜头对象；程序绑定镜号并收集结果，不输出镜头数组或其他镜头。"
    elif data.get("本镜任务"):
        data["输出要求"] += f"镜头数组恰好 {data['本镜任务']['输出新镜头数']} 镜头。"
    if "内容单元" in bound:
        data["输出要求"] += "输出镜头不包含内容单元字段。"
    if data.get("本镜时长预算"):
        data["输出要求"] += "建议秒数由程序管理；按本镜已定任务与预算目标创作画面、必要行动和时长依据。每镜独立生成，全部返回后程序统一计算时间轴；不修改其他镜头任务或全片总长。"
    elif data.get("本镜时长定稿"):
        data["输出要求"] += "建议秒数由程序绑定，沿用已定时长。"
    return data


def 继承声音身份(voice, known):
    if not isinstance(voice, dict):
        return voice
    result = copy.deepcopy(voice)
    roles = 声音角色(voice)
    if len(roles) == 1:
        identity = known.get(roles[0][1], {})
        if identity:
            result["说话人"] = roles[0][1]
            for key in (*声音身份字段, "语速"):
                if key == "语速" and isinstance(result.get(key), str) and result[key].strip():
                    continue
                if isinstance(identity.get(key), str) and identity[key].strip():
                    result[key] = identity[key]
    elif roles:
        supplied = _声音身份(voice)
        for key in (*声音身份字段, "语速"):
            if key == "语速" and isinstance(result.get(key), str) and result[key].strip():
                continue
            values = [known.get(speaker, {}).get(key) or supplied.get(speaker, {}).get(key) for _, speaker in roles]
            if all(isinstance(value, str) and value.strip() for value in values):
                result[key] = values[0] if key != "声线" and len(set(values)) == 1 else "；".join(
                    f"{name}：{value}" for (name, _), value in zip(roles, values))
    return result


def 合并镜头创作(data, payload):
    if payload.get("单镜创作") and isinstance(data, dict) and "镜头" not in data:
        data = {"镜头": [data]}
    if not isinstance(data, dict) or not isinstance(data.get("镜头"), list):
        return data
    result = {"镜头": copy.deepcopy(data["镜头"])} if payload.get("镜头创作约定") else copy.deepcopy(data)
    fields, bound = 创作字段(payload), 绑定字段(payload)
    for index, shot in enumerate(result["镜头"]):
        if not isinstance(shot, dict):
            continue
        clean = {key: copy.deepcopy(shot[key]) for key in fields if key in shot}
        clean.update(copy.deepcopy(bound))
        if "声音设计" in clean and "声音设计" not in bound:
            if payload.get("本镜声音身份") and isinstance(clean["声音设计"], dict):
                clean["声音设计"].update(copy.deepcopy(payload["本镜声音身份"]))
            clean["声音设计"] = 继承声音身份(clean["声音设计"], payload.get("已定声音身份", {}))
        if payload.get("本镜文案定稿") and isinstance(clean.get("时长依据"), dict):
            clean["时长依据"]["发声秒"] = payload["本镜文案定稿"]["发声秒"]
            if not (clean.get("对白", "") + clean.get("旁白", "")).strip():
                clean["时长依据"]["动作与台词"] = "同时"
        if payload.get("本镜声景方案") and isinstance(clean.get("声景设计"), dict):
            clean["声景设计"].update(copy.deepcopy(payload["本镜声景方案"]))
        result["镜头"][index] = clean
    return result
