"""独立后处理：原尺寸精修全部完成后才放大与呈现，不回写初采。"""
from contextlib import ExitStack
import hashlib
import logging
import math
import time
import uuid

import torch

from .初采产物 import 校验初采产物
from .参考素材 import 解析槽位
from .官方管线适配 import 官方节点可用, 调用节点
from .执行核心 import (
    _补丁模型, 提取模型链身份, _人类字节,
    _内存硬限额字节, _内存预警阈值字节,
)
from .显存清理 import 清理显存
from .条件组装 import 选管线
from .段间连续 import 流式拼接, 匹配开头色光, _校验来源音频latent
from .精修条件 import 校验精修素材, _前驱尾, _有效图像
from .精修采样 import 精修一段
from .视频放大 import 计算目标尺寸, 放大图像批
from .H3潜空间放大 import 预检H3放大权重, 加载H3放大模型, 放大H3视频latent
from .后处理缓存 import (
    张量摘要, 取模型身份, 精修键, 放大键, 缓存读写异常,
    读后处理缓存, 写后处理缓存, 后处理缓存统计,
)


_日志 = logging.getLogger(__name__)


def 检查取消():
    from comfy.model_management import throw_exception_if_processing_interrupted
    throw_exception_if_processing_interrupted()


def _校验参数(params):
    strength = params.get("精修强度")
    if type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("精修强度须为0到1的有限数")
    for name, high in (("精修步数", 10000), ("精修种子", 2**64 - 1), ("缓存失效版本", 999999)):
        value = params.get(name)
        low = 1 if name == "精修步数" else 0
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name}须为{low}到{high}的整数")
    from comfy.samplers import KSampler
    for name, choices in (("采样器", KSampler.SAMPLERS), ("调度器", KSampler.SCHEDULERS)):
        if params.get(name) not in choices:
            raise ValueError(f"未知{name}")


def _资源预检(package, models, lines, required, check=None):
    """只检查资源及元信息；不读取或保留源 Tensor/前驱。"""
    from comfy.model_base import MiniMaxH3
    from comfy.ldm.minimax.model import MiniMaxH3Model

    check = check or 检查取消
    generation = package["generation"]
    for name in ("shift_video", "shift_audio"):
        value = generation.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"精修缺少有效初采 {name} 记录")
    required.update(("KSampler", "MiniMaxH3SigmaShift"))
    identities, slots = {}, set()
    for seg in package["segments"]:
        check()
        slot = seg["model_slot"]
        slots.add(slot)
        names = [slot + "_model", "clip", "vae"]
        if slot == "ref2va":
            refs = 解析槽位(seg["refs"])
            if refs["音频"] and type(generation.get("audio_vae")) is not bool:
                raise ValueError(f"精修段{seg['index'] + 1}缺少 audio_vae 布尔记录")
            if refs["音频"] and generation["audio_vae"]:
                names.append("audio_vae")
            if generation.get("参考图尺寸") not in ("match", "max"):
                raise ValueError("精修缺少有效初采参考图尺寸记录")
        for name in names:
            if models.get(name) is None:
                raise ValueError(f"精修段{seg['index'] + 1}缺少 {name}")
        base = getattr(models[slot + "_model"], "model", None)
        if not isinstance(base, MiniMaxH3) or not isinstance(base.diffusion_model, MiniMaxH3Model):
            raise ValueError(f"精修段{seg['index'] + 1}的 {slot}_model 不是当前 H3 模型结构")
        required.add(选管线(seg["task"]))
        if seg["middle_frame_index"] is not None:
            required.add("MiniMaxH3AddGuide")
        校验精修素材(seg, generation)
        identities[seg["index"]] = {name: 取模型身份(models[name]) for name in names}
    if any(v is None for ids in identities.values() for v in ids.values()):
        lines.append("警告: 存在不能弱引用且无内容身份的资源，对应段禁用精修持久缓存")
    if any(v is not None and v["scope"] == "process" for ids in identities.values() for v in ids.values()):
        lines.append("模型身份仅作进程内隔离，未证实同一checkpoint；原位换权重请增加缓存失效版本")
    old = generation.get("模型链身份", {})
    current = 提取模型链身份(models, slots)
    if any(name in current and current[name] != value for name, value in old.items()):
        lines.append("警告: 可证模型链身份不一致，当前精修使用新连接资源")
    return identities


def _采样预检(package, models, lines, required):
    identities = _资源预检(package, models, lines, required)
    seen = {}
    seg = None
    try:
        for seg in package["segments"]:
            检查取消()
            if seg["audio_latent"] is not None:
                _校验来源音频latent(seg["audio_latent"], 1, seg["frame_count"])
            _前驱尾(seg, package["generation"], seen.get(seg["predecessor_index"]))
            seen[seg["index"]] = seg
        return identities
    finally:
        seen.clear()
        seg = None


def _后处理内存预算(package, params, upscale, width, height, enlarged):
    """仅累计本后处理已知数据，跨阶段保守相加；不代表精确峰值或可用内存。"""
    def source_bytes(value):
        if isinstance(value, torch.Tensor):
            # 视图也会持有整块源存储；别名重复计入，不为可能共享的存储打折。
            return max(value.numel() * value.element_size(), value.untyped_storage().nbytes())
        if isinstance(value, dict):
            return sum(source_bytes(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return sum(source_bytes(v) for v in value)
        return 0

    segments = package["segments"]
    first = segments[0]
    refine = params["精修强度"] > 0
    h3 = enlarged and upscale["放大方式"] == "H3潜空间"
    # 精修输出/前驱可能提升精度，至少按 FP32，并保留源中更高精度的空间。
    unit = max(4, *(s["video_latent"].element_size() for s in segments))
    videos = [s["video_latent"].numel() * unit for s in segments]
    enlarged_videos = [24 * s["video_latent"].shape[2] * (height // 16) * (width // 16) * unit
                       for s in segments]
    work = []
    for seg, video in zip(segments, videos):
        audio = seg["audio_latent"]
        audio_unit = max(unit, audio.element_size() if audio is not None else 0)
        audio_bytes = 32 * 2 * round(seg["frame_count"] / 24 * 40) * audio_unit
        # AV工作副本、mask、官方空AV/采样返回、guide隔离/前驱尾余量；另留整段视频保护备份。
        work.append(4 * (video + audio_bytes) + video)
    decode_w, decode_h = (width, height) if h3 else (first["width"], first["height"])
    decode_videos = enlarged_videos if h3 else videos
    # 裁前整段解码+CPU FP32转换副本、隔离latent、尾帧/目标单批临时IMAGE。
    decode = max(2 * s["frame_count"] * decode_w * decode_h * 3 * 4 + v
                 for s, v in zip(segments, decode_videos)) + 3 * width * height * 3 * 4
    parts = {
        "初采IMAGE": package["frame_count"] * first["width"] * first["height"] * 3 * 4,
        "包内源Tensor": source_bytes(package),
        "精修全段视频": sum(videos) if refine else 0,
        "当前工作AV副本/mask": max(work) if refine else 0,
        # _图像副本整图 clone：首尾留在 kw，中间图在调用参数中；段内相加、段间取峰值。
        "当前工作图像副本": max(sum(image.numel() * image.element_size()
                                  for image in _有效图像(s).values() if isinstance(image, torch.Tensor))
                              for s in segments) if refine else 0,
        "最终IMAGE": package["frame_count"] * width * height * 3 * 4,
        "当前解码段": decode,
        "H3全段放大latent": sum(enlarged_videos) if h3 else 0,
        # FP32输入/归一化及输出/反归一化各按三份；不推算网络隐藏层或激活。
        "H3当前段FP32": max(3 * (v + up) // unit * 4 for v, up in zip(videos, enlarged_videos)) if h3 else 0,
        "像素原生scale单批": 0,
    }
    if enlarged and upscale["放大方式"] == "像素模型":
        scale = upscale["像素放大模型"].scale
        # 呈现逐帧调用；按原生scale而非用户目标倍率，留拼块/归一化/输出临时帧。
        parts["像素原生scale单批"] = 4 * math.ceil(first["width"] * scale) * math.ceil(first["height"] * scale) * 3 * 4
    total = sum(parts.values())
    report = "后处理已知数据预算: " + "｜".join(f"{name}≈{_人类字节(size)}" for name, size in parts.items())
    report += (f"｜合计≈{_人类字节(total)}（初采IMAGE按可能驻留计；跨阶段/别名保守相加，不按缓存命中减免；"
               "不含模型权重、未知激活及文件素材解码量，不保证不OOM）")
    return report, total


def _目标预检(package, models, params, upscale):
    _校验参数(params)
    if models.get("vae") is None:
        raise ValueError("后处理缺少视频 vae")
    seg = package["segments"][0]
    width, height = 计算目标尺寸(seg["width"], seg["height"], upscale.get("放大倍率"))
    mode = upscale.get("放大方式")
    if mode not in ("Lanczos", "像素模型", "H3潜空间"):
        raise ValueError("未知放大方式")
    enlarged = (width, height) != (seg["width"], seg["height"])
    required = {"VAEDecode"}
    info = None
    if enlarged:
        if mode == "H3潜空间":
            权重 = upscale.get("H3放大权重")
            if 权重 == "未选择" or not isinstance(权重, str) or not 权重:
                # 默认档就是 H3潜空间，目录里没有兼容权重时下拉只剩「未选择」；报错指到组件上，
                # 也给出免模型的退路。不放宽：这种值 预检H3放大权重 本来也会拒，只是文案说的是路径规则。
                raise ValueError("放大方式为「H3潜空间」时，请在「H3放大权重」下拉选一个 models/latent_upscale_models/ "
                                 "下符合 H3 24 通道 3D 架构的 .safetensors；目录里没有就改用「Lanczos」（免模型）")
            info = 预检H3放大权重(权重)
        else:
            required.add("ImageScale")
            if mode == "像素模型":
                pixel_model = upscale.get("像素放大模型")
                if getattr(pixel_model, "patcher", None) is None:
                    raise ValueError("放大方式为「像素模型」时，请在「像素放大模型」下拉选一个 models/upscale_models/ "
                                     "下的模型文件")
                scale = getattr(pixel_model, "scale", None)
                if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
                    raise ValueError("「像素放大模型」下拉选的文件没给出有限正数放大倍率，已在精修前中止；请换 models/upscale_models/ 下的单图放大模型")
                required.add("ImageUpscaleWithModel")
    return width, height, enlarged, info, required


def _预检(package, models, params, upscale, lines):
    校验初采产物(package)
    width, height, enlarged, info, required = _目标预检(package, models, params, upscale)
    budget, size = _后处理内存预算(package, params, upscale, width, height, enlarged)
    lines.append(budget)
    _日志.info(budget)
    limit = _内存硬限额字节()
    if limit and size > limit:
        raise ValueError(f"后处理已知数据预估{_人类字节(size)}超过硬限额{_人类字节(limit)}，已在精修前中止；{budget}")
    if size > _内存预警阈值字节():
        warning = "警告: 后处理已知数据内存较大，请降低分辨率或时长；未计模型权重和未知激活，不保证不OOM"
        lines.append(warning)
        _日志.warning(warning)
    identities = _采样预检(package, models, lines, required) if params["精修强度"] > 0 else {}
    for name in sorted(required):
        if not 官方节点可用(name):
            raise ValueError(f"后处理缺少官方节点 {name}")
    sources = {s["index"]: 张量摘要(s["video_latent"]) for s in package["segments"]}
    return width, height, enlarged, info, identities, sources


def _直连缓存读(node_id, stage, key, shape, source, 标签, lines):
    """内存直连流的缓存只用于省重算：IO 故障按未命中处理，不能拖垮已经能算完的这一轮。"""
    try:
        return 读后处理缓存(node_id, stage, key, shape, source)
    except 缓存读写异常 as exc:
        lines.append(f"警告: {标签}缓存不可读，按未命中处理：{exc}")
        return None


def _直连缓存写(node_id, stage, key, video, source, 标签, lines):
    try:
        写后处理缓存(node_id, stage, key, video, source)
        return True
    except 缓存读写异常 as exc:
        lines.append(f"警告: {标签}缓存未写入，本轮结果照常返回，重跑需重新采样：{exc}")
        return False


def _精修全部(package, models, params, node_id, identities, sources, lines, counts, advance):
    patched, results, videos = {}, {}, []
    inputs = None
    try:
        for seg in package["segments"]:
            检查取消()
            index = seg["index"]
            if params["精修强度"] == 0:
                video = seg["video_latent"]
            else:
                previous = results.get(seg["predecessor_index"])
                key = 精修键(seg, package["generation"], params, identities[index], previous)
                video = (None if key is None else
                         _直连缓存读(node_id, "refine", key, seg["video_latent"].shape,
                                    sources[index], "精修", lines))
                if video is None:
                    slot = seg["model_slot"]
                    if slot not in patched:
                        patched[slot] = _补丁模型(models[slot + "_model"], package["generation"])
                    inputs = {**models, "model_p": patched[slot]}
                    video = 精修一段(seg, inputs, package["generation"], params, previous)["video_latent"]
                    inputs = None
                    检查取消()
                    if key is not None:
                        if _直连缓存写(node_id, "refine", key, video, sources[index], "精修", lines):
                            counts["精修写入"] += 1
                else:
                    counts["精修命中"] += 1
                original = seg["audio_latent"]
                padding = round(seg["frame_count"] / 24 * 40) - (original.shape[-1] if original is not None else 0)
                if padding:
                    lines.append(f"段{index + 1}冻结工作音频补零{padding}个latent位置，初采音轨不变")
            videos.append(video)
            results[index] = {"index": index, "frame_count": seg["frame_count"],
                              "video_latent": video, "audio_latent": seg["audio_latent"]}
            advance()
        return videos
    finally:
        inputs = previous = video = original = seg = videos = None
        patched.clear()
        results.clear()


def _放大全部(videos, info, width, height, version, node_id, lines, counts, advance):
    outputs = []
    model = None
    try:
        with ExitStack() as stack:
            for video in videos:
                检查取消()
                source = 张量摘要(video)
                key = 放大键(video, width, height, info["digest"], version)
                shape = (1, 24, video.shape[2], height // 16, width // 16)
                output = _直连缓存读(node_id, "h3-upscale", key, shape, source, "放大", lines)
                if output is None:
                    if model is None:
                        model = stack.enter_context(加载H3放大模型(info))
                    output = 放大H3视频latent(video, model, width, height)
                    检查取消()
                    if _直连缓存写(node_id, "h3-upscale", key, output, source, "放大", lines):
                        counts["H3写入"] += 1
                else:
                    counts["H3命中"] += 1
                outputs.append(output)
                advance()
        return outputs
    finally:
        model = output = video = outputs = videos = None


def _呈现(package, videos, vae, upscale, width, height, enlarged, advance, check=None):
    check = check or 检查取消
    stitch = 流式拼接(package["frame_count"], 重叠帧数=0)
    last = images = batch = None
    iterator = iter(videos)
    try:
        # zip 会在复用结果元组时额外持有上一段视频，不能用于严格逐段磁盘流。
        for seg in package["segments"]:
            video = next(iterator)
            check()
            # 官方/第三方VAE包装可能原位处理输入，只隔离当前段latent而非全片IMAGE。
            images = 调用节点("VAEDecode", samples={"samples": video.detach().clone()}, vae=vae)[0]
            expected = (seg["frame_count"], video.shape[-2] * 16, video.shape[-1] * 16, 3)
            if (type(images) is not torch.Tensor or tuple(images.shape) != expected
                    or not images.is_floating_point() or not bool(torch.isfinite(images).all())):
                raise ValueError(f"后处理段{seg['index'] + 1}解码形状或有限值不符，预期{expected}")
            images = images.detach().to(device="cpu", dtype=torch.float32)[seg["crop_prefix"]:]
            if seg["color_match"]:
                匹配开头色光(images, last)
            last = images[-1].clone()
            if enlarged and upscale["放大方式"] != "H3潜空间":
                for frame in range(len(images)):
                    check()
                    batch = 放大图像批(images[frame:frame + 1], upscale["放大方式"], width, height,
                                      upscale.get("像素放大模型"))
                    stitch.追加(batch.detach().to(device="cpu", dtype=torch.float32))
                    batch = None
            else:
                stitch.追加(images)
            if stitch.结果().shape[0] != seg["output_end"]:
                raise ValueError(f"后处理段{seg['index'] + 1}输出区间不符")
            images = video = None
            check()
            清理显存(归还缓存=False)
            advance()
        output = stitch.结果()
        if output is None or tuple(output.shape) != (package["frame_count"], height, width, 3):
            raise ValueError("后处理成片帧数或尺寸不符")
        return output
    finally:
        try:
            close = getattr(videos, "close", None)
            if close is not None:
                close()
        finally:
            iterator = close = last = images = batch = stitch = output = video = videos = None


def 执行后处理(初采包, 模型输入, 精修参数, 放大参数, node_id, 进度回调=None):
    package, params, upscale = 初采包, 精修参数, 放大参数
    videos = images = None
    lines = []
    counts = {"精修命中": 0, "精修写入": 0, "H3命中": 0, "H3写入": 0}
    started = time.perf_counter()
    try:
        检查取消()
        width, height, enlarged, info, identities, sources = _预检(package, 模型输入, params, upscale, lines)
        n = len(package["segments"])
        total, done = n * (3 if info is not None else 2), 0
        if 进度回调:
            进度回调(0, total)

        def advance():
            nonlocal done
            done += 1
            if 进度回调 and done < total:
                进度回调(done, total)

        t0 = time.perf_counter()
        videos = _精修全部(package, 模型输入, params, node_id, identities, sources, lines, counts, advance)
        refine_time = time.perf_counter() - t0
        清理显存()
        t0 = time.perf_counter()
        if info is not None:
            videos = _放大全部(videos, info, width, height, params["缓存失效版本"], node_id, lines, counts, advance)
            清理显存()
        upscale_time = time.perf_counter() - t0
        t0 = time.perf_counter()
        images = _呈现(package, videos, 模型输入["vae"], upscale, width, height, enlarged, advance)
        present_time = time.perf_counter() - t0
        stats = 后处理缓存统计(node_id)
        first = package["segments"][0]
        lines.extend([
            f"来源节点{package['source_node_id']} / 运行{package['source_run_id']}；{n}段",
            f"画布{first['width']}×{first['height']} → {width}×{height}；实际倍率{width / first['width']:.3f}×{height / first['height']:.3f}",
            f"精修强度{params['精修强度']} / 步数{params['精修步数']} / 种子{params['精修种子']} / {params['采样器']} / {params['调度器']}",
            f"放大方式{upscale['放大方式']}" + (f" / 权重{info['name']}" if info is not None else ""),
            f"精修缓存命中{counts['精修命中']} / 写入{counts['精修写入']}；H3缓存命中{counts['H3命中']} / 写入{counts['H3写入']}",
            f"独立后处理缓存: {stats['path']}；{stats['files']}项，{_人类字节(stats['bytes'])}；原清空段缓存按钮不清此目录",
            f"{package['frame_count']}帧 / {package['output_fps']}fps；原初采音轨直接复用，不重解码、不变速",
            f"耗时: 精修{refine_time:.2f}s / H3放大{upscale_time:.2f}s / 呈现{present_time:.2f}s / 总计{time.perf_counter() - started:.2f}s",
            "内存直连仍由宿主持有初采产物与原成片；仅释放本轮临时引用，不请求全局深清理",
        ])
        if enlarged and upscale["放大方式"] == "像素模型":
            lines.append(f"像素模型原生倍率{getattr(upscale['像素放大模型'], 'scale', '未知')}；按目标尺寸再次缩放不等于原生该倍率模型")
        if package["output_fps"] != 24:
            lines.append("警告: 播放时长与24fps采样基座不同，未拉伸原音轨")
        检查取消()
        report = "\n".join(lines)
        _日志.info(report)
        if 进度回调:
            进度回调(total, total)
        return images, package["audio"], report
    finally:
        videos = images = None
        清理显存()


def _描述字节(value):
    """只解释存储清单的 Tensor 描述，不创建占位 Tensor。"""
    if type(value) is dict:
        if set(value) == {"shape", "dtype", "bytes"}:
            units = {"torch.float16": 2, "torch.bfloat16": 2, "torch.float32": 4, "torch.float64": 8}
            shape, size = value["shape"], value["bytes"]
            if (type(shape) is not list or any(type(n) is not int or n < 0 for n in shape)
                    or type(value["dtype"]) is not str or value["dtype"] not in units
                    or type(size) is not int or size != math.prod(shape) * units[value["dtype"]]):
                raise ValueError("磁盘 Tensor 描述形状/精度/字节数不符")
            return size
        return sum(_描述字节(v) for v in value.values())
    if type(value) is list:
        return sum(_描述字节(v) for v in value)
    return 0


def _描述形状(value, expected, label):
    if (type(value) is not dict or set(value) != {"shape", "dtype", "bytes"}
            or value["shape"] != list(expected)):
        raise ValueError(f"磁盘 {label} Tensor 描述形状不符")
    _描述字节(value)


def _磁盘元数据(manifest, refine, check):
    from .初采产物 import (
        初采包, 段快照, _字段, _要求, _整数, _有限数, _容器, _校验素材, _生成字段,
    )
    from .条件组装 import 选模型槽, 需要尾帧
    from .段间连续 import 裁前缀帧数, _video_latent_t, 规范锚帧数, 默认音频上下文帧数

    header = manifest["package"]
    _要求(set(header) == set(初采包.__annotations__) - {"audio", "segments"}, "磁盘包 header 字段")
    _要求(header["type"] == "LVP_FIRST_PASS" and type(header["version"]) is int
        and header["version"] == 1, "磁盘包 type/version")
    _要求(type(header["sampling_fps"]) is int and header["sampling_fps"] == 24, "sampling_fps")
    _要求(_有限数(header["output_fps"]) and header["output_fps"] > 0, "output_fps")
    _要求(_整数(header["frame_count"], 1), "总帧数")
    generation = header["generation"]
    _要求(type(generation) is dict and set(generation) <= _生成字段, "generation 白名单")
    _容器(header, 允许张量=False)
    if "audio_vae" in generation:
        _要求(type(generation["audio_vae"]) is bool, "audio_vae")
    if "音频上下文帧数" in generation:
        _要求(_整数(generation["音频上下文帧数"]), "音频上下文帧数")
    segments = [record["data"] for record in manifest["segments"]]
    seen, cursor, canvas = {}, 0, None
    for seg in segments:
        check()
        _字段(seg, 段快照, "磁盘段")
        _容器(seg, 允许张量=False)
        _描述字节(seg)
        index = seg["index"]
        _要求(_整数(index) and index not in seen, "段 index 须唯一")
        _要求(type(seg["task"]) is str and seg["model_slot"] == 选模型槽(seg["task"]), "task/model_slot")
        _要求(type(seg["prompt"]) is str and type(seg["source_cache_key"]) is str
            and bool(seg["source_cache_key"]), "prompt/source_cache_key")
        _要求(type(seg["refs"]) is dict, "refs")
        _校验素材(seg)
        _要求(_有限数(seg["start"]) and _有限数(seg["end"]) and seg["end"] > seg["start"], "段时间窗")
        w, h, frames = seg["width"], seg["height"], seg["frame_count"]
        _要求(_整数(w, 32) and _整数(h, 32) and w % 32 == h % 32 == 0, "画布须32对齐")
        _要求(canvas is None or canvas == (w, h), "所有段画布须一致")
        canvas = (w, h)
        _要求(_整数(frames, 5) and frames % 17 == 5, "frame_count 须为17k+5")
        _描述形状(seg["video_latent"], (1, 24, _video_latent_t(frames), h // 16, w // 16), "video_latent")
        audio = seg["audio_latent"]
        if audio is not None:
            shape = audio.get("shape") if type(audio) is dict else None
            _要求(type(shape) is list and len(shape) == 4 and shape[:3] == [1, 32, 2]
                and _整数(shape[-1], 1) and shape[-1] <= round(frames / 24 * 40), "audio_latent 形状或长度")
            _描述形状(audio, shape, "audio_latent")
            if refine:
                _要求(shape[-1] < round(默认音频上下文帧数 / 24 * 40)
                    or shape[-1] == round(frames / 24 * 40), "来源音频长度不在完整视频时间网格")
        anchor, crop, predecessor = seg["anchor_frames"], seg["crop_prefix"], seg["predecessor_index"]
        _要求(_整数(anchor) and (anchor == 0 or anchor >= 5 and anchor % 17 == 5), "anchor_frames")
        _要求(_整数(crop) and crop == 裁前缀帧数(frames, anchor) and crop < frames, "crop_prefix")
        if predecessor is None:
            _要求(anchor == 0, "无前驱不能有锚帧")
        else:
            _要求(_整数(predecessor) and predecessor in seen and anchor > 0, "predecessor_index 须指向已出现真实段")
            _要求(anchor <= seen[predecessor]["frame_count"], "前驱锚长度")
            if refine:
                context = generation.get("上下文帧数")
                _要求(_整数(context, 5) and generation.get("音频上下文帧数") == 默认音频上下文帧数,
                    "精修前驱上下文记录")
                expected = 规范锚帧数(min(context, seen[predecessor]["frame_count"]))
                _要求(anchor == expected and anchor <= frames, "精修前驱 anchor_frames 不匹配")
        _要求(_整数(seg["output_start"]) and seg["output_start"] == cursor, "output_start 区间须连续")
        cursor += frames - crop
        _要求(_整数(seg["output_end"], 1) and seg["output_end"] == cursor, "output_end 半开区间")
        middle, middle_ref = seg["middle_frame_index"], seg["refs"].get("中间帧")
        if 需要尾帧(seg["task"]):
            _要求(middle_ref is None or type(middle_ref) is str, "中间帧须为文件名")
        enabled = 需要尾帧(seg["task"]) and bool(middle_ref)
        _要求((enabled and _整数(middle) and crop < middle < frames - 1)
            if middle is not None else not enabled, "middle_frame_index")
        window = seg["reference_audio_window"]
        if window is not None:
            _要求(seg["model_slot"] == "ref2va" and type(window) is list
                and window == [seg["start"], seg["end"]], "reference_audio_window")
        _要求(type(seg["color_match"]) is bool, "color_match")
        if seg["color_match"]:
            _要求(predecessor == index - 1 and predecessor is not None and anchor > 0
                and _整数(generation.get("上下文帧数"), 1), "color_match 须为真实连续段")
        seen[index] = seg
    _要求(cursor == header["frame_count"], "最后区间须等于总帧数")
    if manifest["audio"] is not None:
        audio = manifest["audio"]["data"]
        _要求(set(audio) == {"sample_rate", "waveform"} and _整数(audio["sample_rate"], 1), "原音轨")
        waveform = audio["waveform"]
        _要求(type(waveform) is dict and set(waveform) == {"shape", "dtype", "bytes"}, "waveform 描述")
        _描述字节(audio)
    # 这只是呈现和资源检查的元信息视图，绝不传入内存包/Tensor 校验或采样。
    return {**header, "segments": segments}


def _磁盘内存预算(manifest, package, params, upscale, width, height, enlarged):
    segments = package["segments"]
    refine = params["精修强度"] > 0
    h3 = enlarged and upscale["放大方式"] == "H3潜空间"
    first = segments[0]
    unit = max(4, *(s["video_latent"]["bytes"] // math.prod(s["video_latent"]["shape"]) for s in segments))
    videos = [math.prod(s["video_latent"]["shape"]) * unit for s in segments]
    ups = [24 * s["video_latent"]["shape"][2] * (height // 16) * (width // 16) * unit for s in segments]
    work, tails = [], []
    for seg, video in zip(segments, videos):
        audio = seg["audio_latent"]
        au = max(unit, audio["bytes"] // math.prod(audio["shape"]) if audio else 0)
        work.append(5 * video + 4 * 64 * round(seg["frame_count"] / 24 * 40) * au)
        # 尾块、条件及摘要隔离小副本；按实际锚 token 和原生40音频位置收费。
        from .段间连续 import _video_latent_t
        tail = 24 * _video_latent_t(seg["anchor_frames"]) * (seg["height"] // 16) * (seg["width"] // 16) * unit
        tails.append(3 * (tail + 64 * 40 * au) if seg["predecessor_index"] is not None else 0)
    dw, dh = (width, height) if h3 else (first["width"], first["height"])
    parts = {
        "当前源段Tensor": max(_描述字节(s) for s in segments),
        "当前阶段视频": max(videos) + (max(ups) if h3 else 0),
        "当前工作AV副本/mask": max(work) if refine else 0,
        "当前工作图像副本": max(sum(_描述字节(v) for v in _有效图像(s).values()) for s in segments) if refine else 0,
        "必要前驱小尾": max(tails) if refine else 0,
        "最终IMAGE": package["frame_count"] * width * height * 3 * 4,
        "当前解码段": max(2 * s["frame_count"] * dw * dh * 3 * 4 + v
                          for s, v in zip(segments, ups if h3 else videos)) + 3 * width * height * 3 * 4,
        "原音轨": _描述字节(manifest["audio"]["data"]) if manifest["audio"] else 0,
        "H3当前段FP32": max(3 * (v + up) // unit * 4 for v, up in zip(videos, ups)) if h3 else 0,
        "像素原生scale单批": 0,
    }
    if enlarged and upscale["放大方式"] == "像素模型":
        scale = upscale["像素放大模型"].scale
        parts["像素原生scale单批"] = 4 * math.ceil(first["width"] * scale) * math.ceil(first["height"] * scale) * 3 * 4
    size = sum(parts.values())
    report = "磁盘后处理已知数据预算: " + "｜".join(f"{k}≈{_人类字节(v)}" for k, v in parts.items())
    report += (f"｜合计≈{_人类字节(size)}（跨阶段保守相加，不按缓存命中减免；不含初采全IMAGE/全段精修、"
               "模型权重、未知激活及文件素材解码量，不代表精确峰值，不保证不OOM）")
    return report, size


def _磁盘预检(manifest, models, params, upscale, lines, check):
    _校验参数(params)
    package = _磁盘元数据(manifest, params["精修强度"] > 0, check)
    width, height, enlarged, info, required = _目标预检(package, models, params, upscale)
    budget, size = _磁盘内存预算(manifest, package, params, upscale, width, height, enlarged)
    lines.append(budget)
    _日志.info(budget)
    limit = _内存硬限额字节()
    if limit and size > limit:
        raise ValueError(f"磁盘后处理已知数据预估超过硬限额，已在读段/精修前中止；{budget}")
    if size > _内存预警阈值字节():
        lines.append("警告: 后处理已知数据内存较大，不含模型权重与未知激活，不保证不OOM")
    identities = _资源预检(package, models, lines, required, check) if params["精修强度"] > 0 else {}
    for name in sorted(required):
        if not 官方节点可用(name):
            raise ValueError(f"后处理缺少官方节点 {name}")
    return package, width, height, enlarged, info, identities


def _磁盘缓存读取(node_id, record, *, required=False):
    from .后处理缓存 import 后处理缓存路径

    video = 路径 = None
    try:
        video = 读后处理缓存(node_id, record["stage"], record["key"], record["shape"], record["source_digest"])
        if video is None and ((路径 := 后处理缓存路径(node_id, record["stage"], record["key"])).exists() or required):
            raise ValueError(f"磁盘阶段 {record['stage']} 丢失或损坏，不能继续或默默重采；人工确认后可删 {路径} 再按原参数重采（原清空段缓存按钮不清此目录）")
        return video
    finally:
        video = 路径 = None


def _读磁盘阶段(ref, record, node_id, check):
    from .初采产物存储 import 读源段

    source = video = None
    try:
        check()
        if record["stage"] == "source":
            source = 读源段(ref, record["ordinal"])
            video = source["video_latent"]
        else:
            video = _磁盘缓存读取(node_id, record, required=True)
        return video
    finally:
        source = video = None


def _磁盘前驱(ref, seg, generation, results, node_id, check):
    from .初采产物存储 import 读源段
    from .精修条件 import 提取精修前驱尾

    source = previous = None
    try:
        predecessor = seg["predecessor_index"]
        if predecessor is None:
            return None
        record = results[predecessor]
        check()
        source = 读源段(ref, record["ordinal"])
        # 只留下原音频；读取原尺寸精修阶段前先释放原视频和refs。
        previous = {"index": source["index"], "frame_count": source["frame_count"],
                    "audio_latent": source["audio_latent"]}
        source = None
        previous["video_latent"] = _读磁盘阶段(ref, record, node_id, check)
        return 提取精修前驱尾(seg, generation, previous)
    finally:
        source = previous = None


def _写磁盘阶段(node_id, record, video, check):
    try:
        if type(video) is not torch.Tensor or list(video.shape) != record["shape"]:
            raise ValueError("磁盘阶段输出形状不符")
        check()
        写后处理缓存(node_id, record["stage"], record["key"], video, record["source_digest"])
    finally:
        video = None


def _磁盘精修(ref, package, models, params, node_id, identities, lines, counts, advance, check):
    from .初采产物存储 import 读源段

    patched, results = {}, {}
    seg = previous = video = inputs = None
    try:
        for ordinal, metadata in enumerate(package["segments"]):
            check()
            if params["精修强度"] == 0:
                results[metadata["index"]] = {"stage": "source", "ordinal": ordinal,
                                               "shape": metadata["video_latent"]["shape"]}
            else:
                previous = _磁盘前驱(ref, metadata, package["generation"], results, node_id, check)
                check()
                seg = 读源段(ref, ordinal)
                source = 张量摘要(seg["video_latent"])
                key = 精修键(seg, package["generation"], params, identities[seg["index"]], previous)
                persistent = key is not None
                if key is None:
                    # 模型身份拿不到（不可弱引用）⇒ 无法构造可复现摘要。随机键是一次性桶：本轮写完
                    # 读回的校验照做，但下次运行不可能命中，因此既不读也不谎报命中；文件留在缓存桶。
                    key = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
                record = {"stage": "refine", "key": key, "shape": list(seg["video_latent"].shape),
                          "source_digest": source, "ordinal": ordinal}
                video = _磁盘缓存读取(node_id, record) if persistent else None
                if video is None:
                    slot = seg["model_slot"]
                    if slot not in patched:
                        patched[slot] = _补丁模型(models[slot + "_model"], package["generation"])
                    inputs = {**models, "model_p": patched[slot]}
                    video = 精修一段(seg, inputs, package["generation"], params, previous)["video_latent"]
                    inputs = None
                    _写磁盘阶段(node_id, record, video, check)
                    counts["精修写入"] += 1
                else:
                    counts["精修命中"] += 1
                padding = round(seg["frame_count"] / 24 * 40) - (seg["audio_latent"].shape[-1] if seg["audio_latent"] is not None else 0)
                if padding:
                    lines.append(f"段{seg['index'] + 1}冻结工作音频补零{padding}个latent位置，初采音轨不变")
                seg = previous = video = None
                # 索引没有 Tensor；写完读回验证，阶段丢失/损坏必须硬失败。
                _读磁盘阶段(ref, record, node_id, check)
                results[metadata["index"]] = record
            check()
            advance()
        return results
    finally:
        seg = previous = video = inputs = None
        patched.clear()
        results = None


def _磁盘放大(ref, package, results, info, width, height, version, node_id, counts, advance, check):
    outputs = {}
    model = video = output = None
    try:
        with ExitStack() as stack:
            for metadata in package["segments"]:
                check()
                record = results[metadata["index"]]
                video = _读磁盘阶段(ref, record, node_id, check)
                source = 张量摘要(video)
                key = 放大键(video, width, height, info["digest"], version)
                record = {"stage": "h3-upscale", "key": key,
                          "shape": [1, 24, video.shape[2], height // 16, width // 16],
                          "source_digest": source, "ordinal": record["ordinal"]}
                output = _磁盘缓存读取(node_id, record)
                if output is None:
                    if model is None:
                        check()
                        model = stack.enter_context(加载H3放大模型(info))
                    output = 放大H3视频latent(video, model, width, height)
                    _写磁盘阶段(node_id, record, output, check)
                    counts["H3写入"] += 1
                else:
                    counts["H3命中"] += 1
                output = video = None
                _读磁盘阶段(ref, record, node_id, check)
                outputs[metadata["index"]] = record
                check()
                advance()
        return outputs
    finally:
        model = output = video = outputs = None


def _磁盘视频流(ref, package, results, node_id, check):
    video = None
    try:
        for seg in package["segments"]:
            video = _读磁盘阶段(ref, results[seg["index"]], node_id, check)
            yield video
            video = None
    finally:
        video = None


def 执行磁盘后处理(ref, 模型输入, 精修参数, 放大参数, 进度回调=None):
    """仅持有当前源段及必要前驱小尾；全精修完成后才开始放大。"""
    from .跨任务清理 import 取得协调器
    from .初采产物存储 import 读交接清单, 读原音轨

    coordinator = 取得协调器()
    context = coordinator.取磁盘执行上下文(ref)
    cache_node_id, job, attempt = context["cache_node_id"], context["job_id"], context["attempt"]

    def check():
        检查取消()
        coordinator.检查任务取消(job, attempt)

    images = audio = videos = results = None
    lines = []
    counts = {"精修命中": 0, "精修写入": 0, "H3命中": 0, "H3写入": 0}
    started = time.perf_counter()
    try:
        check()
        manifest = 读交接清单(ref)
        package, width, height, enlarged, info, identities = _磁盘预检(
            manifest, 模型输入, 精修参数, 放大参数, lines, check)
        n = len(package["segments"])
        total, done = n * (3 if info is not None else 2), 0
        if 进度回调:
            进度回调(0, total)

        def advance():
            nonlocal done
            done += 1
            if 进度回调 and done < total:
                进度回调(done, total)

        results = _磁盘精修(ref, package, 模型输入, 精修参数, cache_node_id, identities, lines, counts, advance, check)
        清理显存()
        if info is not None:
            results = _磁盘放大(ref, package, results, info, width, height, 精修参数["缓存失效版本"],
                              cache_node_id, counts, advance, check)
            清理显存()
        videos = _磁盘视频流(ref, package, results, cache_node_id, check)
        images = _呈现(package, videos, 模型输入["vae"], 放大参数, width, height, enlarged, advance, check)
        check()
        audio = 读原音轨(ref)
        stats = 后处理缓存统计(cache_node_id)
        first = package["segments"][0]
        lines.extend([
            f"磁盘来源节点{package['source_node_id']} / 运行{package['source_run_id']}；{n}段；缓存节点{cache_node_id}",
            f"画布{first['width']}×{first['height']} → {width}×{height}；放大方式{放大参数['放大方式']}",
            f"精修缓存命中{counts['精修命中']} / 写入{counts['精修写入']}；H3缓存命中{counts['H3命中']} / 写入{counts['H3写入']}",
            f"独立后处理缓存: {stats['path']}；{stats['files']}项，{_人类字节(stats['bytes'])}",
            f"{package['frame_count']}帧 / {package['output_fps']}fps；原音轨最后读取一次，不重解码、不变速",
            f"磁盘阶段仅保留JSON索引；仅释放本轮局部引用，不修改或清理源文件；总计{time.perf_counter() - started:.2f}s",
        ])
        if enlarged and 放大参数["放大方式"] == "像素模型":
            lines.append(f"像素模型原生倍率{放大参数['像素放大模型'].scale}；按目标尺寸再次缩放不等于原生该倍率模型")
        if package["output_fps"] != 24:
            lines.append("警告: 播放时长与24fps采样基座不同，未拉伸原音轨")
        check()
        report = "\n".join(lines)
        _日志.info(report)
        if 进度回调:
            进度回调(total, total)
        return images, audio, report
    finally:
        try:
            if videos is not None:
                videos.close()
        finally:
            images = audio = videos = results = None
            清理显存()
