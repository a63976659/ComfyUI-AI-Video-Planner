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

参考素材缺失处理（A6）：加载时对照 媒体根() 登记参考素材清单与每段 refs 里已不存在的文件名，
返回给前端「缺失素材」数组以 toast 提示；**不剔除、不压缩**（refs 位置即 <Picture N> 标签，
过滤会使其余素材前移错指），真正的拦截在采样前由 执行核心._预检素材 点名阻止相关段。

存档版本与草稿（A2）：保存信封包含 剪辑草稿（真源＝节点 properties，不回执行 widget），并把
「格式版本」（schema）与「修订号」（编辑轮次）分离；加载对可识别版本前向兼容（保留未识别
扩展字段）、报告旧计划是否缺草稿（前端据此清空不相干草稿并提示，不从执行 prompt 伪造 brief）、
拒绝高于当前支持的未来版本；读取迁移不改写原文件，保存总用最新格式版本。
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

# 计划存档「格式版本」（schema 版本）与「修订号」（编辑次数）分离（A2）：
#   · 格式版本：信封结构版本，随代码演进（v1 无 剪辑草稿、键名 版本；v2 含 剪辑草稿、键名 格式版本）。
#     加载时 高于 _支持最高格式版本 的未来版一律拒绝，可识别版本内未识别的扩展字段原样保留。
#   · 修订号：每次保存 +1，仅记录编辑轮次，与 schema 无关；覆盖保存读旧值递增，新计划从 1 起。
_当前格式版本 = 2
_支持最高格式版本 = _当前格式版本   # 当前只到 v2；未来加 v3 迁移时 _支持最高格式版本 仍等于 _当前格式版本


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
    """逐段登记缺失素材到 缺失，但**原样返回段组、绝不改动 refs**（A6）。
    - 字符串值（首帧/尾帧）不在池中 → 记入缺失，键与值保持原样。
    - 数组值（图片/音频/视频）→ 逐项登记缺失名，数组顺序与长度不变。
    位置即标签：官方按 refs 顺序赋 <Picture N>/<Video K>/<Audio J>（见 执行/参考素材.py），
    过去“过滤掉缺失项”会让后续素材悄悄前移 → 标签错指。现改为保留原引用 + 返回诊断，
    由执行层（执行核心._预检素材）在采样前阻止引用缺失素材的段。
    非 dict 的段/refs 原样透传（前端可能塞了脏数据，不阻断加载）。"""
    if not isinstance(段组, list):
        return 段组
    for 段 in 段组:
        if not isinstance(段, dict):
            continue
        refs = 段.get("refs")
        if not isinstance(refs, dict):
            continue
        for key, v in refs.items():
            if key == "视频音频模式":
                continue
            if isinstance(v, str):
                if v and v not in 池:
                    缺失.append(v)
            elif isinstance(v, list):
                for 名 in v:
                    if isinstance(名, str) and 名 and 名 not in 池:
                        缺失.append(名)
        配 = refs.get("台词配音")
        if isinstance(配, dict):
            名 = 配.get("文件名")
            if isinstance(名, str) and 名 and 名 not in 池:
                缺失.append(名)
    return 段组


def 过滤缺失素材(数据: dict) -> tuple:
    """对照 媒体根() 池**登记**缺失的参考素材，返回 (数据原样, 缺失文件名去重清单)。

    A6：不再从数据里剔除任何引用——refs 的**位置就是 <Picture N> 标签**，静默过滤中间项
    会把后续素材悄悄提前造成错指。缺失只作为诊断返回给前端 toast，真正的拦截在采样前由
    执行核心._预检素材 点名阻止引用缺失素材的可运行段。本函数对入参只读不写，直接返回同一对象。
    媒体根 目录读取失败视为空池 → 所有素材都会被判为缺失；这是极端场景（input 目录不可用），
    此时插件本身也跑不了，让用户看到「全缺」诊断比悄悄保留错误引用更安全。
    """
    from .媒体路由 import 媒体根   # 延迟 import 避免模块级循环（媒体路由 与本模块平级、互不依赖）
    try:
        池 = set(os.listdir(媒体根()))
    except OSError:
        池 = set()

    缺失: list = []

    素材 = 数据.get("参考素材")
    if isinstance(素材, dict):
        for 槽 in ("图片", "音频", "视频"):
            原 = 素材.get(槽)
            if isinstance(原, list):
                for 名 in 原:
                    if isinstance(名, str) and 名 and 名 not in 池:
                        缺失.append(名)

    时间轴 = 数据.get("时间轴")
    if isinstance(时间轴, dict) and isinstance(时间轴.get("segments"), list):
        _过滤段refs(时间轴["segments"], 池, 缺失)   # 只登记，不改数据

    草稿 = 数据.get("剪辑草稿")
    if isinstance(草稿, dict):
        _过滤段refs(草稿.get("segments"), 池, 缺失)

    # 缺失清单去重保序（同名文件被多段引用时只 toast 一次）
    见 = set()
    去重 = []
    for 名 in 缺失:
        if 名 not in 见:
            见.add(名)
            去重.append(名)
    return 数据, 去重


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


def _读修订(路径: str) -> int:
    """读已存在计划文件的 修订号（供覆盖保存递增）；无文件/无字段/非整数 → 0。"""
    try:
        with open(路径, "r", encoding="utf-8") as f:
            旧 = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(旧, dict):
        v = 旧.get("修订")
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return 0


def _读格式版本(文件: dict) -> int:
    """取信封的格式版本：新键 格式版本 优先，回退旧键 版本；两者皆缺/非整数 → 视作 1（旧计划）。

    故意不把脏版本（字符串/None/布尔）当未来版拒绝：宁可回退 v1 走迁移，也不误伤旧存档。
    """
    for 键 in ("格式版本", "版本"):
        v = 文件.get(键)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return 1


def _数据缺草稿(数据) -> bool:
    """数据 里缺有效 剪辑草稿 → True。brief 与 segments 均空也视为缺（无实质草稿内容）。"""
    草 = 数据.get("剪辑草稿") if isinstance(数据, dict) else None
    if not isinstance(草, dict):
        return True
    return not (草.get("brief") or 草.get("segments"))


def _计划元信息(文件: dict) -> dict:
    """从计划文件提取加载所需的版本/修订/缺草稿元信息（A2）。**只读不改**，不触及磁盘。

    返回 {"格式版本", "修订", "缺草稿"}（不带 数据 键：handler 自行 文件.get("数据") 并校验，
    避免同名键双源误导维护者）。
    格式版本 高于 _支持最高格式版本 → 抛 ValueError（路由转 400，拒绝不支持的未来版本）。
    """
    版本 = _读格式版本(文件)
    if 版本 > _支持最高格式版本:
        raise ValueError(
            f"计划格式版本 {版本} 高于当前支持的 {_支持最高格式版本}（未来版本），拒绝加载；请升级插件后再打开此计划"
        )
    修订 = 文件.get("修订")
    修订 = 修订 if isinstance(修订, int) and not isinstance(修订, bool) else 0
    数据 = 文件.get("数据")
    if not isinstance(数据, dict):
        数据 = {}
    return {"格式版本": 版本, "修订": 修订, "缺草稿": _数据缺草稿(数据)}


def _构造存档文件(数据: dict, 创建时间: str, 修订: int, 现在: str) -> dict:
    """构造保存信封（A2）：固定 格式版本=_当前格式版本，修订号独立传入，保留创建时间、刷新更新时间。"""
    return {
        "格式版本": _当前格式版本,
        "修订": 修订,
        "创建时间": 创建时间,
        "更新时间": 现在,
        "数据": 数据,
    }


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
        """按名读取计划 JSON；**读取仅迁移不写盘**；返回 {数据, 缺失素材, 缺草稿, 格式版本, 修订}。

        A2：根据信封格式版本做可识别版本内的前向兼容（保留未识别扩展字段），报告旧计划是否
        缺 剪辑草稿（供前端清空不相干草稿并提示）；拒绝高于当前支持的未来版本。
        400: 名字非法 / 未来版本；404: 计划不存在；500: 读盘/JSON 解析/结构非法。
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
        try:
            元 = _计划元信息(文件)   # 只读迁移；未来版抛 ValueError
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        数据 = 文件.get("数据")
        if not isinstance(数据, dict):
            return web.json_response({"error": "计划文件缺 数据 字段或其非对象"}, status=500)
        try:
            清洗, 缺失 = 过滤缺失素材(数据)   # A6：只登记不剔除，返回同一对象
        except OSError as e:
            # 媒体根 不可读时 过滤缺失素材 已内部兜底为空池，这里再兜一层保险
            return web.json_response({"error": f"参考素材目录读取失败：{e}"}, status=500)
        return web.json_response({
            "数据": 清洗, "缺失素材": 缺失,
            "缺草稿": 元["缺草稿"], "格式版本": 元["格式版本"], "修订": 元["修订"],
        })

    @routes.post("/lvp/plan/save")
    async def 计划保存(request):
        """保存计划：请求体 {名, 数据}；固定写入当前 格式版本，覆盖时保留原 创建时间、递增 修订号。

        允许保存不完整草稿（可运行性只在执行阶段校验）；旧版（v1）计划编辑后保存即升为新版。
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
        修订 = _读修订(目标) + 1   # 编辑修订号与格式版本分离：覆盖递增，新计划从 1 起
        文件 = _构造存档文件(数据, 创建时间, 修订, 现在)

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
        return web.json_response({"名": 名, "格式版本": _当前格式版本, "修订": 修订,
                                  "创建时间": 创建时间, "更新时间": 现在})

    _已注册 = True
