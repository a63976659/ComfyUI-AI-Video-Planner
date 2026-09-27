"""H3 24通道3D整段空间放大，音频不参与。"""
# Apache-2.0; Copyright 2026 ComfyUI-Bernini Contributors; LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler.
# Modified: whole-segment inference only, strict safetensors validation and ComfyUI model lifecycle; see licenses/Apache-2.0-H3-Latent-Upscaler.txt.
from contextlib import contextmanager
import os
from pathlib import PureWindowsPath
import re

import torch
from torch import nn
from torch.nn import functional as F

from .后处理缓存 import 文件摘要
from .路径守卫 import 去设备前缀 as _去设备前缀


LATENTS_MEAN = [
    0.858090341091156, -0.9606591463088989, 1.0661640167236328, -0.5090325474739075,
    -0.2727581858634949, -1.3675414323806763, -0.2553254961967468, -0.26907554268836975,
    -0.5376840829849243, -0.0464097298681736, 0.6657370328903198, 0.19690127670764923,
    -0.5460608005523682, -0.4035342037677765, -0.23683024942874908, 0.25928452610969543,
    -0.30133944749832153, 0.211341992020607, -1.1206848621368408, 0.3581933379173279,
    -0.04225143790245056, 0.2604829967021942, 0.22864092886447906, 0.7056031823158264,
]
LATENTS_STD = [
    1.2223774194717407, 1.2767263650894165, 1.6831774711608887, 1.7549455165863037,
    1.5636216402053832, 2.194143533706665, 0.9653137922286987, 1.0569885969161987,
    0.841948926448822, 0.7729952931404114, 1.8955937623977661, 0.946841835975647,
    0.7996809482574463, 0.44988900423049927, 0.7197399735450743, 0.6936293244361877,
    2.961095094680786, 2.7694199085235596, 3.0496184825897217, 2.1088054180145264,
    3.276226282119751, 3.1627357006073, 2.2816812992095947, 2.6127843856811523,
]
_FOLDER = "latent_upscale_models"


def _norm_tensors(device):
    mean = torch.tensor(LATENTS_MEAN, dtype=torch.float32, device=device).view(1, 24, 1, 1, 1)
    std = torch.tensor(LATENTS_STD, dtype=torch.float32, device=device).view(1, 24, 1, 1, 1)
    return mean, std


class ResBlockEmb3D(nn.Module):
    def __init__(self, channels, emb_channels=64, dropout=0.1):
        super().__init__()
        self.in_layers = nn.Sequential(nn.GroupNorm(32, channels), nn.SiLU(),
                                       nn.Conv3d(channels, channels, 3, padding=1))
        self.emb_layers = nn.Sequential(nn.SiLU(), nn.Linear(emb_channels, 2 * channels))
        self.out_norm = nn.GroupNorm(32, channels)
        self.out_layers = nn.Sequential(nn.SiLU(), nn.Dropout(dropout),
                                        nn.Conv3d(channels, channels, 3, padding=1))
        nn.init.zeros_(self.out_layers[2].weight)
        nn.init.zeros_(self.out_layers[2].bias)

    def forward(self, x, emb):
        h = self.in_layers(x)
        emb_out = self.emb_layers(emb).to(h.dtype)[..., None, None, None]
        scale, shift = torch.chunk(emb_out, 2, dim=1)
        h = self.out_norm(h) * (1 + scale) + shift
        return x + self.out_layers(h)


class TemporalConv(nn.Module):
    def __init__(self, channels, kernel_size=5):
        super().__init__()
        self.norm = nn.GroupNorm(32, channels)
        self.dwconv = nn.Conv3d(channels, channels, (kernel_size, 1, 1),
                                padding=(kernel_size // 2, 0, 0), groups=channels)
        self.pwconv = nn.Conv3d(channels, channels, 1)
        nn.init.zeros_(self.pwconv.weight)
        nn.init.zeros_(self.pwconv.bias)

    def forward(self, x):
        return x + self.pwconv(self.dwconv(F.silu(self.norm(x))))


class LatentResizer3D(nn.Module):
    def __init__(self, channels=512, in_blocks=12, out_blocks=12, temporal_every=2, temporal_kernel=5):
        super().__init__()
        self.conv_in = nn.Conv3d(24, channels, 3, padding=1)
        self.embed = nn.Sequential(nn.Linear(1, 64), nn.SiLU(), nn.Linear(64, 64))
        for name, count in (("in_blocks", in_blocks), ("out_blocks", out_blocks)):
            blocks = nn.ModuleList()
            for b in range(count):
                blocks.append(ResBlockEmb3D(channels))
                if temporal_every and b % temporal_every == 0:
                    blocks.append(TemporalConv(channels, temporal_kernel))
            setattr(self, name, blocks)
        self.norm_out = nn.GroupNorm(32, channels)
        self.conv_out = nn.Conv3d(channels, 24, 3, padding=1)

    def forward(self, x, scale, target_size):
        emb = self.embed(x.new_tensor([[float(scale) - 1.0]]))
        x = self.conv_in(x)
        for block in self.in_blocks:
            x = block(x, emb.expand(x.shape[0], -1)) if isinstance(block, ResBlockEmb3D) else block(x)
        x = F.interpolate(x, size=target_size, mode="trilinear", align_corners=False)
        for block in self.out_blocks:
            x = block(x, emb.expand(x.shape[0], -1)) if isinstance(block, ResBlockEmb3D) else block(x)
        return self.conv_out(F.silu(self.norm_out(x)))


def 列H3放大权重():
    import folder_paths

    names = folder_paths.get_filename_list(_FOLDER)
    return ["未选择"] + sorted(n for n in names if n.lower().endswith(".safetensors"))


def 列兼容H3放大模型():
    """只列「加载端真正认得」的 H3 放大模型：判据与 预检H3放大权重 完全同一套，故清单里的名字
    不会在采样前才被拒（同一目录常被别的扩展放别的 latent 放大 safetensors，那些不适用本流程）。

    单个文件读不了（损坏、无权限、目录被挪走）一律跳过而不抛：清单是 UI 便利，
    不该让节点注册因一个坏文件整体失败；真选中要跑时仍由 预检H3放大权重 硬失败点名。"""
    from safetensors import SafetensorError

    兼容 = []
    for name in (n for n in 列H3放大权重() if n != "未选择"):   # 扩展名与排序沿用全量清单那一份
        try:
            形状, _ = _读头部(_权重路径(name))
            _头部配置(形状)
        except (OSError, ValueError, SafetensorError):
            continue
        兼容.append(name)
    return ["未选择"] + 兼容


def _权重路径(name):
    import folder_paths

    if (type(name) is not str or not name.lower().endswith(".safetensors")
            or PureWindowsPath(name).drive or PureWindowsPath(name).root
            or ".." in name.replace("\\", "/").split("/")):
        raise ValueError("请选择已注册目录中的 H3 3D safetensors 权重")
    path = folder_paths.get_full_path(_FOLDER, name)
    if path is None or not os.path.isfile(path):
        raise ValueError(f"H3放大权重不存在：{name}")
    real = os.path.normcase(_去设备前缀(os.path.realpath(path)))
    for root in folder_paths.get_folder_paths(_FOLDER):
        root = os.path.normcase(_去设备前缀(os.path.realpath(root)))
        try:
            if os.path.commonpath([root, real]) == root:
                return path
        except ValueError:
            continue
    raise ValueError("H3放大权重越出已注册目录")


def _头部配置(shapes):
    shape = shapes.get("conv_in.weight", ())
    if len(shape) != 5 or shape[1:] != (24, 3, 3, 3) or shape[0] < 32 or shape[0] % 32:
        raise ValueError("H3权重必须是24通道3D网络且隐藏通道可被32整除")
    channels = shape[0]
    counts = {}
    for stage in ("in_blocks", "out_blocks"):
        ids = {int(m.group(1)) for key in shapes
               if (m := re.fullmatch(rf"{stage}\.(\d+)\.in_layers\.0\.weight", key))}
        if not ids:
            raise ValueError("H3权重缺少残差层")
        counts[stage] = len(ids)
    temporal = [v for k, v in shapes.items() if k.endswith("dwconv.weight")]
    kernel = temporal[0][2] if temporal and len(temporal[0]) == 5 else 5
    if kernel < 1 or kernel % 2 == 0:
        raise ValueError("H3时间卷积核须为正奇数")
    config = dict(channels=channels, **counts, temporal_every=2 if temporal else 0, temporal_kernel=kernel)
    expected = {}

    def pair(name, weight, bias):
        expected[name + ".weight"] = weight
        expected[name + ".bias"] = (bias,)

    pair("conv_in", (channels, 24, 3, 3, 3), channels)
    pair("conv_out", (24, channels, 3, 3, 3), 24)
    pair("embed.0", (64, 1), 64)
    pair("embed.2", (64, 64), 64)
    pair("norm_out", (channels,), channels)
    for stage, count in counts.items():
        index = 0
        for b in range(count):
            stem = f"{stage}.{index}."
            for norm in ("in_layers.0", "out_norm"):
                pair(stem + norm, (channels,), channels)
            for conv in ("in_layers.2", "out_layers.2"):
                pair(stem + conv, (channels, channels, 3, 3, 3), channels)
            pair(stem + "emb_layers.1", (2 * channels, 64), 2 * channels)
            index += 1
            if temporal and b % 2 == 0:
                stem = f"{stage}.{index}."
                pair(stem + "norm", (channels,), channels)
                pair(stem + "dwconv", (channels, 1, kernel, 1, 1), channels)
                pair(stem + "pwconv", (channels, channels, 1, 1, 1), channels)
                index += 1
    if shapes != expected:
        raise ValueError("H3权重键名、形状或时间层布局不匹配已知3D架构")
    return config


def _读头部(path):
    from safetensors import safe_open

    with safe_open(path, framework="pt", device="cpu") as file:
        keys = list(file.keys())
        prefix = "upscaler." if keys and all(k.startswith("upscaler.") for k in keys) else ""
        shapes = {}
        for key in keys:
            header = file.get_slice(key)
            if header.get_dtype() not in ("F32", "F16", "BF16"):
                raise ValueError(f"H3权重不支持此dtype：{key}")
            shapes[key[len(prefix):]] = tuple(header.get_shape())
    return shapes, prefix


def 预检H3放大权重(name):
    from safetensors import SafetensorError

    path = _权重路径(name)
    try:
        digest = 文件摘要(path)
        shapes, prefix = _读头部(path)
        config = _头部配置(shapes)
        if 文件摘要(path) != digest:
            raise ValueError("H3放大权重在预检期间发生变化")
    except (OSError, SafetensorError) as exc:
        raise ValueError(f"H3放大权重读取失败：{exc}") from exc
    return {"name": name, "path": path, "digest": digest, "config": config, "prefix": prefix}


@contextmanager
def 加载H3放大模型(信息):
    from comfy import model_management
    from comfy.model_patcher import CoreModelPatcher
    from safetensors import SafetensorError
    from safetensors.torch import load_file

    net = patcher = state = None
    try:
        if 文件摘要(信息["path"]) != 信息["digest"]:
            raise ValueError("H3放大权重在预检后发生变化")
        try:
            state = load_file(信息["path"], device="cpu")
        except (OSError, SafetensorError) as exc:
            raise ValueError(f"H3放大权重加载失败：{exc}") from exc
        if 文件摘要(信息["path"]) != 信息["digest"]:
            raise ValueError("H3放大权重在加载期间发生变化")
        prefix = 信息["prefix"]
        state = {k[len(prefix):]: v for k, v in state.items()}
        _头部配置({k: tuple(v.shape) for k, v in state.items()})
        for key in state:
            value = state[key]
            if value.dtype not in (torch.float32, torch.float16, torch.bfloat16) or not bool(torch.isfinite(value).all()):
                raise ValueError(f"H3放大权重非有限或dtype无效：{key}")
            state[key] = value.float()
        with torch.device("meta"):
            net = LatentResizer3D(**信息["config"])
        net.load_state_dict(state, strict=True, assign=True)
        net.eval().requires_grad_(False)
        state = None
        patcher = CoreModelPatcher(net, load_device=model_management.get_torch_device(),
                                   offload_device=torch.device("cpu"))
        yield patcher
    finally:
        try:
            if patcher is not None:
                try:
                    model_management.unload_model_and_clones(patcher, unload_additional_models=False, all_devices=True)
                finally:
                    patcher.detach()
        finally:
            state = net = patcher = None


def 放大H3视频latent(video, 模型, 目标宽, 目标高):
    if (type(video) is not torch.Tensor or video.device.type != "cpu" or video.layout != torch.strided
            or video.ndim != 5 or tuple(video.shape[:2]) != (1, 24) or min(video.shape) < 1
            or not video.is_floating_point() or not bool(torch.isfinite(video).all())):
        raise ValueError("H3放大需要有限 CPU [1,24,T,H,W] 视频latent")
    width, height = video.shape[-1] * 16, video.shape[-2] * 16
    if (type(目标宽) is not int or type(目标高) is not int or 目标宽 % 32 or 目标高 % 32
            or 目标宽 < width or 目标高 < height or max(目标宽, 目标高) > 16384):
        raise ValueError("H3放大目标须为不小于源尺寸的32倍数且不超过16384")
    if (目标宽, 目标高) == (width, height):
        return video
    from comfy import model_management

    x = out = mean = std = None
    try:
        model_management.throw_exception_if_processing_interrupted()
        shape = (1, 24, video.shape[2], 目标高 // 16, 目标宽 // 16)
        channels = 模型.model.conv_in.out_channels
        memory = channels * video.shape[2] * (目标高 // 16) * (目标宽 // 16) * 4 * 6
        model_management.load_models_gpu([模型], memory_required=memory, force_full_load=True)
        with torch.no_grad():
            mean, std = _norm_tensors(模型.load_device)
            x = (video.to(device=模型.load_device, dtype=torch.float32) - mean) / std
            out = 模型.model(x, max(目标宽 / width, 目标高 / height), shape[-3:])
            if type(out) is not torch.Tensor or tuple(out.shape) != shape:
                raise ValueError("H3放大结果形状不匹配")
            out = (out * std + mean).to(device="cpu", dtype=video.dtype, copy=True)
        if not bool(torch.isfinite(out).all()):
            raise ValueError("H3放大结果包含非有限值")
        return out
    finally:
        x = out = mean = std = None
