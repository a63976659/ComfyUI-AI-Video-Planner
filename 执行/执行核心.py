# -*- coding: utf-8 -*-
"""执行核心：解析时间轴 → 逐段（Run-select + 缓存）走官方 H3 链路生成 → 段间连续拼接 → 进度上报。

官方单段链路（严格对齐 comfy_extras/nodes_minimax_h3.py 与 nodes.py）：
  MiniMaxH3SigmaShift(给 model 打补丁) → 条件节点(ImageToVideo / ReferenceToVideo，产 positive + AV 空 latent)
  → [段间连续] MiniMaxH3AddGuide 把上段尾帧(clip)+尾音频锚到 frame_idx=0
  → KSampler(res_multistep / simple, cfg=1.0, negative=positive) → VAEDecode + VAEDecodeAudio(同一 AV latent)
条件节点只输出 positive（无 negative）；cfg=1.0 时 KSampler 忽略 negative，故 negative 直接复用 positive。

本模块是编排层：串起 规划 / 条件组装 / 参考素材 / 采样与解码 / 段间连续 / 段缓存 / 官方管线适配 /
显存清理。GPU 主验证在 Task 19/20；CPU 侧只做静态语法 + 纯函数/编排桩测。
"""
from .规划 import 解析时间轴
from .条件组装 import 选管线, 需要首帧, 需要尾帧, 组装参考入参
from .参考素材 import 解析槽位, 校验标签, 上限
from .采样与解码 import 对齐画布, 解码音视频, 秒转帧数, FPS
from .段间连续 import 钉入上下文, 裁前缀帧数, 拼接段, 默认上下文帧数, 规范锚帧数
from .段缓存 import 段指纹, 命中, 读缓存, 写缓存
from .官方管线适配 import 调用节点
from .显存清理 import 清理显存

# 接缝重叠帧数：与 段间连续.拼接段 的默认值 4 保持同源，供 ⚠️#4 音频对称裁剪对齐。
_拼接重叠帧数 = 4


# ---------- 参考素材：文件名 → 张量（官方节点只吃张量，widget 存的是文件名） ----------

def _加载图像(路径):
    """PIL 读图 → IMAGE [1,H,W,C] float32 0..1。"""
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
    soundfile 不支持的格式（如 m4a/aac/视频音轨）自动用 ffmpeg 转码为 wav 后再读取。"""
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
        temp_wav = os.path.join(temp_dir, f"h3dyt_sf_decode_{h}.wav")
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
    依赖可选视频后端（imageio-ffmpeg 或 av）；缺失时由上层降级为「无视频参考」。"""
    import numpy as np
    import torch
    import imageio.v3 as iio
    帧 = []
    for f in iio.imiter(路径):
        帧.append(np.array(f).astype("float32") / 255.0)
        if len(帧) >= int(上限秒 * fps):
            break
    return torch.from_numpy(np.stack(帧)) if 帧 else None


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


# ---------- 单段生成（官方链路） ----------

def _生成段(seg, 全局参数, 模型输入, 上段尾帧, 上段尾音频, 媒体根):
    """走官方 H3 链路生成单段，返回 {images, audio, 锚帧数, 帧数}。GPU 集成验证。

    帧数一律经 秒转帧数 拿（→ 对齐帧数(round(秒*FPS=24))）：官方模型时间基座恒 FPS=24，
    与用户 widget「帧率」解耦（后者只影响输出容器 fps 标签，不参与帧数换算）。详见
    采样与解码.秒转帧数 docstring 与 Task 4 §接口约束。"""
    帧数 = 秒转帧数(seg.end - seg.start)
    宽, 高 = 对齐画布(int(全局参数.get("宽", 1344)), int(全局参数.get("高", 768)))
    上下文帧数 = int(全局参数.get("上下文帧数", 默认上下文帧数))
    model, clip, vae = 模型输入["model"], 模型输入["clip"], 模型输入["vae"]
    audio_vae = 模型输入.get("audio_vae")

    # 1) SigmaShift 给 model 打补丁（官方输出的是 patched model，不是 sigmas）
    model_p = 调用节点("MiniMaxH3SigmaShift", model=model,
                       shift_video=float(全局参数.get("shift_video", 12.0)),
                       shift_audio=float(全局参数.get("shift_audio", 3.0)))[0]

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
    positive, latent = 调用节点(管线, **kw)[:2]

    # 3) 段间连续：把上段尾帧(clip)+尾音频锚到本段 frame_idx=0（官方 AddGuide）
    锚帧数 = 0
    if 上段尾帧 is not None and 上下文帧数 > 0:
        positive, 锚帧数 = 钉入上下文(positive, latent, 上段尾帧, 上段尾音频,
                                     vae, audio_vae, frame_idx=0)

    # 4) KSampler：cfg=1.0 → negative 被忽略，故 negative 复用 positive；
    #    采样器/调度器 由节点 widget 经 全局参数 传入（默认 res_multistep/simple 与历史硬编码一致）。
    sampled = 调用节点("KSampler", model=model_p,
                       seed=int(全局参数.get("种子", 0)) + seg.index,
                       steps=int(全局参数.get("步数", 25)), cfg=1.0,
                       sampler_name=全局参数.get("采样器", "res_multistep"),
                       scheduler=全局参数.get("调度器", "simple"),
                       positive=positive, negative=positive,
                       latent_image=latent, denoise=1.0)[0]

    # 5) 同一 AV latent 分别喂 VAEDecode(视频流) 与 VAEDecodeAudio(音频流)
    images, audio = 解码音视频(sampled, vae, audio_vae)
    return {"images": images, "audio": audio, "锚帧数": 锚帧数, "帧数": 帧数}


def _模型标识(模型输入):
    """提取 ckpt 标识入指纹（⚠️#1）：优先 模型输入 显式键，退化为 model 的加载路径文件名。
    取 basename 以免 ComfyUI 目录整体迁移时无谓作废旧缓存。取不到返回 None（Task 11 应显式
    提供 模型输入["模型标识"]，否则换 ckpt 无法失效缓存，见报告 Concerns）。"""
    import os
    for k in ("模型标识", "ckpt_name", "ckpt"):
        v = 模型输入.get(k)
        if v:
            return os.path.basename(str(v))
    model = 模型输入.get("model")
    for attr in ("model_path", "ckpt_name", "model_name"):
        v = getattr(model, attr, None) if model is not None else None
        if v:
            return os.path.basename(str(v))
    return None


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


def 执行时间轴(时间轴数据, 全局参数, 模型输入, node_id, 媒体根, 进度回调=None):
    """主入口：返回 (images, audio, report)。GPU 集成验证。
    媒体根＝参考素材文件名的解析根目录（见 后端路由/媒体路由.py 的 媒体根()）。"""
    plan = 解析时间轴(时间轴数据)
    上下文帧数 = int(全局参数.get("上下文帧数", 默认上下文帧数))
    # 指纹只吃「影响产物」的采样参数，排除 运行选择（Run-select 不应使缓存失效）。
    # ⚠️#1（段缓存 code review 回灌）：补齐 种子/步数/shift_video/shift_audio/上下文帧数/模型标识，
    #   否则改了这些参数仍会命中旧缓存；数值入指纹前统一类型（整数入 int、shift 入 float），
    #   避免 1 与 1.0 产不同指纹导致缓存分裂。
    # 【帧率契约】下方 "帧率" 只取用户 widget 值（入指纹防止“用户改 widget 看无变化”的
    #   使用层困惑）；而 _生成段 实际给模型的 length 一律经 秒转帧数(基座 FPS=24)，
    #   与 用户帧率widget 解耦。
    采样参数 = {
        "帧率": int(全局参数.get("帧率", FPS)),
        "宽": int(全局参数.get("宽", 1344)),
        "高": int(全局参数.get("高", 768)),
        "种子": int(全局参数.get("种子", 0)),
        "步数": int(全局参数.get("步数", 25)),
        # 采样器/调度器 现为节点 widget（原硬编码 res_multistep/simple）：影响产物，
        #   必须入指纹，否则切换后仍命中旧缓存→产物不变（与 ⚠️#1 同一失效类）。
        "采样器": str(全局参数.get("采样器", "res_multistep")),
        "调度器": str(全局参数.get("调度器", "simple")),
        "shift_video": float(全局参数.get("shift_video", 12.0)),
        "shift_audio": float(全局参数.get("shift_audio", 3.0)),
        "上下文帧数": int(上下文帧数),
        "模型标识": _模型标识(模型输入),
        # C1（Task 9 code review 回灌）：_生成段 实际消费且影响产物的另两维必须入指纹，
        #   否则用户改这两项仍命中旧缓存→产物不变→静默错乱，与 ⚠️#1 同一失效类。
        #   - 参考图尺寸：r2v/v2v 传给 ReferenceToVideo.ref_image_size；
        #   - audio_vae 存在性：决定 audio 是否为 None，与 I2 拼接告警联动。
        "参考图尺寸": str(全局参数.get("参考图尺寸", "match")),
        "audio_vae": 模型输入.get("audio_vae") is not None,
        # B：参考共用（音频按段切片开关）必须入指纹——否则开/关共用时若段 refs 恰好相同
        #   （段无自有 refs、全局兜底与覆盖产出同一 refs、start/end 也同），整段引用 vs 按窗
        #   切片产物不同却命中同一缓存 → 假命中（与 ⚠️#1/C1 同一失效类；同 参考图尺寸 仅 r2v/v2v 生效但仍全局入指纹）。
        "参考共用": bool(全局参数.get("参考共用")),
    }
    段产物 = []
    上段尾帧 = None
    上段尾音频 = None
    报告行 = []

    for seg in plan.segments:
        seg = _应用全局(seg, 全局参数)          # 合并 运行选择/全局提示词/全局参考/默认任务
        # ⚠️#2：显式挑字段，绝不用 dataclasses.asdict(seg)（会把 run/index 带进去，
        #   Run-select 切换 / 段序变化会令缓存整体失效）。并纳入「本段是否被上游锚定 +
        #   锚帧数 + 上段身份（尾帧/尾音频是否为 None）+ 锁定的 上下文帧数」——否则关掉上一段
        #   重跑时本段指纹不变 → 命中旧锚缓存 → 按旧 锚帧数 误裁真实内容。
        被锚定 = 上段尾帧 is not None and 上下文帧数 > 0
        指纹源 = {"task": seg.task, "prompt": seg.prompt, "refs": seg.refs,
                  "start": seg.start, "end": seg.end,
                  "被锚定": 被锚定,
                  "锚帧数": (规范锚帧数(上段尾帧.shape[0]) if 被锚定 else 0),
                  "上段尾帧": 上段尾帧 is not None,
                  "上段尾音频": 上段尾音频 is not None,
                  "上下文帧数": int(上下文帧数)}
        指纹 = 段指纹(指纹源, 采样参数)
        if not seg.run:
            缓存 = 读缓存(node_id, seg.index, 指纹)
            报告行.append(f"段{seg.index}: 跳过（未选运行）{'，用缓存' if 缓存 else ''}")
            if 缓存:
                缓存 = _裁并拼(缓存)
                段产物.append(缓存)
                上段尾帧, 上段尾音频 = _取尾(缓存, 上下文帧数)
            else:
                # 跳过段且无缓存：本段不进入成片；下段不应锚到“两段之前”
                # （时间轴已断裂，锚过去会拿错错位素材），显式清空 上段尾帧/尾音频，
                # 下段作为独立段生成。
                上段尾帧 = None
                上段尾音频 = None
            continue

        # ⚠️#3：命中 True ≠ 必返回对象。读缓存 对损坏文件自愈返回 None；命中 与 读缓存 之间
        #   也可能被外部清理。故 产物 is None 时必须 fallback 到 _生成段，不得直接下标取键。
        #   禁给 读缓存 加进程内对象缓存——_裁并拼 会原地 mutate 产物，共享对象会被二次裁。
        产物 = 读缓存(node_id, seg.index, 指纹) if 命中(node_id, seg.index, 指纹) else None
        if 产物 is not None:
            报告行.append(f"段{seg.index}: 命中缓存")
        else:
            产物 = _生成段(seg, 全局参数, 模型输入, 上段尾帧, 上段尾音频, 媒体根)
            写缓存(node_id, seg.index, 指纹, 产物)   # 缓存未裁前缀的原段，命中后再裁
            报告行.append(f"段{seg.index}: 已生成 {产物['帧数']}帧（锚{产物['锚帧数']}）")

        产物 = _裁并拼(产物)              # 按锚帧数裁掉 AddGuide 锚定的重复前缀
        段产物.append(产物)
        上段尾帧, 上段尾音频 = _取尾(产物, 上下文帧数)
        if 进度回调:
            进度回调(seg.index + 1, len(plan.segments))
        清理显存()

    images = 拼接段([p["images"] for p in 段产物]) if 段产物 else None
    audios = [p.get("audio") for p in 段产物 if p.get("audio") is not None]
    # I2（Task 9 code review 回灌）：视频侧按 段产物 全量拼接，音频侧过滤 None。
    # 一旦某段 audio=None 而其他段有（旧缓存混新段、audio_vae 中途接入等），音频少一整段
    # 且接缝数也少减一次 → A/V 漂移远超 ⚠️#4 对称裁的 4 帧量级，且无告警。v1 契约下
    # audio_vae 全局同真同假 → 不会触发；本告警为防御性 tripwire，日后若破坏必在报告中留痕。
    if 0 < len(audios) < len(段产物):
        报告行.append(f"警告: 音频段数 {len(audios)} < 视频段数 {len(段产物)}，A/V 可能错位")
    audio = _拼接音频(audios) if audios else None
    return images, audio, "\n".join(报告行)


def _取尾(产物, 上下文帧数):
    """取本段末尾 上下文帧数 帧 + 对应音频，作为下段 AddGuide 的锚素材。音频按基座 FPS 换算。"""
    img = 产物.get("images")
    if 上下文帧数 <= 0 or img is None:
        return None, None
    n = min(上下文帧数, img.shape[0])
    尾音频 = _裁音频尾(产物.get("audio"), n) if 产物.get("audio") is not None else None
    return img[-n:], 尾音频


def _裁并拼(产物):
    """按锚帧数裁掉本段被 AddGuide 锚定的重复前缀（images 与 audio 同步），避免拼接后重复。
    复用纯函数 裁前缀帧数（=min(规范锚帧数, 帧数-1)）确保不会把整段裁空。"""
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


def _裁音频尾(audio, 帧数, fps=FPS):
    """按帧数换算采样点，取音频末尾（作为下段锚音频）。fps=FPS=24 为官方时间基座。"""
    if audio is None or 帧数 <= 0:
        return audio
    取点 = min(int(round(帧数 / fps * audio["sample_rate"])), audio["waveform"].shape[-1])
    return {"waveform": audio["waveform"][..., -取点:], "sample_rate": audio["sample_rate"]}


def _拼接音频(音频列表, fps=FPS, 重叠帧数=_拼接重叠帧数):
    """按时间拼接多段 AUDIO（{waveform, sample_rate}）。GPU 集成验证。
    fps=FPS=24 为官方时间基座（与 拼接段 的净减帧同一时基）。
    ⚠️#4（段间连续不变式回灌）：视频侧 拼接段 每接缝净减 重叠帧数 帧（输出 = Σ输入 − Σ重叠）。
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
