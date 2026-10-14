"""镜头预算分配与已有逐镜内容继承。"""
import copy
import math
import re

from .镜头设计 import 校验镜头设计, 最低表演秒数, 估时字段


def 校验逐镜任务(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 720:
        raise ValueError("逐镜任务须为包含1到720项的对象数组")
    out = []
    for index, row in enumerate(value, 1):
        if not isinstance(row, dict):
            raise ValueError(f"逐镜任务第{index}项须为对象")
        for field in ("任务", "对白", "旁白"):
            if not isinstance(row.get(field), str) or (field == "任务" and not row[field].strip()):
                raise ValueError(f"逐镜任务第{index}项的{field}须为文本，任务不能为空；各镜头对象在数组中并列，不以整段JSON字符串作为字段名")
        timing = row.get("时长依据")
        if not isinstance(timing, dict) or any(field not in timing for field in 估时字段):
            raise ValueError("逐镜任务须提供完整时长依据，不能只声明建议秒数")
        shot = {"对白": row["对白"], "旁白": row["旁白"], "时长依据": timing}
        design = 校验镜头设计(shot)
        clean = {"任务": row["任务"], "对白": row["对白"], "旁白": row["旁白"],
                 "时长依据": design["时长依据"]}
        if 最低表演秒数(clean) <= 0:
            raise ValueError("逐镜任务须有实际发声或必要行动，不能用空段占据固定时长")
        out.append(clean)
    return out


def 编排定稿任务(units, brief, compiler):
    provided = ["逐镜任务" in unit for unit in units]
    if not any(provided):
        return None
    if not all(provided):
        raise ValueError("内容计划的每个单元都须提供逐镜任务，不能混用定稿任务与未分配的提纲")
    tasks = [copy.deepcopy(task) for unit in units for task in unit["逐镜任务"]]
    shots = [{"画面": task["任务"], "建议秒数": 最低表演秒数(task),
              "对白": task["对白"], "旁白": task["旁白"], "时长依据": task["时长依据"]}
             for task in tasks]
    timing_brief = {**brief, "默认任务": "t2v", "素材": [], "按内容计时": True}
    try:
        segments = compiler(shots, timing_brief)
    except ValueError as error:
        raise ValueError(f"内容阶段逐镜任务未兑现全片时长预算：{error}") from error
    for task, segment in zip(tasks, segments):
        task["建议秒数"] = round(segment["end"] - segment["start"], 6)
    return tasks


def 分配镜头预算(units, brief, minimum, maximum, voices=None):
    if all(unit.get("镜头任务") for unit in units):
        tasks = [task for unit in units for task in unit["镜头任务"]]
        if len(tasks) > min(720, brief.get("段数上限") or 720):
            raise ValueError("内容镜头任务数量超过段数上限")
        for unit in units:
            unit["建议镜头数"] = len(unit["镜头任务"])
        speech = [任务发声秒(task, voices) for task in tasks]
        lower = [max(minimum, seconds) for seconds in speech]
        upper = [task.get("锁定秒数", maximum) for task in tasks]
        for index, task in enumerate(tasks):
            if task.get("锁定秒数") is not None:
                if not minimum <= task["锁定秒数"] <= maximum:
                    raise ValueError(f"第{index + 1}镜锁定时长{task['锁定秒数']:g}秒，超出本次执行范围{minimum:g}至{maximum:g}秒")
                if task["锁定秒数"] < lower[index] - 1e-5:
                    raise ValueError(f"第{index + 1}镜的已定文案不能在锁定时长内发声：文案需{speech[index]:g}秒，锁定{task['锁定秒数']:g}秒，执行范围{minimum:g}至{maximum:g}秒")
                lower[index] = task["锁定秒数"]
        for index, (lo, hi) in enumerate(zip(lower, upper)):
            if not minimum <= lo <= hi <= maximum:
                raise ValueError(f"第{index + 1}镜的已定文案发声需要{speech[index]:g}秒，超出本次执行范围{minimum:g}至{maximum:g}秒；请在内容阶段按自然语句拆镜并完整保留文案")
        if not brief.get("总时长"):
            return None
        if sum(lower) > brief["总时长"] + 1e-5:
            raise ValueError(f"已定文案与锁定镜头至少需{sum(lower):g}秒，无法容纳固定总时长{brief['总时长']:g}秒；不能加速发声或删减话语")
        return 分配时长(brief["总时长"], [task["建议秒数"] for task in tasks], lower, upper)
    counts = [unit.get("建议镜头数", 1) for unit in units]
    total = brief.get("总时长", 0)
    if not total:
        return None
    lower = max(len(units), math.ceil(total / maximum))
    upper = min(720, brief.get("段数上限") or 720, math.floor(total / minimum))
    if lower > upper:
        raise ValueError("当前内容单元及执行限制无法安排固定总时长，请调整内容分组或段数")
    number = min(upper, max(lower, sum(counts)))
    if number != sum(counts):
        shares = [(number - len(units)) * count / sum(counts) for count in counts]
        counts = [1 + math.floor(share) for share in shares]
        order = sorted(range(len(units)), key=lambda i: -(shares[i] - math.floor(shares[i])))
        for i in order[:number - sum(counts)]:
            counts[i] += 1
    for unit, count in zip(units, counts):
        unit["建议镜头数"] = count
    seconds = math.floor(total / number * 10 + 1e-8) / 10
    extras = min(number, math.floor((total - seconds * number) * 10 + 1e-8))
    budgets = [round(seconds + 0.1, 1)] * extras + [seconds] * (number - extras)
    budgets[-1] = round(total - sum(budgets[:-1]), 6)
    if all(minimum - 1e-5 <= value <= maximum + 1e-5 for value in budgets):
        return budgets
    seconds = round(total / number, 6)
    return [seconds] * (number - 1) + [round(total - seconds * (number - 1), 6)]


def 校验镜头任务(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 720:
        raise ValueError("镜头任务须为包含1到720项的对象数组")
    tasks = []
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("任务"), str) or not row["任务"].strip():
            raise ValueError("每项镜头任务须包含具体的任务文本")
        seconds = row.get("建议秒数")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("镜头任务的建议秒数须为有限正数")
        task = {"任务": row["任务"].strip(), "建议秒数": seconds}
        for key in ("对白", "旁白"):
            if key in row:
                if not isinstance(row[key], str):
                    raise ValueError(f"镜头任务{key}须为完整发声文本，无发声填空字符串")
                task[key] = row[key]
        if row.get("中文每秒字数") is not None:
            rate = row["中文每秒字数"]
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 0 < rate <= 120:
                raise ValueError("镜头任务中文每秒字数须为0至120之间的有限正数")
            task["中文每秒字数"] = rate
        if "发声秒" in row and row["发声秒"] is not None:
            value = row["发声秒"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("镜头任务发声秒须为有限非负数")
            task["发声秒"] = value
        for key in ("涉及实体", "发声角色", "原镜号"):
            if key in row:
                values = row[key]
                if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                    raise ValueError(f"镜头任务{key}须为文本数组")
                task[key] = list(values)
        if "原文话语" in row:
            values = row["原文话语"]
            if not isinstance(values, list) or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
                raise ValueError("原文话语须为本单元必留台词的从1开始的编号数组")
            task["原文话语"] = list(values)
        for key in ("起始要求", "结束要求", "保留要求"):
            if key in row:
                if not isinstance(row[key], str):
                    raise ValueError(f"镜头任务{key}须为文本")
                task[key] = row[key]
        if "衔接方式" in row:
            if row["衔接方式"] not in ("连续", "时空跳转", "用户锁定"):
                raise ValueError("镜头任务衔接方式须为连续、时空跳转或用户锁定")
            task["衔接方式"] = row["衔接方式"]
            if not row.get("结束要求", "").strip():
                raise ValueError("镜头任务须提供行动完成后的结束要求，供下一连续镜头承接")
            if row["衔接方式"] != "连续" and not row.get("起始要求", "").strip():
                raise ValueError("时空跳转或用户锁定的镜头须提供具体起始要求")
        if row.get("锁定秒数") is not None:
            value = row["锁定秒数"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("锁定秒数须为有限正数")
            task["锁定秒数"] = value
        tasks.append(task)
    return tasks


def 任务发声秒(task, voices=None):
    from .镜头设计 import 中文发声, 已定中文语速
    from .规划定稿 import 声音角色
    text = task.get("对白", "") + task.get("旁白", "")
    if not text.strip():
        return 0
    roles = task.get("发声角色", [])
    identities = [voices.get(key, {}) for name in roles for _, key in 声音角色({"说话人": name})] if voices else []
    shot = {"对白": task.get("对白", ""), "旁白": task.get("旁白", "")}
    if any(re.search(r"原声|原音|音轨", voice.get("声源", "")) for voice in identities):
        if not task.get("发声秒"):
            raise ValueError("保留原音的文案须提供有依据的发声秒数")
        return task["发声秒"]
    if 中文发声(shot):
        if task.get("中文每秒字数") is not None:
            return sum(char.isalnum() for char in text) / task["中文每秒字数"]
        rates = [已定中文语速({"声音设计": voice}) for voice in identities] or [已定中文语速(shot)]
        return sum(char.isalnum() for char in text) / min(rates)
    if not task.get("发声秒"):
        raise ValueError("非中文或混合语言的已定文案须在内容规划中提供发声秒估算")
    return task["发声秒"]


def 汇总镜头预算(shots, budgets, minimum, maximum, tasks):
    lower = [max(minimum, 最低表演秒数(shot)) for shot in shots]
    upper = [maximum] * len(shots)
    for index, task in enumerate(tasks):
        fixed = task.get("任务", task).get("锁定秒数")
        if task.get("定稿"):
            fixed = task["定稿"]["建议秒数"]
        if fixed is not None:
            if not lower[index] - 1e-5 <= fixed <= maximum + 1e-5:
                raise ValueError(f"第{index + 1}镜的必要内容不能在锁定时长内执行")
            lower[index] = upper[index] = fixed
    if any(lo > hi + 1e-5 for lo, hi in zip(lower, upper)):
        raise ValueError("镜头必要内容超过执行时长上限")
    if budgets is None:
        return [min(hi, max(lo, shot.get("建议秒数", lo))) for shot, lo, hi in zip(shots, lower, upper)]
    return 分配时长(round(sum(budgets), 6), budgets, lower, upper)


def 分配时长(total, weights, minimums, maximums):
    minimums = [round(value, 6) for value in minimums]
    maximums = [round(value, 6) for value in maximums]
    if total < sum(minimums) - 1e-5 or total > sum(maximums) + 1e-5:
        raise ValueError("当前任务数量与执行范围无法容纳固定总时长，请按本次镜头数量范围安排任务")
    if round(sum(weights), 6) == round(total, 6) and all(lo <= value <= hi for value, lo, hi in zip(weights, minimums, maximums)):
        result = [round(value, 6) for value in weights]
        result[-1] = round(total - sum(result[:-1]), 6)
        return result
    low, high = 0.0, max(hi / weight for weight, hi in zip(weights, maximums))
    for _ in range(60):
        scale = (low + high) / 2
        if sum(min(hi, max(lo, weight * scale)) for weight, lo, hi in zip(weights, minimums, maximums)) < total:
            low = scale
        else:
            high = scale
    values = [min(hi, max(lo, weight * high)) for weight, lo, hi in zip(weights, minimums, maximums)]
    step = 0.1
    lower = [math.ceil(value / step - 1e-8) for value in minimums]
    upper = [math.floor(value / step + 1e-8) for value in maximums]
    if any(lo > hi for lo, hi in zip(lower, upper)) or not sum(lower) <= total / step <= sum(upper):
        step = 0.000001
        lower = [math.ceil(value / step - 1e-8) for value in minimums]
        upper = [math.floor(value / step + 1e-8) for value in maximums]
    target_ticks = math.floor(total / step + 1e-8)
    if not sum(lower) <= target_ticks <= sum(upper):
        raise ValueError("固定总时长无法在当前执行时长精度内分配")
    ticks = [min(hi, max(lo, math.floor(value / step + 1e-8))) for value, lo, hi in zip(values, lower, upper)]
    remaining = target_ticks - sum(ticks)
    order = sorted(range(len(ticks)), key=lambda i: values[i] / step - ticks[i], reverse=True)
    while remaining:
        direction = 1 if remaining > 0 else -1
        for i in order if direction > 0 else reversed(order):
            if lower[i] <= ticks[i] + direction <= upper[i]:
                ticks[i] += direction
                remaining -= direction
                if not remaining:
                    break
    result = [round(value * step, 6) for value in ticks]
    tail = round(total - sum(result), 6)
    if tail:
        for i in reversed(order):
            if minimums[i] - 1e-5 <= result[i] + tail <= maximums[i] + 1e-5:
                result[i] = round(result[i] + tail, 6)
                break
    return result


def 分配分集预算(weights, brief, minimum, maximum):
    total, cap = brief.get("总时长", 0), brief.get("段数上限", 0)
    count = len(weights)
    if cap and cap < count:
        raise ValueError("全剧段数不足以容纳分集")
    if total and total < minimum * count - 1e-5:
        raise ValueError("固定全剧总时长不足以容纳每集最低执行时长")
    if total:
        number = max(count, math.ceil(total / maximum), min(sum(weights), math.floor(total / minimum)))
        if cap:
            number = min(number, cap)
        if number * maximum < total - 1e-5:
            raise ValueError("固定总时长超过段数上限的执行容量")
    else:
        number = cap or sum(weights)
    shares = [(number - count) * weight / sum(weights) for weight in weights]
    counts = [1 + math.floor(value) for value in shares]
    order = sorted(range(count), key=lambda i: shares[i] - math.floor(shares[i]), reverse=True)
    for i in order[:number - sum(counts)]:
        counts[i] += 1
    durations = 分配时长(total, weights, [n * minimum for n in counts], [n * maximum for n in counts]) if total else [0] * count
    return durations, counts if cap else [0] * count
