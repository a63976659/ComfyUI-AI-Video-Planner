# -*- coding: utf-8 -*-
"""执行核心：解析时间轴 → 逐段（Run-select + 缓存）走官方 H3 链路采样 → 统一解码 → 段间连续拼接 → 进度上报。

官方单段链路（严格对齐 comfy_extras/nodes_minimax_h3.py 与 nodes.py）：
  MiniMaxH3SigmaShift(给 model 打补丁) → 条件节点(ImageToVideo / ReferenceToVideo，产 positive + AV 空 latent)
  → [段间连续] 把上段尾帧 latent 锚到 frame_idx=0（自建 keyframe，等价 MiniMaxH3AddGuide 的产出）
  → KSampler(res_multistep / simple, cfg=1.0, negative=positive) → VAEDecode + VAEDecodeAudio(同一 AV latent)
条件节点只输出 positive（无 negative）；cfg=1.0 时 KSampler 忽略 negative，故 negative 直接复用 positive。

方案 B（延迟解码，两阶段）：
  Phase 1 逐段只跑到 KSampler，把 AV latent 搬到 CPU 存起来（≈45MB/段@1.0MP16s）；
  Phase 2 全部采完后解除 模型缓存 对 DiT 的钉住 + 清理显存，再统一 VAEDecode（images ≈GB/段）。
  动机：16GB 卡跑 1.0MP@16s 时「images 张量 + DiT 权重 + 激活」超显存上限，宿主把权重反复
  offload，AV 解码从 52s 涨到 839s。把 GB 级的 images 从段循环里挪走、并让解码独占空显存即解。
  段缓存随之存 latent 而非 images（缓存格式版本 h3-4）。同口径（1.0MP@16s）实算：单段体积从
  ≈4.7GiB（=5.0GB，396帧×768×1376×3×float32）降到 ≈45MB（=1×24×117×48×86×float32），
  缩到约 1/108；该比值与分辨率无关（H×W 在「latent 字节 / images 字节」里约掉）。

本模块是编排层：串起 规划 / 条件组装 / 参考素材 / 采样与解码 / 段间连续 / 段缓存 / 官方管线适配 /
显存清理。GPU 主验证在 Task 19/20；CPU 侧只做静态语法 + 纯函数/编排桩测。
"""
import itertools
import logging
import time

from .规划 import 解析时间轴
from .条件组装 import 选管线, 选模型槽, 需要首帧, 需要尾帧, 组装参考入参
from .参考素材 import 解析槽位, 校验标签, 上限
from .采样与解码 import 对齐画布, 解码音视频, 秒转帧数, FPS, CANVAS_MULTIPLE
# ⚠️ _latent_t_转帧数 带下划线只表示「不是 段间连续 的对外 API」，同包内借用无妨：_是采样产物
# 要用它做「缓存里的 帧数 与 latent 时长是否同源」的自洽校验（官方 FRAME_PER_TOKEN 累加式的逆换算）。
from .段间连续 import (裁前缀帧数, 默认上下文帧数, 取尾帧_latent, 钉入上下文_from_latent,
                    流式拼接, 预算总帧数, _latent_t_转帧数)
from .段缓存 import 段指纹, 读缓存, 写缓存, 缓存统计
from .官方管线适配 import 调用节点
from .显存清理 import 清理显存
from .模型缓存 import 取模型, 清缓存

_临时序号 = itertools.count()   # 与 段缓存/媒体路由/计划路由 同源：并发写同名文件时生成互不干扰的 .part（doc 12 约定 <路径>.<pid>.<序号>.part）

_日志 = logging.getLogger("长视频规划师.执行核心")

# 接缝重叠帧数（「渐变过渡」开启时）：与 段间连续.流式拼接 / 预算总帧数 的默认值 4 保持同源，
# 供 ⚠️#4 音频对称裁剪对齐。（拼接段 的默认值也是 4 且与之严格同值，但它已不在生产链上——
# 只作零拷贝单段路径与同值参照。）
# ⚠️ 与「渐变过渡」开关联动：执行时间轴 以 上下文帧数>0 判「开启」→ 用本常量 4；「关闭」→
# 传 0（硬切、不做任何接缝过渡）。_拼接音频 的默认参数仍取本常量以保持外部直调路径的向后兼容，
# 生产链路（执行时间轴）会显式覆盖为 接缝重叠 变量。
_拼接重叠帧数 = 4


def _计时开启():
    """诊断计时开关：环境变量 H3_计时 为真值（1/true/yes/on）时启用，默认关闭。

    开启后 _采样段 每段以 info 级输出 ①参考解码 / ②条件节点 / ③段间连续 / ④KSampler 四步耗时、
    _解码段 每段输出 ⑤AV解码 耗时，用于定位「模型初始化久」到底是首段的模型加载（②④ 首段偏大）、
    后续段的采样计算（④ 后续段），还是参考素材解码（①）/ 解码显存乒乓（⑤）。

    两个读日志的口径注意项：
      • **①+②+③+④ == 合计**（五段计时首尾相接、无缝无叠）。旧版曾把素材加载落在
        时刻1→时刻2 的盲区里，造成 ①参考解码 结构性恒为 0.00s 而合计里却包含它。
      • **合计 不包含 ⑤AV解码**（方案 B 下解码已移出段循环、集中在 Phase 2），故旧日志的
        「合计=306.17s（含⑤52.13s）」不得与新版直接比数，要比就比 ④KSampler 与 ⑤AV解码 单项。
    默认关闭 → 正常路径静默、仅多几次 perf_counter（纳秒级），符合日志规范。环境变量约定同
    段缓存._缓存根 的 长视频规划师_段缓存_DIR。刻意不入段缓存指纹：纯诊断开关、不影响产物。"""
    import os
    return os.environ.get("H3_计时", "").strip().lower() in ("1", "true", "yes", "on")


def _内存预警阈值字节():
    """3.1(100) 内存软预警阈值（GiB），环境变量 H3_内存预警_GiB，默认 16GiB；非法值回退默认。
    仅影响报告的预警行，不改产物、不入指纹（与 _计时开启 同构的纯观测/诊断开关）。"""
    import os
    try:
        giB = float(os.environ.get("H3_内存预警_GiB", "").strip() or 16.0)
    except ValueError:
        giB = 16.0
    return int(giB * 1024 ** 3)


def _内存硬限额字节():
    """3.1(100) 内存硬限额（GiB），环境变量 H3_内存硬限额_GiB；**默认关闭**（未设/非法→0=不限）。
    开启后成片估算超过限额将在解码前 ValueError 中止（Phase 1 采样已发生，代价由显式配置者承担）。"""
    import os
    raw = os.environ.get("H3_内存硬限额_GiB", "").strip()
    if not raw:
        return 0
    try:
        return int(float(raw) * 1024 ** 3)
    except ValueError:
        return 0


def _峰值内存描述() -> str:
    """3.1(97) 诊断模式：尽力报告 GPU 显存峰值与 CPU RSS 峰值（MiB）；任一不可得只略过该项、不抛。

    GPU 用 max_memory_allocated（自上次 reset 起的峰值，**不触发同步、不 reset**，以免干扰宿主）；
    CPU 峰值用 resource（Linux 的 ru_maxrss 为 KiB → /1024=MiB），Windows 无该模块 → 自然略过。
    仅由 _计时开启 门控的日志调用，普通运行不进这里（零额外开销）。"""
    项 = []
    try:
        import torch
        if torch.cuda.is_available() and torch.cuda.is_initialized():
            项.append(f"GPU峰值={torch.cuda.max_memory_allocated() / (1024 ** 2):.0f}MiB")
    except Exception:  # noqa: BLE001 - 诊断信息不可得则略过，不得拖挂主流程
        pass
    try:
        import resource
        项.append(f"CPU峰值RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f}MiB")
    except Exception:  # noqa: BLE001 - 同上（Windows 无 resource）
        pass
    return " ".join(项)


# ---------- 参考素材：文件名 → 张量（官方节点只吃张量，widget 存的是文件名） ----------

# B：参考素材解码缓存（单轮作用域）。_解析参考张量 在 _采样段 内部，所以 N 段会把同一批
# 素材读盘/解码/缩放 N 次——r2v 链路上这是仅次于显存乒乓的浪费。此处提供「一次
# 执行时间轴 调用」内的缓存：进入作用域建空 dict、退出即丢弃强引用（不跨轮驻留、不需
# 手动清理，也不会像 模型缓存.py 那样抬高宿主 free_memory() 的 refcount 卸载序）。
# 键含 mtime_ns+size，源文件被同名覆盖后自动失效。
# 并发：依赖 ComfyUI 单 prompt_worker 线程串行执行（与 模型缓存.py 同一前提），不加锁。
_参考缓存 = None      # None = 未启用（直调 _加载图像 等，或 参考共用 OFF）→ 每次现算，行为同旧版


class _参考缓存作用域:
    """with 语义：进入时挂一份新 dict，退出时恢复上一层（支持嵌套、异常安全）。

    启用=False → 不建 dict、保持上层值（顶层即 None），_取缓存 退回「每次现算」旧路径。
    门控理由：缓存是**轮内累积**的（退出 with 才丢引用）。参考共用 OFF 时段级 refs 优先、
    各段素材通常互不相同 → 命中率低，而峰值从「单段素材量」涨到「全轮素材总量」（10 段
    各带一条 15s 参考视频即 10×4.5GB 驻留，C 项省下的又被吃回去还倒贴）。共用 ON 时
    全段同一批素材、命中率 100%，才是纯收益。

    缓存值是**共享张量**（与 模型缓存.取模型 同类契约）：下游不得就地改写。已逐点核验
    官方 MiniMaxH3ImageToVideo / ReferenceToVideo / AddGuide 对入参只做 切片视图 +
    _resize/interpolate/vae.encode（均产新张量），nodes_minimax_h3.py 全文无就地改写算子；
    若日后接入会原地 mutate 入参的节点，需在 _取缓存 返回前 clone。
    """

    def __init__(self, 启用=True):
        self._启用 = 启用

    def __enter__(self):
        global _参考缓存
        self._旧 = _参考缓存
        if self._启用:
            _参考缓存 = {}
        return _参考缓存

    def __exit__(self, *exc):
        global _参考缓存
        _参考缓存 = self._旧
        return False


def _取缓存(种类, 路径, 额外键, 加载):
    """在作用域内按 (种类, 路径, mtime_ns, size, 额外键) 复用 加载() 的结果。
    未进入作用域（_参考缓存 is None）→ 直接 加载()，行为与旧版逐字相同。
    os.stat 失败时同样直接 加载()：让 FileNotFoundError 等原始异常从 加载() 原样抛出，
    不被缓存层改写成别的错（不破坏项目 ValueError-only 契约的可诊断性）。
    用 `键 not in` 而非 .get：_加载视频帧 对空视频返回 None，None 也是合法缓存值。"""
    if _参考缓存 is None:
        return 加载()
    import os
    try:
        st = os.stat(路径)
    except OSError:
        return 加载()
    键 = (种类, 路径, st.st_mtime_ns, st.st_size, 额外键)
    if 键 not in _参考缓存:
        _参考缓存[键] = 加载()
    return _参考缓存[键]


def _加载图像(路径):
    """PIL 读图 → IMAGE [1,H,W,C] float32 0..1。同一轮内按路径+文件戳复用解码结果（B）。"""
    return _取缓存("图", 路径, None, lambda: _读图像(路径))


def _读图像(路径):
    import numpy as np
    import torch
    from PIL import Image
    arr = np.array(Image.open(路径).convert("RGB")).astype("float32") / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def _音频窗采样点(起秒, 止秒, sr, 总样本):
    """把全局时间轴秒窗 [起秒,止秒) 换算为波形采样点区间 [a,b)，两端钳到 [0,总样本]。
    起秒/止秒 任一为 None → (0,总样本)（整段、不切）。纯逻辑可测（B：每段引用音频对应分段）。"""
    if 起秒 is None or 止秒 is None:
        return 0, 总样本
    a = min(max(0, int(round(起秒 * sr))), 总样本)
    b = min(max(a, int(round(止秒 * sr))), 总样本)
    return a, b


# 模块级缓存：ffmpeg 可执行文件路径（首次定位后复用，与 ComfyUI-Artificial-Intelligence 同源）
_FFMPEG_EXE = None


def _定位ffmpeg():
    """定位 ffmpeg 可执行文件：优先系统 PATH（秋叶整合包自带），
    官方便携版/桌面版无 ffmpeg 时回退 imageio-ffmpeg 内置的可执行文件。
    与 ComfyUI-Artificial-Intelligence 的 加载音频节点 同源，避开 torchaudio/torchcodec/FFmpeg DLL 链。"""
    global _FFMPEG_EXE
    if _FFMPEG_EXE is None:
        import shutil
        exe = shutil.which("ffmpeg")
        if not exe:
            try:
                import imageio_ffmpeg
                exe = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                raise RuntimeError(
                    "未找到 ffmpeg：请安装 ffmpeg 并加入系统 PATH，"
                    "或在 ComfyUI 主环境执行 pip install imageio-ffmpeg"
                )
        _FFMPEG_EXE = exe
    return _FFMPEG_EXE


def _读音频张量(路径):
    """使用 soundfile 读取音频，避免 torchaudio 的 torchcodec 后端依赖。
    返回 (waveform[C,L], sample_rate)，与 torchaudio.load 形状一致。
    soundfile 不支持的格式（如 m4a/aac/视频音轨）自动用 ffmpeg 转码为 wav 后再读取。

    B：缓存的是**整条**解码结果，不含时间窗——「全段共用」ON 时每段的窗不同，若把窗
    放进键就完全失不掉重复解码；切窗在 _加载音频 里做（返回视图，不额外占内存）。"""
    return _取缓存("音", 路径, None, lambda: _解码音频(路径))


def _解码音频(路径):
    import soundfile as sf
    import torch
    try:
        data, sr = sf.read(路径, dtype="float32", always_2d=True)
    except Exception:
        # 回退：ffmpeg 转 WAV（m4a/aac/视频音轨等 soundfile 不直接支持的格式）
        # 3.2(111)：抽为 _ffmpeg转码wav，统一 timeout / 返回码 / stderr 捕获 / .part 原子发布
        # / 失败清理 与完整缓存复用、坏缓存自愈。
        temp_wav = _ffmpeg转码wav(路径)
        data, sr = sf.read(temp_wav, dtype="float32", always_2d=True)
    # sf.read(always_2d=True) 返回 (frames, channels)，转置为 (channels, frames)
    wave = torch.from_numpy(data.T).contiguous()
    return wave, sr


def _ffmpeg转码wav(路径, 超时秒=120):
    """3.2(111)：ffmpeg 转 WAV 的加固助手（`_解码音频` soundfile 不直接支持时的回退路径）。

    返回可直接交给 `sf.read` 的 temp_wav 绝对路径。契约：
      • 命中完整缓存（temp_wav 存在且 size > 44）→ 直接返回，不起子进程（同名覆盖后
        mtime_ns+size 变→哈希变→自动失效，保留原语义）。
      • 坏缓存（存在但 size ≤ 44，只有 WAV 头或上次崩后的截断产物）→ 删除重转。
      • 转码写到 `f"{temp_wav}.{pid}.{序号}.part"` 临时文件，成功后 `os.replace` 原子发布；
        失败/超时/返回码非零/产物过短一律抛 ValueError（与上层 ValueError-only 契约对齐），
        并在 finally 里清理 .part，不让半截产物污染最终缓存。
      • 超时：subprocess.TimeoutExpired → ValueError（点名 超时秒）。
      • 返回码非零：ValueError，携 stderr 尾部 500 字供排障（之前 DEVNULL 造成“ffmpeg 失败
        但插件不知何故”的目盲）。无 GPU/无 ffmpeg 环境不预先报错（`_定位ffmpeg` 依旧延迟到子进
        程启动时才抛 RuntimeError，保留给用户的引导文案）。
    与 段缓存.写缓存 同模式（.part + os.replace + finally），pid+序号 同源保证并发不互踩。"""
    import os
    import hashlib
    import subprocess
    import folder_paths
    temp_dir = folder_paths.get_temp_directory()
    # 文件戳进哈希：源文件被同名覆盖后转码缓存自动失效
    st = os.stat(路径)
    戳 = f"{st.st_mtime_ns}_{st.st_size}"
    h = hashlib.md5(f"{路径}_{戳}".encode("utf-8")).hexdigest()
    temp_wav = os.path.join(temp_dir, f"lvp_sf_decode_{h}.wav")
    # 完整缓存复用：存在且 > 44 字节（>44 才能含至少一帧样本，不是只 WAV 头）
    try:
        if os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 44:
            return temp_wav
    except OSError:
        pass  # stat 竞态（发则删）→ 当作不存在，走重转分支
    # 坏缓存（存在但 ≤ 44）：删掉重转（保留原 ≤44 语义）
    if os.path.exists(temp_wav):
        try:
            os.remove(temp_wav)
        except OSError:
            pass
    部分 = f"{temp_wav}.{os.getpid()}.{next(_临时序号)}.part"
    cmd = [_定位ffmpeg(), "-y", "-i", 路径, "-vn", "-acodec", "pcm_s16le", 部分]
    try:
        try:
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               text=True, timeout=超时秒)
        except subprocess.TimeoutExpired:
            raise ValueError(f"ffmpeg 转码超时（>{超时秒}s）：{路径}")
        if r.returncode != 0:
            尾 = (r.stderr or "").strip()[-500:]
            raise ValueError(f"ffmpeg 转码失败（返回码 {r.returncode}）：{路径}\n{尾}")
        try:
            大小 = os.path.getsize(部分)
        except OSError:
            大小 = 0
        if 大小 <= 44:
            raise ValueError(f"ffmpeg 输出过短（{大小}B，疑似截断）：{路径}")
        os.replace(部分, temp_wav)   # 原子发布：只有到此步才会让 temp_wav 可见
        部分 = None                  # 已改名，finally 不再删
        return temp_wav
    finally:
        if 部分 and os.path.exists(部分):
            try:
                os.remove(部分)
            except OSError:
                pass


def _加载音频(路径, 起秒=None, 止秒=None):
    """soundfile 读音频（+ ffmpeg 回退）→ AUDIO {waveform[1,C,L], sample_rate}。
    避开 torchaudio 2.9 的 torchcodec 后端依赖（需 FFmpeg full-shared DLL，用户环境常缺）。
    与 ComfyUI-Artificial-Intelligence 的 加载音频节点 同源技术栈。

    起秒/止秒（全局时间轴秒窗）给定时只切出对应分段——B（并入「全段共用」）：参考共用 ON
    后每段仅引用自己 [start,end) 那段音频。止秒超出音频实际长度自动钳到末尾；"超过视频
    总时长的音频不引用"由逐段切片天然满足（末段 end=总时长，其后音频永不落入任何段窗）。
    切后为空（段窗整体落在音频长度之外）→ 返回 None，上层 组装参考入参 丢弃该参考音频。"""
    wave, sr = _读音频张量(路径)          # [C,L]
    a, b = _音频窗采样点(起秒, 止秒, sr, wave.shape[-1])
    if 起秒 is not None and 止秒 is not None and b <= a:
        return None                            # 空窗：该段不引用此音频
    return {"waveform": wave[:, a:b].unsqueeze(0), "sample_rate": sr}


def _加载视频帧(路径, fps=24, 上限秒=15):
    """imageio 读视频 → IMAGE [T,H,W,C] float32 0..1（官方参考视频按 24fps、2-15s，>=5 帧）。
    依赖可选视频后端（imageio-ffmpeg 或 av）；缺失时由上层降级为「无视频参考」。

    C（内存）：**逐帧解码后立即缩放到官方目标画布**，不把源分辨率整段堆进内存——
    4K/15s 按源分辨率是 ~36GB float32（1080p 也 ~9GB，且旧版 np.stack 还多一份峰值副本），
    缩到 1344x768 后 ~4.5GB。⚠️ 此 1344x768 是**参考视频画布**的典型值（由源视频自身尺寸经
    _参考视频画布 推导），与主画布无关、不随「输出分辨率/百万像素」变（主画布默认 864x480）。
    目标画布与缩放算法逐行复刻官方 nodes_minimax_h3.py L318-323，
    故官方节点随后那次**同尺寸** _resize 是逐位恒等变换（comfy.utils.lanczos 先量化到
    uint8，而本函数产出的正是 uint8/255，round-trip 无损；PIL 同尺寸 resize 直接 copy），
    产物与「不预缩放」逐位相同——无需动段缓存指纹。B：同一轮内按路径+文件戳复用。"""
    return _取缓存("视", 路径, (fps, 上限秒), lambda: _读视频帧(路径, fps, 上限秒))


def _参考视频画布(源宽, 源高):
    """官方 MiniMaxH3ReferenceToVideo.execute L318-322 的目标画布推导（逐行复刻）：
    先 对齐画布（=官方 adapt_canvas），若源面积小于它（小视频不该被放大）则退回
    「源尺寸按 32 取整」。CANVAS_MULTIPLE 取自 采样与解码（单一真源，不散落魔法）。"""
    cw, ch = 对齐画布(源宽, 源高)
    if 源宽 * 源高 < cw * ch:
        cw = max(CANVAS_MULTIPLE, round(源宽 / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
        ch = max(CANVAS_MULTIPLE, round(源高 / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
    return cw, ch


_缩放降级已告警 = False   # _缩放到画布 逐帧调用 → 只告警一次，免得 360 帧刷 360 条同样的日志


def _缩放到画布(帧, 宽, 高):
    """与官方 nodes_minimax_h3._resize(..., crop="disabled") 走同一条
    comfy.utils.common_upscale("lanczos") 路径，保证预缩放与官方缩放逐位一致。
    逐帧调用与官方批量调用结果相同：lanczos() 内部就是逐张 PIL Image.resize。
    `[..., :3]` 对齐官方 _resize（L68 先砍到 3 通道再缩放），维持两者逐行对应；入参已由
    _读视频帧 在解码处砍过，故此处**幂等**——保留它是为了不让「与官方逐位一致」的论证
    反过来依赖调用方，也不致改走 PIL 的 RGBA resize 路径而与 RGB 路径产生差异。
    comfy.utils 不可导入时退回原尺寸并告警一次——此时官方节点仍会自己缩放，产物正确、
    只是 C 项内存优化整体失效；不告警的话用户只会看到内存暴涨而无从定位。"""
    global _缩放降级已告警
    try:
        from comfy.utils import common_upscale
    except ImportError:
        if not _缩放降级已告警:
            _缩放降级已告警 = True
            _日志.warning("comfy.utils 不可导入，参考视频预缩放跳过（内存优化失效，产物仍正确）")
        return 帧
    return common_upscale(帧[..., :3].movedim(-1, 1), 宽, 高, "lanczos", "disabled").movedim(1, -1)


def _探测源fps(路径, iio):
    """3.2(110)：读源视频 fps，供参考视频按时间重采样。imageio 的 `immeta()` 在 pyav /
    imageio-ffmpeg 后端会给 "fps" 字段；无后端、字段缺失、非数字、非正或 NaN 都返回 None
    → 上层走「告警 + 回退旧按帧数」分支。任何异常均吞掉（包括旧版 imageio 无 immeta 属性的
    AttributeError）：_读视频帧 不能因元数据探测失败而冒泡。"""
    try:
        meta = iio.immeta(路径)
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    f = meta.get("fps") or meta.get("frame_rate")
    if f is None:
        return None
    try:
        f = float(f)
    except (TypeError, ValueError):
        return None
    if not (f > 0):        # NaN 与 <=0 同时命中
        return None
    return f


def _读视频帧(路径, fps, 上限秒):
    import numpy as np
    import torch
    import imageio.v3 as iio

    输出上限 = int(上限秒 * fps)
    目标 = None

    def 处理(f):
        nonlocal 目标
        # [..., :3] 在解码处就砍掉 alpha：本函数有「缩放」与「原尺寸直通」两条路径（源尺寸
        # 恰等于目标画布时不缩放，如源就是 1344x768），只在 _缩放到画布 里砍会漏掉直通
        # 路径 → RGBA 素材两条路径通道数不一致。放这里则全路径统一 3 通道，且省 25% 内存。
        # 前提：视频后端（imageio-ffmpeg / av）恒以 rgb24 或 rgba 出帧，末维必为通道维。
        t = torch.from_numpy(np.array(f).astype("float32") / 255.0).unsqueeze(0)[..., :3]   # [1,H,W,3]
        if 目标 is None:
            目标 = _参考视频画布(t.shape[2], t.shape[1])     # 画布只看首帧尺寸，全片统一
        if (t.shape[2], t.shape[1]) != 目标:
            t = _缩放到画布(t, 目标[0], 目标[1])
        return t

    帧 = []
    # 3.2(110)：优先按源时间戳重采样到目标 fps（默认 24）。旧行为 `for f in imiter(...)` 把
    # 「源帧数」直接当「源时长 × 目标 fps」→ 与官方参考视频时基 24fps 解耦：源 30fps 下会多采
    # 25%（时间轴偷长），源 12fps 下会少采 50%。新行为 floor(j*源fps/fps) 取源帧（流式，
    # 不缓存全片，保 C 项内存优化精精神）。探测不到时记 warning 回退旧行为（用户批准），
    # 不硬失败，兼容 imageio-ffmpeg 后端不返 fps 的老素材与 av 依赖缺失环境。
    源fps = _探测源fps(路径, iio)
    if 源fps is None:
        _日志.warning(
            "参考视频无法探测源 fps（immeta 缺失或 fps 字段无效），回退按帧数截断"
            "（源≠%dfps 时时间轴会漂移；安装 imageio-ffmpeg 或 av 并确保容器携带 fps 可解）" % int(fps)
        )
        for f in iio.imiter(路径):
            帧.append(处理(f))
            if len(帧) >= 输出上限:
                break
    else:
        it = iter(iio.imiter(路径))
        i = -1
        最后 = None
        耗尽 = False
        j = 0
        while j < 输出上限 and not 耗尽:
            目标i = int(j * 源fps / fps)
            # 单调 floor 映射：目标i >= 上轮目标i → 只需向前推进；回不去（上采样时目标i
            # 可能等于上轮 → 直接复用 最后，实现“同帧写 N 次”）。
            while i < 目标i:
                try:
                    f = next(it)
                except StopIteration:
                    耗尽 = True
                    break
                i += 1
                最后 = 处理(f)
            if 耗尽:
                break
            帧.append(最后)
            j += 1

    # torch.cat 一次分配到位，不像旧版 list[np] + np.stack 那样多出一份峰值副本。
    return torch.cat(帧) if 帧 else None



def _绝对路径(名, 媒体根):
    import os
    return 名 if os.path.isabs(名) else os.path.join(媒体根, 名)


def _确保图像(值, 媒体根):
    """首/尾帧既可能是文件名（widget），也可能是已连入的 IMAGE 张量。"""
    if 值 is None:
        return None
    return _加载图像(_绝对路径(值, 媒体根)) if isinstance(值, str) else 值


def _守卫参考长度(图片, 视频, 音频):
    """官方 MiniMaxH3ReferenceToVideo.execute 无长度校验（max=9/3 仅在 UI schema 层）：
    API 直连或 解析槽位 截断逻辑回归时，超限会静默喂进官方 Autogrow 产出错乱素材。此处显式
    守卫，阈值取自 参考素材.上限（单一真源），不硬编码 9/3。超限一律 ValueError（走项目
    ValueError-only 契约，由 Task 11 UI 边界接住）。落地位置：Task 8 §接口约束 4「必修」。"""
    if len(图片) > 上限["图片"]:
        raise ValueError(f"参考图片 {len(图片)} 张，超过官方上限 {上限['图片']}")
    if len(视频) > 上限["视频"]:
        raise ValueError(f"参考视频 {len(视频)} 段，超过官方上限 {上限['视频']}")
    if len(音频) > 上限["音频"]:
        raise ValueError(f"参考音频 {len(音频)} 段，超过官方上限 {上限['音频']}")


def _预检素材(段列表, 媒体根):
    """执行前守卫（A6）：任一 run 段的 refs 引用了 媒体根 下不存在的素材文件 → ValueError 点名该段。

    refs 的**位置就是 <Picture N>/<Video K>/<Audio J> 标签**（见 参考素材.py）；计划加载已改为
    保留缺失引用不压缩（见 计划路由.过滤缺失素材），所以拦截必须落在这里：不拦则缺失项会在
    _解析参考张量 深处抛难定位的 file-not-found，或（若上游静默剔除）使后续素材前移错指。
    只对 run 段检查（未选运行的段不参与采样）；首/尾帧已连入的 IMAGE 张量（非字符串）跳过。
    走项目 ValueError-only 契约，由 Task 11 UI 边界接住。"""
    import os
    缺失段 = []
    for seg in 段列表:
        if not seg.run:
            continue
        refs = seg.refs or {}
        槽位 = 解析槽位(refs)   # 图片/音频/视频，保持顺序（不剔除），与下游赋标签同源
        坏 = []
        for 类 in ("图片", "音频", "视频"):
            for 名 in 槽位.get(类, []):
                if not os.path.isfile(_绝对路径(名, 媒体根)):
                    坏.append(f"{类}:{名}")
        for 键 in ("首帧", "尾帧"):
            值 = refs.get(键)
            if isinstance(值, str) and 值 and not os.path.isfile(_绝对路径(值, 媒体根)):
                坏.append(f"{键}:{值}")
        if 坏:
            缺失段.append(f"段{seg.index + 1}（{'、'.join(坏)}）")
    if 缺失段:
        raise ValueError(
            "以下运行段引用了不存在的参考素材，已阻止执行以避免标签错指（请重新上传或从该段移除缺失引用）："
            + "；".join(缺失段))


def _有限(x) -> bool:
    """可转 float 且为有限数（非 NaN/Inf、非 None/字符串）→ True。"""
    import math
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _预检数值与时长(段列表, 全局参数):
    """3.1(99)：执行前校验关键数值有限、每 run 段时长为正且裁前缀后仍有有效帧，返回计划时长（秒）。

    把“深水区才能发现的坏参数”（如 NaN 时长会在 秒转帧数→round 抛难定位错、非正时长会空跑）
    提到采样前一次性 ValueError 点名（走项目 ValueError-only 契约，由 UI 边界接住）。
    仅校 run 段（未选运行不参与采样，与 _预检素材 一致）。计划时长 = Σ run 段 (end-start)（对齐/裁剪前）。"""
    for 键 in ("宽", "高", "种子", "步数", "上下文帧数", "缓存失效版本", "帧率"):
        if 键 in 全局参数 and not _有限(全局参数[键]):
            raise ValueError(f"参数「{键}」必须是有限数值，收到 {全局参数[键]!r}")
    上下文 = int(全局参数.get("上下文帧数", 默认上下文帧数))
    计划时长 = 0.0
    for seg in 段列表:
        if not seg.run:
            continue
        if not (_有限(seg.start) and _有限(seg.end)):
            raise ValueError(f"段{seg.index + 1} 起止时间非有限数：start={seg.start!r} end={seg.end!r}")
        if seg.end <= seg.start:
            raise ValueError(f"段{seg.index + 1} 结束时间须大于开始时间：[{seg.start}, {seg.end}]")
        帧 = 秒转帧数(seg.end - seg.start)
        if 帧 - 裁前缀帧数(帧, 上下文) <= 0:
            raise ValueError(
                f"段{seg.index + 1} 裁锚定前缀后无有效帧（{帧}帧、上下文{上下文}帧），"
                f"请缩短上下文帧数或加长该段时长")
        计划时长 += float(seg.end) - float(seg.start)
    return 计划时长


def _官方节点注册表():
    """读宿主 NODE_CLASS_MAPPINGS；非完整运行时（import nodes 失败/无该属性）→ None。

    宽捕获：`import nodes` 会连带拉起 comfy.model_management（可能因无 GPU / CUDA 初始化失败而抛
    RuntimeError/AssertionError 等非 ImportError），单测环境常见。本函数只作 best-effort 探测，
    任何异常都归为「无法核对」返回 None → 上游跳过预检（真正的缺节点仍会在 调用节点 处报错）。"""
    try:
        import nodes
    except Exception:  # noqa: BLE001 - best-effort 探测：详见 docstring
        return None
    映射 = getattr(nodes, "NODE_CLASS_MAPPINGS", None)
    return 映射 if isinstance(映射, dict) else None


def _预检官方节点(管线集, 需要音频):
    """3.1(99)：执行前核对所需官方节点已注册，缺失即 ValueError 点名（不跑到模型加载后才炸）。

    best-effort 降级：注册表不可读（None）或连哨兵 VAEDecode 都缺失（=comfy_extras 未加载的
    裸导入环境，如单测）→ 跳过，不误伤；真正运行时 comfy_extras 已加载，此时缺 H3 节点才是真缺。"""
    映射 = _官方节点注册表()
    if 映射 is None or "VAEDecode" not in 映射:
        return
    需要 = set(管线集) | {"KSampler", "VAEDecode"}
    if 需要音频:
        需要.add("VAEDecodeAudio")
    缺 = sorted(n for n in 需要 if n not in 映射)
    if 缺:
        raise ValueError(
            f"缺少官方节点：{', '.join(缺)}（请确认 ComfyUI 官方 MiniMax H3 节点包已安装并注册到 NODE_CLASS_MAPPINGS）")


def _解析参考张量(refs, 媒体根, prompt=None, 音频窗=None):
    """把段 refs（文件名槽位）解析并加载为官方 ReferenceToVideo 的 Autogrow 入参字典。
    v1：图片→ref_images、视频→ref_videos（仅画面帧）、音频→ref_audios（独立参考音频）；
    ref_video_audios（参考视频自带音轨配对）留待 v2。参考视频采样帧率取默认 fps=24
    （官方参考视频基座），不读用户「帧率」widget。
    音频窗=(起秒,止秒) 非空时（B：参考共用 ON）每条参考音频都按该全局时间轴窗切片后再入 ref_audios。

    I4（Task 9 code review 回灌）：解析槽位 会静默截断超限项（12 图 → 9 图）；若 prompt
    引用被丢弃项，官方 tokenizer 静默忽略 → 产物与预期不符。Task 3 预留了 校验标签 交叉
    检查（docstring 点名"Task 8/9 在把 refs 送进 Autogrow 之前调用"），本函数为唯一接入点；
    截断悬空 前移为显式 ValueError（走项目 ValueError-only 契约，Task 11 UI 边界接住）。"""
    槽位 = 解析槽位(refs)   # {图片:[名], 视频:[名], 音频:[名]}
    校验标签(prompt, 槽位)   # I4：prompt 中 <Picture N>/<Video K>/<Audio J> 必须指向留存项
    图片名 = 槽位.get("图片", [])
    视频名 = 槽位.get("视频", [])
    音频名 = 槽位.get("音频", [])
    _守卫参考长度(图片名, 视频名, 音频名)   # Task 8 §约束 4 长度守卫（防御性，见函数注释）
    图片 = [_加载图像(_绝对路径(n, 媒体根)) for n in 图片名]
    视频 = [_加载视频帧(_绝对路径(n, 媒体根)) for n in 视频名]
    # B：音频窗=(起秒,止秒) 时每条参考音频都按同一全局时间轴窗切片（“全部同样切”）；
    # 空切片的音频 _加载音频 返回 None，组装参考入参 自动丢弃（不影响图片/视频序号）。
    起秒, 止秒 = 音频窗 if 音频窗 else (None, None)
    音频 = [_加载音频(_绝对路径(n, 媒体根), 起秒, 止秒) for n in 音频名]
    return 组装参考入参(图片, 视频, None, 音频)


# ---------- 模型补丁：SigmaShift 提到段循环外 + 跨轮缓存（官方链路） ----------

def _补丁模型(model, 全局参数):
    """A：MiniMaxH3SigmaShift 提到段循环外——shift_video/shift_audio 是**全局**值，逐段调用
    只会让官方 model.clone() 每段产出一个新的 ModelPatcher 对象；而宿主
    model_management.LoadedModel.__eq__ 是按 patcher **对象身份**判「是否已加载」
    （comfy/model_management.py L836-837），身份每段都变 → 每段都走完整加载路径并把上一份
    detach（L970-975），显存紧张时 DiT 权重反复搬运、控制台每段刷一次 Requested to load。
    复用同一个 clone 即恢复 ComfyUI 节点缓存下的常态（同一 patcher 跨多次采样复用）；
    安全前提：CFGGuider 只 prepare_model_patcher + finally restore_hook_patches，不破坏性改写。

    返回的 patcher 不入段缓存指纹：shift_video/shift_audio 本身已在 采样参数 里，补丁
    只是它们的函数，不引入新维度。model 为 None（单测桩）→ 直接返回 None，不触官方节点。
    现作为 _取补丁模型 的「加载函数」：仅跨轮模型缓存未命中时才被调用 clone（见下）。"""
    if model is None:
        return None
    return 调用节点("MiniMaxH3SigmaShift", model=model,
                    shift_video=float(全局参数.get("shift_video", 12.0)),
                    shift_audio=float(全局参数.get("shift_audio", 3.0)))[0]


# A：跨轮复用「已打补丁的 model」。_补丁模型 每轮 clone 出新 ModelPatcher 身份，而宿主
#   model_management.LoadedModel.__eq__ 按对象身份判「是否已加载」→ 每轮都被当未加载、走完整
#   加载路径（detach 上一份 + 把 DiT 权重重新搬进显存）。这正是「热进程逐轮变慢、重启才快」的
#   结构性根因：重启后显存整块可用、无残留，故同一段又跑回原速。接入 模型缓存 后，同一
#   (槽, id(model), shift) 跨轮返回**同一个** patcher 对象 → 宿主认作已加载 → 跳过重载与显存乒乓。
#   双模型改造：键含「槽」(fl2va/ref2va)、_模型缓存上次键 改为 {槽: 键} 按槽各自 LRU-1——混合时间轴
#   fl2va↔ref2va 交替不再互相驱逐重载（消除抖动），任何时刻最多钉住 2 份（每槽 1 份）；单管线时间轴
#   只用到 1 槽，行为与旧版一致。宿主 model_management 仍按 refcount 顺序把非活动模型 offload 到 CPU
#   （钉住只影响卸载顺序、不阻止腾显存时卸载，见 模型缓存.py docstring 的 refcount 告诫）。
_模型缓存上次键 = {}


def _模型缓存键(槽, model, 全局参数):
    """已打补丁 model 的缓存键 = (槽, id(model), shift_video, shift_audio)。

    槽（fl2va/ref2va）隔离两管线模型，令二者可并存、互不驱逐。model 身份用 id(model)：借 ComfyUI
    对 loader 输出的对象缓存（同一 ckpt 重复跑 → 同一 ModelPatcher 对象 → id 稳定命中；换 ckpt →
    loader 重跑 → 新对象 → id 变 → 未命中重载）。原 model 被缓存值连带钉住（见 _取补丁模型），算键
    时它仍存活 → 其 id 不会被 GC 后复用 → 不会假命中。shift_video/shift_audio 改变补丁内容，必须入键。
    ⚠️ 双模型改造后已移除 模型标识(ckpt 名) 维度（ModelPatcher 通常不带 ckpt 名、探测多半落空）：同一
    槽上「换了哪个 ckpt 文件」不再被段缓存指纹感知（详 段缓存.缓存格式版本 h3-3 注释）；但本进程内
    模型缓存仍靠 id 自动重载（换 ckpt→新对象→id 变→未命中），不受影响。"""
    return (槽, f"id:{id(model)}",
            float(全局参数.get("shift_video", 12.0)),
            float(全局参数.get("shift_audio", 3.0)))


def _取补丁模型(模型输入, 全局参数, 槽):
    """跨轮取某槽「已打补丁的 model」：命中 模型缓存 即复用同一 patcher 身份，未命中才 clone。

    从 模型输入[f"{槽}_model"] 取原 model；为 None（未连接/单测桩）→ 返回 None、不触缓存，行为与
    旧版直调 _补丁模型 逐字一致。按槽 LRU-1 驱逐：本槽键与上次不同（换 ckpt/shift）先 清缓存(旧键)，
    放掉旧补丁+旧 model 的引用，宿主 free_memory 才卸得动它；**只驱逐本槽**、不动另一槽（混合时间轴
    fl2va/ref2va 交替不再互相驱逐重载）。驱逐在加载新模型**之前**，故换 ckpt 那一轮本槽不会新旧并存。
    缓存值 = (patched, model)：连带钉住原 model，防其被 GC 后 id 被新模型复用造成假命中。
    _模型缓存上次键[槽] 在 取模型 成功后才更新，加载抛错时不污染上次键（同键可安全重试，对齐 模型缓存.取模型 契约 3）。"""
    model = 模型输入.get(f"{槽}_model")
    if model is None:
        return None
    键 = _模型缓存键(槽, model, 全局参数)
    global _模型缓存上次键
    上次 = _模型缓存上次键.get(槽)
    if 上次 is not None and 上次 != 键:
        清缓存(上次)
    patched, _原model = 取模型(键, lambda: (_补丁模型(model, 全局参数), model))
    _模型缓存上次键[槽] = 键
    return patched


# ---------- B（两层缓存·同一套真实依赖，规格 §二·B）：把「影响采样的真实因素」规范化进指纹 ----------

def _可信模型身份(对象):
    """仅接受**内容绑定、跨进程稳定、可复现**的模型标识（规格 §B-2：不能只用槽名/对象 id/路径，
    也不每段扫全部权重张量）。来源=上游 loader 显式挂的可复现 token（约定属性 lvp_模型身份：
    str 或 dict）。无此类可证标识 → None（不伪造假稳定标识）；调用方据此对该输入**不新增指纹维度**，
    换 ckpt 等无法自动感知的失效由「缓存失效版本」让用户手动作废（见 提取模型链身份 docstring）。
    ⚠️ 给 loader 打 lvp_模型身份 标记（真·换 ckpt 自动失效）属后续批次，需接入 节点/官方管线适配 层。"""
    身份 = getattr(对象, "lvp_模型身份", None)
    if isinstance(身份, str) and 身份:
        return 身份
    if isinstance(身份, dict) and 身份:
        import json
        return json.dumps(身份, sort_keys=True, ensure_ascii=False)
    return None


def 提取模型链身份(模型输入, 用到槽):
    """汇总本 run 相关 模型/CLIP/VAE 的**可证**内容标识 → JSON-safe dict（可能为空）。

    空 dict = 这些输入当前无可复现标识 → 不新增指纹维度（保持既有复用行为；裸对象/未连接/桩都落此支，
    故不因子把整盘段缓存误伤为「永不命中」）。非空 = 换模型使该 dict 变 → 采样参数变 → 相关段缓存精确失效。
    None 输入（未连接/单测桩）跳过。用到槽 只取实际参与采样的模型槽，避免为不涉及的槽强求身份。"""
    身份 = {}
    for 槽 in sorted(用到槽):
        t = _可信模型身份(模型输入.get(f"{槽}_model"))
        if t:
            身份[f"{槽}_model"] = t
    for 名 in ("clip", "vae", "audio_vae"):
        t = _可信模型身份(模型输入.get(名))
        if t:
            身份[名] = t
    return 身份


def 构建采样参数(全局参数, 共用素材非空, audio_vae存在, 上下文帧数, 模型链身份, 缓存失效版本):
    """段缓存指纹的**全局依赖**描述（纯函数，JSON-safe）。作 段指纹 的 全局参数 入参。

    ⚠️ 刻意**不含「帧率」**：官方采样时基恒 FPS=24，用户「帧率」只是输出容器/封装元数据，
    不参与 秒转帧数 的帧数换算（见 采样与解码.秒转帧数）。旧版把它放进本字典 → 只改播放 fps
    也会整体作废段缓存、白白重采样（规格 §B-5）。宽/高 影响采样画布与 latent 形状，故保留。
    「缓存失效版本」与「模型链身份」是本 run 的作废/换型手段：任一变化 → 全部段指纹变（§B-2）。"""
    return {
        "宽": int(全局参数.get("宽", 1344)),
        "高": int(全局参数.get("高", 768)),
        "种子": int(全局参数.get("种子", 0)),
        "步数": int(全局参数.get("步数", 20)),
        "采样器": str(全局参数.get("采样器", "res_multistep")),
        "调度器": str(全局参数.get("调度器", "simple")),
        "shift_video": float(全局参数.get("shift_video", 12.0)),
        "shift_audio": float(全局参数.get("shift_audio", 3.0)),
        "上下文帧数": int(上下文帧数),
        "参考图尺寸": str(全局参数.get("参考图尺寸", "match")),
        "audio_vae": bool(audio_vae存在),
        "参考共用": bool(共用素材非空),
        "模型链身份": 模型链身份,
        "缓存失效版本": 缓存失效版本,
    }


def 构建段指纹源(seg, 素材摘要, 被锚定, 锚帧数, 前段指纹, 上下文帧数):
    """段级依赖描述（纯函数）→ 作 段指纹 的 seg 入参。

    在旧版 task/prompt/refs/start/end/被锚定/锚帧数/上下文帧数 基础上补两维（规格 §B-1/§B-3）：
      - 素材摘要：本段引用的每个素材文件的内容摘要（文件名不变但内容被替换 → 该段失效）。
      - 前段指纹：仅当本段被上游锚定（被锚定=True）时纳入**上一有效段落的指纹**，使上游内容变化
        沿连续链级联失效；独立段/锚定关闭（上下文帧数≤0）/链断裂处 → 前段指纹=None，不级联。
    refs 仍原样保留（位置即 <Picture N> 标签的槽位身份，见 _预检素材/解析槽位），素材摘要 只补内容维度。

    ⚠️ 锚定历史取舍（h3-5/h3-6，勿删本段）：尾帧_video 为 None 时 锚帧数 必为 0（取尾帧_latent 的
    返回契约），故一个「被锚定」布尔已足够表达旧版「被锚定 + 上段尾帧」两个同值键（h3-5 删）。h3-6
    又删了「上段尾音频」：官方 _empty_av_latent 无条件造 video+audio 两支 ⇒ audio_latent 恒非 None ⇒
    尾帧_audio is None ⟺ 尾帧_video is None，与之同值。但该键与「上段尾帧」**性质不同**（它是不同谓词，
    同值只是官方实现细节的副产物）：若官方将来把 audio 支改成条件化（如 audio_vae 未连接时只返回 video），
    **必须把「尾帧_audio is None」加回本字典**，否则「带音频锚」与「不带音频锚」的段会撞同一指纹 → 静默
    假命中（_是采样产物 查不出：形状仍合法）。改指纹 payload 必须同时升 缓存格式版本，详 段缓存.py 模块头。
    """
    return {"task": seg.task, "prompt": seg.prompt, "refs": seg.refs,
            "start": seg.start, "end": seg.end,
            "素材摘要": 素材摘要,
            "被锚定": bool(被锚定),
            "锚帧数": int(锚帧数),
            "前段指纹": (前段指纹 if 被锚定 else None),
            "上下文帧数": int(上下文帧数)}


def _内容摘要器():
    """惰性取 后端路由.媒体路由.内容摘要（与 节点 层同款相对→顶层双 import，避免模块级循环）。"""
    try:
        from ..后端路由.媒体路由 import 内容摘要
    except ImportError:
        from 后端路由.媒体路由 import 内容摘要
    return 内容摘要


def _素材摘要(refs, 媒体根, 摘要缓存):
    """把本段实际消费的素材文件（解析槽位 的 图片/音频/视频 + 首帧/尾帧字符串）映射为内容摘要。

    顺序与 解析槽位 同源（不排序/去重），使摘要与 <Picture N> 标签一一对照；同一路径的摘要按 摘要缓存
    复用（一轮内多段共享同一参考只哈希一次）。非字符串（已连入的 IMAGE 张量）跳过——与 _预检素材 一致，
    其内容属宿主输入链管理。读文件失败兜底为占位串（预检已保证 run 段文件存在；skip 段缺文件不该炸整轮）。"""
    import os
    内容摘要 = _内容摘要器()
    槽位 = 解析槽位(refs or {})
    项 = {}

    def _摘(名):
        路径 = _绝对路径(名, 媒体根)
        d = 摘要缓存.get(路径)
        if d is None:
            try:
                d = 内容摘要(路径)
            except OSError:
                d = f"<不可读:{os.path.basename(路径)}>"
            摘要缓存[路径] = d
        return d

    for 类 in ("图片", "音频", "视频"):
        名单 = 槽位.get(类) or []
        if 名单:
            项[类] = [_摘(n) for n in 名单]
    for 键 in ("首帧", "尾帧"):
        值 = (refs or {}).get(键)
        if isinstance(值, str) and 值:
            项[键] = _摘(值)
    return 项


def _人类字节(字节: int) -> str:
    """字节数转可读串（供报告§B-7 缓存体量展示）：整数量级自适应 B/KB/MB/GB，保留 1 位小数。"""
    数 = float(字节)
    for 单位 in ("B", "KB", "MB", "GB", "TB"):
        if 数 < 1024 or 单位 == "TB":
            return f"{数:.1f}{单位}" if 单位 != "B" else f"{int(数)}B"
        数 /= 1024
    return f"{数:.1f}TB"


def 估算成片内存字节(总帧数: int, 宽: int, 高: int, 通道: int = 3, 字节: int = 4) -> int:
    """3.1(100)：按 帧数×宽×高×通道×字节 估算成片 images 张量的系统内存（CPU float32 RGB）。

    纯容量上界估算，不含帧格/接缝/音频/解码中间量，**不承诺不 OOM**（见规格「容量边界」：
    180s@24fps×768×1344×RGB-f32 仅成片≈49.8GiB）。任一维非正 → 返回 0（防御：坏参数不抛，
    交由 3.1(99) 预检拒绝真实执行）。"""
    维 = (int(总帧数), int(宽), int(高), int(通道), int(字节))
    if any(x <= 0 for x in 维):
        return 0
    return 维[0] * 维[1] * 维[2] * 维[3] * 维[4]


def 内存预算报告行(总帧数, 段帧数列表, 宽, 高, 通道=3, 字节=4):
    """3.1(100)：生成内存预算观测行（纯字符串 + 成片字节数，不含预警/硬限额判断，便于单测）。

    返回 (行, 成片字节)：行含成片总量与最大单解码段量级（段以**裁前原始帧数**计，
    即解码时的峰值），并带「不保证不OOM」免责；调用方拿 成片字节 自行判断预警/硬限额。"""
    成片 = 估算成片内存字节(总帧数, 宽, 高, 通道, 字节)
    最大段 = max(段帧数列表) if 段帧数列表 else 0
    单段 = 估算成片内存字节(最大段, 宽, 高, 通道, 字节)
    行 = (f"内存预算: 成片≈{_人类字节(成片)}（{总帧数}帧×{宽}×{高}×{通道}通道×float32，"
          f"容量上界估算，不保证不OOM）｜最大解码段≈{_人类字节(单段)}（{最大段}帧）")
    return 行, 成片


# ---------- §B-4：宿主外部依赖指纹（补进 caching 签名，令同名换素材即重跑） ----------
# 缓存签名 = [class_type, fingerprint_inputs 返回值] + 全部 widget 字面值 + 连线依赖
# （见 comfy_execution/caching.py:117）。widget 值变化本就各自触发重跑，本指纹**只叠加**
# 签名里唯一缺失的一维＝「被引用素材文件的内容」：同名换内容时 时间轴数据/参考素材 widget
# 值不变、无上游依赖变化 → 宿主默认跳过 execute（连磁盘段缓存都不会去查）。补上内容维后，
# 内容一变即重跑，交由既有 素材摘要/失效版本 逻辑决定重采样范围。
_指纹摘要备忘录 = {}     # abspath -> (size, mtime_ns, digest)：跨队列按文件戳复用，稳态每轮只 os.stat


def _指纹摘要(名, 媒体根):
    """单个引用素材的内容摘要，按 (size, mtime_ns) 跨队列备忘录复用：文件未变则不重读，
    避免每次入队都把大视频整个 sha256（那会把「查缓存是否要重跑」本身变成瓶颈）。缺文件/读
    失败退化为占位 token（与 _素材摘要 同口径），逐字稳定——缺文件这种状态本身不该反复变。
    ⚠️ 同名等长且 mtime 未动的「原子覆盖」极端场景会被漏判（依赖 mtime/size）；上传同名异内容
    已被 A1 媒体路由摘要后缀改名为不同文件，本指纹主要兜住「绕过上传直接换盘上文件」。"""
    import os
    路径 = _绝对路径(名, 媒体根)
    try:
        st = os.stat(路径)
        戳 = (st.st_size, st.st_mtime_ns)
    except OSError:
        return f"<缺:{os.path.basename(路径)}>"
    旧 = _指纹摘要备忘录.get(路径)
    if 旧 is not None and 旧[0] == 戳:
        return 旧[1]
    try:
        d = _内容摘要器()(路径)
    except OSError:
        d = f"<不可读:{os.path.basename(路径)}>"
    _指纹摘要备忘录[路径] = (戳, d)
    return d


def _外部依赖指纹(时间轴数据, 媒体根, 缓存失效版本=0):
    """汇总「时间轴各段实际引用的素材文件内容摘要」→ 一个稳定短哈希，供 fingerprint_inputs 用。

    收集范围与 _素材摘要 同源（解析槽位 的图片/音频/视频 + 首帧/尾帧字符串），覆盖**所有**段
    （不分 run/skip）：skip 段素材变了也重跑，但那轮 run 段仍命中磁盘缓存（重跑＝秒级读缓存），
    代价远小于漏判。返回 sha256 前 32 位；任何异常（非法 JSON、refs 非 dict 等）一律吞成占位，
    **绝不外抛**——抛会被宿主记 NaN 而每轮无条件强制重跑（昂贵）。"""
    import hashlib
    import json
    名集 = set()
    try:
        数据 = json.loads(时间轴数据) if isinstance(时间轴数据, str) else 时间轴数据
        段组 = 数据.get("segments") if isinstance(数据, dict) else None
    except Exception:  # noqa: BLE001 - 编辑中间态/坏 JSON 走占位，绝不抛（详上）
        段组 = None
    if isinstance(段组, list):
        for seg in 段组:
            refs = seg.get("refs") if isinstance(seg, dict) else None
            if not isinstance(refs, dict):
                continue
            try:
                槽位 = 解析槽位(refs)
            except Exception:  # noqa: BLE001 - 单段 refs 结构异常不影响其余段收集
                槽位 = {}
            for 类 in ("图片", "音频", "视频"):
                for n in 槽位.get(类, []):
                    if isinstance(n, str) and n:
                        名集.add(n)
            for 键 in ("首帧", "尾帧"):
                值 = refs.get(键)
                if isinstance(值, str) and 值:
                    名集.add(值)
    tokens = sorted(_指纹摘要(n, 媒体根) for n in 名集)
    raw = f"lvp-ext-v1|失效:{int(缓存失效版本 or 0)}|" + "|".join(tokens)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ---------- 方案 B：延迟解码（采样/解码两阶段） ----------
# 每段只跑 KSampler，把 AV latent 搬到 CPU 存着（≈45MB/段@1.0MP16s）；全部采完后解除
# 模型缓存 的钉住 + 清理显存，再统一 VAEDecode（images ≈GB/段）。三条收益：
#   1. 段循环里不再驻留 GB 级 images → 16GB 卡跑 1.0MP@16s 不再把 DiT 挤到反复 offload；
#   2. 解码独占空显存 → 实测 AV 解码 839s 回到 ~52s 量级；
#   3. 尾帧锚定直接切 latent（段间连续.钉入上下文_from_latent），省掉 decode→encode 往返。
# latent 累积：10 段 × 45MB ≈ 450MB（CPU 内存），对照 images 的 10 × 4.8GB ≈ 48GB。


def _拆_av_latent(sampled):
    """KSampler 输出的 AV 嵌套 latent → (video, audio) 两张普通张量；audio 缺失返回 None。

    为什么必须拆：段缓存 用 torch.load(weights_only=True) 读回，而 comfy.nested_tensor.NestedTensor
    是自定义类、不在其白名单里 → 整个嵌套对象落盘就永远读不回来（每次都被当坏缓存删掉重算）。
    拆成纯张量字典后 weights_only 放行，用前再经 _建_av_latent 还原。"""
    samples = sampled["samples"]
    if not getattr(samples, "is_nested", False):
        return samples, None
    tensors = samples.tensors
    return tensors[0], (tensors[1] if len(tensors) > 1 else None)


def _建_av_latent(video_latent, audio_latent):
    """_拆_av_latent 的逆：还原官方 VAEDecode / VAEDecodeAudio 认的 {"samples": NestedTensor}。
    两个节点分别取 unbind()[0] / unbind()[-1]，故张量顺序必须 (video, audio)。"""
    from comfy.nested_tensor import NestedTensor
    张量 = [video_latent] if audio_latent is None else [video_latent, audio_latent]
    return {"samples": NestedTensor(张量)}


def _采样段(seg, 全局参数, 模型输入, 尾帧_video, 尾帧_audio, 锚帧数, 媒体根):
    """方案 B Phase 1：走官方 H3 链路跑到 KSampler 为止，返回 CPU 上的 AV latent（不解码）。

    帧数一律经 秒转帧数 拿（→ 对齐帧数(round(秒*FPS=24))）：官方模型时间基座恒 FPS=24，
    与用户 widget「帧率」解耦（后者只影响输出容器 fps 标签，不参与帧数换算）。详见
    采样与解码.秒转帧数 docstring 与 Task 4 §接口约束。

    尾帧_video/尾帧_audio/锚帧数 由 执行时间轴 从上一段产物经 取尾帧_latent 取得后传入：
    锚帧数 同时是段缓存指纹的一维，「指纹算的」与「真锚的」必须是同一个值，故不在本函数内重算。

    返回: {"video_latent": Tensor(cpu), "audio_latent": Tensor(cpu)|None,
           "锚帧数": int, "帧数": int, "index": int}
    —— 纯张量 + 标量，可直接 torch.save/load(weights_only=True)（见 _拆_av_latent）。"""
    帧数 = 秒转帧数(seg.end - seg.start)
    计时 = _计时开启()                     # 诊断计时开关（环境变量 H3_计时，默认关，见 _计时开启）
    时刻0 = time.perf_counter()            # ① 参考解码起点（含全局参数读取 + 下方 if/else 里的素材加载）
    # 主画布**原样透传** 分辨率到宽高 的产出，不过 对齐画布：官方 adapt_canvas 的唯一调用点是
    # MiniMaxH3ReferenceToVideo.execute L319 的参考视频循环（只规范参考视频），主画布走
    # _empty_av_latent(width, height, length) → torch.zeros([B,24,latent_t,h//16,w//16]) 直接用
    # 用户值。此前多过一次 adapt_canvas 会抹平「百万像素」预算（短边恒 768 → 16:9 下 0.4MP 与
    # 1.0MP 产物几乎同尺寸，9:16+0.4MP 本该 480x864 却被托到 768x1376）。
    # 合法性由上游保证：分辨率到宽高 的 multiple=CANVAS_MULTIPLE(32) → 宽高必为 32 倍数且 ≥32
    # （latent 取 h//16，32 倍数是硬要求）；面积上限则由「百万像素」widget 的 max 兜。
    # ⚠️ 对齐画布 仍被 _参考视频画布 使用（L211），删本行不等于删 import。
    宽, 高 = int(全局参数.get("宽", 1344)), int(全局参数.get("高", 768))
    model, clip, vae = 模型输入["model"], 模型输入["clip"], 模型输入["vae"]
    audio_vae = 模型输入.get("audio_vae")

    # 1) SigmaShift 补丁模型：由 执行时间轴 在段循环外算好后经 模型输入["model_p"] 传入（A）。
    #    键不存在 = 直调本函数的单测/外部路径 → 就地补算，行为与旧版一致。
    model_p = 模型输入["model_p"] if "model_p" in 模型输入 else _补丁模型(model, 全局参数)

    # 2) 条件节点：产 positive 条件 + AV 空 latent（官方只输出 positive）
    管线 = 选管线(seg.task)
    if 管线 == "MiniMaxH3ImageToVideo":
        kw = dict(clip=clip, vae=vae, prompt=seg.prompt, width=宽, height=高, length=帧数)
        首 = _确保图像(seg.refs.get("首帧"), 媒体根)
        尾 = _确保图像(seg.refs.get("尾帧"), 媒体根)
        if 需要首帧(seg.task) and 首 is not None:
            kw["first_frame"] = 首
        if 需要尾帧(seg.task) and 尾 is not None:
            kw["last_frame"] = 尾
    else:  # MiniMaxH3ReferenceToVideo
        kw = dict(clip=clip, vae=vae, audio_vae=audio_vae, prompt=seg.prompt,
                  width=宽, height=高, length=帧数,
                  ref_image_size=全局参数.get("参考图尺寸", "match"))
        # B（并入「全段共用」）：参考共用 ON 时每段只引用自己 [start,end) 那段参考音频
        # （按全局时间轴切片）；OFF 时 音频窗=None → 整段引用（现状不变）。start/end 与
        # 视频段时间轴同源（状态栏面板.js 建段 start=i*5、end=i*5+5，全局累计秒）。
        音频窗 = (seg.start, seg.end) if 全局参数.get("参考共用") else None
        kw.update(_解析参考张量(seg.refs, 媒体根, seg.prompt, 音频窗=音频窗))
    时刻1 = time.perf_counter()            # ① 参考解码止（素材已解码完毕）/ ② 条件节点起
    positive, latent = 调用节点(管线, **kw)[:2]
    时刻2 = time.perf_counter()            # ② 条件节点止（含 CLIP/VAE 编码，首段还含其加载）

    # 3) 段间连续：把上段尾帧 latent 锚到本段 frame_idx=0（等价官方 AddGuide，免 encode 往返）
    if 尾帧_video is not None:
        positive = 钉入上下文_from_latent(positive, latent, 尾帧_video, 尾帧_audio, 锚帧数, frame_idx=0)
    时刻3 = time.perf_counter()            # ③ 段间连续止

    # 4) KSampler：cfg=1.0 → negative 被忽略，故 negative 复用 positive；
    #    采样器/调度器 由节点 widget 经 全局参数 传入（默认 res_multistep/simple 与历史硬编码一致）。
    sampled = 调用节点("KSampler", model=model_p,
                       seed=int(全局参数.get("种子", 0)) + seg.index,
                       steps=int(全局参数.get("步数", 20)), cfg=1.0,   # fallback 与 长视频规划师「步数」default 同步
                       sampler_name=全局参数.get("采样器", "res_multistep"),
                       scheduler=全局参数.get("调度器", "simple"),
                       positive=positive, negative=positive,
                       latent_image=latent, denoise=1.0)[0]
    时刻4 = time.perf_counter()            # ④ KSampler 止（首段含 DiT 加载，后续段为纯采样计算）

    # 5) 拆嵌套 + 搬 CPU：latent 要跨整轮存活（Phase 2 才解码），留在显存里 N 段就把方案 B
    #    省下的空间吃回去；且段缓存落盘必须是纯张量（weights_only=True 不认 NestedTensor）。
    #    .cpu() 是同步 D2H 拷贝，45MB 量级可忽略；解码侧 comfy VAE.decode 自带 .to(self.device)。
    video_latent, audio_latent = _拆_av_latent(sampled)
    产物 = {"video_latent": video_latent.cpu(),
            "audio_latent": audio_latent.cpu() if audio_latent is not None else None,
            "锚帧数": int(锚帧数), "帧数": 帧数, "index": seg.index}
    if 计时:
        # 惰性 %s（日志规范）：级别被过滤时不拼串。首段 = 本槽(fl2va/ref2va)首个真采样段（②④ 含
        # 该模型首次加载），由 执行时间轴 经 模型输入[_计时首段] 标注；直调本函数的单测/外部路径
        # 无此键 → 默认 False。据此区分「模型加载」(首段②④偏大) vs「采样计算」(后续段④)
        # vs「素材解码」(①)；⑤AV解码 由 _解码段 单独输出（方案 B 下它已不在段循环里，故不计入合计）。
        # 四段区间首尾相接 → ①+②+③+④ 恒等于合计（旧版素材加载落在时刻1→时刻2 的盲区，
        # 造成 ① 结构性恒 0.00s 而合计里却包含它，无法靠日志定位素材开销）。
        _日志.info(
            "段%d 采样计时[%s]: ①参考解码=%.2fs ②条件节点=%.2fs ③段间连续=%.2fs ④KSampler=%.2fs 合计=%.2fs",
            seg.index + 1, "首段" if 模型输入.get("_计时首段") else "后续段",
            时刻1 - 时刻0, 时刻2 - 时刻1, 时刻3 - 时刻2, 时刻4 - 时刻3, 时刻4 - 时刻0)
    return 产物


def _解码段(采样产物, vae, audio_vae):
    """方案 B Phase 2：把 _采样段 存下的 AV latent 解码成 images/audio。

    返回 {images, audio, 锚帧数, 帧数}——下游 _裁并拼 / 流式拼接 / _拼接音频 认的就是这个段产物
    形状（锚帧数 从采样产物原样带过来，供 _裁并拼 裁掉被锚定的重复前缀）。
    统一解码阶段调用：此时 DiT/CLIP 已让出显存，不再触发 offload。"""
    计时 = _计时开启()
    时刻0 = time.perf_counter()            # ⑤ AV 解码起
    av_latent = _建_av_latent(采样产物["video_latent"], 采样产物.get("audio_latent"))
    images, audio = 解码音视频(av_latent, vae, audio_vae)
    if 计时:
        _日志.info("段%d 解码计时: ⑤AV解码=%.2fs",
                   采样产物.get("index", -1) + 1, time.perf_counter() - 时刻0)
    return {"images": images, "audio": audio,
            "锚帧数": int(采样产物.get("锚帧数", 0)), "帧数": int(采样产物.get("帧数", 0))}


def _查找共用素材(segments, 全局参数):
    """查找段级「全段共用」标记：第一个 refs.共用=True 的段的素材将覆盖所有段。

    优先级：段级 refs.共用 > 全局 widget 参考共用（向后兼容）。
    返回共用素材 dict（图片/音频/视频）或 None（无共用）。"""
    for seg in segments:
        refs = seg.refs or {}
        if refs.get("共用"):
            return {k: (refs.get(k) or []) for k in ("图片", "音频", "视频")}
    # 旧版兼容：全局 参考共用=True 时用全局素材池覆盖所有段
    if 全局参数.get("参考共用"):
        import json as _json
        v = 全局参数.get("参考素材")
        if isinstance(v, str):
            try:
                v = _json.loads(v or "{}")
            except (ValueError, TypeError):
                v = {}
        return v if isinstance(v, dict) else {}
    return None


def _应用全局(seg, 全局参数, 共用素材=None):
    """把状态栏全局 widgets 合并进段（SegmentPlan 不可变，返回副本）：
    运行选择→run（Run-select）、全局提示词→prompt 前缀、参考素材→refs 兜底、任务类型→默认 task。

    共用素材 非空时（某段开了全段共用）：该素材覆盖所有段的 图片/音频/视频；
    共用素材=None 时：段级 refs 已有的素材保留，全局素材仅兜底缺失的键。"""
    import dataclasses
    import json

    def _读json(v):
        """I3（Task 9 code review 回灌）：归一为非 None dict，避免 AttributeError 越过
        ValueError-only 契约。json.loads("null")→None、json.loads("[]")→list、json.loads("3")→int
        都会让消费者 .get/.items 抛 AttributeError，Task 11 UI 边界 catch 不住。归一为 {} 保证
        消费侧无论入参如何都能 .get/.items 不抛（行为等同于未配全局）。"""
        if isinstance(v, str):
            try:
                # try 体仅 v or "{}"（v 已是 str，恒不抛）+ json.loads（第三方）；
                # 收窄到 (ValueError, TypeError)：JSONDecodeError ⊂ ValueError，TypeError 兜非预期入参，
                # 不吞 AttributeError/NameError 等我方真 bug。见报告对 spec 宽 catch 的判断说明。
                v = json.loads(v or "{}")
            except (ValueError, TypeError):
                return {}
        return v if isinstance(v, dict) else {}

    运行选择 = _读json(全局参数.get("运行选择"))
    run = 运行选择.get(str(seg.index), 运行选择.get(seg.index, seg.run))
    全局提示词 = (全局参数.get("全局提示词") or "").strip()
    prompt = f"{全局提示词}\n{seg.prompt}".strip() if 全局提示词 else seg.prompt
    task = seg.task or 全局参数.get("默认任务") or "t2v"
    refs = dict(seg.refs or {})
    # 移除非素材键（段级共用标记不传给下游 解析槽位/组装参考入参）
    refs.pop("共用", None)
    if 共用素材 is not None:
        # 有段开了全段共用：用共用段的素材覆盖所有段的 图片/音频/视频
        refs.update(共用素材)
    elif 全局参数.get("参考共用"):
        # 向后兼容：直调本函数（未经 执行时间轴 的 _查找共用素材）时仍尊重全局 参考共用 标记
        全局素材 = _读json(全局参数.get("参考素材"))
        refs.update(全局素材)
    else:
        # 无共用：段级素材已在 refs 中，全局素材仅兜底缺失的键（向后兼容旧计划）
        全局素材 = _读json(全局参数.get("参考素材"))
        for k, v in 全局素材.items():
            refs.setdefault(k, v)
    return dataclasses.replace(seg, run=bool(run), prompt=prompt, task=task, refs=refs)


def _是采样产物(产物) -> bool:
    """段缓存读回的对象是否为本版本的采样产物（h3-4：扁平 latent 字典 + 标量）。

    缓存格式版本 升版后旧文件不再被同一指纹命中，本判定只防「文件被外力改坏」或「日后改
    schema 忘了升版」：那种情况下 读缓存 会成功返回一个键不对的 dict，直接下标就是在主循环
    深处抛 KeyError，越过项目的 ValueError-only 契约。判为未命中 → 重算，本次自然修复。

    ⚠️ **三条缺一不可，第三条（自洽）尤其不能省**：`帧数` 与 `video_latent` 的 T_lat 必须同源。
    生产里 `帧数 = 秒转帧数(…)` 已上抬到 17k+5 网格、T_lat 由官方 `video_latent_t(帧数)` 定，
    故 `_latent_t_转帧数(T_lat) == 帧数` **严格成立**（17k+5 ↔ 5k+2 互逆）。
    只查前两条时，一个「键都对、但 帧数 与 latent 时长不自洽」的坏文件会一路通过本守卫 →
    Phase 2 的 `预算总帧数` 按 `帧数` 预分配成片、而 VAE 实际解码出 `_latent_t_转帧数(T_lat)` 帧
    → `流式拼接._容得下` 抛 ValueError。那已是 **Phase 1 全跑完（1.0MP@16s 七段 ≈4.4 小时）之后**，
    且坏文件仍在盘上 ⇒ 重跑立刻在同一处再抛，形成**必须手动清目录才能解开的硬锁**。
    放在这里判未命中，代价只是一次重算（与「坏文件自愈返回 None」同一处置）。"""
    if not (isinstance(产物, dict)
            and getattr(产物.get("video_latent"), "ndim", 0) == 5
            and isinstance(产物.get("帧数"), int)):
        return False
    return _latent_t_转帧数(int(产物["video_latent"].shape[2])) == 产物["帧数"]


def 执行时间轴(时间轴数据, 全局参数, 模型输入, node_id, 媒体根, 进度回调=None, run_id=None):
    """公开入口（3.2(108)）：在主体外围加一层 try/finally 兜底——无论成功/异常/取消，
    都向宿主完整归还 CUDA 显存池（清理显存 缺省 归还缓存=True），避免异常路径下长期占住
    影响下游节点与其他工作流。

    铁律：finally 不 catch 任何异常（取消 KeyboardInterrupt 等属 BaseException，原样上抛）；
    不强清 模型缓存/段缓存（同轮重试仍需它们）。完整归还在本 finally 仅一次，内部不再重复。
    主体编排见 _执行时间轴内部。"""
    try:
        return _执行时间轴内部(时间轴数据, 全局参数, 模型输入, node_id, 媒体根,
                              进度回调=进度回调, run_id=run_id)
    finally:
        # D（上提至外层 finally）：整轮结束才完整归还——参考缓存已随 with 退出丢引用、
        # latent 已解码或异常已出栈，gc 能真正回收，再把空出的池交还下游（VideoCombine/SaveAudio 等）。
        清理显存()


def _执行时间轴内部(时间轴数据, 全局参数, 模型输入, node_id, 媒体根, 进度回调=None, run_id=None):
    """主入口：返回 (images, audio, report)。GPU 集成验证。
    媒体根＝参考素材文件名的解析根目录（见 后端路由/媒体路由.py 的 媒体根()）。
    run_id（3.1(98)）：本轮运行的短标识（默认 uuid4().hex[:8]），随进度事件下发供前端丢弃 stale
    回调（多轮预取或用户取消后旧 websocket 事件延迟到达时的去抖定位）。测试传固定值可验证事件。

    方案 B 两阶段（详见模块头）：
      Phase 1 逐段采样，只把 AV latent 搬到 CPU 攒着（几十 MB/段）；段间锚定直接切上段
              尾帧 latent（取尾帧_latent → 钉入上下文_from_latent），不经 decode→encode。
      Phase 2 全部采完后解除 模型缓存 对 DiT 的钉住 + 清理显存，再逐段 VAEDecode、裁前缀、
              流式写入预分配成片（流式拼接，峰值内存 = 成片 + 当前段）。
    进度（3.1(98) 两阶段模型）：max 恒为 2×N（N=段列表长度），Phase 1 每段一步（值 1..N），
    Phase 2 每解码段一步（值 N+1..N+M，M=采样产物列表长度 ≤N）；整体完成只在最终输出就绪时
    补一个 完成 事件（值 = max）。事件信息 payload 携 {run, stage, segment, stage_done, stage_total}，
    旧字段 value/max 保留（前端未升级仍可当“通用进度条”）。"""
    plan = 解析时间轴(时间轴数据)
    上下文帧数 = int(全局参数.get("上下文帧数", 默认上下文帧数))
    共用素材 = _查找共用素材(plan.segments, 全局参数)
    # 同步到全局参数副本：_采样段 的音频窗切片据此判断是否启用（段级共用 ON 等同全局共用 ON）
    全局参数 = dict(全局参数)
    全局参数["参考共用"] = 共用素材 is not None

    段列表 = [_应用全局(s, 全局参数, 共用素材) for s in plan.segments]
    用到槽 = {选模型槽(s.task) for s in 段列表 if s.run}
    for 槽 in sorted(用到槽):
        if 模型输入.get(f"{槽}_model") is None:
            涉及 = sorted({s.task for s in 段列表 if s.run and 选模型槽(s.task) == 槽})
            raise ValueError(
                f"时间轴含 {槽} 管线任务（{', '.join(涉及)}），但「{槽}模型」输入未连接；"
                f"请连接对应模型，或移除/改型该类任务段")

    # A6：采样前统一校验各 run 段 refs 都能解析到实文件，缺失即 ValueError 点名段（不跑一半才炸）。
    _预检素材(段列表, 媒体根)

    # 3.1(99)：采样前的数值/时长/官方节点预检（有限性、正时长、裁前缀后有效帧、节点注册）；
    # 计划时长（对齐/裁剪前）一路带到尾部供三时长报告。
    计划时长 = _预检数值与时长(段列表, 全局参数)
    _预检官方节点({选管线(s.task) for s in 段列表 if s.run},
                  需要音频=模型输入.get("audio_vae") is not None)

    # B（§二·B）：段缓存全局依赖 = 影响采样的参数（**不含播放 fps**）+ 可证模型链身份 + 缓存失效版本。
    # 模型链身份须在 用到槽 之后算（只覆盖实际参与采样的槽）；播放 fps 仅进输出元数据，不进此键。
    缓存失效版本 = int(全局参数.get("缓存失效版本", 0))
    模型链身份 = 提取模型链身份(模型输入, 用到槽)
    采样参数 = 构建采样参数(全局参数, 共用素材 is not None,
                            模型输入.get("audio_vae") is not None,
                            上下文帧数, 模型链身份, 缓存失效版本)

    # 3.1(97)：缓存IO / 解码循环 / 拼接 的分项计时累加器（同 _采样段 既有风格：始终累加、
    # 只在 _计时开启 时输出；perf_counter 非同步、开销可忽略，符合「普通运行不强制同步」）。
    计时 = _计时开启()
    计时计 = {"读秒": 0.0, "读次": 0, "写秒": 0.0, "写次": 0,
             "解码秒": 0.0, "解码次": 0, "拼接秒": 0.0}

    def _读段缓存(index, 指纹):
        """读缓存 + 形状校验（见 _是采样产物）：不符即当未命中返回 None。"""
        起 = time.perf_counter()
        产物 = 读缓存(node_id, index, 指纹)
        计时计["读秒"] += time.perf_counter() - 起
        计时计["读次"] += 1
        return 产物 if _是采样产物(产物) else None

    采样产物列表 = []      # Phase 1 产出：CPU 上的 AV latent（跨整轮存活）
    报告行 = []
    采样数 = 命中数 = 跳过数 = 0   # §B-7 可观测性：本轮三类段计数（进报告末尾统计行）
    补丁 = {}
    尾帧_video = 尾帧_audio = None      # 上一段的锚素材 latent（首段/断裂处为 None）
    尾帧锚帧数 = 0
    前段指纹 = None                     # 上一有效段落的指纹：锚定段纳入它以级联失效（§B-3）；链断裂即清空
    摘要缓存 = {}                       # 本 run 内按绝对路径复用素材内容摘要（多段共享同一参考只哈希一次）
    # 3.1(98)：两阶段进度模型（max=2×段列表长度，完成事件在 images 就绪时补发）
    采样段数 = len(段列表)               # Phase 1 上界：每段 1 步（skip 无缓存仍占一步，不致卡进度）
    总步数 = 2 * 采样段数                 # 两阶段固定上界，完成 事件 值 = 总步数 = max
    运行标识 = run_id if run_id is not None else __import__("uuid").uuid4().hex[:8]

    def _发进度(值, 阶段, 段, 已完成, 段总):
        """3.1(98)：统一向 进度回调 发一事件（无回调则 no-op）。事件信息 固定 5 字段：
        run/stage/segment/stage_done/stage_total（与旧 value/max 同层，前端向后兼容）。"""
        if 进度回调:
            进度回调(值, 总步数, {"run": 运行标识, "stage": 阶段, "segment": 段,
                                  "stage_done": 已完成, "stage_total": 段总})

    # ========== Phase 1：逐段采样，只留 latent ==========
    # 参考缓存作用域只包住 Phase 1（素材解码只发生在采样侧）；退出 with 即丢引用，
    # 让 Phase 2 的 清理显存 能真把它们 gc 掉，解码前多腾一份空间。
    with _参考缓存作用域(启用=共用素材 is not None):
        for seg in 段列表:
            # 本段依赖：素材内容摘要（同名换内容即失效，§B-1）+ 锚定信息（被锚定/锚帧数/前段指纹）。
            # 锚帧数/前段指纹 由上一有效段一路带下来，与真锚定所用值同源，杜绝「指纹算一套、真锚另一套」。
            # 被锚定/锚帧数/上段尾音频 的历史取舍（为何一个布尔够用）见 构建段指纹源 docstring。
            素材 = _素材摘要(seg.refs, 媒体根, 摘要缓存)
            指纹源 = 构建段指纹源(seg, 素材, 尾帧_video is not None,
                                   尾帧锚帧数, 前段指纹, 上下文帧数)
            指纹 = 段指纹(指纹源, 采样参数)

            if not seg.run:
                缓存 = _读段缓存(seg.index, 指纹)
                跳过数 += 1
                报告行.append(f"段{seg.index + 1}: 跳过（未选运行）{'，用缓存' if 缓存 else ''}")
                if 缓存:
                    采样产物列表.append(缓存)
                    # Concern #5：skip 段**有缓存**时它仍参与拼接，故其尾帧继续作下段锚素材。
                    尾帧_video, 尾帧_audio, 尾帧锚帧数 = 取尾帧_latent(
                        缓存["video_latent"], 缓存.get("audio_latent"), 上下文帧数)
                    前段指纹 = 指纹        # 有缓存的 skip 段仍是下段的锚来源 → 级联基准随它
                else:
                    # skip 且无缓存 → 时间轴在此断裂，下段作为独立段生成，
                    # 不得锚到「两段之前」的旧素材（显式清空）。
                    尾帧_video = 尾帧_audio = None
                    尾帧锚帧数 = 0
                    前段指纹 = None        # 链断裂：下段作为独立段，不带前段依赖指纹
                # skip 段也占掉它在 Phase 1 的那一步（进度只反映采样阶段，skip 段虽不采样但仍占位）
                _发进度(seg.index + 1, "采样", seg.index + 1, seg.index + 1, 采样段数)
                continue

            # M1：不再先 命中() 再 读缓存()——读缓存 内部已含 os.path.exists 判断（不存在即返 None），
            # 多调一次 命中() 只是重复一次文件系统 stat，且与上方 skip 分支的写法不一致。
            产物 = _读段缓存(seg.index, 指纹)
            if 产物 is not None:
                命中数 += 1
                报告行.append(f"段{seg.index + 1}: 命中缓存")
                采样产物列表.append(产物)
            else:
                槽 = 选模型槽(seg.task)
                该槽首段 = 槽 not in 补丁
                if 该槽首段:
                    补丁[槽] = _取补丁模型(模型输入, 全局参数, 槽)
                段模型输入 = dict(模型输入)
                段模型输入["model"] = 模型输入[f"{槽}_model"]
                段模型输入["model_p"] = 补丁[槽]
                段模型输入["_计时首段"] = 该槽首段
                产物 = _采样段(seg, 全局参数, 段模型输入,
                               尾帧_video, 尾帧_audio, 尾帧锚帧数, 媒体根)
                起 = time.perf_counter()
                写缓存(node_id, seg.index, 指纹, 产物)
                计时计["写秒"] += time.perf_counter() - 起
                计时计["写次"] += 1
                采样数 += 1
                报告行.append(f"段{seg.index + 1}: 已采样 {产物['帧数']}帧（锚{产物['锚帧数']}）")
                采样产物列表.append(产物)

            # 取本段尾帧 latent 作下段锚素材（方案 B：不再 decode 出像素）
            尾帧_video, 尾帧_audio, 尾帧锚帧数 = 取尾帧_latent(
                产物["video_latent"], 产物.get("audio_latent"), 上下文帧数)
            前段指纹 = 指纹                # 本段成为下段的前段依赖（锚定段级联失效用，§B-3）

            _发进度(seg.index + 1, "采样", seg.index + 1, seg.index + 1, 采样段数)
            清理显存(归还缓存=False)

    # ========== Phase 2：让出显存 → 逐段解码 → 裁前缀 → 流式并入成片 ==========
    # 进度只反映 Phase 1（采样阶段），Phase 2 不上报进度。
    if 计时:
        _日志.info("缓存IO计时: 读%.3fs/%d次 写%.3fs/%d次",
                   计时计["读秒"], 计时计["读次"], 计时计["写秒"], 计时计["写次"])

    # 内存峰值项（2026-09 回归审查 C1，与 段缓存.py 里 Task 9 的「C1 初衷」不是同一编号，勿混读）：
    # 成片预分配 + 逐段原位写入。旧写法把 N 段 images 全攒进列表再 拼接段 折叠，
    # 峰值 = 全量段(N) + 折叠中间量(≈2N) ≈ 3N；而解码输出恒落 CPU float32（comfy/sd.py:1079
    # + model_management.py:1257），1.0MP@16s 单段 images ≈5.0GB、3 段即 ≈40GB 系统内存——
    # 方案 B 把 DiT 请出显存后，CPU 内存就是下一个瓶颈（症状是 Phase 2 越到后面越慢，
    # 与显存乒乓相似但成因不同，别按 11 §H3 的解 pin 去查）。流式写入把峰值压到 成片(N) + 当前段(1)。
    # 总帧数在解码前即可精确预算：裁后帧数 = 帧数 − 裁前缀帧数(帧数, 锚帧数)，每接缝再净减
    # 接缝重叠（与 流式拼接 的不变式同式；拼接段 与它严格同值，但已不在生产链上）。
    # 对不上时由 流式拼接._容得下 显式抛 ValueError。
    # 接缝重叠与「渐变过渡」开关联动（上下文帧数>0 ⟺ 尾帧锚定=开）：开启时 4 帧 crossfade、
    # 关闭时 0（硬切、不做任何过渡）。三处（预算总帧数 / 流式拼接 / _拼接音频）必须传同一个值——
    # 预算与实际写入不符会由 流式拼接._容得下 抛 ValueError；音频侧不同源则 A/V 逐段累积漂移。
    接缝重叠 = _拼接重叠帧数 if 上下文帧数 > 0 else 0
    裁后帧数列表 = [_裁后帧数(p) for p in 采样产物列表]
    预计总帧数 = 预算总帧数(裁后帧数列表, 接缝重叠)
    拼 = 流式拼接(预计总帧数, 重叠帧数=接缝重叠)
    # 3.1(100) 内存预算（观测优先）：用**实际**采样产物帧数（含命中缓存段）复核成片 images 的
    # 系统内存量级——等价「解码前用缓存元数据复核」。这是容量上界估算（帧×宽×高×3×float32），
    # 不含音频/中间量，不承诺不 OOM（见规格「容量边界」）。段峰值按裁前原始帧数计（解码时 images
    # 先以完整帧数落地、_裁并拼 才裁前缀）。超软阈值追加预警；硬限额默认关，经 H3_内存硬限额_GiB
    # 开启后在解码前拒绝（Phase 1 采样已发生，代价仅在用户显式配置时承担）。
    if 采样产物列表:
        预算行, 成片字节 = 内存预算报告行(预计总帧数, [int(p.get("帧数", 0)) for p in 采样产物列表],
                                       int(全局参数.get("宽", 1344)), int(全局参数.get("高", 768)))
        报告行.append(预算行)
        硬限额 = _内存硬限额字节()
        if 硬限额 and 成片字节 > 硬限额:
            raise ValueError(
                f"预估成片内存 {_人类字节(成片字节)} 超过配置的硬限额 {_人类字节(硬限额)}"
                f"（H3_内存硬限额_GiB），已在解码前中止；如确需运行请调高限额或降低分辨率/时长")
        elif 成片字节 > _内存预警阈值字节():
            报告行.append("警告: 预估成片内存较大，Phase 2 解码可能内存不足（可调 H3_内存预警_GiB 或降低规模）")
    音频列表 = []                # 音频量级是 MB 而非 GB（16s 约 3MB），攒列表再 cat 即可
    缺失音频段数 = 0             # 3.3(117)：无音频段计数，用于静音补齐后的报告 tripwire
    if 采样产物列表:
        # 解码要整块显存，先解除我方对 DiT 的钉住：模型缓存.py docstring 明写「宿主
        # free_memory() 以 sys.getrefcount 排卸载序，钉住的模型排最后；需主动让出显存时
        # 调用方必须先 清缓存」。补丁 dict 也一起清——它同样持 patcher 强引用，只清
        # 模型缓存 的话 refcount 仍降不下来。
        # 代价：牺牲 A 的「跨轮复用同一 patcher 身份」。但方案 B 本来就要在解码前把 DiT
        # 请出显存，跨轮复用已无从谈起；换来的是每轮解码都跑在近似冷启动的空显存上
        # （用户实测冷启动正是快的那条路径：④245s / ⑤52s）。
        补丁.clear()
        清缓存()
        _模型缓存上次键.clear()
        清理显存()

        for i, 采样产物 in enumerate(采样产物列表):
            起d = time.perf_counter()
            段 = _裁并拼(_解码段(采样产物, 模型输入["vae"], 模型输入.get("audio_vae")))
            计时计["解码秒"] += time.perf_counter() - 起d
            计时计["解码次"] += 1
            起p = time.perf_counter()
            拼.追加(段["images"])
            计时计["拼接秒"] += time.perf_counter() - 起p
            if 段.get("audio") is not None:
                音频列表.append(段["audio"])
            else:
                # 3.3(117)：音频缺失段 append 一段静音占位（{waveform:None, 帧数=裁后帧数}），
                # 由 _拼接音频 按当前时基换算成 torch.zeros 补齐，保持 A/V 帧时间轴等长。
                # 帧数 取 _裁后帧数(采样产物)（= 帧数 − 锚裁），与视频段裁后帧数同式；接缝重叠
                # 交给 _拼接音频 统一处理（与有音段完全同一路径）。
                音频列表.append({"waveform": None, "帧数": _裁后帧数(采样产物)})
                缺失音频段数 += 1
            # 3.1(98)：Phase 2 逐段一步（值 N+1..N+M，阶段=解码）。segment 取采样产物自带的原段 index（+1）
            _发进度(采样段数 + i + 1, "解码",
                     int(采样产物.get("index", i)) + 1, i + 1, len(采样产物列表))
            del 段        # 立即丢本段引用：images 已拷进成片，留着就把流式写入省下的内存吃回去
            # 逐段只 gc 不归还：下一段解码马上要重新分配同量级张量，empty_cache 纯负优化
            # （理由三条见 显存清理.清理显存 docstring）。整轮结束再完整归还。
            清理显存(归还缓存=False)

    images = 拼.结果()
    if 计时:
        # 解码含 _裁并拼（裁前缀）；拼接为 流式写入预分配成片；附诊断模式下的 GPU/CPU 峰值（若有）。
        _日志.info("Phase2计时: 解码+裁前缀=%.2fs/%d段 流式拼接=%.2fs｜%s",
                   计时计["解码秒"], 计时计["解码次"], 计时计["拼接秒"], _峰值内存描述())
    # I2（Task 9 code review 回灌）+ 3.3(117)：视频侧按 采样产物列表 全量拼接；音频侧缺失段
    # 补等长静音（见 Phase 2 循环 else 分支）→ A/V 总长天然对齐，不再产生旧版「音频少一整段」的累积漂移。
    # v1 契约下 audio_vae 全局同真同假 → 一般全段有或全段无；本行仅为部分段缺失（旧缓存混新段、
    # audio_vae 中途接入等）留 tripwire，日后若破坏必在报告中留痕（信息性，非警告）。
    if 缺失音频段数:
        if 缺失音频段数 < len(音频列表):
            报告行.append(
                f"提示: {缺失音频段数}/{len(音频列表)} 段无音频，已按等长静音补齐对齐 A/V")
        else:
            报告行.append("提示: 全部段无音频，输出为无声成片")
    audio = _拼接音频(音频列表, 重叠帧数=接缝重叠) if 音频列表 else None
    # 3.1(99)：三时长报告——计划（Σ run 段跨度）→ 对齐/裁剪后预计（成片帧数@基座24fps）
    # → 输出播放（成片帧数@用户帧率）。后两者不同即“非24fps 播放会拉伸时长”的可见信号（不暗改时基）。
    预计秒 = 预计总帧数 / FPS
    输出帧 = int(images.shape[0]) if images is not None else 0
    用户帧率 = float(全局参数.get("帧率", FPS)) or FPS
    报告行.append(
        f"时长: 计划{计划时长:.1f}s → 对齐/裁剪后预计{预计秒:.1f}s → "
        f"输出播放{输出帧 / 用户帧率:.1f}s（{输出帧}帧@{用户帧率:g}fps）")
    # 3.3(119)：非 24fps 显式提示——成片按基座 FPS=24 采样（时间轴/帧时基），输出时按用户帧率
    # 重新打包→播放会被拉伸。不暗改时基（与 3.1(99) 同一契约），仅在两值不等时补一行可见信号。
    if 用户帧率 != FPS:
        报告行.append(
            f"注意: 输出帧率 {用户帧率:g}fps ≠ 基座 {FPS}fps，成片按 {FPS}fps 采样，播放时按 {用户帧率:g}fps 拉伸")
    # §B-7：报告末尾追加一行缓存可观测性——本轮 采样/命中/跳过 计数 + 当前段缓存体量/格式版本。
    # 采样>0 即“该段指纹未命中磁盘缓存”（失效原因统一表现为重采样；逐段哪一维度变的根因需
    # 跨轮留存上次指纹，§B-7 首版不做）。行量信息走 缓存统计（一次目录扫描，不在关键路径）。
    try:
        统计 = 缓存统计()
        报告行.append(
            f"缓存统计: 采样{采样数}/命中{命中数}/跳过{跳过数}"
            f"｜当前 {统计['条目数']}项 {_人类字节(统计['大小字节'])}（格式 {统计['版本']}）")
    except Exception as e:  # noqa: BLE001 - 可观测性不得打挂已跑了数小时的生成（try 体仅目录扫描+拼接）
        报告行.append(f"缓存统计: 采样{采样数}/命中{命中数}/跳过{跳过数}（统计不可用：{type(e).__name__}）")
    # 3.1(98)：整体完成事件（只在 images/audio 真正就绪后补发，保证 value==max 意味“可取回产物”）。
    # 完整归还显存由 执行时间轴 外层 finally 兜底（3.2(108)），成功/异常都执行且仅此一次（旧 D 行已上提）。
    _发进度(总步数, "完成", None, len(采样产物列表), len(采样产物列表))
    return images, audio, "\n".join(报告行)


def _裁后帧数(采样产物) -> int:
    """预算用：本段解码并裁掉锚定前缀后将保留的帧数 = 帧数 − 裁前缀帧数(帧数, 锚帧数)。

    与 _裁并拼 的实际裁剪同式（那边用解码出的 img.shape[0]）；二者相等的前提是「解码帧数 ==
    采样产物[帧数]」，由 采样与解码.秒转帧数 的 对齐帧数（上抬到 17k+5）与官方
    _empty_av_latent(length) 的时间栅格保证。对不上也不静默：流式拼接._容得下 会抛 ValueError。"""
    帧 = max(0, int(采样产物.get("帧数", 0)))
    return max(0, 帧 - 裁前缀帧数(帧, int(采样产物.get("锚帧数", 0))))


def _裁并拼(产物):
    """按锚帧数裁掉本段被段间锚定（钉入上下文_from_latent）覆盖的重复前缀（images 与 audio 同步），
    避免拼接后重复。复用纯函数 裁前缀帧数（=min(规范锚帧数, 帧数-1)）确保不会把整段裁空。"""
    锚 = int(产物.get("锚帧数", 0))
    img = 产物.get("images")
    if 锚 <= 0 or img is None:
        return 产物
    裁 = 裁前缀帧数(img.shape[0], 锚)
    if 裁 > 0:
        产物["images"] = img[裁:]
        产物["audio"] = _裁音频前缀(产物.get("audio"), 裁)
    return 产物


def _裁音频前缀(audio, 帧数, fps=FPS):
    """按帧数换算采样点，裁掉音频前缀（与视频裁前缀同步）。fps=FPS=24 为官方时间基座，
    与用户输出帧率 widget 解耦。"""
    if audio is None or 帧数 <= 0:
        return audio
    裁点 = int(round(帧数 / fps * audio["sample_rate"]))
    wave = audio["waveform"]
    return audio if 裁点 >= wave.shape[-1] else {"waveform": wave[..., 裁点:], "sample_rate": audio["sample_rate"]}


def _拼接音频(音频列表, fps=FPS, 重叠帧数=_拼接重叠帧数):
    """按时间拼接多段 AUDIO（{waveform, sample_rate}）。GPU 集成验证。
    fps=FPS=24 为官方时间基座（与 流式拼接 的净减帧同一时基）。
    ⚠️#4（段间连续不变式回灌）：视频侧 流式拼接 每接缝净减 重叠帧数 帧（输出 = Σ输入 − Σ重叠）。
    纯 torch.cat 不裁 → A/V 逐段累积漂移。此处按同规则对称裁剪：每个后续段头部丢弃 重叠帧数
    换算的采样点（接缝对称裁——非 crossfade：不做包络混合，仅裁掉后续段头部重叠样本；
    真正的音频淡化（等 power 补包络）列为后续显式能力，本函数不宣称支持），使音频总时长与视频净减帧数一致。
    重叠样本按每段自身可用样本数钳制，至少留 1 样本避免把整段裁空（对齐 裁前缀帧数 的 帧数-1 语义）。
    3.3(117)：入参是**全量有序**列表，缺失段以 {waveform:None, 帧数:N} 占位（由 Phase 2 循环补齐）；
    本段按全局 sr 将 N 帧换算成 torch.zeros 静音插回，使音频段数与视频段数相等。全段均无有效
    波形（无任何非 None waveform）→ 返回 None（纯无声成片）。单段有效且列表仅一项→直传原对象（保持契约）。"""
    import torch
    if not 音频列表:
        return None
    if len(音频列表) == 1:
        单 = 音频列表[0]
        return 单 if 单.get("waveform") is not None else None
    # 全局采样率：取首个有效段；全段无有效波形 → 无声，返回 None
    sr = next((a["sample_rate"] for a in 音频列表 if a.get("waveform") is not None), None)
    if sr is None:
        return None
    重叠样本 = max(0, int(round(重叠帧数 / fps * sr)))
    片段 = []
    for i, a in enumerate(音频列表):
        w = a.get("waveform")
        if w is None:
            # 3.3(117)：缺失段补等长静音（帧数 → 按全局 sr/时基 换算样本数）。
            # 兜底：占位段缺 帧数 键、或 帧数 值为 None 时按 0 帧（`or 0`），避免 int(None) 抛错。
            帧 = max(0, int(a.get("帧数") or 0))
            w = torch.zeros(1, int(round(帧 / fps * sr)))
        if i > 0:
            裁 = min(重叠样本, max(0, w.shape[-1] - 1)) if w.shape[-1] > 0 else 0   # 至少留 1 样本，避免裁空
            w = w[..., 裁:]
        片段.append(w)
    wave = torch.cat(片段, dim=-1)
    return {"waveform": wave, "sample_rate": sr}
