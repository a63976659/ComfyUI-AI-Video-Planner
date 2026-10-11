# -*- coding: utf-8 -*-
"""H3 规划路由：aiohttp 薄壳 handler + 可脱离 PromptServer 的纯函数。

handler 委托纯逻辑（规划器.规划 + 配置.默认opener）；HTTP 域不抛未捕获异常，
一律 web.json_response({error}, status)；阻塞 LLM 调用走 run_in_executor。
设计依据：文档/规格/2026-09-10-H3规划器-设计.md §7.3 + §13。
"""
import asyncio
import json
import logging
import os
import threading
from math import ceil

from aiohttp import web

try:                                        # ComfyUI 运行时（以包形式加载）
    from ..规划.规划器 import 规划
    from ..规划.配置 import 默认opener, 造opener, 读配置, 取脱敏配置, 写配置, 测连通性, LLM错误
    from ..规划.方法论 import PLATFORM_HINTS, HOOK_TYPES, ROLE_COLORS
    from ..规划.知识库 import 风格选项, 辅助风格选项, 技能选项, 通用改写技能, 规范改写技能
    from ..规划.提示词生成 import 分批生成提示词, 目标索引
    from ..规划.改写请求 import 造改写opener, 每批耗时上限, 单次请求上限
    from .规划任务路由 import 注册规划任务路由
except ImportError:                         # pytest（插件根在 sys.path，`..` 越界）
    from 规划.规划器 import 规划
    from 规划.配置 import 默认opener, 造opener, 读配置, 取脱敏配置, 写配置, 测连通性, LLM错误
    from 规划.方法论 import PLATFORM_HINTS, HOOK_TYPES, ROLE_COLORS
    from 规划.知识库 import 风格选项, 辅助风格选项, 技能选项, 通用改写技能, 规范改写技能
    from 规划.提示词生成 import 分批生成提示词, 目标索引
    from 规划.改写请求 import 造改写opener, 每批耗时上限, 单次请求上限
    from 后端路由.规划任务路由 import 注册规划任务路由

_已注册 = False
_任务码 = ["t2v", "i2v", "fl2v", "r2v", "v2v", "rv2v"]
_素材类型 = ("图像", "视频", "音频", "文本")     # 前端镜像：网页资源/组件/规划素材区.js 素材类型枚举（Task 9 常量同步锁）
# 媒体名安全阀：拒绝 Windows 保留设备名（含带扩展名形态如 CON.txt）；文本素材按名直拼 open，防读到设备流/意外行为。
_WIN保留名 = frozenset(
    ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]
)
_详细内容上限 = 20000
_素材条目上限 = 40
_总时长上限 = 3600
_后台任务 = set()               # 持有 SSE worker future 引用，防事件循环侧提前 GC


def _校验brief(body):
    """纯函数：校验 brief。返回 (ok: bool, err: str|None)。可脱离 PromptServer 单测。
    素材/详细内容 为可选新键（设计 2026-09-29 §5.1）：缺省＝不校验，旧请求体行为逐字节不变。"""
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
    详细 = body.get("详细内容")
    if 详细 is not None and (not isinstance(详细, str) or len(详细) > _详细内容上限):
        return False, f"详细内容须为不超过 {_详细内容上限} 字的字符串"
    素材 = body.get("素材")
    if 素材 is not None:
        if not isinstance(素材, list) or len(素材) > _素材条目上限:
            return False, f"素材须为不超过 {_素材条目上限} 项的数组"
        for m in 素材:
            if not isinstance(m, dict):
                return False, "素材项必须是对象"
            原名 = m.get("名")
            if not isinstance(原名, str) or not 原名:
                return False, "素材名须为非空字符串"
            if 原名 != os.path.basename(原名) or any(c in '/\\:<>"|?*' or ord(c) < 32 for c in 原名):
                return False, "素材名不合法（须为媒体文件名，禁路径分隔符/盘符/备用流/控制字符）"
            if 原名.split(".", 1)[0].upper() in _WIN保留名:
                return False, "素材名为 Windows 保留设备名"
            if m.get("类型") not in _素材类型:
                return False, f"素材类型须为 {'/'.join(_素材类型)}"
    return True, None


def _校验segments(body):
    """纯函数：校验提示词生成请求体。返回 (ok, err)。segments 必须为非空段对象数组。"""
    if not isinstance(body, dict):
        return False, "请求体必须是对象"
    segs = body.get("segments")
    if not isinstance(segs, list) or not segs or not all(isinstance(s, dict) for s in segs):
        return False, "segments 必须是非空段对象数组"
    return True, None


def _校验流式请求(body):
    """纯函数：流式提示词请求体校验。segments 必填（同 _校验segments）；
    目标段ids 可选（给了则非空字符串数组，缺省＝全段为目标）；批大小 可选（1..20 整数）。"""
    ok, err = _校验segments(body)
    if not ok:
        return ok, err
    try:
        规范改写技能(body.get("风格技能"))
    except ValueError as e:
        return False, str(e)
    ids = body.get("目标段ids")
    if ids is not None and (not isinstance(ids, list) or not ids
                            or not all(isinstance(x, str) and x.strip() for x in ids)):
        return False, "目标段ids 给了就必须是非空字符串数组"
    批 = body.get("批大小")
    if 批 is not None and (isinstance(批, bool) or not isinstance(批, int) or not (1 <= 批 <= 20)):
        return False, "批大小须为 1..20 的整数"
    资料 = body.get("改写资料")
    if 资料 is not None:
        if not isinstance(资料, dict):
            return False, "改写资料须为对象"
        for key in ("制作", "规划资料", "执行参考", "素材理解"):
            if key in 资料 and not isinstance(资料[key], dict):
                return False, f"改写资料的{key}须为对象"
        if "素材" in 资料 and not isinstance(资料["素材"], list):
            return False, "改写资料的素材须为数组"
        if "执行提示词" in 资料 and not isinstance(资料["执行提示词"], str):
            return False, "改写资料的执行提示词须为字符串"
        制作 = 资料.get("制作", {})
        if "实体" in 制作 and (not isinstance(制作["实体"], list) or not all(isinstance(e, dict) for e in 制作["实体"])):
            return False, "改写资料的制作实体须为对象数组"
        if "镜头" in 制作 and (not isinstance(制作["镜头"], dict) or not all(isinstance(s, dict) for s in 制作["镜头"].values())):
            return False, "改写资料的制作镜头须为对象映射"
    return True, None


def _sse(名, 载荷) -> bytes:
    """纯函数：一帧 SSE（event 名 + 单行 JSON data + 空行分隔；中文不转义）。"""
    return f"event: {名}\ndata: {json.dumps(载荷, ensure_ascii=False)}\n\n".encode("utf-8")


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


def _解析模型覆盖(body, 用途="planning"):
    """纯函数：pop body['模型id'] → 在配置盘 api_models 按 id 命中返回 {base_url,model,api_key}；
    未带时读取指定用途的已保存选择；未选择或未命中 → None（回落配置盘默认模型）。
    命中条 api_key 空串＝该模型确无 Key（opener 不加 Authorization）。
    pop 副作用保证 模型id 不入 规划(brief) 的提示词构建。"""
    cfg = 读配置()
    mid = str((body or {}).pop("模型id", "") or "").strip()
    if not mid:
        mid = (cfg.get("ai_model_selections") or {}).get(用途, "")
    if not mid:
        return None
    for e in cfg.get("api_models") or []:
        if e.get("id") == mid:
            return {"base_url": e.get("base_url", ""), "model": e.get("model", ""),
                    "api_key": e.get("api_key", "")}
    return None


def _错误响应(e):
    """纯函数：异常 → (响应体, HTTP 状态)。LLM错误 携结构化的 可重试/请求ID/状态码，
    路由不再靠中文异常子串判定 HTTP 状态（B4）；其余 RuntimeError → 500（统一 {error} 结构）。"""
    if isinstance(e, LLM错误):
        return {"error": str(e), "retryable": e.可重试, "requestId": e.请求ID, "category": e.类别}, e.状态码
    return {"error": str(e)}, 500


def 注册路由():
    global _已注册
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes

    注册规划任务路由(routes, _解析模型覆盖, app=getattr(PromptServer.instance, "app", None))
    from .专项配置路由 import 注册专项配置路由
    注册专项配置路由(routes)

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

    @routes.post("/lvp/prompt/optimize")
    async def 编辑提示词优化接口(request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "请求体不是合法 JSON"}, status=400)
        ok, err = _校验流式请求(body)
        if not ok or len(body["segments"]) != 1:
            return web.json_response({"error": err or "提示词优化只接受当前一段"}, status=400)
        if not str(body["segments"][0].get("prompt") or "").strip():
            return web.json_response({"error": "请先填写当前段提示词"}, status=400)
        覆盖 = _解析模型覆盖(body, "editor")
        停止 = threading.Event()

        def worker():
            return 分批生成提示词(
                body.get("brief") if isinstance(body.get("brief"), dict) else {},
                body["segments"], 造改写opener(覆盖, 停止=停止.is_set),
                批大小=1, 技能=通用改写技能, 资料=body.get("改写资料"),
                禁用字幕=body.get("禁用字幕") is True, 停止=停止.is_set)

        任务 = asyncio.get_running_loop().run_in_executor(None, worker)
        _后台任务.add(任务)
        任务.add_done_callback(_后台任务.discard)
        try:
            result = await asyncio.shield(任务)
            seg = result["segments"][0]
            report = seg.get("提示词生成") or {}
            if report.get("完成") is not True:
                return web.json_response({"error": "；".join(report.get("问题") or ["提示词生成失败，已保留原文"])}, status=422)
            return web.json_response({"prompt": seg["prompt"], "提示词生成": report, "调用": result["调用"]})
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except RuntimeError as e:
            payload, status = _错误响应(e)
            return web.json_response(payload, status=status)
        except Exception as e:
            logging.exception("[长视频规划师] 提示词优化未预期错误")
            return web.json_response({"error": f"提示词优化失败：{e}"}, status=500)
        finally:
            停止.set()

    @routes.post("/lvp/plan/prompts/stream")
    async def 提示词流式接口(request):
        """A6 分批流式：每批一条 SSE batch 事件（含段副本与逐段状态），结尾 done/fatal。
        worker 在 executor 线程串行发 LLM 调用，经 call_soon_threadsafe 投 asyncio.Queue；
        客户端断开（写失败/取消）→ 停止置位，下一批不再发起。事件序：meta → batch×N → done | fatal。
        两条兜底：① worker 一律以终止帧收尾（含 BaseException 逃逸），否则消费侧 while 永挂连接；
        ② prepare 起全程在 try 内，任何早退都走 finally 置停，不留无人听的整单 LLM 调用。"""
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "请求体不是合法 JSON"}, status=400)
        ok, err = _校验流式请求(body)
        if not ok:
            return web.json_response({"error": err}, status=400)
        覆盖 = _解析模型覆盖(body, "timeline")
        禁用字幕 = body.get("禁用字幕") is True
        批大小 = 1  # 旧请求参数仍校验，实际逐段执行
        目标段数 = len(目标索引(body["segments"], body.get("目标段ids")))
        总批数 = max(1, ceil(目标段数 / 批大小))   # 与 分批生成提示词 同走 目标索引，未知/重复 id 不再把分母撑大
        loop = asyncio.get_running_loop()
        队列: asyncio.Queue = asyncio.Queue()
        停止 = threading.Event()

        def worker():
            逐段状态 = {}
            请求数 = 0
            当前进度 = {"阶段": "改写提示词", "批次": 1, "总批数": 总批数, "修复轮次": 0}

            def 发(项):
                loop.call_soon_threadsafe(队列.put_nowait, 项)

            def 回调(k, 段批, 批状态):
                发(("batch", {"index": k, "segments": 段批, "promptStatus": 批状态}))
                当前进度["批次"] = k + 2

            def 阶段进度(p):
                当前进度.update(p)
                发(("progress", {**当前进度, "调用": 请求数}))

            def 真实请求():
                nonlocal 请求数
                请求数 += 1
                发(("progress", {**当前进度, "调用": 请求数}))

            try:
                opener = 造改写opener(覆盖, 请求回调=真实请求, 停止=停止.is_set)
                结果 = 分批生成提示词(
                    body.get("brief") if isinstance(body.get("brief"), dict) else {},
                    body["segments"], opener,
                    目标ids=body.get("目标段ids"), 批大小=批大小,
                    技能=通用改写技能,
                    状态=逐段状态, 禁用字幕=禁用字幕,
                    每批回调=回调, 停止=停止.is_set,
                    资料=body.get("改写资料"), 进度=阶段进度)
            except BaseException as e:   # 含 每批回调/编排逃逸：必须补一帧终止，队列消费侧才能收尾
                logging.exception("[长视频规划师] 提示词时间轴失败 requestId=%s category=%s", getattr(e, "请求ID", ""), getattr(e, "类别", "unknown"))
                载荷, _码 = _错误响应(e) if isinstance(e, RuntimeError) else ({"error": str(e)}, 500)
                发(("fatal", 载荷))
                return
            发(("done", {"promptStatus": 逐段状态, "degraded": 结果["降级"],
                         "stopped": 停止.is_set(), "调用": 请求数}))

        任务 = loop.run_in_executor(None, worker)
        _后台任务.add(任务)
        任务.add_done_callback(_后台任务.discard)

        resp = web.StreamResponse(status=200, headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"})
        try:
            await resp.prepare(request)
            await resp.write(_sse("meta", {"总批数": 总批数, "批大小": 批大小,
                                          "每批调用上限": 1, "每批秒数上限": 每批耗时上限}))
            截止 = loop.time() + 总批数 * 每批耗时上限 + 单次请求上限 + 15
            while True:
                transport = getattr(request, "transport", None)
                if transport is not None and transport.is_closing():
                    break
                if loop.time() >= 截止:
                    await resp.write(_sse("fatal", {"error": "提示词改写已达任务耗时上限，自动停止；已有完成段保留。"}))
                    break
                try:
                    名, 载荷 = await asyncio.wait_for(队列.get(), timeout=2)
                except asyncio.TimeoutError:
                    await resp.write(_sse("heartbeat", {}))
                    continue
                await resp.write(_sse(名, 载荷))
                if 名 in ("fatal", "done"):
                    break
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass                       # 客户端断开：不再读队列，finally 里置停
        finally:
            停止.set()
        return resp

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
