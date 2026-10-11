"""规划阶段共用协议；版本、结构约束与恢复标识不依赖视频模型。"""
import copy
import hashlib
import json
from .规划定稿 import 定稿版本
from .文本话语 import 内容话语候选, 台词项上限

协议版本 = 10
来源项上限 = 24
验收问题上限 = 20
缺陷类型 = ("原文遗漏或擅改", "当前状态互斥", "素材缺失或错绑", "明确时长不足")
来源要求 = ("内容来源归属由程序绑定时，内容单元不输出来源字段，程序按固定编号恢复真实原文；不要另造范围、坐标或出处。"
          f"需要模型选择来源时，来源只填写本次来源引用表中的1到{来源项上限}项非空编号字符串数组，"
          "不可省略、填空数组或单个字符串；数组元素直接是编号，不再包数组。"
          "不返回范围/引文对象或空对象。程序恢复范围与逐字原文；不改写引文、不自造编号。"
          "超量须拆分单元保留全部出处，不删引用。自己的字段错误不是用户需求冲突。")


class 规划预算耗尽(ValueError):
    """预算在发起请求前检查；不得因耗尽继续整集返修。"""


def 指纹(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def 来源字段模式(table, fallback):
    item = {"type": "string", "enum": list(table)} if isinstance(table, dict) and table else fallback
    return {"type": "array", "items": item, "minItems": 1, "maxItems": 来源项上限,
            "description": 来源要求 if isinstance(table, dict) and table else "真实范围与逐字原文引文，禁止伪造出处。"}


def _模型资料(value):
    if isinstance(value, list):
        return [_模型资料(item) for item in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    omit = set()
    if str(value.get("稳定标识", "")).startswith("事件-"):
        omit.update(("来源位置", "原文单元"))
    if isinstance(value.get("内容单元"), list):
        omit.add("原文覆盖")
    return {key: _模型资料(item) for key, item in value.items() if key not in omit}


def 请求契约(stage, payload):
    data = _模型资料(payload)
    data.update(规划协议版本=协议版本, 规划定稿版本=定稿版本, 规划阶段=stage)
    if isinstance(data.get("来源引用表"), dict) and data["来源引用表"]:
        example_id = next(iter(data["来源引用表"]))
        data["字段格式约束"] = {**data.get("字段格式约束", {}),
                            "来源格式示例": [example_id], "来源": 来源要求,
                            "内容单元结构示例": {"内容": "仅为字段形状示例，实际事件从当前完整原文提取",
                                "来源": [example_id], "必留台词": [], "建议镜头数": 1,
                                "时长预算说明": "按实际发声字数、动作先后与独立停顿填写容量和所需镜头，不照抄示例数值"},
                            "必留台词": "直接填写原文中的实际话语字符串数组，无话语用[]；不包数组、不填数字、不把制作要求写成台词",
                            "建议镜头数": "每单元必填正整数；先依据完整表演容量确定，不省略、不填待定，合计遵守本次镜头上限"}
        if stage in ("理解内容", "章节理解", "汇总内容") and len(data["来源引用表"]) == 1:
            data["内容来源归属"] = {"由程序绑定": True, "固定值": [example_id]}
            shape = data["字段格式约束"]
            shape["内容单元结构示例"].pop("来源")
            shape.pop("来源格式示例", None)
            shape.pop("来源范围仅允许", None)
            shape["来源"] = shape["来源输出类型"] = "唯一来源由程序绑定，输出的内容单元不包含来源字段，不填写范围、位置坐标或引用编号。"
            output = data.get("输出要求", "")
            for field in ("来源:[来源引用表中的引用ID字符串],", "来源:[来源引用表中的编号字符串],"):
                output = output.replace(field, "")
            data["输出要求"] = output + "\n本次只有一条合法来源，无须选择；内容单元不返回来源字段，程序按内容来源归属的固定值恢复出处。来源仅证明用户提供的原文，不证明创作补全的事实。"
    if stage in ("理解内容", "章节理解", "汇总内容"):
        candidates = 内容话语候选(data)
        rule = ("原文话语候选只来自当前用户原文或已通过本地校验的分块必留台词，不能从本次创作补全的内容反向提取。"
                "不把作品题目、制作要求或讲解要点当台词；朗诵、讲解和对白的创作补全完整写进内容及逐镜任务，后续由镜头对白/旁白承载。")
        if candidates:
            rule = (f"每个内容单元最多{台词项上限}项，只能从原文话语候选中逐字选取，不得改写或自行增加候选。" + rule)
        else:
            rule = ("本次没有已提供的具体话语候选，所有内容单元的必留台词固定填写[]，最多0项。"
                    "不能因需要朗诵作品或创作对白而添加锁定项；空数组不表示禁止朗诵、旁白或对白。" + rule)
        data["本次必留台词约束"] = {"原文话语候选": candidates,
                                "最多项": 台词项上限 if candidates else 0, "规则": rule}
        if not candidates:
            data["本次必留台词约束"]["字段固定值"] = []
        data["字段格式约束"] = {**data.get("字段格式约束", {}), "必留台词": rule}
        data["输出要求"] = data.get("输出要求", "") + "\n本次必留台词字段必须遵守本次必留台词约束：" + rule
    # 轮次、纠错文本不改变同一阶段的收费预算身份；实际原文或镜头变化仍改变身份。
    identity = {k: v for k, v in data.items() if k not in (
        "阶段任务标识", "验收轮次", "修订依据", "修复要求", "待修订输出", "修复范围",
        "镜头修订要求", "内容修订要求")}
    data["阶段任务标识"] = 指纹(identity)
    return data


def 绑定内容来源(data, payload):
    table = payload.get("来源引用表")
    if (isinstance(table, dict) and len(table) == 1
            and payload.get("内容来源归属") == {"由程序绑定": True, "固定值": list(table)}
            and isinstance(data.get("内容单元"), list)):
        for unit in data["内容单元"]:
            if isinstance(unit, dict):
                unit["来源"] = list(table)
    return data


def 验收缓存输入(payload):
    """只忽略操作性修订信息，不忽略镜头、原文、参考图及真实规则。"""
    return {k: v for k, v in payload.items() if k not in (
        "验收轮次", "修订依据", "阶段任务标识")}


def 批次修订(revision, group, start, size):
    if not isinstance(revision, dict):
        return None
    issues = revision.get("建议", [])
    if not isinstance(issues, list):
        raise ValueError("镜头修订建议须为数组")
    ids = {u["id"] for u in group}
    events = {u.get("稳定标识") for u in group if u.get("稳定标识")}
    selected = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("镜头修订建议须为对象")
        units, numbers, linked = issue.get("关联单元"), issue.get("镜号"), issue.get("关联事件")
        for values, label in ((units, "关联单元"), (linked, "关联事件")):
            if values is not None and (not isinstance(values, list) or any(not isinstance(v, str) for v in values)):
                raise ValueError(f"修订{label}须为编号字符串数组")
        if numbers is not None and (not isinstance(numbers, list) or any(
                isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in numbers)):
            raise ValueError("修订镜号须为正整数数组")
        if linked:
            relevant = bool(events.intersection(linked))
        elif units:
            relevant = bool(ids.intersection(units))
        elif numbers:
            relevant = any(start <= n < start + size for n in numbers)
        else:
            relevant = True  # 无可靠定位的旧报告不能静默忽略。
        if relevant:
            selected.append(copy.deepcopy(issue))
    if not selected and issues:
        return None
    return {"建议": selected, "数量说明": "拆镜数量已落实到本批镜头数，按当前内容单元和输出要求执行，不沿用历史数量。"}
