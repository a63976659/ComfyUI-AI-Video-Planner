"""Windows 设备命名空间前缀处理；剥前缀只用于路径比对，交给文件系统的仍是原路径。"""
import os


def 去设备前缀(路径):
    r"""GetFinalPathNameByHandle 在建目录后短暂返回 \\?\ 形式；比对前剥掉，否则合法路径被判成链接。"""
    if 路径.startswith("\\\\?\\"):
        return "\\\\" + 路径[8:] if 路径.startswith("\\\\?\\UNC\\") else 路径[4:]
    return 路径


def 真实路径(path):
    return 去设备前缀(os.path.realpath(path))
