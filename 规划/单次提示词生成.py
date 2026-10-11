# -*- coding: utf-8 -*-
"""逐段单次请求；质量要求由生成规则交给模型，不运行独立验收或修复。"""
import copy
import hashlib
import time
from pathlib import Path
from .改写请求 import 单次请求上限


def 加载单次生成规则():
    return (Path(__file__).resolve().parent.parent / "AI生成提示词" / "SKILL.md").read_text(encoding="utf-8")


def 逐段一次生成(segments, indices, shots, opener, 构建请求, 解析输出,
             状态=None, 每批回调=None, 停止=None, 进度=None):
    result = copy.deepcopy(segments)
    status = 状态 if isinstance(状态, dict) else {}
    calls, failed = 0, 0
    stopped = lambda: bool(停止 and 停止())
    for number, i in enumerate(indices):
        if stopped():
            break
        sid = shots[i]["segment_id"]
        error = None
        try:
            system, user = 构建请求(i)
            if stopped():
                break
            deadline = time.monotonic() + 单次请求上限
            if hasattr(opener, "设置批次期限"):
                opener.设置批次期限(deadline)
            if 进度:
                进度({"阶段": "生成提示词", "批次": number + 1, "总批数": len(indices), "调用": calls + 1})
            if stopped():
                break
            calls += 1
            raw = opener(system, user)
            if stopped():
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("本段提示词请求超时，未写入超时结果")
            prompt = 解析输出(raw, i)
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("模型未返回完整非空提示词")
        except Exception as exc:
            if stopped():
                break
            error = exc
        if stopped():
            break
        result[i].pop("提示词验收", None)
        if error is None:
            result[i]["分镜原稿"] = shots[i]["原始分镜"]
            result[i]["prompt"] = prompt
            result[i].pop("台词时长提示", None)
            report = {"完成": True, "问题": [], "提示词摘要": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
            state = "ok"
        else:
            failed += 1
            report = {"完成": False, "问题": [str(error) or type(error).__name__]}
            # 保留旧生成来源摘要，失败后再次点击仍从原分镜生成。
            previous = segments[i].get("提示词生成") or segments[i].get("提示词验收") or {}
            if isinstance(previous, dict) and previous.get("提示词摘要"):
                report["提示词摘要"] = previous["提示词摘要"]
            state = "degraded"
        result[i]["提示词生成"] = report
        status[sid] = state
        if 每批回调:
            每批回调(number, [copy.deepcopy(result[i])], {sid: state})
        # 明确的连接、鉴权、配置故障保留当前段后收尾，不重复发送。
        if error is not None and getattr(error, "可重试", None) is False:
            raise error
    return {"segments": result, "批次总": len(indices), "降级": failed, "调用": calls, "stopped": stopped()}
