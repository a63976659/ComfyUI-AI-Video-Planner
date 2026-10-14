# -*- coding: utf-8 -*-
"""时间轴提示词改写入口：冻结分镜，每个目标段一次直接生成。

旧技能/辅助参数保留以兼容旧计划；旧处理模式不再生效，质量自查要求写入生成规则。
"""
from .知识库 import 通用改写技能, 规范改写技能, load_skill_docs, 任务类型映射
from .H3改写验收 import 自动改写, 准备依据, 全局依据, 构建改写请求
from .模型适配 import 取模型能力, 通用编译

默认批大小 = 1


def 拆批(段索引, 批大小):
    批大小 = max(1, int(批大小))
    return [段索引[i:i + 批大小] for i in range(0, len(段索引), 批大小)]


def 目标索引(segments, 目标ids=None):
    """按时间轴顺序取目标，供改写入口和流式进度共同使用。"""
    目标集 = {str(x) for x in (目标ids or []) if x not in (None, "")}
    return [i for i, s in enumerate(segments or [])
            if not 目标集 or str(s.get("segment_id") or "") in 目标集]


def _校验分镜(segments):
    if not isinstance(segments, list) or not segments or not all(isinstance(s, dict) for s in segments):
        raise ValueError("提示词改写：segments 必须是非空分镜对象数组")
    ids = [str(s["segment_id"]) for s in segments if s.get("segment_id") not in (None, "")]
    if len(ids) != len(set(ids)):
        raise ValueError("提示词改写：segment_id 重复，无法确定提示词归属")


def _记录知识库(回执, shots, indices):
    if isinstance(回执, dict):
        types = list(dict.fromkeys(任务类型映射(shots[i]["任务"]) for i in indices))
        回执["知识库"] = load_skill_docs(通用改写技能, types, 精简=True)[2]


def 构建提示词生成prompt(brief, segments, 技能=通用改写技能, 辅助="无", 回执=None, 禁用字幕=False):
    return 构建局部重试prompt(brief, segments, list(range(len(segments))), 技能,
                         辅助, 回执, 禁用字幕)


def 构建局部重试prompt(brief, segments, 目标索引, 技能=通用改写技能,
                    辅助="无", 回执=None, 禁用字幕=False):
    规范改写技能(技能)
    _校验分镜(segments)
    if not 目标索引 or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(segments)
                        for i in 目标索引) or len(set(目标索引)) != len(目标索引):
        raise ValueError("提示词改写：目标索引为空、重复或越界")
    indices = sorted(目标索引)
    brief = brief if isinstance(brief, dict) else {}
    shots = 准备依据(brief, segments)
    _记录知识库(回执, shots, indices)
    return 构建改写请求(shots, indices, 全局依据(brief), 禁用字幕=禁用字幕)


def 生成提示词(brief, segments, opener, 技能=通用改写技能, 辅助="无",
             回执=None, 状态=None, 禁用字幕=False):
    规范改写技能(技能)
    _校验分镜(segments)
    brief = brief if isinstance(brief, dict) else {}
    indices = list(range(len(segments)))
    if 取模型能力(brief)["提示词格式"] != "H3":
        return 通用编译(brief, segments, opener, indices, 状态=状态, 禁用字幕=禁用字幕)["segments"]
    _记录知识库(回执, 准备依据(brief, segments), indices)
    return 自动改写(brief, segments, opener, indices, 禁用字幕=禁用字幕, 状态=状态)["segments"]


def 局部重试(brief, segments, 目标ids, opener, 技能=通用改写技能, 辅助="无",
          回执=None, 状态=None, 禁用字幕=False):
    _校验分镜(segments)
    targets = {str(x) for x in (目标ids or []) if x not in (None, "")}
    indices = [i for i, s in enumerate(segments) if str(s.get("segment_id") or "") in targets]
    if not indices or targets != {str(segments[i]["segment_id"]) for i in indices}:
        raise ValueError("局部重试：目标段清单为空或与 segments 的 segment_id 不匹配")
    规范改写技能(技能)
    brief = brief if isinstance(brief, dict) else {}
    if 取模型能力(brief)["提示词格式"] != "H3":
        return 通用编译(brief, segments, opener, indices, 状态=状态, 禁用字幕=禁用字幕)["segments"]
    _记录知识库(回执, 准备依据(brief, segments), indices)
    return 自动改写(brief, segments, opener, indices, 禁用字幕=禁用字幕, 状态=状态)["segments"]


def 分批生成提示词(brief, segments, opener, 目标ids=None, 批大小=默认批大小,
                 技能=通用改写技能, 辅助="无", 状态=None, 禁用字幕=False,
                 每批回调=None, 停止=None, 资料=None, 进度=None, **旧参数):
    """各段一次请求；请求或格式失败保留原稿，停止后不发布在途结果。"""
    规范改写技能(技能)
    _校验分镜(segments)
    if isinstance(批大小, bool) or not isinstance(批大小, int) or not 1 <= 批大小 <= 20:
        raise ValueError("分批改写：批大小须为 1..20 的整数")
    indices = 目标索引(segments, 目标ids)
    targets = {str(x) for x in (目标ids or []) if x not in (None, "")}
    if not indices or (targets and targets != {str(segments[i].get("segment_id") or "") for i in indices}):
        raise ValueError("分批改写：目标段清单为空或与 segment_id 不匹配")
    if any(not str(segments[i].get("segment_id") or "").strip() for i in indices):
        raise ValueError("分批改写：目标段缺少 segment_id，无法按批定位")
    brief = brief if isinstance(brief, dict) else {}
    kwargs = dict(状态=状态, 每批回调=每批回调, 停止=停止, 进度=进度, 禁用字幕=禁用字幕, 资料=资料)
    if 取模型能力(brief)["提示词格式"] != "H3":
        return 通用编译(brief, segments, opener, indices, **kwargs)
    return 自动改写(brief, segments, opener, indices, **kwargs)
