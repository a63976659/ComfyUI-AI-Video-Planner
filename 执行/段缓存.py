# -*- coding: utf-8 -*-
"""段产物磁盘缓存：指纹纯函数 + 读写封装（部分重跑/续跑）。

公开符号恰好 6 个（常量除外）：段指纹 / _缓存根 / 缓存路径 / 命中 / 读缓存 / 写缓存。
（另有模块级常量 缓存格式版本，它是第 7 个公开顶层名，不计入上述 6 个函数符号。）

错误契约（ValueError-only）：缓存路径/读缓存/写缓存 面向 Task 9 与入口层的失败
一律收敛为 ValueError。唯一例外是 读缓存 的「坏文件自愈」分支——它在语义上是
未命中（返回 None，本次重跑自然修复），不是失败；真 IO 失败（OSError）不在此
例外内，仍上抛 ValueError。

⚠️ 体积警示：段产物为解码后的原段，单段 float32 IMAGE ≈1.4 GiB；缓存目录默认落在
系统盘 %TEMP%（可用环境变量 H3_段缓存_DIR 覆盖），且**没有自动淘汰**。清理入口与
容量淘汰策略归 Task 11（UI「清理段缓存」按钮）/ backlog，本模块刻意不提供删除接口。
"""
import contextlib
import hashlib
import itertools
import json
import logging
import os
import pickle
import re
import tempfile

# 缓存内容格式版本：作为指纹盐，格式（字段语义/落盘结构）一变即整体作废旧缓存。
缓存格式版本 = "h3-1"

_指纹_正则 = re.compile(r"[0-9a-f]{16}")

_日志 = logging.getLogger("H3导演台.段缓存")

_临时序号 = itertools.count()  # 仅用于给并发写生成互不干扰的 .part 文件名


def 段指纹(seg: dict, 全局参数: dict) -> str:
    """对 (格式版本 + 段内容 + 全局参数) 做稳定哈希；键序无关，返回 16 位十六进制。

    调用方契约（Task 9 执行核心必读）——**任何**会影响本段输出的因素都必须纳入
    传入的 seg 或 全局参数，至少含：
        - task / prompt / refs / start / end
        - 本段是否被上游锚定 + 锚帧数 + 上段身份
          （写缓存 会把 锚帧数 一起落盘：上一段重跑时若锚定状态不进指纹，本段指纹
           不变 → 命中带旧锚的缓存 → 读回旧 锚帧数 → 凭空裁掉真实内容）
        - 种子 / 步数 / shift_video / shift_audio / 上下文帧数
        - 模型标识（ckpt 名）
        - 宽 / 高 / 帧率
    漏掉其中任一项都会造成「改了参数却命中旧缓存」的假命中。

    实现约束：
        1. 入参必须是 JSON-safe 标量/容器；**不要直传 SegmentPlan**（frozen dataclass
           不可 JSON 序列化，会抛 TypeError），须显式挑字段构造 dict。
        2. 数值入指纹前须统一类型（全 int 或全 float）：json 会区分 1 与 1.0，
           二者产生不同指纹 → 永不命中（by-design，见 测试_段指纹_数值类型敏感）。
        3. `run` 不得进指纹——Task 9 的 Run-select 会改写 run，进了会让缓存整体失效。
        4. SegmentPlan 是 frozen + dict 字段（浅不可变、整体不可哈希），故必须用
           json.dumps(..., sort_keys=True) 做稳定序列化，不能 hash(seg)。
    """
    payload = json.dumps(
        {"v": 缓存格式版本, "seg": seg, "g": 全局参数},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _缓存根() -> str:
    """缓存根目录（幂等创建）。默认 %TEMP%/h3导演台_段缓存。

    环境变量 H3_段缓存_DIR 可覆盖（测试注入 tmp_path、或改到非系统盘）。
    注意：段产物 ≈1.4 GiB/段且无自动淘汰，清理与容量策略归 Task 11/backlog。
    """
    root = os.environ.get("H3_段缓存_DIR") or os.path.join(
        tempfile.gettempdir(), "h3导演台_段缓存"
    )
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    return root


def 缓存路径(node_id: str, seg_index: int, 指纹: str) -> str:
    """拼 <根>/<安全node_id>_<seg_index>_<指纹>.pt；入参非法一律抛 ValueError。

    指纹 必须是 段指纹 的产出格式（16 位小写十六进制）。这里**不做** node_id 式
    白名单清洗：把 `../escape` 静默改写成 `escape` 会制造假命中碰撞，比拒绝更糟。
    node_id 仍走白名单，因为它只影响文件名归并（同目录不同名 → 同一文件），内容
    正确性由 指纹 保证（见 code review M5）。
    """
    if not isinstance(指纹, str) or not _指纹_正则.fullmatch(指纹):
        raise ValueError(f"非法指纹格式: {指纹!r}（须为 段指纹 产出的 16 位小写十六进制）")
    try:
        i = int(seg_index)
    except (TypeError, ValueError) as e:
        raise ValueError(f"非法 seg_index: {seg_index!r}") from e
    if i < 0:
        raise ValueError(f"非法 seg_index: {seg_index!r}（须 >= 0）")
    try:
        root = _缓存根()
    except OSError as e:
        raise ValueError(f"段缓存目录创建失败：{e}") from e
    安全id = "".join(c for c in str(node_id) if c.isalnum() or c in "._-") or "node"
    路径 = os.path.join(root, f"{安全id}_{i}_{指纹}.pt")
    # 纵深防御：断言结果仍在根内（指纹与 seg_index 已校验，正常不可能越界）。
    根 = os.path.normcase(root)
    if os.path.commonpath([根, os.path.normcase(os.path.abspath(路径))]) != 根:
        raise ValueError(f"缓存路径越出缓存根目录：{路径}")
    return 路径


def 命中(node_id: str, seg_index: int, 指纹: str) -> bool:
    """缓存文件是否存在。入参非法按 缓存路径 的契约抛 ValueError。"""
    return os.path.exists(缓存路径(node_id, seg_index, 指纹))


def 读缓存(node_id: str, seg_index: int, 指纹: str):
    """命中返回 torch.load 的对象；未命中或缓存文件损坏返回 None。磁盘 IO，CPU 可测。

    自愈分两层（顺序即语义）：
        1. OSError = 真 IO 失败（权限、path 是目录、文件被并发删走、磁盘读写错误）：
           文件本身可能完好，删它等于白丢缓存，故**不删、不自愈**，按 ValueError-only
           契约上抛（见 I2）。
        2. 其余异常 = torch.load 解码/反序列化过程中的一切损坏形态：删该文件、告警、
           按未命中返回 None——本次重跑自然修复。

    为何第 2 层可以宽到 Exception：try 体只含 torch.load 单行，我方代码（路径解析、
    存在性判断、删除）全在体外，故不存在「把我方 bug 洗成静默未命中」的风险，与项目
    「禁 except Exception 吞我方 bug」纪律不冲突（见函数内注释）。
    """
    p = 缓存路径(node_id, seg_index, 指纹)
    if not os.path.exists(p):
        return None
    import torch

    # try 体刻意只包 torch.load 这一行：异常来源只能是「解码这个文件」，而不是我方逻辑。
    # 上一轮白名单 (RuntimeError, EOFError, BadZipFile, UnpicklingError) 已被实测证伪为
    # 不完备——torch 2.10 上头截断抛 IndexError、结构区位翻转抛 UnicodeDecodeError，另有
    # KeyError 与 torch 自身 ValueError 等，均非 OSError 子类、形态跨 torch 版本极多，白
    # 名单追不全；漏捕获会让坏文件永久卡死（命中 恒真、每次读都抛），C1 初衷复发。
    try:
        对象 = torch.load(p, map_location="cpu", weights_only=True)
    except OSError as e:
        # 真 IO 失败：不能当损坏处理，否则磁盘故障时会把整批好缓存删光。
        raise ValueError(f"段缓存读取失败：{p}：{e}") from e
    except Exception as e:  # noqa: BLE001 - 见上方注释：try 体无我方代码，按「非 IO 即损坏」兜底
        # 告警保留异常类型名 + 消息，便于区分「真损坏」与「torch 版本新增的解码异常」。
        _日志.warning("段缓存损坏已丢弃、将重算：%s（%s: %s）", p, type(e).__name__, e)
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)  # 并发下可能已被他人删除，语义仍是未命中
        return None
    return 对象


def 写缓存(node_id: str, seg_index: int, 指纹: str, 对象):
    """torch.save 段产物 {images, audio, 锚帧数, 帧数}（解码后、未裁前缀的原段）。

    磁盘 IO，CPU 可测。先写同目录的临时文件（<最终路径>.<pid>.<序号>.part），成功后
    os.replace 原子改名，因此中断（Ctrl-C/OOM/磁盘满）不会让最终路径出现半截文件；
    序号＋pid 是为了并发写同一指纹时不会互相踩脚（共用固定 .part 名会让两个写入者
    交替写同一临时文件，或被 Windows 的 replace 拒绝）。失败抛 ValueError。
    进程被强杀（kill -9）时来不及清理，目录里可能残留 .part 孤儿，清理归 Task 11/backlog。
    """
    import torch

    路径 = 缓存路径(node_id, seg_index, 指纹)
    临时 = f"{路径}.{os.getpid()}.{next(_临时序号)}.part"
    已落盘 = False
    try:
        torch.save(对象, 临时)
        os.replace(临时, 路径)
        已落盘 = True
    except (OSError, TypeError, ValueError, RuntimeError, pickle.PicklingError) as e:
        raise ValueError(f"段缓存写入失败：{路径}：{e}") from e
    finally:
        if not 已落盘:  # 含 BaseException（KeyboardInterrupt）路径
            with contextlib.suppress(OSError):
                os.remove(临时)
