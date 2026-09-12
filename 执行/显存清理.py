# -*- coding: utf-8 -*-
"""段间显存清理，降低多段连跑 OOM 风险。"""
import gc
import logging

_日志 = logging.getLogger("H3导演台.显存清理")


def 清理显存(激进: bool = False):
    gc.collect()
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
