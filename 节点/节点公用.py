# -*- coding: utf-8 -*-
"""节点公用：任务类型中文标签映射 + 校验助手（供主节点与状态栏共用）。

单一真源约束（Task 4 §接口约束）：CANVAS_MULTIPLE 必须来自 执行.采样与解码，
禁散落魔法 32/8192。ComfyUI 运行时 本模块路径为
`custom_nodes.ComfyUI-AI-Edit-Video.节点.节点公用`，走相对导入；pytest 走
`节点.节点公用`（插件根已在 sys.path），相对 `..` 越界 → 回退绝对导入。
"""
from __future__ import annotations

import math

try:                                                    # ComfyUI 运行时
    from ..执行.采样与解码 import CANVAS_MULTIPLE
except ImportError:                                     # pytest（插件根在 sys.path）
    from 执行.采样与解码 import CANVAS_MULTIPLE

# 采样器/调度器选项：与 KSampler 同源（comfy.samplers.KSampler.SAMPLERS/SCHEDULERS）。
# pytest 无 ComfyUI 环境时回退到执行核心默认组合，保证 schema 冒烟可跑；默认值
# res_multistep/simple 与 执行核心._采样段 的历史硬编码一致（行为不变）。
try:                                                    # ComfyUI 运行时
    from comfy.samplers import KSampler as _KSampler
    采样器选项 = list(_KSampler.SAMPLERS)
    调度器选项 = list(_KSampler.SCHEDULERS)
except Exception:                                       # pytest：无 comfy.samplers(ImportError)
    # 或 CPU-only torch 下 import 链触 comfy.model_management 抛 CUDA AssertionError（非
    # ImportError），故捕 Exception 而非仅 ImportError，保证 schema 冒烟可跑。
    采样器选项 = ["res_multistep", "euler", "dpmpp_2m", "ddim"]
    调度器选项 = ["simple", "normal", "karras", "exponential"]
if "res_multistep" not in 采样器选项:
    采样器选项 = ["res_multistep"] + 采样器选项
if "simple" not in 调度器选项:
    调度器选项 = ["simple"] + 调度器选项

# 输出分辨率（宽高比）选项：与参考节点前端一致（ResolutionSelector 的 8 档 + 中文后缀）。
# 标签前缀 "a:b" 即宽高比，解析见 解析分辨率比例；状态栏前端 提示词编辑器.js 的
# 分辨率选项 必须与本表逐字一致（单一真源在 Python，前端为镜像）。
分辨率选项 = [
    "1:1 (方形)", "2:3 (竖照片)", "3:2 (照片)", "3:4 (竖标准)",
    "4:3 (标准)", "9:16 (竖宽屏)", "16:9 (宽屏)", "21:9 (超宽屏)",
]
默认分辨率 = "16:9 (宽屏)"
默认百万像素 = 0.4

任务标签 = {
    "t2v": "文生视频 t2v",
    "i2v": "图生视频 i2v",
    "fl2v": "首尾帧 fl2v",
    "r2v": "参考生视频 r2v",
    "v2v": "视频改视频 v2v",
    "rv2v": "参考+视频 rv2v",
}
任务选项 = list(任务标签.values())
标签到任务 = {v: k for k, v in 任务标签.items()}

# 画布最大边：仅拦截“明显过大”（远大于任何 H3 输出规格）的非法值。注：长视频规划师 已无
# 宽/高 widget（改由 分辨率到宽高 推导），故本阈值不再与 widget max 同源；面积上限
# 实际由「百万像素」widget 的 max 兜（官方 adapt_canvas 的面积≤768×1344 收缩只作用于
# 参考视频，不作用于主画布，详见 校验画布 docstring）。
_画布最大边 = 8192


def 解析任务(标签):
    """中文标签 → 内部任务码；未知回退 t2v。"""
    return 标签到任务.get((标签 or "").strip(), "t2v")


def 解析分辨率比例(标签):
    """分辨率标签前缀 "a:b" → (a, b) 浮点比；解析失败/非正回退 16:9。"""
    头 = (标签 or 默认分辨率).split(" ", 1)[0]
    try:
        a, b = (float(x) for x in 头.split(":"))
        if a <= 0 or b <= 0:
            raise ValueError
        return a, b
    except ValueError:
        return 16.0, 9.0


def 分辨率到宽高(标签, 百万像素, 倍数=None):
    """宽高比 + 百万像素预算 → (宽, 高)。逐行等同 comfy_extras/nodes_resolution.py
    ResolutionSelector.execute；multiple 取 CANVAS_MULTIPLE 以对齐 H3 画布 32 倍数。
    本函数的产出**就是最终主画布**（执行核心._采样段 原样透传给官方条件节点的
    width/height）——与官方一致：adapt_canvas 只规范参考视频，主画布不过它。
    故「百万像素」真实生效：9:16+0.4MP → 480x864、16:9+1.0MP → 1376x768。"""
    倍数 = 倍数 or CANVAS_MULTIPLE
    a, b = 解析分辨率比例(标签)
    总像素 = float(百万像素 or 默认百万像素) * 1024 * 1024
    缩放 = math.sqrt(总像素 / (a * b))
    宽 = round(a * 缩放 / 倍数) * 倍数
    高 = round(b * 缩放 / 倍数) * 倍数
    return max(倍数, 宽), max(倍数, 高)


def 校验画布(宽, 高):
    """只拦截明显非法值（<CANVAS_MULTIPLE 或 >_画布最大边）。阈值取自 采样与解码
    （Task 4 §接口约束：禁散落魔法 32/8192）。
    ⚠️ 主画布**不会**被官方 adapt_canvas 自动规范（它只作用于参考视频），故本校验是主画布
    唯一的合法性关卡；但目前尚未接入生产路径（长视频规划师.execute 未调），实际兜底是
    分辨率到宽高 的 multiple=32 + max(倍数, …) 下限，产出必为 ≥32 的 32 倍数。
    如后续开放自定义宽高输入，必须先把本函数接进 execute。"""
    宽 = int(宽)
    高 = int(高)
    if 宽 < CANVAS_MULTIPLE or 高 < CANVAS_MULTIPLE:
        return f"宽/高过小（官方最小 {CANVAS_MULTIPLE}，且对齐到 {CANVAS_MULTIPLE} 倍数）"
    if 宽 > _画布最大边 or 高 > _画布最大边:
        return f"宽/高过大（超过 {_画布最大边}）"
    return None
