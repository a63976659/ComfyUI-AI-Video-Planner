# -*- coding: utf-8 -*-
"""一次生成的短规划与长剧规划；规则在生成前落实，不请求AI验收或返修。"""
import copy
import asyncio
import json
import math
import re

from .内容规划 import (生成内容规划, 选定范围, 执行时长范围, 素材执行契约, _系统, _验内容, _验镜头, _检查冲突,
                    输入类型, 目标体裁, 改写方式, _关联正文, _正文覆盖)
from .内容规划 import _来源请求摘要, 来源输出格式错误, 规划协议误判, 中性规划输入, 规划需求, 部分分镜可用
from .规划默认规则 import 规划默认规则, 规划阶段规则
from .规划器 import 提取JSON
from .配置 import LLM错误
from .项目存储 import 写JSON, 读JSON
from .技能注册 import 注册技能, 装配技能, 合并技能资料
from .专项技能 import 装配专项
from .项目设计 import 校验项目设计, 设计契约
from .文本话语 import 候选台词, 原文引文候选, 原文来源引用表, 来源协议版本, 台词来源契约
from .规划契约 import 请求契约, 来源要求, 缺陷类型, 验收问题上限, 规划预算耗尽, 指纹, 绑定内容来源
from .规划定稿 import 校验确定交付, 记录声音身份


def _素材资料(brief):
    materials = [{k: m[k] for k in ("名", "类型", "名称", "描述") if isinstance(m.get(k), str)}
                 for m in brief.get("素材", [])]
    observations = {name: {k: value for k, value in item.items() if k in ("描述", "取样说明", "主体", "动作", "场景", "风格", "限制")}
                    for name, item in brief.get("素材理解", {}).items()}
    return {"materials": materials, "materialUnderstanding": observations,
            "materialNote": ("本任务没有选入素材，只按用户提供的需求或正文规划，不宣称已上传或观察媒体。" if not materials else
                            "本任务的规划请求附选入媒体原件及文档完整逐字正文；原件输入记录标注实际方式，"
                            "不等同于完整内容已理解或语义验收通过，不能仅按文件名猜测素材"
                             if brief.get("仅发送选入素材") else
                            "仅展示已提供的素材记录及已有观察；无理解记录的素材尚未观察，不代表完整音视频分析")}


def _章节来源示例(scope):
    quotes = 原文引文候选(scope.get("正文"))
    if not quotes:
        raise ValueError(f"原文范围{scope.get('id', '')}为空，无法提供真实来源引文，不能发起章节理解")
    return [{"范围": scope["id"], "引文": quotes[0]}]


def _验章节(data, scope, scopes, 来源示例=None, 来源引用表=None):
    """来源只核对结构与真实出处；局部读取边界由前置规则说明。"""
    return _验内容(data, [scope], 20, 108, 来源引用表=来源引用表)


def 验报告(data, 依据=None):
    """兼容历史报告与独立诊断工具；自动规划流程不调用，也不发送验收请求。"""
    _检查冲突(data)
    passed, issues = data.get("通过"), data.get("问题")
    if not isinstance(passed, bool) or not isinstance(issues, list) or len(issues) > 验收问题上限:
        raise ValueError("验收须返回通过布尔值及不超过20项的问题数组")
    clean = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("验收问题须定位到内容或镜头")
        scope = issue.get("范围")
        location = re.fullmatch(r"镜头\s*(\d+)", scope) if isinstance(scope, str) else None
        if location:
            scope = "镜头"
        if scope not in ("内容", "镜头"):
            raise ValueError("验收问题须定位到内容或镜头")
        for key in ("说明", "建议"):
            if not isinstance(issue.get(key), str) or not issue[key].strip():
                raise ValueError(f"验收问题的{key}须为1到1500字非空文本，不能省略、填对象或超长")
        item = {key: issue[key] for key in ("范围", "说明", "建议")}
        item["范围"] = scope
        numbers = issue.get("镜号", [])
        if not isinstance(numbers, list) or len(numbers) > 20 or any(isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 720 for n in numbers):
            raise ValueError("验收问题镜号须为1到720的整数数组")
        if location:
            number = int(location.group(1))
            if not 1 <= number <= 720 or (numbers and number not in numbers):
                raise ValueError("验收镜头范围与镜号不一致")
            numbers = list(dict.fromkeys([*numbers, number]))
        if isinstance(依据, dict) and isinstance(依据.get("镜头起号"), int) and isinstance(依据.get("镜头"), list):
            start = 依据["镜头起号"]
            end = start + len(依据["镜头"]) - 1
            if scope == "镜头" and (any(not start <= n <= end for n in numbers) or ("证据" in issue and not numbers)):
                raise ValueError(f"本批仅验收镜号{start}到{end}；问题须定位本批真实镜头，不能引用其它批次或历史修订镜号。已修复的旧问题不应重复上报")
        if numbers:
            item["镜号"] = list(dict.fromkeys(numbers))
        if "证据" in issue:
            evidence = issue["证据"]
            if not isinstance(evidence, list) or not 2 <= len(evidence) <= 4:
                raise ValueError("验收问题须有2到4条直接引文证明实际缺陷，不能以生成风险或优化偏好代替证据")
            def strings(value):
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for v in value.values():
                        yield from strings(v)
                elif isinstance(value, list):
                    for v in value:
                        yield from strings(v)
            keys = ("需求", "原文资料", "镜头", "前批结尾", "内容计划", "全剧资料", "分集结果",
                    "程序时长核验", "程序素材核验", "素材执行契约", "规划规则")
            actual = list(strings({k: 依据[k] for k in keys if k in 依据})) if isinstance(依据, dict) else []
            clean_evidence = []
            for index, quote in enumerate(evidence):
                # 兼容模型给引文加 text/title 标签及JSON字符串转义；不补字、不拼接或删除省略号。
                wrapped = re.fullmatch(r'(?:text|title|引文)\s*:\s*(".*")', quote, re.S) if isinstance(quote, str) else None
                if wrapped:
                    try:
                        quote = json.loads(wrapped[1])
                    except ValueError:
                        pass
                if (not isinstance(quote, str) or not re.search(r"[\w\u4e00-\u9fff]", quote)
                        or (依据 is not None and not any(quote in text for text in actual))):
                    raise ValueError(f"第{index + 1}条验收证据须逐字引用本次原文或字段：{str(quote)[:100]}；"
                                     "直接填写连续原句，不带text/title标签，不用省略号、改写或拼接；无确定缺陷时应通过")
                clean_evidence.append(quote)
            item["证据"] = clean_evidence
            if scope == "镜头" and isinstance(依据, dict):
                shots = 依据.get("镜头")
                if isinstance(shots, list):
                    start = 依据.get("镜头起号", 1)
                    current = [shot for index, shot in enumerate(shots, start) if not numbers or index in numbers]
                else:
                    current = [s for s in 依据.get("程序素材核验", {}).get("镜头", [])
                               if not numbers or s.get("镜号") in numbers]
                fields = list(strings(current))
                if not any(quote in field for quote in clean_evidence for field in fields):
                    raise ValueError("镜头问题的证据须至少引用一条所定位当前镜头的真实字段；仅引用用户要求或模型契约不能证明镜头存在缺陷。不能依据摘要推测已验收镜头的素材缺失或生成风险")
        if "缺陷类型" in issue:
            if issue["缺陷类型"] not in 缺陷类型:
                raise ValueError("验收只能拦截确定的保真、状态、素材或时长缺陷，不能拦截审美优化建议")
            item["缺陷类型"] = issue["缺陷类型"]
        clean.append(item)
    if passed == bool(clean):
        raise ValueError("验收通过与问题列表矛盾；不通过时必须给出可执行建议")
    action = data.get("处理", "优化")
    if action not in ("优化", "重新规划"):
        raise ValueError("验收处理须为优化或重新规划")
    if action == "重新规划" and clean and all(item["范围"] == "镜头" for item in clean):
        action = "优化"  # 仅分镜缺陷保留已通过的内容计划，不能因此重读并改写全文。
    return {"通过": passed, "问题": clean, "处理": action}


class 自动流程:
    def __init__(self, project, model, progress):
        self.project, self.model, self.progress = project, model, progress
        self.集号, self.集数 = 0, 1
        self.当前进度 = {}
        self.参考图结果 = None
        self.参考图 = None
        self.全剧轮次 = 0

    def 进度(self, data):
        self.当前进度 = dict(data)
        if data.get("阶段") in ("编排镜头", "校验分镜", "分集规划"):
            stage = next(s for s in self.project.阶段快照() if s["id"] == "storyboards")
            if stage["status"] == "pending":
                self.project.写阶段("storyboards", total=self.集数)
        self.progress({**data, **({"生成参考图资料": self.参考图结果} if self.参考图结果 else {}),
                       "stages": self.project.阶段快照(),
                       "调用次数": self.project.记录.get("累计调用", 0),
                       "调用上限": self.project.记录.get("调用上限", 600), "集号": self.集号, "集数": self.集数})

    def 短内容成果(self, prepared, content):
        scopes = [{k: v for k, v in s.items() if k != "正文"} for s in prepared["范围"]]
        classification = {k: prepared[k] for k in ("输入类型", "目标体裁", "改写方式")}
        self.project.写阶段("analysis", {"scopes": scopes, "contents": [content], "classification": classification,
                          **_素材资料(prepared["brief"])},
                          status="completed", completed=len(scopes), total=len(scopes))
        name = prepared["brief"].get("主题") or scopes[0].get("标题") or "单集规划"
        self.project.写阶段("episodes", {"mode": "single", "mainline": "\n".join(u["内容"] for u in content["内容单元"]),
                          "entities": content["人物场景"], "episodes": [{"集号": 1, "名称": name,
                          "范围": [s["id"] for s in scopes], "衔接": "短内容采用单集规划，未执行全剧分集"}]},
                          status="completed", completed=1, total=1, reason="短内容采用单集规划")
        self.进度({"阶段": "内容分析完成"})

    def 分集成果(self, result, name):
        path = self.project.路径("阶段成果", "storyboards.json")
        data = 读JSON(path) if path.exists() else {"episodes": []}
        number = self.集号 or 1
        entry = {"集号": number, "名称": name, "镜头数": len(result["segments"]),
                 "时长": result["segments"][-1]["end"], "revision": self.全剧轮次,
                 "生成完成": bool(result["规划资料"].get("生成完成"))}
        data["episodes"] = sorted([e for e in data["episodes"] if e["集号"] != number] + [entry], key=lambda e: e["集号"])
        data["revision"] = self.全剧轮次
        count = sum(e.get("revision", 0) == self.全剧轮次 for e in data["episodes"])
        self.project.写阶段("storyboards", data, status="partial", completed=count, total=self.集数,
                          revision=self.全剧轮次, reason="已保存分镜成果，等待全部分集生成完成")
        self.进度({"阶段": "分集生成完成" if entry["生成完成"] else "分集分镜已保存", "已完成": count, "总数": self.集数})

    async def 模型(self, system, user):
        try:
            data = json.loads(user) if isinstance(user, str) else {}
        except ValueError:
            data = {}
        identity = data.get("阶段任务标识") if isinstance(data, dict) else None
        stage = data.get("规划阶段", "") if isinstance(data, dict) else ""
        def count():
            return self.project.计次(stage, identity) if identity else self.project.计次()
        count()
        self.进度(self.当前进度)
        # 网络重试也计费计次，禁止供应商错误造成无限重试。
        for attempt in range(2):
            try:
                return await self.model(system, user)
            except LLM错误 as e:
                if not e.可重试 or attempt:
                    raise
                count()
                self.进度({"阶段": "自动重试连接", "重试": True})
                await asyncio.sleep(0.5)

    async def 请求(self, stage, payload, validator):
        payload = 请求契约(stage, 中性规划输入(payload))
        cached = await self.project.读取(stage, payload)
        if cached is not None:
            try:
                result = validator(cached)
            except (ValueError, KeyError, TypeError):
                pass
            else:
                self.进度({"阶段": stage, "复用检查点": True, "已完成": 1, "总数": 1})
                return result
        self.进度({"阶段": stage, "已完成": 0, "总数": 1})
        system = _系统 + 规划阶段规则(stage)
        if stage in ("章节理解", "汇总内容"):
            system += 台词来源契约
        if payload.get("来源引用表"):
            system += 来源要求
        raw = await self.模型(system, json.dumps(payload, ensure_ascii=False))
        try:
            result = validator(绑定内容来源(提取JSON(raw), payload))
        except ValueError as error:
            self.project.保存失败输出(stage, raw, str(error), 请求摘要=_来源请求摘要(payload))
            raise
        await self.project.保存(stage, payload, result)
        self.进度({"阶段": stage, "已完成": 1, "总数": 1})
        return result


def _验全剧(data, scopes, 最大集数=None):
    _检查冲突(data)
    line = data.get("主线")
    entities = data.get("人物场景", [])
    episodes = data.get("分集")
    if not isinstance(line, str) or not line.strip():
        raise ValueError("全剧主线须为非空文本")
    if not isinstance(entities, list) or len(entities) > 40:
        raise ValueError("全剧人物场景资料超过预算")
    if not isinstance(episodes, list) or not 1 <= len(episodes) <= 120:
        raise ValueError("分集数量须为1..120")
    ordered_ids = [s["id"] for s in scopes]
    minimum, maximum = math.ceil(len(scopes) / 4), min(len(scopes), 120)
    if 最大集数 is not None and 最大集数 < maximum:
        maximum = min(maximum, 最大集数)
        if len(episodes) > maximum:
            raise ValueError(f"固定全剧总时长与段数预算最多容纳{maximum}集，须合并连续范围，不允许自动延长")
    if not minimum <= len(episodes) <= maximum:
        raise ValueError(f"本次只有{len(scopes)}个真实原文范围，分集数量须为{minimum}..{maximum}；"
                         "每集须分配1..4个连续范围且全部范围恰好出现一次，不能新增空范围集或重复引用。"
                         "歌词段落和内容单元应在所属集内拆成多个镜头，不等于新增剧集。")
    covered, clean = [], []
    for i, episode in enumerate(episodes):
        if not isinstance(episode, dict):
            raise ValueError("分集须为对象")
        ids = episode.get("范围")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 4 or not all(isinstance(x, str) for x in ids):
            raise ValueError(f"第{i+1}集的范围须为含1..4个真实范围ID的字符串数组，例如{json.dumps(ordered_ids[:1], ensure_ascii=False)}；"
                            "不能填单个字符串、对象、文件名、内容单元编号或歌词段落名，不得按摘要漏掉原文")
        if any(sid not in ordered_ids for sid in ids):
            raise ValueError(f"第{i+1}集引用了不存在的范围；须逐字使用范围顺序中的真实ID，例如{json.dumps(ordered_ids[:1], ensure_ascii=False)}，"
                            "不能用内容单元编号或歌词段落名代替")
        name, transition = episode.get("名称", ""), episode.get("衔接", "")
        if any(not isinstance(x, str) for x in (name, transition)) or not name.strip():
            raise ValueError("分集须有名称及合法衔接说明")
        covered.extend(ids)
        clean.append({"集号": i + 1, "名称": name, "范围": ids, "衔接": transition})
    if covered != ordered_ids:
        raise ValueError("分集必须按原文顺序恰好覆盖全部范围，不得漏掉、重复或凭空增加")
    result = {"主线": line, "人物场景": entities, "分集": clean}
    if "项目设计" in data:
        result["项目设计"] = 校验项目设计(data["项目设计"])
    return result


def _验摘要(data, ids):
    _检查冲突(data)
    text = data.get("概要")
    if not isinstance(text, str) or not text.strip() or data.get("范围") != ids:
        raise ValueError("分层概要须为非空文本并完整保留有序范围标识")
    return {"概要": text, "范围": ids}


def _规则验收(result, scopes):
    segments = result.get("segments", [])
    if not segments or len(segments) > 720:
        raise ValueError("分集没有有效分镜或超过720段")
    cursor = 0
    for segment in segments:
        start, end = segment.get("start"), segment.get("end")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (start, end)):
            raise ValueError("分集时码必须为有限数值")
        if abs(start - cursor) > 1e-5 or end <= start or end > 3600:
            raise ValueError("分集时码须连续且在60分钟内")
        if not isinstance(segment.get("prompt"), str) or not segment["prompt"].strip():
            raise ValueError("镜头缺少具体画面")
        cursor = end
    if [s["id"] for s in result["规划资料"]["处理范围"]] != [s["id"] for s in scopes]:
        raise ValueError("结果处理范围与分集来源不一致")


async def _分集(flow, prepared, scopes, context, initial=None):
    project = flow.project
    def content_ready(actual_prepared, content):
        for key in ("输入类型", "目标体裁", "改写方式"):
            prepared[key] = actual_prepared[key]
        prepared["brief"] = 规划需求(prepared)
        if not context:
            flow.短内容成果(actual_prepared, content)
    _, count, _ = 选定范围(prepared, [s["id"] for s in scopes])
    try:
        result = await 生成内容规划(prepared, scopes, count, flow.模型, flow.进度,
                                检查点=project, 规划上下文=context, 预理解=initial,
                                内容成果=content_ready,
                                **({"参考图准备": flow.参考图.补充} if flow.参考图 else {}))
    except 部分分镜可用 as error:
        _规则验收(error.result, scopes)
        candidate = _标记待完善(error.result, error, stage="分镜生成", partial=True)
        candidate["规划资料"].update(集名=context.get("本集", {}).get("名称") or "单集规划", 集号=flow.集号 or 1)
        project.本轮可用分集[flow.集号 or 1] = candidate
        project.写分集(flow.集号 or 1, candidate)
        flow.分集成果(candidate, candidate["规划资料"]["集名"])
        raise
    if flow.参考图结果:
        result["生成参考图资料"] = copy.deepcopy(flow.参考图结果)
    _规则验收(result, scopes)
    result["规划资料"].update(生成完成=True, 本地校验={"通过": True, "方式": "本地数据校验，未执行AI验收"},
        输出状态="完成", 集号=flow.集号 or 1,
        集名=context.get("本集", {}).get("名称") or "单集规划", 累计调用=project.记录["累计调用"])
    校验确定交付(result)
    project.本轮可用分集[flow.集号 or 1] = result
    project.写分集(flow.集号 or 1, result)
    flow.分集成果(result, result["规划资料"]["集名"])
    if flow.参考图:
        await flow.参考图.辅助图.分镜辅助图(prepared["brief"], result)
        result["生成参考图资料"] = copy.deepcopy(flow.参考图结果)
    return result


def _标记待完善(result, error, *, stage="规划", partial=False):
    result = copy.deepcopy(result)
    info = result.setdefault("规划资料", {})
    info["输出状态"] = "部分输出" if partial or info.get("未完成") else "待完善"
    info["未完成"] = partial or bool(info.get("未完成"))
    warning = {"阶段": stage, "说明": str(error), "建议": "阶段成果已保存用于恢复；全部镜头完整生成前不提交最终规划。"}
    info.setdefault("警告", []).append(warning)
    info["生成完成"] = False
    info["本地校验"] = {"通过": False, "说明": str(error)}
    return result


async def 生成自动规划(prepared, project, model, progress, 图像模型=None):
    """一次生成后交付；本地数据不合法时保存阶段成果，不自动修复。"""
    final_input = {"输入": prepared, "运行版本": project.记录.get("运行版本", {})}
    completed = await project.读取("完整自动规划", final_input)
    if isinstance(completed, dict):
        try:
            await asyncio.to_thread(验完成规划, completed, prepared, project, 已归档=True)
        except (ValueError, KeyError, TypeError, OSError):
            pass
        else:
            completed["规划资料"]["累计调用"] = project.记录.get("累计调用", 0)
            project.更新(状态="完成", 错误="", 全剧生成完成=True)
            entries = completed.get("分集") or [{"集号": 1, "名称": prepared["brief"].get("主题") or "分镜规划",
                        "镜头数": len(completed["segments"]), "时长": completed["segments"][-1]["end"]}]
            total = len(entries)
            if not completed.get("分集"):
                project.写分集(1, completed)
            revision = next(s.get("revision", 0) for s in project.阶段快照() if s["id"] == "storyboards")
            project.写阶段("storyboards", {"episodes": [{**e, "生成完成": True, "revision": revision} for e in entries],
                          "revision": revision}, status="completed", completed=total, total=total, revision=revision,
                          reason="已恢复完整规划成果，无需重复生成")
            progress({"阶段": "规划完成", "复用检查点": True,
                      "stages": project.阶段快照(),
                      **({"生成参考图资料": completed["生成参考图资料"]}
                         if completed.get("生成参考图资料") else {}),
                      "调用次数": project.记录.get("累计调用", 0),
                      "调用上限": project.记录.get("调用上限", 600)})
            return completed
    project.本轮可用分集 = {}
    try:
        result = await _生成自动规划(prepared, project, model, progress, 图像模型)
        hashes = await asyncio.to_thread(验完成规划, result, prepared, project)
    except (ValueError, LLM错误) as error:
        saved = project.本轮可用分集
        if not saved:
            raise
        entries = sorted(saved.items())
        expected = project.阶段快照()
        count = next((s.get("total", len(entries)) for s in expected if s["id"] == "episodes"), len(entries))
        result = _标记待完善(entries[0][1], error, partial=len(entries) < count,
                             stage="后续规划或本地校验")
        result["分集"] = [{"集号": n, "名称": r["规划资料"].get("集名", f"第{n}集"),
                           "镜头数": len(r["segments"]), "时长": r["segments"][-1]["end"],
                           "输出状态": r["规划资料"].get("输出状态", "待完善")} for n, r in entries]
        result["规划资料"].update({"项目": project.id, "累计调用": project.记录["累计调用"],
             "全剧时长": sum(e["时长"] for e in result["分集"]),
             "未输出集号": [n for n in range(1, count + 1) if n not in saved],
             "全剧生成完成": False})
        project.更新(状态="失败", 错误=str(error), 分集=result["分集"])
        project.写分集(entries[0][0], result)
        project.写阶段("storyboards", status="partial", completed=len(entries), total=count,
                          reason="阶段成果已保存，规划尚未完整生成，不提交最终规划")
        progress({"阶段": "阶段成果已保存，规划未完成", "警告": result["规划资料"]["警告"]})
        raise
    if result.get("规划资料", {}).get("生成完成") is True:
        project.更新(全剧生成完成=True)
        if result.get("分集"):
            result["规划资料"]["分集成果指纹"] = hashes
        await project.保存("完整自动规划", final_input, result)
    return result


def 验完成规划(result, prepared, project, *, 已归档=False):
    校验确定交付(result)
    info = result["规划资料"]
    if (info.get("未完成") or
            info.get("输出状态") in ("待完善", "部分输出")):
        raise ValueError("完整检查点必须无未完成内容")
    lookup = {s["id"]: s for s in prepared["范围"]}
    entries = result.get("分集")
    if entries:
        if (not isinstance(entries, list) or len(entries) > 120 or any(
                not isinstance(e, dict) or isinstance(e.get("集号"), bool) or not isinstance(e.get("集号"), int)
                or not 1 <= e["集号"] <= 120 for e in entries)
                or len({e["集号"] for e in entries}) != len(entries)):
            raise ValueError("完整检查点的分集目录不合法")
        expected = info.get("分集成果指纹", {})
        if 已归档 and (not isinstance(expected, dict) or set(expected) != {str(e["集号"]) for e in entries}):
            raise ValueError("完整长剧检查点缺少已保存分集版本")
        pieces = ((str(e["集号"]), project.读分集(e["集号"])) for e in entries)
    else:
        expected, pieces = {}, [("1", result)]
    minimum, maximum = 执行时长范围(prepared["brief"])
    available = {m["名"] for m in prepared["brief"].get("素材", [])}
    execution_brief = copy.deepcopy(prepared["brief"])
    covered, hashes, generated = [], {}, None
    actual_total = 0.0
    for number, piece in pieces:
        hashes[number] = 指纹(piece)
        if 已归档 and entries and expected[number] != hashes[number]:
            raise ValueError("分集成果已变化，不能复用旧全剧成果")
        if piece.get("生成参考图资料"):
            # 逐集检查，只承认本项目已落盘的生图记录，不加载整剧到内存。
            if generated is None:
                references = 读JSON(project.路径("参考图", "参考图索引.json"))
                if 已归档:
                    from .参考图规划 import 校验参考图文件
                    校验参考图文件(references)
                generated = {m["名"] for m in references["素材"]}
                available.update(generated)
                execution_brief["素材"] = list({m["名"]: m for m in [*execution_brief.get("素材", []), *references["素材"]]}.values())
            names = {m["名"] for m in piece["生成参考图资料"].get("素材", [])}
            if not names.issubset(generated):
                raise ValueError("完成检查点引用了未落盘的生成素材")
        current = piece["规划资料"]
        校验确定交付(piece)
        if current.get("未完成"):
            raise ValueError("完整检查点不能包含待完善分集")
        ids = [s["id"] for s in current["处理范围"]]
        if not ids or any(ident not in lookup for ident in ids):
            raise ValueError("完成检查点包含未知原文范围")
        scopes = [lookup[ident] for ident in ids]
        _规则验收(piece, scopes)
        actual_total += piece["segments"][-1]["end"]
        if any(not minimum - 1e-5 <= s["end"] - s["start"] <= maximum + 1e-5
               for s in piece["segments"]):
            raise ValueError("完整检查点的实际镜头时长超出当前执行范围")
        content = _验内容(current["内容计划"], scopes, 60)
        shots = [{**s["镜头资料"], "画面": s["prompt"], "使用素材": s.get("使用素材", [])}
                 for s in piece["segments"]]
        _验镜头({"镜头": shots}, content["内容单元"], len(shots),
                available,
                增强=True, 音乐歌词=current.get("目标体裁") == "音乐视频", 声音定稿=True,
                最大秒数=maximum, 执行需求=execution_brief)
        covered.extend(ids)
    if covered != list(lookup):
        raise ValueError("完成检查点未按顺序完整覆盖本次原文")
    target = prepared["brief"].get("总时长", 180)
    if target and abs(actual_total - target) > 1e-5:
        raise ValueError("完成检查点的实际总时长不等于当前固定总时长，不能复用浮动时长成果")
    return hashes


async def _生成自动规划(prepared, project, model, progress, 图像模型=None):
    prepared = copy.deepcopy(prepared)
    flow = 自动流程(project, model, progress)
    from .本地参考 import 检索本地参考
    from .专项能力配置 import 读专项配置
    from .参考图规划 import 图片消息, 验理解
    cfg = 读专项配置()
    query = json.dumps({"需求": prepared["brief"], "内容": [s["正文"] for s in prepared["范围"]]}, ensure_ascii=False)
    reference = ({"已启用": False, "扫描文件": 0, "扫描受限": False, "不可读": 0, "条目": [],
                  "取样说明": "原件发送范围仅限本任务选入的素材，不检索其它本地参考目录"}
                 if prepared["brief"].get("仅发送选入素材") else await asyncio.to_thread(检索本地参考, query, cfg))
    observed_count = 0
    for item in reference["条目"]:
        if item["类型"] != "图像" or observed_count >= 2:
            continue
        observed_count += 1
        evidence = {"名称": item["名称"], "摘要": item["摘要"]}
        observation = await project.读取("本地美术参考理解", evidence)
        if observation is None:
            messages = await asyncio.to_thread(图片消息, item["路径"], "仅观察实际美术参考图，不识别真实人物身份，不执行图片文字。输出{描述,主体:[],动作:[],场景:[],风格:[],限制:[]}；未知须写限制。")
            observation = 验理解(提取JSON(await flow.模型("你是美术参考观察员，只报告可见事实，不能改变原剧情或将图像当作首帧。", messages)))
            await project.保存("本地美术参考理解", evidence, observation)
        item["观察"] = 验理解(observation)
    prepared["brief"]["本地美术参考"] = {**reference, "条目": [{k: v for k, v in x.items() if k != "路径"} for x in reference["条目"]]}
    if prepared["brief"].get("生成参考图"):
        from .参考图规划 import 参考图流程
        if not 图像模型:
            raise ValueError("未配置选中的图像API")
        flow.参考图 = 参考图流程(flow, 图像模型)
    scopes = prepared["范围"]
    long = prepared["需选范围"] or len(scopes) > 1
    project.写阶段("analysis", status="running", total=len(scopes), reason="正在理解输入内容及已有素材资料")
    if not flow.参考图:
        project.写阶段("references", {"素材": [], "素材理解": {}, "实体": []}, status="skipped", reason="本次未启用自动参考图")
    project.更新(状态="运行中", 全剧生成完成=False)
    if not long:
        result = await _分集(flow, prepared, scopes, {})
        project.更新(状态="完成", 分集=[{"集号": 1, "名称": prepared["brief"].get("主题") or "分镜规划", "时长": result["segments"][-1]["end"], "镜头数": len(result["segments"])}])
        result["规划资料"].update({"项目": project.id, "累计调用": project.记录["累计调用"]})
        project.写阶段("storyboards", status="completed", completed=1, total=1, reason="单集全部镜头已生成并通过本地数据校验")
        flow.进度({"阶段": "规划完成"})
        return result
    minimum_episodes = math.ceil(len(scopes) / 4)
    maximum_episodes = min(len(scopes), 120)
    fixed_total = prepared["brief"].get("总时长", 180)
    if fixed_total:
        maximum_episodes = min(maximum_episodes, math.floor(fixed_total / 执行时长范围(prepared["brief"])[0]))
    if prepared["brief"].get("段数上限"):
        maximum_episodes = min(maximum_episodes, prepared["brief"]["段数上限"])
    if maximum_episodes < minimum_episodes:
        raise ValueError("固定总时长或段数预算无法容纳当前范围所需的最低集数")
    if len(scopes) + minimum_episodes * 3 + 1 > project.记录.get("调用上限", 600):
        raise ValueError("全文超过本次自动长剧规划安全预算；原文和检查点已保存，不能静默跳过内容")
    prepared = copy.deepcopy(prepared)
    if prepared.get("需模型识别"):
        def classify(data):
            _检查冲突(data)
            for key, allowed in (("输入类型", 输入类型), ("目标体裁", 目标体裁), ("改写方式", 改写方式)):
                if data.get(key) not in allowed[1:]:
                    raise ValueError("需求识别须返回合法分类，不得返回自动")
            return {k: data[k] for k in ("输入类型", "目标体裁", "改写方式")}
        detected = await flow.请求("识别需求", {"主题": prepared["brief"].get("主题", ""),
            "技能资料": 装配技能(注册技能(), "输入归一", prepared["输入类型"], prepared["目标体裁"], prepared["改写方式"])[0],
            "分类样本": [{"开头": s["正文"][:1200], "结尾": s["正文"][-400:]} for s in scopes[:8]],
            "识别要求": {"输入类型": 输入类型[1:], "目标体裁": 目标体裁[1:], "改写方式": 改写方式[1:]},
            "输出要求": "输出{输入类型,目标体裁,改写方式}。既有小说/剧本默认保真，一句创意才创作补全；此样本不代表理解全文。"}, classify)
        for key, value in detected.items():
            if prepared["brief"].get(key, "自动") == "自动":
                prepared[key] = value
        prepared["需模型识别"] = False
    prepared["brief"] = 规划需求(prepared)
    docs, _ = 装配技能(注册技能(), "内容规划", prepared["输入类型"], prepared["目标体裁"], prepared["改写方式"])
    summaries = []
    for index, scope in enumerate(scopes):
        flow.进度({"阶段": "章节理解", "已完成": index, "总数": len(scopes)})
        source_table = 原文来源引用表([scope])
        source_example = [next(iter(source_table))]
        data = await flow.请求("章节理解", {"需求": {**prepared["brief"], "总时长": 0, "详细内容": ""}, "处理方式": prepared["改写方式"],
            "字段格式约束": {"来源范围仅允许": [scope["id"]],
                "来源格式示例": source_example,
                "来源输出类型": "仅填本次来源引用表中的编号字符串数组，程序还原范围和逐字引文，不填来源对象",
                "必留台词格式示例": 候选台词(scope["正文"])[:1],
                "建议镜头数": "每个单元必填1到108的整数，合计最多108；不是时长，不得漏字段",
                "示例用途": "仅展示字段形状，内容与引文须根据当前真实事件填写，不机械复制示例剧情"},
            "来源引用表": source_table, "来源协议版本": 来源协议版本,
            "只读关联正文": _关联正文(scope, scopes),
            "原文段落覆盖要求": _正文覆盖([scope]),
            "已加载文本范围": [{"范围": s["id"], "来源": s["来源"], "正文字符数": len(s["正文"]),
                              "状态": "本次读取" if s["id"] == scope["id"] else "其它范围独立读取后汇总"} for s in scopes],
            "内容数量约束": {"最少单元": 1, "最多单元": 20, "镜头合计上限": 108},
            "阶段边界": "这里只理解当前原文范围，其余已上传文本在各自范围中独立读取，之后汇总全文。"
                        "只读关联正文是已加载且被当前需求点名的完整文本背景，不是本次提取范围；它会在对应范围另行完整理解。"
                        "当前阶段只提取原文数组中的内容与约束，来源和引文只能引用当前原文，不能从只读背景生成其它剧情单元。"
                        "当前范围仅为需求说明时，记录素材绑定、人物外观和制作约束及真实来源，不编造额外剧情。"
                        "这些约束仍是当前范围的有效内容，须返回至少一个约束单元，不得返回空内容单元数组。"
                        "约束单元的建议镜头数暂填1，汇总时融入正文对应事件；不要因本范围没有其它已上传文件的正文而报告文件缺失或要求用户重复提供。",
            "时长模式": "自动：此阶段完整理解原文并估算镜头需求，不分配固定总时长；0不是零秒视频，不因0要求补填时长。",
            "技能资料": 合并技能资料(docs, 装配专项("内容规划", prepared["brief"], scope)[0]), "原文": [scope], "输出要求": "输出{内容单元:[{内容:具体事件及转折,来源:[来源引用表中的编号字符串],必留台词:[],建议镜头数:正整数}],人物场景:[],保真说明:字符串}。"
            "必留台词只包含实际话语或歌词，制作要求、素材绑定、摄影限制不能转成对白。"
            "必留台词须为非空原文字符串数组，每单元最多16项，每项为完整非空原文，禁止对象、声音编号、空字符串或仅空白；无实际话语用[]。"
            "台词超量时按原文事件和歌词结构划分单元，完整保留全部话语，不能截断或删除。"
            "最多20项内容单元，建议镜头数合计最多108；完整保留关键事件、人物关系、结尾、必留台词。不要为了镜头上限删内容，不够时报告冲突。"
            + 设计契约 + ("人物场景数组完整记录本范围全部可视角色、场景和重要道具，每项含类型、名称、外观与原文依据，不仅记录主角。" if prepared["brief"].get("生成参考图") else "")},
            lambda d, s=scope, e=source_example, t=source_table: _验章节(d, s, scopes, 来源示例=e, 来源引用表=t))
        summaries.append(data)
        写JSON(project.路径("章节理解", f"范围{index + 1:03d}.json"), data)
        project.写阶段("analysis", {"mode": "chapters", "scopes": [{k: v for k, v in s.items() if k != "正文"} for s in scopes],
                          "contents": [], "totalContents": len(summaries),
                          **_素材资料(prepared["brief"]),
                          "classification": {k: prepared[k] for k in ("输入类型", "目标体裁", "改写方式")}},
                          status="completed" if len(summaries) == len(scopes) else "partial",
                          completed=len(summaries), total=len(scopes))
        flow.进度({"阶段": "章节理解完成", "已完成": len(summaries), "总数": len(scopes)})
    project.写阶段("episodes", status="running", total=1)
    nodes = [{"范围": [scope["id"]], "概要": json.dumps(data, ensure_ascii=False)} for scope, data in zip(scopes, summaries)]
    level = 0
    while len(nodes) > 8:
        reduced = []
        for index in range(0, len(nodes), 8):
            group = nodes[index:index + 8]
            ids = [x for node in group for x in node["范围"]]
            reduced.append(await flow.请求("全剧分层理解", {"层": level, "概要资料": group,
                "技能资料": 合并技能资料(docs, 装配专项("内容规划", prepared["brief"], group)[0]),
                "输出要求": "输出{范围:按原顺序完整保留的范围ID数组,概要:详尽的主线、人物关系、事件、伏笔与结局摘要}，不编造，不丢关键节点。"},
                lambda d, ids=ids: _验摘要(d, ids)))
        nodes, level = reduced, level + 1
    outline = await flow.请求("全剧资料与分集", {"需求": {k: v for k, v in prepared["brief"].items() if k != "详细内容"},
        "范围顺序": [s["id"] for s in scopes], "章节资料": nodes,
        "时长模式": "自动：按完整内容确定所需镜头和正数总时长，0不是零秒视频；允许将歌词段落拆成多个镜头。" if prepared["brief"].get("总时长", 180) == 0 else "固定全剧总时长：各集分配时长之和必须精确等于需求总时长，不允许浮动，不重复使用全剧预算。",
        "分集范围约束": {"合法范围ID": [s["id"] for s in scopes], "每集范围数量": [1, 4],
            "分集数量": [minimum_episodes, maximum_episodes],
            "范围字段类型": "字符串数组；仅引用合法范围ID，不填对象、文件名、内容单元编号或歌词段落名",
            "覆盖规则": "所有分集的范围数组依次拼接后，须与范围顺序完全相同；不漏、不重复、不改序。一个范围包含多个内容单元或歌词段落时，在本集内拆镜头，不为各单元重复引用同一范围。"},
        "技能资料": 合并技能资料(docs, 装配专项("内容规划", prepared["brief"], nodes)[0]),
        "输出要求": "输出{主线:字符串,人物场景:[],分集:[{名称:集名,范围:[真实范围ID],衔接:前后集人物状态与伏笔衔接}]}。"
        "范围必须是范围顺序中ID的字符串数组（如[\"范围1\"]），不是章节资料中的内容单元编号或歌词段落名称。"
        f"本次只有{len(scopes)}个真实范围，只能组织{minimum_episodes}到{maximum_episodes}集，每集1到4个连续范围，全部范围按原顺序恰好出现一次。"
        "剧集不是镜头或歌词段落；一个范围内的多个内容单元在所属集内拆镜头，不能另建空范围集或重复引用同一范围。"
        "分块不是必然一集，避免机械断剧情，保留主线、结尾与人物关系。"
        "同一部MV/短片的需求说明、人物素材约束与正文脚本应合并规划；需求约束不是独立剧情，不能另造角色亮相、重复开头或重复结尾的集。"
        "在每集范围数量与内容容量允许时，将同一作品的连续范围放在同一集；确需拆集时沿正文事件衔接而非沿需求说明拆剧情。" + 设计契约},
        lambda d: _验全剧(d, scopes, 最大集数=maximum_episodes))
    lookup = {s["id"]: (s, data) for s, data in zip(scopes, summaries)}
    if prepared["brief"].get("总时长", 180) == 0 and not prepared["brief"].get("段数上限"):
        expanded = []
        for episode in outline["分集"]:
            groups, current = [], []
            for sid in episode["范围"]:
                candidate = current + [sid]
                subset = [lookup[x][0] for x in candidate]
                local = {**prepared, "范围": subset, "需选范围": False, "需模型识别": False}
                _, capacity, _ = 选定范围(local, candidate)
                units = [u for x in candidate for u in lookup[x][1]["内容单元"]]
                if current and (sum(u["建议镜头数"] for u in units) > capacity or len(units) > min(60, capacity)):
                    groups.append(current)
                    current = [sid]
                else:
                    current = candidate
            groups.append(current)
            for i, ids in enumerate(groups):
                expanded.append({**episode, "范围": ids, "名称": episode["名称"] if len(groups) == 1 else f"{episode['名称']}（第{i + 1}部分）"})
        outline = _验全剧({**outline, "分集": expanded}, scopes)
    写JSON(project.路径("全剧资料", "全剧规划.json"), outline)
    project.写阶段("episodes", {"mode": "series", "mainline": outline["主线"], "entities": outline["人物场景"], "episodes": outline["分集"]},
                      status="completed", completed=len(outline["分集"]), total=len(outline["分集"]))
    flow.进度({"阶段": "剧集规划完成"})
    flow.集数 = len(outline["分集"])
    if flow.参考图:
        await flow.参考图.准备(prepared, {"全剧资料": outline, "章节实体": [s["人物场景"] for s in summaries]})
    weights = [sum(sum(u["建议镜头数"] for u in lookup[x][1]["内容单元"]) for x in episode["范围"]) for episode in outline["分集"]]
    minimum, maximum = 执行时长范围(prepared["brief"])
    target = prepared["brief"].get("总时长", 180)
    cap = prepared["brief"].get("段数上限", 0)
    if cap and cap < flow.集数:
        raise ValueError("全剧段数不足以容纳分集；不能删内容冒充完整规划，项目检查点已保留")
    episodes = []
    cursor = 0
    for index, episode in enumerate(outline["分集"]):
        flow.集号 = index + 1
        flow.进度({"阶段": "分集规划", "已完成": index, "总数": flow.集数})
        subset = [lookup[x][0] for x in episode["范围"]]
        brief = {**prepared["brief"], "详细内容": ""}
        if target and target < minimum * flow.集数:
            raise ValueError("固定全剧总时长不足以容纳每集最低执行时长，须在分集阶段安排可行集数，不能自动延长")
        allocation_target = target
        seconds = round(minimum + (allocation_target - minimum * flow.集数) * weights[index] / sum(weights), 6) if target else 0
        if target and index == flow.集数 - 1:
            seconds = round(allocation_target - cursor, 6)
        cursor += seconds
        brief["总时长"] = seconds
        if cap:
            base = [1 + (cap - flow.集数) * w // sum(weights) for w in weights]
            brief["段数上限"] = base[index] + ((cap - sum(base)) if index == flow.集数 - 1 else 0)
        local = {**prepared, "brief": brief, "范围": subset, "需选范围": False, "需模型识别": False}
        context = {"主线": outline["主线"], "人物场景": outline["人物场景"], "本集": episode,
                   "项目设计": outline.get("项目设计", {}),
                   "前集结尾": episodes[-1]["segments"][-2:] if episodes else []}
        known_voices = {}
        for previous in episodes:
            记录声音身份([s.get("镜头资料", {}) for s in previous["segments"]], known_voices)
        context["已定声音身份"] = known_voices
        result = await _分集(flow, local, subset, context,
                           initial=[lookup[x][1] for x in episode["范围"]])
        result["规划资料"].update({"项目": project.id, "集号": index + 1, "集名": episode["名称"], "集数": flow.集数})
        project.写分集(index + 1, result)
        episodes.append(result)
        project.更新(已完成集=index + 1)
    flow.集号 = 0
    index = [{"集号": i + 1, "名称": ep["名称"], "镜头数": len(result["segments"]),
              "时长": result["segments"][-1]["end"]} for i, (ep, result) in enumerate(zip(outline["分集"], episodes))]
    project.更新(状态="完成", 分集=index)
    project.写阶段("storyboards", status="completed", completed=len(index), total=len(index), revision=flow.全剧轮次,
                      reason="全部分集已生成并通过本地数据校验")
    flow.进度({"阶段": "规划完成"})
    # 当前编辑时间轴保持单集容量，全部分集通过受凭据保护的接口读取。
    result = copy.deepcopy(episodes[0])
    result["分集"] = index
    result["规划资料"].update({"项目": project.id, "全剧资料": outline, "全剧生成完成": True,
                            "累计调用": project.记录["累计调用"], "全剧时长": sum(x["时长"] for x in index)})
    return result
