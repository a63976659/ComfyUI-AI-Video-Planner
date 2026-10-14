# -*- coding: utf-8 -*-
"""时间轴专用有界、可取消请求；不改变AI规划或视频生成的请求策略。"""
import asyncio
import time
from urllib.parse import urlparse

from .配置 import 读配置, LLM错误, _整数配置
from .异步请求 import 异步模型请求

单次请求上限 = 600
每批耗时上限 = 单次请求上限


def 改写请求选项(cfg, 验收=False, system="", user=""):
    import json
    # 不设置输出token上限；仅对已匹配且实测通过的端点启用非思考和结构化输出。
    # 仅对实测的百炼Qwen3.8-Flash启用；Omni/纯思考型号的参数约定不同。
    host = (urlparse(str(cfg.get("base_url") or "")).hostname or "").lower()
    model = str(cfg.get("model") or "").lower()
    if host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"} and model == "qwen3.8-flash":
        options = {"enable_thinking": False}
        if system:
            options["response_format"] = {"type": "json_object"}
            # 已在规划模块使用的供应商结构化协议；只向已匹配端点发送。
            if "MiniMax H3 分镜适配导演" in system:
                try:
                    data = json.loads(user.split("\n\n知识库文档：", 1)[0])
                    shot = data["当前分镜"][0]
                    keys = ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music") if shot["任务"] in ("r2v", "v2v", "rv2v") else ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
                    row = {"type": "object", "properties": {"segment_id": {"type": "string", "enum": [shot["segment_id"]]}, **{k: {"type": "string", "minLength": 1} for k in keys}}, "required": ["segment_id", *keys], "additionalProperties": False}
                    schema = {"type": "object", "properties": {"prompts": {"type": "array", "items": row, "minItems": 1, "maxItems": 1}}, "required": ["prompts"], "additionalProperties": False}
                    options["response_format"] = {"type": "json_schema", "json_schema": {"name": "shot_prompt", "strict": True, "schema": schema}}
                except (ValueError, KeyError, IndexError, TypeError):
                    pass
            elif "独立的 H3 提示词验收员" in system:
                try:
                    ids = [shot["segment_id"] for shot in json.loads(user)["验收目标"]]
                    evidence = {"type": "object", "properties": {k: {"type": "string", "minLength": 1} for k in ("原稿引用", "候选引用")}, "required": ["原稿引用", "候选引用"], "additionalProperties": False}
                    row = {"type": "object", "properties": {
                        "segment_id": {"type": "string", "enum": ids}, "通过": {"type": "boolean"},
                        "问题": {"type": "array", "items": {"type": "string"}},
                        "建议": {"type": "array", "items": {"type": "string"}},
                        "依据": {"type": "array", "items": evidence}},
                        "required": ["segment_id", "通过", "问题", "建议", "依据"], "additionalProperties": False}
                    schema = {"type": "object", "properties": {"验收": {"type": "array", "items": row, "minItems": len(ids), "maxItems": len(ids)}}, "required": ["验收"], "additionalProperties": False}
                    options["response_format"] = {"type": "json_schema", "json_schema": {"name": "shot_review", "strict": True, "schema": schema}}
                except (ValueError, KeyError, TypeError):
                    pass
        return options
    return {}


def 造改写opener(覆盖=None, 请求回调=None, 停止=None, 用量回调=None):
    deadline = [float("inf")]

    async def run(system, user):
        cfg = {**读配置(), **(覆盖 or {})}
        if not cfg.get("base_url") or not cfg.get("model"):
            raise LLM错误("LLM 未配置", 类别="config", 状态码=400)
        limit = min(单次请求上限, _整数配置(cfg, "timeout", 单次请求上限, 下限=1), deadline[0] - time.monotonic())
        if limit <= 0:
            raise LLM错误("本段提示词改写已达等待期限，自动停止并保留原稿", 类别="deadline", 状态码=504)
        cfg["timeout"] = max(1, limit)

        async def send():
            async with 异步模型请求(cfg, 请求选项=改写请求选项(cfg, "提示词验收员" in system, system, user),
                              请求回调=请求回调, 总超时=limit, 仅正文=True) as model:
                text = await model(system, user)
                if 用量回调:
                    用量回调(list(model.用量))
                return text

        task = asyncio.create_task(send())
        end = time.monotonic() + limit
        try:
            while not task.done():
                if 停止 is not None and 停止():
                    raise LLM错误("提示词改写已停止", 类别="cancelled", 状态码=409)
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise LLM错误("提示词请求超时，已停止；没有自动重发收费请求", 类别="deadline", 状态码=504)
                await asyncio.wait({task}, timeout=min(0.1, remaining))
            return await task
        except LLM错误 as e:
            # 暂态网络错误不伪装成提示词质量错误，避免上层再次发送收费请求。
            e.可重试 = False
            raise
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def opener(system, user):
        if 停止 is not None and 停止():
            raise LLM错误("提示词改写已停止", 类别="cancelled", 状态码=409)
        return asyncio.run(run(system, user))

    opener.设置批次期限 = lambda value: deadline.__setitem__(0, value)
    return opener
