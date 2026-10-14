# -*- coding: utf-8 -*-
"""官方管线适配：经 ComfyUI 注册表查找官方节点并按其 FUNCTION 调用，隔离官方 API 变动。"""


def 取节点(类名: str):
    """从 nodes.NODE_CLASS_MAPPINGS 取官方节点类；缺失则给出明确安装提示。"""
    import nodes
    映射 = getattr(nodes, "NODE_CLASS_MAPPINGS", {})
    if 类名 not in 映射:
        raise RuntimeError(
            f"未找到官方节点「{类名}」。请确认已安装 ComfyUI 官方 MiniMax H3 节点包，"
            f"且其已注册到 NODE_CLASS_MAPPINGS。"
        )
    return 映射[类名]


def 调用节点(类名: str, **kwargs):
    """实例化官方节点并调用其 FUNCTION 方法（V1 实例方法 / V3 classmethod execute 皆兼容），
    并把 io.NodeOutput 归一化为普通 tuple——NodeOutput 非 tuple/list/dict 子类但带 .args
    （comfy_api/latest/_io.py:2286 self.args = args；类体 L2281-2312）；归一化动机：
    给调用侧一个稳定的 tuple 契约，不依赖 NodeOutput 本身的选型化。"""
    类 = 取节点(类名)
    实例 = 类()
    方法名 = getattr(类, "FUNCTION", "execute")
    结果 = getattr(实例, 方法名)(**kwargs)
    args = getattr(结果, "args", None)
    if isinstance(args, tuple) and not isinstance(结果, (tuple, list, dict)):
        return args
    return 结果


def 官方节点可用(类名: str) -> bool:
    """启动期预检：官方节点是否已注册到 NODE_CLASS_MAPPINGS。
    与 段缓存.读缓存 的宽 catch 例外不同：try 体 `取节点(类名)` 是我方代码，存在真实
    逻辑（import nodes / getattr / in），不适用“try 体仅含第三方 API 单行”前提。收窄到
    ImportError（nodes 不可导入）+ RuntimeError（取节点 主动抛）两种已知“不可用”形态，
    避免吞掉日后 取节点 内部的 TypeError/AttributeError 类真 bug。"""
    try:
        取节点(类名)
        return True
    except (ImportError, RuntimeError):
        return False
