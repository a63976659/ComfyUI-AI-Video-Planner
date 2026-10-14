"""节点上下拉选官方像素放大模型：清单与加载都复用宿主加载器那一套，不再要求用户额外摆一个连线节点。"""

_可选扩展名 = (".pth", ".ckpt", ".safetensors")


def 列像素放大模型():
    """models/upscale_models/ 里宿主能读的三个扩展名，按名排序，「未选择」居首（与 H3放大权重 同款款式）。

    这里只按扩展名筛，不像 H3 那样逐个探架构：像素模型的架构判定要把整份权重读进内存建网，
    每次构建节点定义都跑一遍会拖慢启动；真正选中时由 加载像素放大模型 硬失败并点名文件。

    列目录失败（目录被挪走、无权限）一律退回只剩「未选择」而不抛：清单是 UI 便利，
    不该让整枚节点因列不出文件而注册失败（同 列兼容H3放大模型 的口径）。"""
    import folder_paths

    try:
        names = folder_paths.get_filename_list("upscale_models") or []
    except (OSError, ValueError, RuntimeError):
        return ["未选择"]
    return ["未选择"] + sorted(n for n in names if n.lower().endswith(_可选扩展名))


def 加载像素放大模型(name):
    from comfy_extras.nodes_upscale_model import UpscaleModelLoader

    if type(name) is not str or not name or name == "未选择":
        raise ValueError("放大方式选「像素模型」时，请在「像素放大模型」下拉里选一个权重文件")
    try:
        return UpscaleModelLoader.load_model(name).args[0]
    except Exception as exc:  # noqa: BLE001 - 宿主文案不含文件名，用户无法定位是哪一个权重
        raise ValueError(f"像素放大模型 {name} 加载失败（需为 spandrel 认得的单图放大模型）：{exc}") from exc
