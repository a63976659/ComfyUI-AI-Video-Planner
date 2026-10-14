"""规划阶段共用协议；版本、结构约束与恢复标识不依赖视频模型。"""
import copy
import hashlib
import json
from .规划定稿 import 定稿版本
from .文本话语 import 内容话语候选, 台词项上限

协议版本 = 15
来源要求 = ("内容来源归属由程序绑定时，内容单元不输出来源字段，程序按固定编号恢复真实原文；不要另造范围、坐标或出处。"
          "需要模型选择来源时，来源只填写本次来源引用表中的非空编号字符串数组，至少1项，"
          "不可省略、填空数组或单个字符串；数组元素直接是编号，不再包数组。"
          "不返回范围/引文对象或空对象。程序恢复范围与逐字原文；不改写引文、不自造编号。"
          "完整保留本单元的全部出处，不限制来源项数，不因来源数量拆分剧情或删除引用。自己的字段错误不是用户需求冲突。")


class 规划预算耗尽(ValueError):
    """预算在发起请求前检查；不得因耗尽继续整集返修。"""


def 指纹(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def 来源字段模式(table, fallback):
    item = {"type": "string", "enum": list(table)} if isinstance(table, dict) and table else fallback
    return {"type": "array", "items": item, "minItems": 1,
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


def 模型请求资料(value):
    if isinstance(value, list):
        return [模型请求资料(item) for item in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    omit = {"格式版本", "规划协议版本", "规划定稿版本", "分镜契约版本", "来源协议版本", "修订版本", "规划规则指纹"}
    return {key: 模型请求资料(item) for key, item in value.items() if key not in omit}


def 请求契约(stage, payload):
    data = _模型资料(payload)
    data.update(规划协议版本=协议版本, 规划定稿版本=定稿版本, 规划阶段=stage)
    if isinstance(data.get("来源引用表"), dict) and data["来源引用表"]:
        example_id = next(iter(data["来源引用表"]))
        data["字段格式约束"] = {**data.get("字段格式约束", {}),
                            "来源格式示例": [example_id], "来源": 来源要求,
                            "内容单元结构示例": {"内容": "仅为字段形状示例，实际事件从当前完整原文提取",
                                "来源": [example_id], "必留台词": [],
                                "时长预算说明": "说明不同任务的内容分工、动作先后与节奏理由，不另算字数、发声秒或全片合计"},
                            "必留台词": "直接填写原文中的实际话语字符串数组，无话语用[]；不包数组、不填数字、不把制作要求写成台词",
                            "建议镜头数": "已提供逐镜任务时由程序按数组长度计算，无须输出；未提供任务数组时填写正整数，合计遵守本次镜头上限"}
        shape = data["字段格式约束"]
        if data.get("内容阶段职责") == "原文分析":
            shape["内容单元结构示例"]["建议镜头数"] = 1
            shape["建议镜头数"] = "原文事件的执行段需求估计，不在章节理解阶段创作分镜任务。"
        elif data.get("分镜生成方式") == "按场次":
            shape["内容单元结构示例"].update(建议镜头数=1, 涉及实体=[], 衔接方式="连续")
            shape["建议镜头数"] = "场次节奏参考，实际段数由第四步按完整文案、动作和执行范围确定。"
            shape["场次职责"] = "规划完整场次事件、来源、用户原话和共享设定；不输出逐镜台词、语速、精确发声秒或镜头任务。"
        else:
            shape.pop("建议镜头数", None)
            shape["内容单元结构示例"]["镜头任务"] = [{"任务": "本镜推进的具体事件或信息", "建议秒数": 8,
                "对白": "", "旁白": "", "发声秒": None, "中文每秒字数": None,
                "涉及实体": [], "发声角色": [], "衔接方式": "连续", "起始要求": "首镜动作发生前的实际状态", "结束要求": "本镜行动与话语完成后的实际状态",
                "原镜号": [], "保留要求": "", "锁定秒数": None}]
            shape["镜头任务"] = "每项包含任务、完整对白、完整旁白、中文每秒字数、发声秒、建议秒数、涉及实体、发声角色、起始要求、结束要求、原镜号、保留要求、锁定秒数。原文话语逐字写入对应任务的对白或旁白，跨镜时按自然语句分配；编号与片段归属由程序从实际文案绑定，不输出原文话语编号。全部发声文案在本阶段定稿，发声角色对应项目声音方案；无人声的对白旁白填空字符串。中文新配音按Skills和本镜表演确定具体的中文每秒字数，发声秒由程序计算并填null；无人声、非中文、混合语言或原音的中文每秒字数填null，实际发声时填写有依据的发声秒估算。锁定秒数仅沿用用户已确定时长或实际音轨时间依据，否则填null。每项是一个执行段，后续只创作画面与表演，不再改写文案或另选语速。"
            shape["镜头任务"] += ("本次局部纯制作约束可填[]，汇总须融入实际任务。" if data.get("内容阶段职责") == "局部内容规划" else
                                "每个单元至少一个实际任务，主题和制作说明放入项目设计，不单列说明单元或零秒任务。")
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
                "不把作品题目、制作要求或讲解要点当台词；朗诵、讲解和对白的创作补全按当前阶段写进内容或镜头对白/旁白，不能冒充锁定原文。")
        if candidates:
            rule = (f"每个内容单元最多{台词项上限}项，只能从原文话语候选中逐字选取。跨镜原话先按自然语句拆成连续原文片段，再分别分配；片段合起来完整保留原话，不改字、不重复、不遗漏。" + rule)
        else:
            rule = ("本次没有已提供的具体话语候选，所有内容单元的必留台词固定填写[]，最多0项。"
                    "不能因需要朗诵作品或创作对白而添加锁定项；空数组不表示禁止朗诵、旁白或对白。" + rule)
        data["本次必留台词约束"] = {"原文话语候选": candidates,
                                "最多项": 台词项上限 if candidates else 0, "规则": rule}
        if not candidates:
            data["本次必留台词约束"]["字段固定值"] = []
        elif data.get("内容阶段职责") != "原文分析":
            data["本次必留台词约束"]["跨镜分配"] = (
                "完整原话按自然语句写入各镜实际对白或旁白。跨镜片段按任务顺序拼接后逐字等于原话；程序恢复片段与原话的对应关系，不要求模型再输出编号。")
        data["字段格式约束"] = {**data.get("字段格式约束", {}), "必留台词": rule}
        data["输出要求"] = data.get("输出要求", "") + "\n本次必留台词字段必须遵守本次必留台词约束：" + rule
    # 轮次、纠错文本不改变同一阶段的收费预算身份；实际原文或镜头变化仍改变身份。
    identity = {k: v for k, v in data.items() if k not in (
        "阶段任务标识", "验收轮次", "修订依据", "修复要求", "待修订输出", "修复范围",
        "镜头修订要求", "内容修订要求")}
    data["阶段任务标识"] = 指纹(identity)
    return data


def 绑定内容来源(data, payload):
    if not isinstance(data, dict):
        raise ValueError("模型输出须为当前任务约定的JSON对象，不能返回数组或空列表")
    if isinstance(data.get("内容单元"), list):
        data["内容单元"] = [unit for unit in data["内容单元"] if not isinstance(unit, dict) or any(
            value is not None and value != "" and value != [] and value != {} for value in unit.values())]
    table = payload.get("来源引用表")
    if (isinstance(table, dict) and len(table) == 1
            and payload.get("内容来源归属") == {"由程序绑定": True, "固定值": list(table)}
            and isinstance(data.get("内容单元"), list)):
        for unit in data["内容单元"]:
            if isinstance(unit, dict):
                unit["来源"] = list(table)
    return data


