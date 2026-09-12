# -*- coding: utf-8 -*-
"""预设路由：GET /h3dyt/preset/options 下发「画风」选项表 +「预设」txt 清单（含正文）。

为什么只是只读接口：状态栏的 画风/预设 两个下拉并不新增 widget，而是把
「画风名 + 换行 + 预设正文」拼接后写回**已有的**「全局提示词」widget（该 widget 已在
节点上隐藏）。真源仍是 node.widgets，执行链（执行核心._应用全局 把 全局提示词 作段
prompt 前缀）零改动，故后端只需提供选项数据，不接收写入。

  画风选项 —— 单一真源在本文件，前端不镜像硬编码。（与 分辨率选项 的「Python 定义 +
              前端镜像」约定不同：分辨率必须进 io.Combo 的 options 才能过 V3 schema，
              画风没有对应 widget，只经此接口下发，镜像反而制造第二份真源。）
  预设清单 —— 扫描 插件根/预设/ 下**最高两层**（根目录直下 + 一层子文件夹）的 .txt。
              显示名：根目录取文件名，子层取「子文件夹/文件名」，均去掉 .txt 后缀；
              路径保留相对 预设根 的 posix 形式，供前端做选中项的稳定标识。

正文随清单一次返回（txt 体量小），省掉二次请求，也让前端能按正文反解析出当前选中的
预设以完成回填。编码按 Windows 中文习惯依次尝试 utf-8-sig / gbk，最后 utf-8 replace
兜底——记事本另存的 ANSI(GBK) txt 若直接按 utf-8 读会整篇乱码进 prompt。
"""
import os

from aiohttp import web

_已注册 = False

# 画风选项：状态栏「画风」下拉的全部可选项，选中后以**标签原文**写入全局提示词首行。
画风选项 = [
    "写实风格", "国风仙侠", "3D机甲", "赛璐璐风格", "Mika Pikazo",
    "像素风格", "油画风格", "版画风格", "壁画风格", "素描风格",
    "黑白电影风格", "科幻风格", "抽象风格", "迷幻风格", "文艺复兴",
    "水彩风格", "赛博朋克风格", "动漫风格", "中国水墨风格", "中式传统风格",
    "黑白动画风格", "浮世绘风格", "点彩派风格", "蒸汽朋克风格", "皮克斯风格",
    "吉卜力风格", "迪士尼风格", "美漫风格", "故障艺术风格", "全息投影效果",
    "数据可视化风格", "UI界面风格", "毛毡风格", "3D卡通风格", "木偶动画风格",
    "3D游戏风格", "黏土风格", "二次元风格", "低多边形风格", "印度风格",
    "阿拉伯风格", "印第安风格", "非洲部落风格", "东南亚风格",
]

_预设文件夹名 = "预设"
_预设后缀 = ".txt"


def 插件根() -> str:
    """插件根目录绝对路径（本文件位于 <根>/后端路由/预设路由.py）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def 预设根() -> str:
    """预设 txt 根目录：插件根/预设/，不存在则创建（与 媒体根() 同款自愈语义）。"""
    root = os.path.join(插件根(), _预设文件夹名)
    os.makedirs(root, exist_ok=True)
    return root


def 读文本(路径: str) -> str:
    """读 txt 正文：utf-8-sig（吃掉记事本 BOM）→ gbk（ANSI 中文）→ utf-8 replace 兜底。"""
    with open(路径, "rb") as f:
        原始 = f.read()
    for 编码 in ("utf-8-sig", "gbk"):
        try:
            return 原始.decode(编码)
        except UnicodeDecodeError:
            continue
    return 原始.decode("utf-8", errors="replace")


def 扫描预设() -> list[dict]:
    """扫描 预设根 下最高两层 .txt → [{"显示名","路径","内容"}]，按显示名排序。

    只读两层：根目录直下的 .txt，以及根目录下一层子文件夹里的 .txt；更深层级忽略。
    单个文件读失败（被占用/无权限）只跳过该文件，不让整份清单变成 500。
    """
    root = 预设根()
    项: list[dict] = []

    def 收(相对: str, 显示名: str):
        try:
            内容 = 读文本(os.path.join(root, *相对.split("/")))
        except OSError:
            return
        项.append({"显示名": 显示名, "路径": 相对, "内容": 内容})

    try:
        一层 = sorted(os.listdir(root))
    except OSError:
        return 项
    for 名 in 一层:
        p = os.path.join(root, 名)
        if os.path.isfile(p) and 名.lower().endswith(_预设后缀):
            收(名, os.path.splitext(名)[0])
        elif os.path.isdir(p):
            try:
                二层 = sorted(os.listdir(p))
            except OSError:
                continue
            for 子 in 二层:
                sp = os.path.join(p, 子)
                if os.path.isfile(sp) and 子.lower().endswith(_预设后缀):
                    收(f"{名}/{子}", f"{名}/{os.path.splitext(子)[0]}")
    项.sort(key=lambda x: x["显示名"])
    return 项


def 注册路由():
    """幂等注册 aiohttp 路由（供 __init__.py 调用）。"""
    global _已注册
    if _已注册:
        return
    from server import PromptServer
    routes = PromptServer.instance.routes

    @routes.get("/h3dyt/preset/options")
    async def 预设选项(request):
        """画风选项 + 预设清单。目录级 IO 失败 → 500 JSON {error}（前端能读到 message），
        与 媒体路由 的 HTTP 边界错误契约一致：不让 aiohttp 把异常吞成 text/plain。"""
        try:
            预设 = 扫描预设()
        except OSError as e:
            return web.json_response({"error": f"预设目录读取失败：{e}"}, status=500)
        return web.json_response({"画风": 画风选项, "预设": 预设})

    _已注册 = True
