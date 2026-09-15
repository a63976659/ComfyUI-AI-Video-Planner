# -*- coding: utf-8 -*-
"""段间显存清理，降低多段连跑 OOM 风险。"""
import gc
import logging

_日志 = logging.getLogger("长视频规划师.显存清理")


def 清理显存(激进: bool = False, 归还缓存: bool = True):
    """段间/轮末显存清理，降低多段连跑 OOM 风险。

    归还缓存=False → 只做 gc.collect()，不把 torch 分配器的保留块还给驱动。用于「下一段
    马上要重新分配同量级张量」的段间时机，理由三条：
      1. empty_cache() 只能归还「已保留但当前未用」的块，**动不了任何存活张量**——跨段
         真正累积的是 段产物 images/audio，那要靠 gc 掉引用才可能释放，与 empty_cache 无关；
      2. 模型的显存腾挪本就由宿主 comfy.model_management.free_memory() 在每次
         load_models_gpu 时负责（它按 sys.getrefcount 排序卸载），不需要我方代劳；
      3. 归还后下一段的分配只能重新 cudaMalloc，Windows/WDDM 下还伴随隐式同步 → 纯负优化。
    真正该归还的时机是整轮结束（把池子交还下游节点/其他工作流），由调用方以缺省
    归还缓存=True 触发。激进 仅表示额外做 ipc_collect（语义不变）。
    """
    gc.collect()
    if not 归还缓存:
        return
    try:
        import torch
        if torch.cuda.is_available():
            # 顺序对齐宿主 comfy/model_management.soft_empty_cache：synchronize → empty_cache → ipc_collect。
            # synchronize 仅在已初始化时做：empty_cache 内部本有 is_initialized 保护，而无条件 synchronize
            # 会给从未用过 GPU 的进程新建 context、反吃数百 MB。激进 仅表示额外做 ipc_collect。
            if torch.cuda.is_initialized():
                torch.cuda.synchronize()
            torch.cuda.empty_cache()
            if 激进:
                torch.cuda.ipc_collect()
    except Exception as e:  # noqa: BLE001 - best-effort 清理：见下方注释
        # try 体仅含 torch API 调用、无我方逻辑，故放宽捕获安全：漏捕获会以
        # ImportError（缺 DLL）/RuntimeError/AssertionError（broken build）中断多段主流程，
        # 正是此处要避免；误吞代价仅一次清理未生效且仍告警可诊断。与 段缓存.读缓存 同构。
        _日志.warning("显存清理跳过: %s: %s", type(e).__name__, e)
