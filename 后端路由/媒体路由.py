# -*- coding: utf-8 -*-
"""媒体路由：/h3dyt/media/* 提供文件列表 / 上传 / 去重（文件名+size）。

并发不变量（与 执行/段缓存.py 同源）：写盘用 `<目标>.<pid>.<序号>.part` 唯一临时名 +
`os.replace` 原子改名；共用固定 `.part` 会让两个写入者交替写同一临时文件互相截断，
或被 Windows 的 replace 因文件被别写者占用而拒绝（WinError 5）。失败/中断路径由
`finally` 统一清理临时，孤儿 `.part` 由 媒体列表 的 endswith 过滤兜掉。

HTTP 边界错误契约：参数/Content-Type/multipart 语法错一律 4xx JSON（前端能读到 message），
IO 失败 5xx JSON。此处**不套** Task 11 UI 边界的 ValueError-only 契约——那是节点执行链
的约定；aiohttp handler 抛未捕获异常会被吞成通用 500 text/plain，前端 `resp.json()` 直接抛。

非 multipart 拦截不能仅靠 `except ValueError`：aiohttp 3.13 内部 `MultipartReader.__init__`
对非 multipart Content-Type 抛 AssertionError、对缺失 Content-Type 抛 KeyError，异常类型
因版本而异。入口靠 `request.content_type` 属性前置拦截（HeadersMixin，缺失时按 RFC 2616
回退 `application/octet-stream`，不抛 KeyError），不依赖 aiohttp 版本内部实现。"""
import contextlib
import hashlib
import itertools
import os

from aiohttp import web

_已注册 = False
_临时序号 = itertools.count()  # 与 段缓存 同源：并发写同名文件时生成互不干扰的 .part


def 去重键(文件名: str, 大小: int) -> str:
    """文件名+大小 → 16 位稳定哈希（去重判定）。"""
    return hashlib.sha256(f"{文件名}|{大小}".encode("utf-8")).hexdigest()[:16]


def 媒体根() -> str:
    """参考素材根目录：ComfyUI 输入目录下的 h3导演台_媒体/（用户上传的参考图/音/视频）。
    公开函数，供 节点/导演台.py 与 执行/执行核心.py 解析文件名。"""
    import folder_paths
    root = os.path.join(folder_paths.get_input_directory(), "h3导演台_媒体")
    os.makedirs(root, exist_ok=True)
    return root


def 注册路由():
    """幂等注册 aiohttp 路由（供 __init__.py 调用）。"""
    global _已注册
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes

    @routes.get("/h3dyt/media/list")
    async def 媒体列表(request):
        root = 媒体根()
        项 = []
        for 名 in sorted(os.listdir(root)):
            p = os.path.join(root, 名)
            if os.path.isfile(p) and not 名.endswith(".part"):
                大小 = os.path.getsize(p)
                项.append({"name": 名, "size": 大小, "key": 去重键(名, 大小)})
        return web.json_response({"items": 项})

    @routes.post("/h3dyt/media/upload")
    async def 媒体上传(request):
        """流式落盘 + 原子改名；参数/Content-Type/multipart 语法错→415/400，IO 失败→500。

        本 handler **不抛**未捕获异常（走 500 text/plain 前端无 message）：所有 aiohttp 侧
        可能报错的 await 集中到一个 try，异常元组 (ValueError,AssertionError,KeyError) 接
        构造期与解析期各类边界（缺 boundary / 找不到起始边界 / 非 multipart CT / CT 缺失），
        OSError 接 磁盘满/权限/Windows replace 独占失败。"""
        # 前置 Content-Type 判定（`request.content_type` 不抛，缺失时 RFC 2616 回退
        # `application/octet-stream`）。
        if not request.content_type.startswith("multipart/"):
            return web.json_response(
                {"error": f"需要 multipart/form-data，收到 {request.content_type}"},
                status=415,
            )
        名 = ""
        大小 = 0
        临时 = None
        目标 = None
        已落盘 = False
        try:
            reader = await request.multipart()
            field = await reader.next()
            if field is None:                        # 空 body：无文件字段
                return web.json_response({"error": "媒体上传缺少 multipart 文件字段"}, status=400)
            root = 媒体根()                          # 目录创建失败（OSError）一并接住
            # basename 二次兜底：客户端传 "foo/" 时首层 basename 会返回 ""
            名 = os.path.basename(field.filename or "") or "upload.bin"
            目标 = os.path.join(root, 名)
            临时 = f"{目标}.{os.getpid()}.{next(_临时序号)}.part"
            with open(临时, "wb") as f:               # 流式写盘，兼容大视频
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    大小 += len(chunk)
                    f.write(chunk)
            if os.path.exists(目标) and os.path.getsize(目标) == 大小:
                # 去重命中：不进 replace，直接 return；finally 会清 临时（因 已落盘 仍 False）
                return web.json_response({"name": 名, "dedup": True, "key": 去重键(名, 大小)})
            os.replace(临时, 目标)
            已落盘 = True
        except (ValueError, AssertionError, KeyError) as e:  # multipart 构造/解析各类形态
            return web.json_response({"error": f"multipart 解析失败：{e}"}, status=415)
        except OSError as e:                         # 磁盘满/权限/Windows 独占失败等
            return web.json_response({"error": f"媒体写入失败：{e}"}, status=500)
        finally:
            if 临时 is not None and not 已落盘:          # 含中断/异常/去重命中/KeyboardInterrupt
                with contextlib.suppress(OSError):
                    os.remove(临时)
        return web.json_response({"name": 名, "dedup": False, "key": 去重键(名, 大小)})

    @routes.get("/h3dyt/media/file")
    async def 媒体文件(request):
        """按名回传媒体文件（供前端缩略图/预览）；basename 防目录穿越。"""
        名 = os.path.basename(request.query.get("name", ""))
        p = os.path.join(媒体根(), 名)
        if not 名 or not os.path.isfile(p):
            return web.Response(status=404, text="not found")
        return web.FileResponse(p)

    _已注册 = True
