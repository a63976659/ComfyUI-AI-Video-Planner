import json
import logging
from functools import wraps

from aiohttp import web

if "." in __package__:
    from ..执行.跨任务清理 import 交接错误
else:
    from 执行.跨任务清理 import 交接错误


_已注册 = False
_最大请求字节 = 8 * 1024 * 1024


def _协调器():
    if "." in __package__:
        from ..执行.跨任务清理 import 取得协调器
    else:
        from 执行.跨任务清理 import 取得协调器
    return 取得协调器()


def _响应(value, status=200):
    return web.json_response(value, status=status, headers={"Cache-Control": "no-store"})


def _边界(handler):
    @wraps(handler)
    async def wrapped(request):
        try:
            if request.query:
                raise web.HTTPBadRequest()
            if request.headers.get("X-LVP-Handoff") != "1":
                raise web.HTTPForbidden()
            return _响应(await handler(request))
        except web.HTTPRequestEntityTooLarge:
            return _响应({"error": "交接请求超过大小限制"}, 413)
        except web.HTTPBadRequest:
            return _响应({"error": "交接请求字段或 JSON 格式不合法"}, 400)
        except (web.HTTPForbidden, PermissionError):
            return _响应({"error": "当前用户或控制能力无权操作此交接任务"}, 403)
        except 交接错误 as exc:
            return _响应({"error": str(exc), "code": exc.code}, exc.status_code)
        except ValueError:
            return _响应({"error": "交接请求被拒绝，请检查图边界、任务版本与队列状态"}, 409)
        except Exception:
            logging.exception("[长视频规划师] 交接路由未预期错误")   # 客户端只拿通用摘要，服务端必须留 traceback
            return _响应({"error": "交接操作失败，任务未被当作成功处理"}, 500)
    return wrapped


def _所有者(request):
    from server import PromptServer
    try:
        return PromptServer.instance.user_manager.get_request_user_id(request)
    except KeyError:
        raise web.HTTPForbidden() from None


def _能力(request):
    value = request.headers.get("X-LVP-Capability", "")
    if not value or len(value) > 256:
        raise web.HTTPForbidden()
    return value


async def _请求(request, required, optional=()):
    if request.content_type != "application/json":
        raise web.HTTPBadRequest()
    if request.content_length is not None and request.content_length > _最大请求字节:
        raise web.HTTPRequestEntityTooLarge(max_size=_最大请求字节, actual_size=request.content_length)
    body = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        body.extend(chunk)
        if len(body) > _最大请求字节:
            raise web.HTTPRequestEntityTooLarge(max_size=_最大请求字节, actual_size=len(body))
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise web.HTTPBadRequest() from None
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise web.HTTPBadRequest()
    for field in ("client_id", "request_id"):
        if field in value and (type(value[field]) is not str or not value[field].strip() or len(value[field]) > 256):
            raise web.HTTPBadRequest()
    for field in ("output", "workflow", "options"):
        if field in value and type(value[field]) is not dict:
            raise web.HTTPBadRequest()
    return value


def 注册路由():
    global _已注册
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes

    @routes.post("/lvp/handoff/submit")
    @_边界
    async def 提交(request):
        owner = _所有者(request)
        data = await _请求(request, ("output", "workflow", "client_id", "request_id"), ("options",))
        return await _协调器().提交交接任务(
            data["output"], data["workflow"], owner=owner, client_id=data["client_id"],
            request_id=data["request_id"], options=data.get("options"))

    @routes.get("/lvp/handoff/status/{job_id}")
    @_边界
    async def 状态(request):
        owner, capability = _所有者(request), _能力(request)
        return _协调器().取交接状态(request.match_info["job_id"], owner=owner, capability=capability)

    _已注册 = True
