# -*- coding: utf-8 -*-
"""H3 规划路由：aiohttp 薄壳 handler + 可脱离 PromptServer 的纯函数。

handler 委托纯逻辑（规划器.规划 + 配置.默认opener）；HTTP 域不抛未捕获异常，
一律 web.json_response({error}, status)；阻塞 LLM 调用走 run_in_executor。
设计依据：文档/规格/2026-09-10-H3规划器-设计.md §7.3 + §13。
"""
import asyncio
import json
import logging

from aiohttp import web

try:                                        # ComfyUI 运行时（以包形式加载）
    from ..规划.规划器 import 规划
    from ..规划.配置 import 默认opener, 造opener, 读配置, 取脱敏配置, 写配置, 测连通性, LLM错误
    from ..规划.方法论 import PLATFORM_HINTS, HOOK_TYPES, ROLE_COLORS
    from ..规划.知识库 import 风格选项, 辅助风格选项, 技能选项
    from ..规划.提示词生成 import 生成提示词, 局部重试
except ImportError:                         # pytest（插件根在 sys.path，`..` 越界）
    from 规划.规划器 import 规划
    from 规划.配置 import 默认opener, 造opener, 读配置, 取脱敏配置, 写配置, 测连通性, LLM错误
    from 规划.方法论 import PLATFORM_HINTS, HOOK_TYPES, ROLE_COLORS
    from 规划.知识库 import 风格选项, 辅助风格选项, 技能选项
    from 规划.提示词生成 import 生成提示词, 局部重试

_已注册 = False
_任务码 = ["t2v", "i2v", "fl2v", "r2v", "v2v", "rv2v"]
_总时长上限 = 3600


def _校验brief(body):
    """纯函数：校验 brief。返回 (ok: bool, err: str|None)。可脱离 PromptServer 单测。"""
    if not isinstance(body, dict):
        return False, "请求体必须是对象"
    主题 = body.get("主题")
    if not isinstance(主题, str) or not 主题.strip():
        return False, "主题不能为空"
    总时长 = body.get("总时长", 30)
    if isinstance(总时长, bool) or not isinstance(总时长, (int, float)):
        return False, "总时长必须是数字"
    if not (1 <= float(总时长) <= _总时长上限):
        return False, f"总时长须在 1..{_总时长上限} 秒"
    return True, None


def _校验segments(body):
    """纯函数：校验提示词生成请求体。返回 (ok, err)。segments 必须为非空段对象数组。"""
    if not isinstance(body, dict):
        return False, "请求体必须是对象"
    segs = body.get("segments")
    if not isinstance(segs, list) or not segs or not all(isinstance(s, dict) for s in segs):
        return False, "segments 必须是非空段对象数组"
    return True, None


def _校验重试请求(body):
    """纯函数：校验 A2 局部重试请求体。复用 segments 非空校验；额外要求 目标段ids 为非空字符串数组。"""
    ok, err = _校验segments(body)
    if not ok:
        return ok, err
    ids = body.get("目标段ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x.strip() for x in ids):
        return False, "目标段ids 必须是非空字符串数组"
    return True, None


def _plan_meta() -> dict:
    """纯函数：前端下拉枚举（杜绝前端复制方法论常量）。职能枚举为 {名,色} 对象数组。"""
    return {
        "平台": list(PLATFORM_HINTS.keys()),
        "钩子": list(HOOK_TYPES),
        "职能": [{"名": k, "色": v} for k, v in ROLE_COLORS.items()],
        "任务": list(_任务码),
        "风格技能": 风格选项(),
        "辅助风格": 辅助风格选项(),
        "brief技能": 技能选项(),   # brief 区「技能」独立源＝根目录 Skills/（剪辑时间轴生成行仍用 风格技能）
    }


def _解析模型覆盖(body):
    """纯函数：pop body['模型id'] → 在配置盘 api_models 按 id 命中返回 {base_url,model,api_key}；
    未带或未命中 → None（回落配置盘默认模型）。命中条 api_key 空串＝该模型确无 Key（opener 不加 Authorization）。
    pop 副作用保证 模型id 不入 规划(brief) 的提示词构建。"""
    mid = str((body or {}).pop("模型id", "") or "").strip()
    if not mid:
        return None
    for e in 读配置().get("api_models") or []:
        if e.get("id") == mid:
            return {"base_url": e.get("base_url", ""), "model": e.get("model", ""),
                    "api_key": e.get("api_key", "")}
    return None


def _错误响应(e):
    """纯函数：异常 → (响应体, HTTP 状态)。LLM错误 携结构化的 可重试/请求ID/状态码，
    路由不再靠中文异常子串判定 HTTP 状态（B4）；其余 RuntimeError → 500（统一 {error} 结构）。"""
    if isinstance(e, LLM错误):
        return {"error": str(e), "retryable": e.可重试, "requestId": e.请求ID}, e.状态码
    return {"error": str(e)}, 500


def 注册路由():
    global _已注册
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes

    @routes.post("/lvp/plan")
    async def 规划接口(request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "请求体不是合法 JSON"}, status=400)
        ok, err = _校验brief(body)
        if not ok:
            return web.json_response({"error": err}, status=400)
        覆盖 = _解析模型覆盖(body)   # pop 模型id → 按所选模型临时切换 opener（不写盘）
        opener = 造opener(覆盖) if 覆盖 else 默认opener
        try:
            loop = asyncio.get_running_loop()
            结果 = await loop.run_in_executor(None, 规划, body, opener)
            return web.json_response(结果)
        except RuntimeError as e:
            payload, 状态 = _错误响应(e)   # 结构化：LLM错误带 可重试/请求ID/状态码，不再中文子串判定
            return web.json_response(payload, status=状态)
        except Exception as e:
            logging.exception("[长视频规划师] /lvp/plan 未预期错误")   # 保留 traceback 便于服务端排查（客户端仅得摘要）
            return web.json_response({"error": f"规划失败：{e}"}, status=500)

    @routes.post("/lvp/plan/prompts")
    async def 提示词生成接口(request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "请求体不是合法 JSON"}, status=400)
        ok, err = _校验segments(body)
        if not ok:
            return web.json_response({"error": err}, status=400)
        覆盖 = _解析模型覆盖(body)   # pop 模型id → 按所选模型临时切换 opener（不写盘），同 /lvp/plan
        禁用字幕 = body.get("禁用字幕") is True
        opener = 造opener(覆盖) if 覆盖 else 默认opener
        try:
            loop = asyncio.get_running_loop()
            回执 = {}
            逐段状态 = {}
            结果 = await loop.run_in_executor(
                None, lambda: 生成提示词(
                    body.get("brief") if isinstance(body.get("brief"), dict) else {},
                    body["segments"], opener,
                    str(body.get("风格技能") or "不指定"), str(body.get("辅助风格") or "无"),
                    回执=回执, 状态=逐段状态, 禁用字幕=禁用字幕))
            响应 = {"segments": 结果}
            if 回执.get("知识库") is not None:        # A5：选了知识库时回显实际来源/截断/缺失
                响应["knowledge"] = 回执["知识库"]
            if 逐段状态:                              # A1：逐段提示词状态按 segment_id 映射返回（不整单掩盖）
                响应["promptStatus"] = 逐段状态
            return web.json_response(响应)
        except RuntimeError as e:
            payload, 状态 = _错误响应(e)   # 同 /lvp/plan：结构化错误定状态
            return web.json_response(payload, status=状态)
        except Exception as e:
            logging.exception("[长视频规划师] /lvp/plan/prompts 未预期错误")
            return web.json_response({"error": f"提示词生成失败：{e}"}, status=500)

    @routes.post("/lvp/plan/prompts/retry")
    async def 局部重试接口(request):
        # A2：局部重试——携带完整故事只读上下文 + 目标段清单，服务端仅改写目标段。
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "请求体不是合法 JSON"}, status=400)
        ok, err = _校验重试请求(body)
        if not ok:
            return web.json_response({"error": err}, status=400)
        覆盖 = _解析模型覆盖(body)   # 同 /lvp/plan/prompts：按所选模型临时切换 opener（不写盘）
        禁用字幕 = body.get("禁用字幕") is True
        opener = 造opener(覆盖) if 覆盖 else 默认opener
        try:
            loop = asyncio.get_running_loop()
            回执 = {}
            逐段状态 = {}
            结果 = await loop.run_in_executor(
                None, lambda: 局部重试(
                    body.get("brief") if isinstance(body.get("brief"), dict) else {},
                    body["segments"], body["目标段ids"], opener,
                    str(body.get("风格技能") or "不指定"), str(body.get("辅助风格") or "无"),
                    回执=回执, 状态=逐段状态, 禁用字幕=禁用字幕))
            响应 = {"segments": 结果}
            if 回执.get("知识库") is not None:
                响应["knowledge"] = 回执["知识库"]
            if 逐段状态:                              # A1：仅目标段的逐段状态
                响应["promptStatus"] = 逐段状态
            return web.json_response(响应)
        except ValueError as e:                     # 目标清单与 segment_id 不匹配 → 400（未发起网络）
            return web.json_response({"error": str(e)}, status=400)
        except RuntimeError as e:
            payload, 状态 = _错误响应(e)   # 同 /lvp/plan：结构化错误定状态
            return web.json_response(payload, status=状态)
        except Exception as e:
            logging.exception("[长视频规划师] /lvp/plan/prompts/retry 未预期错误")
            return web.json_response({"error": f"局部重试失败：{e}"}, status=500)

    @routes.get("/lvp/llm_config")
    async def 取配置接口(request):
        try:
            return web.json_response(取脱敏配置())
        except Exception as e:
            return web.json_response({"error": f"读配置失败：{e}"}, status=500)

    @routes.post("/lvp/llm_config")
    async def 写配置接口(request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "请求体不是合法 JSON"}, status=400)
        try:
            写配置(body if isinstance(body, dict) else {})
            return web.json_response(取脱敏配置())
        except OSError as e:
            return web.json_response({"error": f"写配置失败：{e}"}, status=500)

    @routes.post("/lvp/llm_test")
    async def 测连通接口(request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"ok": False, "error": "请求体不是合法 JSON"}, status=400)
        try:
            # 阻塞网络请求走 executor，不卡事件循环；结果永远 200+{ok,error} 供面板展示
            结果 = await asyncio.get_running_loop().run_in_executor(
                None, 测连通性, body if isinstance(body, dict) else {})
            return web.json_response(结果)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"测试失败：{e}"}, status=500)

    @routes.get("/lvp/plan_meta")
    async def 元信息接口(request):
        try:
            return web.json_response(_plan_meta())
        except Exception as e:
            return web.json_response({"error": f"元信息失败：{e}"}, status=500)

    _已注册 = True
