# -*- coding: utf-8 -*-
"""段产物磁盘缓存：指纹纯函数 + 读写封装（部分重跑/续跑）。

公开符号恰好 7 个（常量与私有状态除外）：段指纹 / _缓存根 / _淘汰旧版本 / 缓存路径 /
命中 / 读缓存 / 写缓存。（另有模块级常量 缓存格式版本 与私有状态 _已淘汰基，不计入。）
其中 命中 自 M1 去冗余后**不再有编排层调用者**（执行核心 直接调 读缓存，后者内部已含
存在性判断）；保留作缓存层的存在性查询 API，删它需同步改本节与 10-测试策略.md。

错误契约（ValueError-only）：缓存路径/读缓存/写缓存 面向 Task 9 与入口层的失败
一律收敛为 ValueError。唯一例外是 读缓存 的「坏文件自愈」分支——它在语义上是
未命中（返回 None，本次重跑自然修复），不是失败；真 IO 失败（OSError）不在此
例外内，仍上抛 ValueError。

⚠️ 体积与清理：h3-4 起段产物为 KSampler 输出的 CPU latent。1.0MP@16s **同口径**实算：单段
≈45MB（=1×24×117×48×86×float32），对照 h3-3 及之前存解码后 images 的 ≈4.7GiB
（=5.0GB，396帧×768×1376×3×float32），缩到约 **1/108**；该比值与分辨率无关（H×W 在
「latent 字节 / images 字节」里约掉）。缓存基目录默认落在系统盘 %TEMP%（可用环境
变量 H3_段缓存_DIR 覆盖）；h3-6 起**按 缓存格式版本 分子目录**存放，并由 _淘汰旧版本 在
进程内首次取根时自动删掉旧版本目录与分目录改造前遗留的散缓存文件 ⇒ **用户无需手动清理，
升版也不再堆积死文件**（h3-3→h3-4 曾因此在 %TEMP% 留下 27.9GB 永不命中的旧 images 段）。
同版本内**刻意不做容量上限淘汰**：同版本文件都可能被再次命中（把参数改回去就命中），删它们
等于牺牲「改一段、其余段命中缓存」的部分重跑能力。UI「清理段缓存」按钮归 Task 11/backlog。
"""
import contextlib
import hashlib
import itertools
import json
import logging
import os
import pickle
import re
import shutil
import tempfile

# 缓存内容格式版本：作为指纹盐，格式（字段语义/落盘结构）一变即整体作废旧缓存。
# h3-1 → h3-2：主画布不再过 对齐画布（=官方 adapt_canvas）。指纹里的 "宽"/"高" 存的一直是
# **原始** 全局参数值（非规范后画布），故同一对 (宽,高) 在改动前后映射到不同画布：旧缓存段是
# 按规范后尺寸（如 0.4MP+9:16 的 768x1376）生成的，新跑的段是 480x864 → 不升版会假命中，
# 把两种尺寸的段交给 流式拼接 混拼。
# h3-2 → h3-3：改双模型架构（导演台 fl2va模型/ref2va模型 按段任务自动匹配）。采样参数移除了「模型
# 标识」维度——fl2va/ref2va 已由 指纹源 的 task 天然区分（task→槽确定），但同一槽上「换了哪个 ckpt
# 文件」不再入指纹；且移除该维度本身即改变指纹 payload。升版令 h3-3 前的旧缓存整体作废重算（干净
# 起点）。取舍：今后换 checkpoint 文件需手动清缓存目录（h3-6 起是 %TEMP%\h3导演台_段缓存\<当前版本>，
# H3_段缓存_DIR 覆盖的是**基**；⚠️ _淘汰旧版本 只删**旧版本**目录，同版本内不淘汰）
# 才会重算；进程内模型缓存不受影响（靠 id(model) 自动重载，见 执行核心._模型缓存键）。
# h3-3 → h3-4：方案 B（延迟解码）把落盘内容从「解码后的段产物 {images, audio, 锚帧数, 帧数}」
# 改为「KSampler 输出的 CPU latent {video_latent, audio_latent, 锚帧数, 帧数, index}」。这正是
# 缓存格式版本 存在的场景——落盘结构一变即整体作废旧缓存：不升版则旧文件仍被同一指纹命中，
# 执行核心 读回一个 images 形态的 dict 当 latent 用（虽有 执行核心._是采样产物 兜住不崩、判为
# 未命中重算，但整目录旧文件就此变成永不命中也永不被覆盖的死文件）。附带收益：单段体积
# ≈4.7GiB → ≈45MB（同口径，见模块 docstring）。取舍同 h3-2→h3-3：升级后首轮全量重算，旧缓存需手动清目录。
# ⚠️ 本次升版正是那 27.9GB 死文件的来源（无人手动清）——h3-6 起由 _淘汰旧版本 自动清，见下。
# h3-4 → h3-5：删掉 执行核心 指纹源 里的同值冗余键（旧版同时写了 "被锚定" 与 "上段尾帧"，
# 两者都是 尾帧_video is not None）。删它本身就改变 段指纹 的 payload JSON → 指纹全变，故必须
# 升版：不升则新旧两套指纹共存于同一目录、旧文件永不命中也永不被覆盖（同 h3-3→h3-4 的死文件
# 后果）。产物 schema 未变（仍是扁平 latent 字典），所以 _是采样产物 不需改；升版只为了把
# h3-4 旧文件干净作废。取舍同上：升级后首轮全量重算，旧缓存需手动清目录（h3-6 起不再需要，见下）。
# h3-5 → h3-6：两件事合并升版。**① 删 指纹源 同值键「上段尾音频」**：它与「被锚定」在所有
# 可达状态下同值——官方 _empty_av_latent(width, height, length) 无条件造 video+audio 两支
# （签名里根本没有 audio_vae），故 audio_latent 恒非 None ⇒ 尾帧_audio is None ⟺
# 尾帧_video is None。⚠️ 但它与 h3-5 删的「上段尾帧」**性质不同**：那是 尾帧_video is not None
# 的字面重复（删它零风险），本键是**不同谓词**，同值只是官方实现细节的副产物。若官方将来把
# audio 支改成条件化（如 audio_vae 未连接时只返回 video），本键立刻恢复区分力 ⇒ **届时必须
# 把它加回 指纹源**，否则「带音频锚」与「不带音频锚」的段会撞同一指纹 → 静默假命中
# （同 h3-1→h3-2 把两种尺寸的段混拼的事故型，且 _是采样产物 查不出：形状仍合法）。
# **② 缓存改按版本分子目录**（<基>/<缓存格式版本>/）：目录名即指纹的盐，于是 _淘汰旧版本
# 能一眼认出「哪些文件属于代码里已不存在的旧指纹世代」并整目录删除；同时清掉分目录改造前
# 遗留在 基 根下的散缓存文件。路径规则变更本身即令 h3-5 及之前的文件不可达，故与 ① 同批升版。
# ⇒ 自本版起**升版不再需要用户手动清目录**（旧文件由程序自动删）。产物 schema 未变，
# _是采样产物 不需改。取舍：升级后首轮仍全量重算一次（指纹变了，不可避免），但这是最后一次。
缓存格式版本 = "h3-6"

_指纹_正则 = re.compile(r"[0-9a-f]{16}")

# 版本子目录名白名单：只有本模块自己造过的 <基>/h3-<数字> 才可能被 _淘汰旧版本 删除。
# 这是纵深防御——即使 H3_段缓存_DIR 被误设成某个重要目录，也绝不会碰到无关内容。
_版本目录_正则 = re.compile(r"h3-\d+")

# 分目录改造（h3-6）前遗留在 基 根下的散缓存文件名白名单：缓存路径 产出的
# <安全node_id>_<seg_index>_<16位hex>.pt，以及 写缓存 的临时名 <最终名>.<pid>.<序号>.part。
# 用严格正则而非「凡 .pt 都删」：模型权重（model.pt / vae.pt）等同扩展名文件必须免伤。
_散缓存_正则 = re.compile(r"[0-9A-Za-z._-]+_\d+_[0-9a-f]{16}\.pt(?:\.\d+\.\d+\.part)?")

# 已完成淘汰的 基 目录集合：进程内每个基只扫一遍（_缓存根 每段每轮都会被调，不能反复
# scandir + rmtree）。按基而非全局布尔，测试注入不同 tmp_path 时天然互不干扰。
_已淘汰基 = set()

_日志 = logging.getLogger("H3导演台.段缓存")

_临时序号 = itertools.count()  # 仅用于给并发写生成互不干扰的 .part 文件名


def 段指纹(seg: dict, 全局参数: dict) -> str:
    """对 (格式版本 + 段内容 + 全局参数) 做稳定哈希；键序无关，返回 16 位十六进制。

    调用方契约（Task 9 执行核心必读）——**任何**会影响本段输出的因素都必须纳入
    传入的 seg 或 全局参数，至少含：
        - task / prompt / refs / start / end
        - 本段是否被上游锚定（「被锚定」布尔）+ 锚帧数
          （写缓存 会把 锚帧数 一起落盘：上一段重跑时若锚定状态不进指纹，本段指纹
           不变 → 命中带旧锚的缓存 → 读回旧 锚帧数 → 凭空裁掉真实内容）
        - 种子 / 步数 / shift_video / shift_audio / 上下文帧数
        - （模型维度由 task 覆盖：task→fl2va/ref2va 槽确定；h3-3 起不再单列「模型标识」，
          同一槽换 ckpt 文件不入指纹——详见模块头 缓存格式版本 注释）
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


def _淘汰旧版本(基: str) -> None:
    """删掉「永不可能再被命中」的历史缓存；进程内每个 基 只做一遍（见 _已淘汰基）。

    两类目标，都靠**只可能由本模块自己产出**的名字形态识别，绝不碰其它东西：
        1. 基 下名为 h3-<数字> 且不等于当前 缓存格式版本 的**子目录** → 整个 rmtree；
        2. 基 **根下**符合 _散缓存_正则 的散文件 → 分目录改造（h3-6）后 缓存路径 恒返回
           <基>/<版本>/…，故根下不可能再产出新文件，凡在根下者必是 h3-5 及之前的遗留。

    为何 100% 安全：目录名就是 缓存格式版本（指纹的盐）。旧版本的指纹算法在代码里已不存在
    ⇒ 缓存路径 永远拼不出那些文件名 ⇒ 永不命中、也永不被覆盖（纯死文件）。两个正则白名单
    是纵深防御：即使 H3_段缓存_DIR 被误设到重要目录，也只动本模块自己造过的东西。

    失败一律吞掉（清理不在关键路径上）：单条目被占用/权限不足不影响其余，更不得让「删不掉
    旧垃圾」把整轮生成打挂。故本函数**不抛异常**，在 ValueError-only 契约之外。
    """
    if 基 in _已淘汰基:
        return
    _已淘汰基.add(基)          # 先置位：即使中途失败也不反复重试
    try:
        扫描 = os.scandir(基)
    except OSError:
        return                 # 基 尚不存在或不可读（首次运行）：无事可做
    with 扫描:
        for 条目 in 扫描:
            try:
                if 条目.is_dir():
                    if _版本目录_正则.fullmatch(条目.name) and 条目.name != 缓存格式版本:
                        shutil.rmtree(条目.path, ignore_errors=True)
                elif 条目.is_file() and _散缓存_正则.fullmatch(条目.name):
                    os.remove(条目.path)
            except OSError:
                continue       # 单条删不掉（被占用等）不影响其余条目


def _缓存根() -> str:
    """当前版本的缓存目录（幂等创建）：<基>/<缓存格式版本>，基 默认 %TEMP%/h3导演台_段缓存。

    环境变量 H3_段缓存_DIR 覆盖的是 **基**（不含版本层），测试注入 tmp_path 同理。
    按版本分目录是自动淘汰的前提：目录名即指纹的盐，程序因此能认出「哪些文件属于已不存在
    的旧指纹世代」并整目录删掉（_淘汰旧版本），升版不再需要用户手动清 %TEMP%。
    注意：段产物 ≈45MB/段（h3-4 起存 latent）；跨版本死文件自动清，**同版本内不做容量上限
    淘汰**（同版本文件都可能被再次命中，删它们会牺牲部分重跑能力），UI 清理归 Task 11/backlog。
    """
    基 = os.environ.get("H3_段缓存_DIR") or os.path.join(
        tempfile.gettempdir(), "h3导演台_段缓存"
    )
    基 = os.path.abspath(基)
    os.makedirs(基, exist_ok=True)
    _淘汰旧版本(基)
    root = os.path.join(基, 缓存格式版本)
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
    """缓存文件是否存在。入参非法按 缓存路径 的契约抛 ValueError。

    ⚠️ 存在 ≠ 可用：坏文件自愈与形状守卫都在 读缓存 侧，故本函数为真不代表 读缓存 非 None
    （见 执行核心._是采样产物 与 test_执行时间轴_坏形状缓存判未命中不崩）。自 M1 去冗余后
    编排层不再先查本函数再读（那是重复一次 stat），仅留作外部存在性查询。"""
    return os.path.exists(缓存路径(node_id, seg_index, 指纹))


def 读缓存(node_id: str, seg_index: int, 指纹: str):
    """命中返回 torch.load 的对象；未命中或缓存文件损坏返回 None。磁盘 IO，CPU 可测。

    ⚠️ 落盘内容约束：这里用 weights_only=True 读（安全默认，不执行任意 __reduce__），故
    写缓存 的对象只能是「纯张量 + 标量 + 内建容器」。自定义类**读不回来**——它会被判为
    第 2 层损坏：删文件、告警、按未命中重算，于是缓存永久失效而每次跑都白写一遍。
    comfy.nested_tensor.NestedTensor 正是这类（KSampler 的 AV 输出外层），故 执行核心
    以 _拆_av_latent 拆成扁平张量字典再落盘、用前经 _建_av_latent 还原。

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
    """torch.save 采样产物 {video_latent, audio_latent, 锚帧数, 帧数, index}。

    h3-4 起存的是 KSampler 输出搬到 CPU 的扁平 AV latent（未解码、未裁前缀的原段），
    schema 见 执行核心._采样段、落盘内容约束见 读缓存。

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
