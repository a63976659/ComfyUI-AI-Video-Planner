# -*- coding: utf-8 -*-
"""专项运行配置；不保存模型凭据，不自动扫描整盘。"""
import threading
from pathlib import Path

from .项目存储 import 读JSON, 写JSON

_锁 = threading.RLock()


def 配置路径():
    return Path(__file__).with_name("专项能力配置.json")


def 默认专项配置():
    return {"本地参考目录": [], "检索参考": True, "辅助图": "按需", "辅助图上限": 8,
            "目标模型": "H3", "模型能力": {"名称": "H3", "最短秒": 5, "最长秒": 30,
                "任务": ["t2v", "i2v", "fl2v", "r2v", "v2v", "rv2v"], "最大参考图": 9, "提示词格式": "H3"}}


def 校验专项配置(data, 检查目录=True):
    if not isinstance(data, dict):
        raise ValueError("专项配置须为对象")
    result = 默认专项配置()
    result.update({k: data[k] for k in result if k in data})
    roots = result["本地参考目录"]
    if not isinstance(roots, list) or len(roots) > 10:
        raise ValueError("本地参考目录最多10个")
    cleaned = []
    for value in roots:
        if not isinstance(value, str) or not value.strip() or len(value) > 1000:
            raise ValueError("参考库目录路径无效")
        path = Path(value).expanduser()
        if not path.is_absolute() or path.is_symlink() or (检查目录 and not path.is_dir()):
            raise ValueError("参考库须为已存在的绝对目录，不接受符号链接")
        resolved = path.resolve()
        if len(resolved.parts) < 3 or resolved == Path.home().resolve() or str(resolved).startswith(("\\\\", "//")):
            raise ValueError("不能把磁盘根目录、用户根目录或网络共享设为参考库")
        cleaned.append(str(resolved))
    result["本地参考目录"] = list(dict.fromkeys(cleaned))
    for key in ("检索参考",):
        if not isinstance(result[key], bool):
            raise ValueError(f"{key}须为布尔值")
    if result["辅助图"] not in ("关闭", "按需", "全部"):
        raise ValueError("辅助图模式须为关闭、按需或全部")
    for key, maximum in (("辅助图上限", 24),):
        if isinstance(result[key], bool) or not isinstance(result[key], int) or not 0 <= result[key] <= maximum:
            raise ValueError(f"{key}须为0到{maximum}的整数")
    from .模型适配 import 校验模型能力
    result["模型能力"] = 校验模型能力(result["模型能力"])
    if result["模型能力"]["提示词格式"] == "H3":
        try:
            from ..执行.参考素材 import 上限
        except ImportError:
            from 执行.参考素材 import 上限
        result["目标模型"] = result["模型能力"]["名称"] = "H3"
        result["模型能力"].update(任务=["t2v", "i2v", "fl2v", "r2v", "v2v", "rv2v"], 最大参考图=上限["图片"])
    if result["目标模型"] != result["模型能力"]["名称"]:
        raise ValueError("目标模型须与模型能力名称一致")
    return result


def 读专项配置():
    with _锁:
        data = 读JSON(配置路径()) if 配置路径().is_file() else {}
        return 校验专项配置(data, 检查目录=False)


def 写专项配置(patch):
    with _锁:
        result = 校验专项配置({**读专项配置(), **patch})
        写JSON(配置路径(), result)
        return result
