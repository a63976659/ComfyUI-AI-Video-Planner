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
from .段缓存 import 段指纹, 读缓存, 写缓存
from .官方管线适配 import 调用节点
from .显存清理 import 清理显存
from .模型缓存 import 取模型, 清缓存

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
        if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) <= 44:
            # <=44 字节 = 只有 WAV 头/截断的坏缓存（ffmpeg 中途失败留下的），删掉重转
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
            cmd = [_定位ffmpeg(), "-y", "-i", 路径, "-vn", "-acodec", "pcm_s16le", temp_wav]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        data, sr = sf.read(temp_wav, dtype="float32", always_2d=True)
    # sf.read(always_2d=True) 返回 (frames, channels)，转置为 (channels, frames)
    wave = torch.from_numpy(data.T).contiguous()
    return wave, sr


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


def _读视频帧(路径, fps, 上限秒):
    import numpy as np
    import torch
    import imageio.v3 as iio
    帧 = []
    目标 = None
    for f in iio.imiter(路径):
        # [..., :3] 在解码处就砍掉 alpha：本函数有「缩放」与「原尺寸直通」两条路径（源尺寸
        # 恰等于目标画布时不缩放，如源就是 1344x768），只在 _缩放到画布 里砍会漏掉直通
        # 路径 → RGBA 素材两条路径通道数不一致。放这里则全路径统一 3 通道，且省 25% 内存。
        # 前提：视频后端（imageio-ffmpeg / av）恒以 rgb24 或 rgba 出帧，末维必为通道维。
        t = torch.from_numpy(np.array(f).astype("float32") / 255.0).unsqueeze(0)[..., :3]   # [1,H,W,3]
        if 目标 is None:
            目标 = _参考视频画布(t.shape[2], t.shape[1])     # 画布只看首帧尺寸，全片统一
        if (t.shape[2], t.shape[1]) != 目标:
            t = _缩放到画布(t, 目标[0], 目标[1])
        帧.append(t)
        if len(帧) >= int(上限秒 * fps):
            break
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


def _应用全局(seg, 全局参数):
    """把状态栏全局 widgets 合并进段（SegmentPlan 不可变，返回副本）：
    运行选择→run（Run-select）、全局提示词→prompt 前缀、参考素材→refs 兜底、任务类型→默认 task。"""
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
    全局素材 = _读json(全局参数.get("参考素材"))
    if 全局参数.get("参考共用"):
        refs.update(全局素材)      # 全段统一：全局池覆盖段级 refs（r2v/v2v/rv2v 只编辑提示词即可）
    else:
        for k, v in 全局素材.items():   # 段级优先，全局兜底
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


def 执行时间轴(时间轴数据, 全局参数, 模型输入, node_id, 媒体根, 进度回调=None):
    """主入口：返回 (images, audio, report)。GPU 集成验证。
    媒体根＝参考素材文件名的解析根目录（见 后端路由/媒体路由.py 的 媒体根()）。

    方案 B 两阶段（详见模块头）：
      Phase 1 逐段采样，只把 AV latent 搬到 CPU 攒着（几十 MB/段）；段间锚定直接切上段
              尾帧 latent（取尾帧_latent → 钉入上下文_from_latent），不经 decode→encode。
      Phase 2 全部采完后解除 模型缓存 对 DiT 的钉住 + 清理显存，再逐段 VAEDecode、裁前缀、
              流式写入预分配成片（流式拼接，峰值内存 = 成片 + 当前段）。
    进度：Phase 1 期间以 2×段数 为上界上报（每段一步），Phase 2 前收敛为
    段数 + 实际解码段数（skip-无缓存 的段不解码），故最终一步恒为 100%。"""
    plan = 解析时间轴(时间轴数据)
    上下文帧数 = int(全局参数.get("上下文帧数", 默认上下文帧数))
    采样参数 = {
        "帧率": int(全局参数.get("帧率", FPS)),
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
        "audio_vae": 模型输入.get("audio_vae") is not None,
        "参考共用": bool(全局参数.get("参考共用")),
    }

    段列表 = [_应用全局(s, 全局参数) for s in plan.segments]
    用到槽 = {选模型槽(s.task) for s in 段列表 if s.run}
    for 槽 in sorted(用到槽):
        if 模型输入.get(f"{槽}_model") is None:
            涉及 = sorted({s.task for s in 段列表 if s.run and 选模型槽(s.task) == 槽})
            raise ValueError(
                f"时间轴含 {槽} 管线任务（{', '.join(涉及)}），但「{槽}模型」输入未连接；"
                f"请连接对应模型，或移除/改型该类任务段")

    def _读段缓存(index, 指纹):
        """读缓存 + 形状校验（见 _是采样产物）：不符即当未命中返回 None。"""
        产物 = 读缓存(node_id, index, 指纹)
        return 产物 if _是采样产物(产物) else None

    采样产物列表 = []      # Phase 1 产出：CPU 上的 AV latent（跨整轮存活）
    报告行 = []
    补丁 = {}
    尾帧_video = 尾帧_audio = None      # 上一段的锚素材 latent（首段/断裂处为 None）
    尾帧锚帧数 = 0
    总步数 = 2 * len(段列表)            # Phase 1 期间的上界估计；Phase 2 前收敛到精确值（见下方 L2）

    # ========== Phase 1：逐段采样，只留 latent ==========
    # 参考缓存作用域只包住 Phase 1（素材解码只发生在采样侧）；退出 with 即丢引用，
    # 让 Phase 2 的 清理显存 能真把它们 gc 掉，解码前多腾一份空间。
    with _参考缓存作用域(启用=bool(全局参数.get("参考共用"))):
        for seg in 段列表:
            # 锚帧数 由 取尾帧_latent 在上一段末尾算好并一路带下来：它既是本段指纹的一维，
            # 也是本段真锚定时用的值（同一个数），杜绝「指纹算一套、真锚另一套」的假命中。
            # 尾帧_video 为 None 时 尾帧锚帧数 必为 0（取尾帧_latent 的返回契约），故一个
            # 「被锚定」布尔已足够表达旧版「被锚定 + 上段尾帧」两个同值键（h3-5 删）。
            # h3-6 又删了「上段尾音频」：官方 _empty_av_latent 无条件造 video+audio 两支
            # ⇒ audio_latent 恒非 None ⇒ 尾帧_audio is None ⟺ 尾帧_video is None，与之同值。
            # ⚠️ 但该键与「上段尾帧」**性质不同**（它是不同谓词，同值只是官方实现细节的副产物）：
            # 若官方将来把 audio 支改成条件化（如 audio_vae 未连接时只返回 video），**必须把它
            # 加回本字典**，否则「带音频锚」与「不带音频锚」的段会撞同一指纹 → 静默假命中
            # （_是采样产物 查不出：形状仍合法）。改指纹 payload 必须同时升 缓存格式版本，
            # 详 段缓存.py 模块头 h3-5→h3-6 注释。
            指纹源 = {"task": seg.task, "prompt": seg.prompt, "refs": seg.refs,
                      "start": seg.start, "end": seg.end,
                      "被锚定": 尾帧_video is not None,
                      "锚帧数": int(尾帧锚帧数),
                      "上下文帧数": int(上下文帧数)}
            指纹 = 段指纹(指纹源, 采样参数)

            if not seg.run:
                缓存 = _读段缓存(seg.index, 指纹)
                报告行.append(f"段{seg.index + 1}: 跳过（未选运行）{'，用缓存' if 缓存 else ''}")
                if 缓存:
                    采样产物列表.append(缓存)
                    # Concern #5：skip 段**有缓存**时它仍参与拼接，故其尾帧继续作下段锚素材。
                    尾帧_video, 尾帧_audio, 尾帧锚帧数 = 取尾帧_latent(
                        缓存["video_latent"], 缓存.get("audio_latent"), 上下文帧数)
                else:
                    # skip 且无缓存 → 时间轴在此断裂，下段作为独立段生成，
                    # 不得锚到「两段之前」的旧素材（显式清空）。
                    尾帧_video = 尾帧_audio = None
                    尾帧锚帧数 = 0
                # L2：skip 段也必须占掉它在 Phase 1 的那一步。旧版在此直接 continue 不上报，
                # 于是上报过的最大 value 永远 < 总步数 → 前端进度条卡在 83%之类的值直到节点结束。
                if 进度回调:
                    进度回调(seg.index + 1, 总步数)
                continue

            # M1：不再先 命中() 再 读缓存()——读缓存 内部已含 os.path.exists 判断（不存在即返 None），
            # 多调一次 命中() 只是重复一次文件系统 stat，且与上方 skip 分支的写法不一致。
            产物 = _读段缓存(seg.index, 指纹)
            if 产物 is not None:
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
                写缓存(node_id, seg.index, 指纹, 产物)
                报告行.append(f"段{seg.index + 1}: 已采样 {产物['帧数']}帧（锚{产物['锚帧数']}）")
                采样产物列表.append(产物)

            # 取本段尾帧 latent 作下段锚素材（方案 B：不再 decode 出像素）
            尾帧_video, 尾帧_audio, 尾帧锚帧数 = 取尾帧_latent(
                产物["video_latent"], 产物.get("audio_latent"), 上下文帧数)

            if 进度回调:
                进度回调(seg.index + 1, 总步数)
            清理显存(归还缓存=False)

    # ========== Phase 2：让出显存 → 逐段解码 → 裁前缀 → 流式并入成片 ==========
    # L2：解码段数已确定 → 把总步数从「上界 2N」收敛到精确值（N 步采样 + 实际会解码的段数）。
    # 不收敛则 skip-无缓存 / 全命中缓存以外的任何缺段都会让进度条永远到不了 100%。
    总步数 = len(段列表) + len(采样产物列表)
    if 进度回调 and 段列表 and not 采样产物列表:
        进度回调(总步数, 总步数)         # 全程无解码段（全 skip 且无缓存）：Phase 1 停在 50%，补满格

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
    拼 = 流式拼接(预算总帧数([_裁后帧数(p) for p in 采样产物列表], 接缝重叠),
                  重叠帧数=接缝重叠)
    音频列表 = []                # 音频量级是 MB 而非 GB（16s 约 3MB），攒列表再 cat 即可
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
            段 = _裁并拼(_解码段(采样产物, 模型输入["vae"], 模型输入.get("audio_vae")))
            拼.追加(段["images"])
            if 段.get("audio") is not None:
                音频列表.append(段["audio"])
            if 进度回调:
                进度回调(len(段列表) + i + 1, 总步数)
            del 段        # 立即丢本段引用：images 已拷进成片，留着就把流式写入省下的内存吃回去
            # 逐段只 gc 不归还：下一段解码马上要重新分配同量级张量，empty_cache 纯负优化
            # （理由三条见 显存清理.清理显存 docstring）。整轮结束再完整归还。
            清理显存(归还缓存=False)

    images = 拼.结果()
    # I2（Task 9 code review 回灌）：视频侧按 采样产物列表 全量拼接，音频侧过滤 None。
    # 一旦某段 audio=None 而其他段有（旧缓存混新段、audio_vae 中途接入等），音频少一整段
    # 且接缝数也少减一次 → A/V 漂移远超 ⚠️#4 对称裁的 4 帧量级，且无告警。v1 契约下
    # audio_vae 全局同真同假 → 不会触发；本告警为防御性 tripwire，日后若破坏必在报告中留痕。
    if 0 < len(音频列表) < len(采样产物列表):
        报告行.append(
            f"警告: 音频段数 {len(音频列表)} < 视频段数 {len(采样产物列表)}，A/V 可能错位")
    audio = _拼接音频(音频列表, 重叠帧数=接缝重叠) if 音频列表 else None
    # D：整轮结束才做完整归还——参考缓存已随 with 退出丢引用、latent 也已解码完毕，
    #   gc 能真正回收它们，再把空出来的池子交还下游节点（VideoCombine/SaveAudio 等）与其他工作流。
    清理显存()
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
    换算的采样点（等价于视频 crossfade 区用后段覆盖前段尾），使音频总时长与视频净减帧数一致。
    重叠样本按每段自身可用样本数钳制，至少留 1 样本避免把整段裁空（对齐 裁前缀帧数 的 帧数-1 语义）。"""
    import torch
    有效 = [a for a in 音频列表 if a is not None and a.get("waveform") is not None]
    if not 有效:
        return None
    if len(有效) == 1:
        return 有效[0]
    sr = 有效[0]["sample_rate"]
    重叠样本 = max(0, int(round(重叠帧数 / fps * sr)))
    片段 = [有效[0]["waveform"]]
    for a in 有效[1:]:
        w = a["waveform"]
        裁 = min(重叠样本, max(0, w.shape[-1] - 1))   # 至少留 1 样本，避免裁空
        片段.append(w[..., 裁:])
    wave = torch.cat(片段, dim=-1)
    return {"waveform": wave, "sample_rate": sr}
