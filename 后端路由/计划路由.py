# -*- coding: utf-8 -*-
"""计划路由：/lvp/plan/* 提供「计划数据」的列表 / 加载 / 保存。

计划数据 = 用户把当前节点的全部 widget（任务类型/分辨率/百万像素/画风+预设拼接的全局
提示词/帧率/步数/采样器/调度器/参考共用/尾帧锚定/运行选择）+ 时间轴 JSON + 参考素材
清单打包保存，落盘为独立 JSON 文件，供下次一键加载直接运行。

存储位置：插件根/计划数据/<名>.json，与 预设/ 平级；文件由本路由按需创建目录（自愈语义
与 预设根()/媒体根() 一致）。

写盘并发不变量（与 媒体路由/段缓存 同源）：`<目标>.<pid>.<序号>.part` 唯一临时名 +
`os.replace` 原子改名，避免共用固定 .part 时两个写入者互相截断，也避开 Windows 因
临时文件被别写者占用而拒绝 replace（WinError 5）。

HTTP 边界错误契约（与 媒体路由/预设路由 同源）：参数错→400 JSON、资源不存在→404 JSON、
IO 失败→500 JSON；handler **不抛**未捕获异常（aiohttp 会吞成 text/plain，前端 resp.json()
读不到 message）。

参考素材缺失处理：加载时对照 媒体根() 过滤参考素材清单与每段 refs 里已不存在的文件名，
返回给前端「缺失素材」数组以 toast 提示，避免用户拿着指向已被删文件的计划点运行时才报错。
"""
import contextlib
import itertools
import json
import os
import re
import time

from aiohttp import web

_已注册 = False
_临时序号 = itertools.count()   # 与 媒体路由/段缓存 同源：并发写同名文件时生成互不干扰的 .part

_计划文件夹名 = "计划数据"
_计划后缀 = ".json"
# Windows/POSIX 都不允许的文件名字符 + 控制字符；换行/制表符也一并拒（防 UI 输入框粘贴多行）
_非法名字符 = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# Windows 保留设备名，即使加扩展名也不可用作文件名
_保留名 = {"CON", "PRN", "AUX", "NUL",
           *(f"COM{i}" for i in range(1, 10)),
           *(f"LPT{i}" for i in range(1, 10))}
_名最长 = 100   # 单条计划名的字符上限；配合插件根路径远低于 Windows MAX_PATH(260)


def 插件根() -> str:
    """插件根目录绝对路径（本文件位于 <根>/后端路由/计划路由.py）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def 计划根() -> str:
    """计划数据根目录：插件根/计划数据/，不存在则创建（与 预设根()/媒体根() 同款自愈语义）。"""
    root = os.path.join(插件根(), _计划文件夹名)
    os.makedirs(root, exist_ok=True)
    return root


def 安全名(名) -> str:
    """规范化计划名 → 可直接作文件名的净名；非法则返回空串（由调用方转 400）。

    拒绝：非字符串 / 空 / 首尾空白后为空 / 含路径分隔符或控制字符 / . 或 .. / Windows 保留名 /
    首尾为点或空格（Windows 会静默剥离，导致「A.」与「A」写同一文件）/ 超长。
    """
    if not isinstance(名, str):
        return ""
    净 = 名.strip()
    if not 净 or 净 in (".", ".."):
        return ""
    if _非法名字符.search(净):
        return ""
    if 净[0] in ". " or 净[-1] in ". ":
        return ""
    # 去扩展名后比对保留名（Windows 判定规则）
    主 = os.path.splitext(净)[0].upper()
    if 主 in _保留名:
        return ""
    if len(净) > _名最长:
        return ""
    return 净


def 扫描计划() -> list:
    """扫描 计划根 下顶层 .json 文件（不递归），按名字排序返回 [{名, 大小, 更新时间}]。

    .part 临时文件跳过（写入中断的孤儿）；单文件 stat 失败也跳过，不让整份清单 500。
    """
    root = 计划根()
    项: list = []
    try:
        条目 = sorted(os.listdir(root))
    except OSError:
        return 项
    for 文件 in 条目:
        if not 文件.lower().endswith(_计划后缀) or 文件.endswith(".part"):
            continue
        p = os.path.join(root, 文件)
        if not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        项.append({
            "名": os.path.splitext(文件)[0],
            "大小": st.st_size,
            "更新时间": int(st.st_mtime),
        })
    return 项


def _过滤段refs(段组, 池: set, 缺失: list):
    """逐段清洗 refs：
    - 字符串值（首帧/尾帧）不在池中 → 视为缺失，删该键并追加到缺失清单。
    - 数组值（段级素材 图片/音频/视频）→ 逐项过滤不存在的文件。
    - 其他值（如 共用 布尔标记）→ 原样保留。
    非 dict 的段原样透传（前端可能塞了脏数据，不阻断加载）。"""
    if not isinstance(段组, list):
        return 段组
    新段组 = []
    for 段 in 段组:
        if not isinstance(段, dict):
            新段组.append(段)
            continue
        refs = 段.get("refs")
        if not isinstance(refs, dict):
            新段组.append(段)
            continue
        新refs = {}
        for k, v in refs.items():
            if isinstance(v, str) and v and v not in 池:
                缺失.append(v)
            elif isinstance(v, list):
                # 段级素材数组（图片/音频/视频）：逐项过滤不存在的文件
                保 = []
                for 名 in v:
                    if isinstance(名, str) and 名:
                        if 名 in 池:
                            保.append(名)
                        else:
                            缺失.append(名)
                    else:
                        保.append(名)
                新refs[k] = 保
            else:
                新refs[k] = v
        新段组.append({**段, "refs": 新refs})
    return 新段组


def 过滤缺失素材(数据: dict) -> tuple:
    """对照 媒体根() 池过滤参考素材：不存在的文件从清单里剔除，同时清洗每段 refs（首帧/尾帧 + 段级素材数组）。

    返回 (清洗后的数据副本, 缺失文件名去重清单)。原数据不改（浅拷贝顶层 + 需要动的子字段）。
    媒体根 目录读取失败视为空池 → 所有素材都会被判为缺失；这是极端场景（input 目录不可用），
    此时插件本身也跑不了，让用户看到「全缺」比悄悄保留错误引用更安全。
    """
    from .媒体路由 import 媒体根   # 延迟 import 避免模块级循环（媒体路由 与本模块平级、互不依赖）
    try:
        池 = set(os.listdir(媒体根()))
    except OSError:
        池 = set()

    缺失: list = []
    新数据 = dict(数据)

    素材 = 数据.get("参考素材")
    if isinstance(素材, dict):
        新素材 = {}
        for 槽 in ("图片", "音频", "视频"):
            原 = 素材.get(槽)
            if not isinstance(原, list):
                新素材[槽] = []
                continue
            保 = []
            for 名 in 原:
                if isinstance(名, str) and 名:
                    if 名 in 池:
                        保.append(名)
                    else:
                        缺失.append(名)
            新素材[槽] = 保
        新数据["参考素材"] = 新素材

    时间轴 = 数据.get("时间轴")
    if isinstance(时间轴, dict) and isinstance(时间轴.get("segments"), list):
        新段组 = _过滤段refs(时间轴["segments"], 池, 缺失)
        新数据["时间轴"] = {**时间轴, "segments": 新段组}

    # 缺失清单去重保序（同名文件被多段引用时只 toast 一次）
    见 = set()
    去重 = []
    for 名 in 缺失:
        if 名 not in 见:
            见.add(名)
            去重.append(名)
    return 新数据, 去重


def _读创建时间(路径: str) -> str:
    """尝试从已存在的计划文件里读出 创建时间 字段，覆盖保存时保留原值；读失败/无字段返回空串。"""
    try:
        with open(路径, "r", encoding="utf-8") as f:
            旧 = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    if isinstance(旧, dict):
        v = 旧.get("创建时间")
        if isinstance(v, str):
            return v
    return ""


def 注册路由():
    """幂等注册 aiohttp 路由（供 __init__.py 调用）。"""
    global _已注册
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes

    @routes.get("/lvp/plan/list")
    async def 计划列表(request):
        """返回 [{名, 大小, 更新时间}]，按名排序。目录级 IO 失败 → 500 JSON {error}。"""
        try:
            计划 = 扫描计划()
        except OSError as e:
            return web.json_response({"error": f"计划目录读取失败：{e}"}, status=500)
        return web.json_response({"计划": 计划})

    @routes.get("/lvp/plan/load")
    async def 计划加载(request):
        """按名读取计划 JSON；服务端过滤已缺失的参考素材；返回 {数据, 缺失素材}。

        400: 名字非法；404: 计划不存在；500: 读盘/JSON 解析/结构非法。
        """
        名 = 安全名(request.query.get("name", ""))
        if not 名:
            return web.json_response({"error": "计划名非法"}, status=400)
        p = os.path.join(计划根(), 名 + _计划后缀)
        if not os.path.isfile(p):
            return web.json_response({"error": f"计划不存在：{名}"}, status=404)
        try:
            with open(p, "r", encoding="utf-8") as f:
                文件 = json.load(f)
        except OSError as e:
            return web.json_response({"error": f"计划读取失败：{e}"}, status=500)
        except json.JSONDecodeError as e:
            return web.json_response({"error": f"计划文件非法 JSON：{e}"}, status=500)
        if not isinstance(文件, dict):
            return web.json_response({"error": "计划文件顶层必须是对象"}, status=500)
        数据 = 文件.get("数据")
        if not isinstance(数据, dict):
            return web.json_response({"error": "计划文件缺 数据 字段或其非对象"}, status=500)
        try:
            清洗, 缺失 = 过滤缺失素材(数据)
        except OSError as e:
            # 媒体根 不可读时 过滤缺失素材 已内部兜底为空池，这里再兜一层保险
            return web.json_response({"error": f"参考素材目录读取失败：{e}"}, status=500)
        return web.json_response({"数据": 清洗, "缺失素材": 缺失})

    @routes.post("/lvp/plan/save")
    async def 计划保存(request):
        """保存计划：请求体 {名, 数据}；覆盖已存在计划时保留原 创建时间。

        400: 请求体非法 JSON / 名非法 / 数据非对象；500: 写盘失败。
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as e:
            return web.json_response({"error": f"请求体非法 JSON：{e}"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "请求体必须是对象"}, status=400)
        名 = 安全名(body.get("名"))
        if not 名:
            return web.json_response(
                {"error": f"计划名非法（不能为空、不能含 \\ / : * ? \" < > | 或控制字符、"
                          f"不能是 . / .. / Windows 保留名、长度 ≤ {_名最长}）"},
                status=400,
            )
        数据 = body.get("数据")
        if not isinstance(数据, dict):
            return web.json_response({"error": "数据 字段必须是对象"}, status=400)

        目标 = os.path.join(计划根(), 名 + _计划后缀)
        现在 = time.strftime("%Y-%m-%dT%H:%M:%S")
        创建时间 = _读创建时间(目标) or 现在   # 覆盖保存时保留原创建时间；新计划=现在
        文件 = {"版本": 1, "创建时间": 创建时间, "更新时间": 现在, "数据": 数据}

        临时 = f"{目标}.{os.getpid()}.{next(_临时序号)}.part"
        已落盘 = False
        try:
            with open(临时, "w", encoding="utf-8") as f:
                json.dump(文件, f, ensure_ascii=False, indent=2)
            os.replace(临时, 目标)
            已落盘 = True
        except OSError as e:
            return web.json_response({"error": f"计划写入失败：{e}"}, status=500)
        except (TypeError, ValueError) as e:
            # json.dump 遇不可序列化对象（理论上 数据 已由前端 JSON 传过来，都是可序列化的）
            return web.json_response({"error": f"计划数据不可序列化：{e}"}, status=400)
        finally:
            if not 已落盘:
                with contextlib.suppress(OSError):
                    os.remove(临时)
        return web.json_response({"名": 名, "创建时间": 创建时间, "更新时间": 现在})

    _已注册 = True
