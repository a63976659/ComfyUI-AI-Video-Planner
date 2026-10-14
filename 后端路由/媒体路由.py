# -*- coding: utf-8 -*-
"""媒体路由：/lvp/media/* 提供文件列表 / 上传 / 内容摘要去重（流式 sha256）。

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
import asyncio
import hashlib
import itertools
import os

from aiohttp import web

_已注册 = False
_临时序号 = itertools.count()  # 与 段缓存 同源：并发写同名文件时生成互不干扰的 .part


def 去重键(文件名: str, 大小: int) -> str:
    """文件名+大小 → 16 位稳定哈希（媒体列表的展示/前端轻量指纹）。

    ⚠️ 这是列表用的廉价指纹，**不是**上传去重判定依据。上传去重已改用
    内容摘要（见下 A5），因为「文件名+大小」会把同名等长异内容误判为重复。"""
    return hashlib.sha256(f"{文件名}|{大小}".encode("utf-8")).hexdigest()[:16]


def 内容摘要(路径: str) -> str:
    """流式读文件算 sha256 前 16 位（内容摘要）。分块读，不把大视频整个进内存。"""
    h = hashlib.sha256()
    with open(路径, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def 带后缀名(名: str, 摘要: str, 次: int = 1) -> str:
    """给原文件名插入内容摘要后缀（保留扩展名）：cat.png + abcd..→ cat.abcdef01.png；
    同摘要后缀再冲突时追加序号：cat.abcdef01.2.png。摘要前 8 位足以区分（碰撞时代码内再递增）。"""
    stem, ext = os.path.splitext(名)
    盐 = 摘要[:8] if 次 <= 1 else f"{摘要[:8]}.{次}"
    return f"{stem}.{盐}{ext}"


def 计划落盘名(根: str, 名: str, 上传摘要: str) -> tuple:
    """上传落盘命名决策（纯逻辑，不写盘）：返回 (最终文件名, 是否命中去重)。

    规则（A5：同名同内容复用、同名异内容不静默覆盖）：
      - 根下无同名 → (名, False)：直接落原名为新文件。
      - 同名已存且内容摘要相同 → (名, True)：复用，不重写。
      - 同名已存但内容不同 → 派生 带后缀名；若该后缀名已存且内容相同也复用，
        否则递增序号找一个空闲名落新文件。（绝不把异内容 os.replace 到原同名文件上）。
    读现存文件的摘要属文件 IO，失败按 OSError 上抛，由 handler 接成 500。"""
    目标 = os.path.join(根, 名)
    if not os.path.exists(目标):
        return (名, False)
    if 内容摘要(目标) == 上传摘要:
        return (名, True)
    次 = 1
    while True:
        候选名 = 带后缀名(名, 上传摘要, 次)
        候选 = os.path.join(根, 候选名)
        if not os.path.exists(候选):
            return (候选名, False)
        if 内容摘要(候选) == 上传摘要:
            return (候选名, True)
        次 += 1


def 媒体根() -> str:
    """参考素材根目录：ComfyUI 输入目录下的 长视频规划师_媒体/（用户上传的参考图/音/视频）。
    公开函数，供 节点/长视频规划师.py 与 执行/执行核心.py 解析文件名。"""
    import folder_paths
    root = os.path.join(folder_paths.get_input_directory(), "长视频规划师_媒体")
    os.makedirs(root, exist_ok=True)
    return root


def 参考标签列表(refs, root):
    try:
        from ..执行.参考素材 import 解析槽位, 探测参考音轨, 参考标签槽位, 视频音频模式
    except ImportError:
        from 执行.参考素材 import 解析槽位, 探测参考音轨, 参考标签槽位, 视频音频模式
    slots = 解析槽位(refs)
    for name in slots["视频"]:
        path = os.path.realpath(os.path.join(root, name))
        if os.path.commonpath([os.path.realpath(root), path]) != os.path.realpath(root):
            raise ValueError("参考视频必须位于媒体目录内")
    flags = 探测参考音轨(slots, root)
    result = 参考标签槽位(slots, flags)
    count = sum(flags)
    suffix = "（视频音轨）" if 视频音频模式(refs) == "默认" else "（视频音轨，已禁用参考）"
    result["音频"] = [name + suffix if i < count else name
                      for i, name in enumerate(result["音频"])]
    return result


def 注册路由():
    """幂等注册 aiohttp 路由（供 __init__.py 调用）。"""
    global _已注册
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes

    @routes.post("/lvp/media/reference_labels")
    async def 参考标签(request):
        try:
            refs = await request.json()
            result = await asyncio.to_thread(参考标签列表, refs, 媒体根())
            return web.json_response(result)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except OSError as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @routes.get("/lvp/media/list")
    async def 媒体列表(request):
        root = 媒体根()
        项 = []
        for 名 in sorted(os.listdir(root)):
            p = os.path.join(root, 名)
            if os.path.isfile(p) and not 名.endswith(".part"):
                大小 = os.path.getsize(p)
                项.append({"name": 名, "size": 大小, "key": 去重键(名, 大小)})
        return web.json_response({"items": 项})

    @routes.post("/lvp/media/upload")
    async def 媒体上传(request):
        """流式落盘 + 原子改名；参数/Content-Type/multipart 语法错→415/400，IO 失败→500。

        本 handler **不抛**未捕获异常（走 500 text/plain 前端无 message）：所有 aiohttp 侧
        可能报错的 await 集中到一个 try，异常元组 (ValueError,AssertionError,KeyError) 接
        构造期与解析期各类边界（缺 boundary / 找不到起始边界 / 非 multipart CT / CT 缺失），
        OSError 接 磁盘满/权限/Windows replace 独占失败。

        ⚠️ 响应 `key` 语义：本接口＝**内容摘要**（sha256[:16]，A5 去重判据）；
        `/lvp/media/list` 的 `key`＝去重键(名+大小) 廉价指纹——同名不同义，消费方勿混用。"""
        # 前置 Content-Type 判定（`request.content_type` 不抛，缺失时 RFC 2616 回退
        # `application/octet-stream`）。
        if not request.content_type.startswith("multipart/"):
            return web.json_response(
                {"error": f"需要 multipart/form-data，收到 {request.content_type}"},
                status=415,
            )
        名 = ""
        临时 = None
        已落盘 = False
        try:
            reader = await request.multipart()
            field = await reader.next()
            if field is None:                        # 空 body：无文件字段
                return web.json_response({"error": "媒体上传缺少 multipart 文件字段"}, status=400)
            root = 媒体根()                          # 目录创建失败（OSError）一并接住
            # basename 二次兜底：客户端传 "foo/" 时首层 basename 会返回 ""
            名 = os.path.basename(field.filename or "") or "upload.bin"
            临时 = f"{os.path.join(root, 名)}.{os.getpid()}.{next(_临时序号)}.part"
            哈希器 = hashlib.sha256()               # A5：边写盘边算内容摘要（流式，兼容大视频）
            with open(临时, "wb") as f:               # 流式写盘，兼容大视频
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)
                    哈希器.update(chunk)
            上传摘要 = 哈希器.hexdigest()[:16]
            # 内容摘要决定落盘名：同名同内容→复用不重写；同名异内容→摘要后缀新名，绝不静默覆盖
            最终名, 命中 = 计划落盘名(root, 名, 上传摘要)
            if 命中:
                # 不进 replace；finally 清 临时（已落盘 仍 False），盘上既有文件保持不动
                return web.json_response({"name": 最终名, "dedup": True, "key": 上传摘要})
            os.replace(临时, os.path.join(root, 最终名))
            已落盘 = True
        except (ValueError, AssertionError, KeyError) as e:  # multipart 构造/解析各类形态
            return web.json_response({"error": f"multipart 解析失败：{e}"}, status=415)
        except OSError as e:                         # 磁盘满/权限/Windows 独占失败等
            return web.json_response({"error": f"媒体写入失败：{e}"}, status=500)
        finally:
            if 临时 is not None and not 已落盘:          # 含中断/异常/去重命中/KeyboardInterrupt
                with contextlib.suppress(OSError):
                    os.remove(临时)
        return web.json_response({"name": 最终名, "dedup": False, "key": 上传摘要})

    @routes.get("/lvp/media/file")
    async def 媒体文件(request):
        """按名回传媒体文件（供前端缩略图/预览）；basename 防目录穿越。"""
        名 = os.path.basename(request.query.get("name", ""))
        p = os.path.join(媒体根(), 名)
        if not 名 or not os.path.isfile(p):
            return web.Response(status=404, text="not found")
        return web.FileResponse(p)

    _已注册 = True
