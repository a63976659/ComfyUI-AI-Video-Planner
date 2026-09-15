# -*- coding: utf-8 -*-
"""计划路由纯函数单测：安全名 / _过滤段refs / 过滤缺失素材 / _读创建时间 / 扫描计划。

只测不依赖 ComfyUI 运行时的纯函数与文件 IO；注册路由() 依赖 server.PromptServer，
静态单测不触发（与 测试_媒体路由.py 同源策略）。

IO 测试一律用 monkeypatch 把 计划根/媒体根 指到 tmp_path，不污染真实插件目录。
"""
import json
import os

import pytest

from 后端路由.计划路由 import (
    _过滤段refs,
    _读创建时间,
    _名最长,
    安全名,
    扫描计划,
    插件根,
    计划根,
    过滤缺失素材,
)


# ---------- 安全名：参数化覆盖全部拒绝分支 + 合法边界 ----------

@pytest.mark.parametrize("输入,期望", [
    # 合法：中文普通名、带空格中间、带扩展名、恰好 100 字符
    ("计划A", "计划A"),
    ("我的 计划", "我的 计划"),
    ("plan.json", "plan.json"),
    ("a" * 100, "a" * 100),
    # 拒绝：非字符串
    (None, ""),
    (123, ""),
    ([], ""),
    # 拒绝：空 / 首尾空白后为空
    ("", ""),
    ("   ", ""),
    ("\t\n", ""),
    # 拒绝：. 与 ..
    (".", ""),
    ("..", ""),
    # 拒绝：非法字符（逐个）
    ("a/b", ""),
    ("a\\b", ""),
    ("a:b", ""),
    ("a*b", ""),
    ("a?b", ""),
    ('a"b', ""),
    ("a<b", ""),
    ("a>b", ""),
    ("a|b", ""),
    ("a\x00b", ""),
    ("a\x1fb", ""),
    # 拒绝：首尾点（Windows 会静默剥离，导致「A.」与「A」写同一文件）
    # 注：首尾空格被 strip() 先剥离，故 " a" / "a " 实际返回 "a"（合法），不在此拒绝分支
    (".a", ""),
    ("a.", ""),
    # 拒绝：Windows 保留名（大小写不敏感、带扩展名也拒）
    ("CON", ""),
    ("con", ""),
    ("CON.json", ""),
    ("PRN", ""),
    ("AUX", ""),
    ("NUL", ""),
    ("COM1", ""),
    ("COM9", ""),
    ("LPT1", ""),
    ("LPT9", ""),
    # 拒绝：超长
    ("a" * 101, ""),
], ids=[
    "合法-中文普通名", "合法-中间空格", "合法-带扩展名", "合法-恰好100",
    "拒-None", "拒-int", "拒-list",
    "拒-空串", "拒-纯空白", "拒-制表换行",
    "拒-点", "拒-点点",
    "拒-斜杠", "拒-反斜杠", "拒-冒号", "拒-星号", "拒-问号",
    "拒-双引号", "拒-小于", "拒-大于", "拒-竖线",
    "拒-控制字符NUL", "拒-控制字符US",
    "拒-首点", "拒-尾点",
    "拒-保留名CON", "拒-保留名con小写", "拒-保留名CON带扩展", "拒-保留名PRN", "拒-保留名AUX", "拒-保留名NUL",
    "拒-保留名COM1", "拒-保留名COM9", "拒-保留名LPT1", "拒-保留名LPT9",
    "拒-超长101",
])
def test_安全名(输入, 期望):
    assert 安全名(输入) == 期望


def test_安全名_首尾空白被剥离后合法():
    """首尾空白 strip 后若变成合法名则通过（与"纯空白拒绝"是两条独立分支）。
    
    注：docstring 说"拒绝首尾为点或空格"，但代码实现是 strip() 后再检查，
    所以空格已被剥离、检查不到；只有"点"能在 strip 后幸存并被拒。
    这是 by-design：用户输入 " 计划A " 意图是"计划A"，strip 是友好行为。
    """
    assert 安全名("  计划A  ") == "计划A"
    assert 安全名(" a") == "a"      # 首空格 strip 后合法
    assert 安全名("a ") == "a"      # 尾空格 strip 后合法
    assert 安全名("\ta\t") == "a"   # 制表符同理


# ---------- _过滤段refs：纯函数，逐分支覆盖 ----------

def test__过滤段refs_非list原样透传():
    assert _过滤段refs("脏数据", {"a.png"}, []) == "脏数据"
    assert _过滤段refs(None, {"a.png"}, []) is None


def test__过滤段refs_非dict段原样透传():
    段组 = ["脏", 123, None]
    缺失 = []
    结果 = _过滤段refs(段组, {"a.png"}, 缺失)
    assert 结果 == 段组
    assert 缺失 == []


def test__过滤段refs_无refs或refs非dict_原样透传():
    段组 = [{"prompt": "x"}, {"refs": "脏"}, {"refs": 123}]
    缺失 = []
    结果 = _过滤段refs(段组, {"a.png"}, 缺失)
    assert 结果 == 段组
    assert 缺失 == []


def test__过滤段refs_缺失被剔除并记录():
    段组 = [{"refs": {"首帧": "a.png", "尾帧": "b.png"}}]
    缺失 = []
    结果 = _过滤段refs(段组, {"a.png"}, 缺失)
    assert 结果 == [{"refs": {"首帧": "a.png"}}]
    assert 缺失 == ["b.png"]


def test__过滤段refs_空字符串值保留():
    """空字符串不是"缺失"（用户可能故意清空首帧），保留在 refs 里。"""
    段组 = [{"refs": {"首帧": "", "尾帧": "b.png"}}]
    缺失 = []
    结果 = _过滤段refs(段组, {"a.png"}, 缺失)
    assert 结果 == [{"refs": {"首帧": ""}}]
    assert 缺失 == ["b.png"]


def test__过滤段refs_非字符串值保留():
    """refs 里非字符串值（如 None、数字）原样保留，不参与缺失判定。"""
    段组 = [{"refs": {"首帧": None, "尾帧": 123}}]
    缺失 = []
    结果 = _过滤段refs(段组, {"a.png"}, 缺失)
    assert 结果 == [{"refs": {"首帧": None, "尾帧": 123}}]
    assert 缺失 == []


# ---------- 过滤缺失素材：monkeypatch 媒体根 ----------

def _注入媒体根(monkeypatch, tmp_path, 文件列表):
    """把 媒体根() 指到 tmp_path/媒体，并在里面造出 文件列表 里的空文件。"""
    媒体目录 = tmp_path / "媒体"
    媒体目录.mkdir()
    for 名 in 文件列表:
        (媒体目录 / 名).write_bytes(b"")
    # 延迟 import 在函数内部，monkeypatch  sys.modules 里的 媒体路由.媒体根
    import 后端路由.媒体路由 as 媒体路由模块
    monkeypatch.setattr(媒体路由模块, "媒体根", lambda: str(媒体目录))
    return str(媒体目录)


def test_过滤缺失素材_参考素材过滤(monkeypatch, tmp_path):
    _注入媒体根(monkeypatch, tmp_path, ["a.png", "b.mp3"])
    数据 = {"参考素材": {"图片": ["a.png", "c.png"], "音频": ["b.mp3"], "视频": ["d.mp4"]}}
    新数据, 缺失 = 过滤缺失素材(数据)
    assert 新数据["参考素材"] == {"图片": ["a.png"], "音频": ["b.mp3"], "视频": []}
    assert 缺失 == ["c.png", "d.mp4"]


def test_过滤缺失素材_时间轴refs过滤(monkeypatch, tmp_path):
    _注入媒体根(monkeypatch, tmp_path, ["a.png"])
    数据 = {"时间轴": {"segments": [
        {"refs": {"首帧": "a.png", "尾帧": "b.png"}},
        {"refs": {"首帧": "c.png"}},
    ]}}
    新数据, 缺失 = 过滤缺失素材(数据)
    assert 新数据["时间轴"]["segments"] == [
        {"refs": {"首帧": "a.png"}},
        {"refs": {}},
    ]
    assert 缺失 == ["b.png", "c.png"]


def test_过滤缺失素材_去重保序(monkeypatch, tmp_path):
    """同名文件被多段引用时只 toast 一次（去重），且保持首次出现顺序。"""
    _注入媒体根(monkeypatch, tmp_path, [])
    数据 = {
        "参考素材": {"图片": ["x.png", "y.png"], "音频": [], "视频": []},
        "时间轴": {"segments": [{"refs": {"首帧": "x.png"}}, {"refs": {"首帧": "y.png"}}]},
    }
    _, 缺失 = 过滤缺失素材(数据)
    assert 缺失 == ["x.png", "y.png"]   # 各出现 2 次，去重后仍 2 项、顺序保持


def test_过滤缺失素材_媒体根不可读_全缺(monkeypatch, tmp_path):
    """媒体根 listdir 抛 OSError → 池为空 → 所有素材判为缺失（极端兜底）。"""
    import 后端路由.媒体路由 as 媒体路由模块
    def 炸():
        raise OSError("input 目录不可用")
    monkeypatch.setattr(媒体路由模块, "媒体根", 炸)
    数据 = {"参考素材": {"图片": ["a.png"], "音频": [], "视频": []}}
    新数据, 缺失 = 过滤缺失素材(数据)
    assert 新数据["参考素材"]["图片"] == []
    assert 缺失 == ["a.png"]


def test_过滤缺失素材_原数据不被修改(monkeypatch, tmp_path):
    """返回的是副本，原 dict 不动（调用方可能还要用原数据做别的事）。"""
    _注入媒体根(monkeypatch, tmp_path, ["a.png"])
    数据 = {"参考素材": {"图片": ["a.png", "b.png"], "音频": [], "视频": []}}
    原图片 = list(数据["参考素材"]["图片"])
    过滤缺失素材(数据)
    assert 数据["参考素材"]["图片"] == 原图片   # 原数据未变


def test_过滤缺失素材_无参考素材字段_透传(monkeypatch, tmp_path):
    _注入媒体根(monkeypatch, tmp_path, ["a.png"])
    数据 = {"任务类型": "t2v"}
    新数据, 缺失 = 过滤缺失素材(数据)
    assert 新数据 == 数据
    assert 缺失 == []


# ---------- _读创建时间：tmp_path 文件 IO ----------

def test__读创建时间_正常(tmp_path):
    p = tmp_path / "计划.json"
    p.write_text(json.dumps({"创建时间": "2026-09-15T10:00:00", "数据": {}}), encoding="utf-8")
    assert _读创建时间(str(p)) == "2026-09-15T10:00:00"


def test__读创建时间_无字段(tmp_path):
    p = tmp_path / "计划.json"
    p.write_text(json.dumps({"数据": {}}), encoding="utf-8")
    assert _读创建时间(str(p)) == ""


def test__读创建时间_坏JSON(tmp_path):
    p = tmp_path / "计划.json"
    p.write_text("{坏", encoding="utf-8")
    assert _读创建时间(str(p)) == ""


def test__读创建时间_文件不存在(tmp_path):
    assert _读创建时间(str(tmp_path / "不存在.json")) == ""


def test__读创建时间_顶层非dict(tmp_path):
    p = tmp_path / "计划.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert _读创建时间(str(p)) == ""


def test__读创建时间_创建时间非字符串(tmp_path):
    p = tmp_path / "计划.json"
    p.write_text(json.dumps({"创建时间": 12345}), encoding="utf-8")
    assert _读创建时间(str(p)) == ""


# ---------- 扫描计划：monkeypatch 计划根 ----------

def _注入计划根(monkeypatch, tmp_path):
    """把 计划根() 指到 tmp_path/计划数据，返回目录路径。"""
    目录 = tmp_path / "计划数据"
    目录.mkdir()
    import 后端路由.计划路由 as 计划路由模块
    monkeypatch.setattr(计划路由模块, "计划根", lambda: str(目录))
    return str(目录)


def test_扫描计划_空目录(monkeypatch, tmp_path):
    _注入计划根(monkeypatch, tmp_path)
    assert 扫描计划() == []


def test_扫描计划_正常(monkeypatch, tmp_path):
    目录 = _注入计划根(monkeypatch, tmp_path)
    (tmp_path / "计划数据" / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "计划数据" / "a.json").write_text("{}", encoding="utf-8")
    结果 = 扫描计划()
    assert [x["名"] for x in 结果] == ["a", "b"]   # 按名排序
    assert all("大小" in x and "更新时间" in x for x in 结果)


def test_扫描计划_跳过part(monkeypatch, tmp_path):
    _注入计划根(monkeypatch, tmp_path)
    (tmp_path / "计划数据" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "计划数据" / "a.json.123.0.part").write_text("{}", encoding="utf-8")
    结果 = 扫描计划()
    assert [x["名"] for x in 结果] == ["a"]


def test_扫描计划_跳过非json(monkeypatch, tmp_path):
    _注入计划根(monkeypatch, tmp_path)
    (tmp_path / "计划数据" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "计划数据" / "b.txt").write_text("x", encoding="utf-8")
    (tmp_path / "计划数据" / "c").write_text("x", encoding="utf-8")
    结果 = 扫描计划()
    assert [x["名"] for x in 结果] == ["a"]


def test_扫描计划_跳过目录(monkeypatch, tmp_path):
    _注入计划根(monkeypatch, tmp_path)
    (tmp_path / "计划数据" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "计划数据" / "子目录.json").mkdir()
    结果 = 扫描计划()
    assert [x["名"] for x in 结果] == ["a"]


def test_扫描计划_目录不存在_返回空(monkeypatch, tmp_path):
    """计划根() 指向不存在的目录 → listdir 抛 OSError → 返回 []（不 500）。"""
    import 后端路由.计划路由 as 计划路由模块
    monkeypatch.setattr(计划路由模块, "计划根", lambda: str(tmp_path / "不存在"))
    assert 扫描计划() == []


# ---------- 插件根 / 计划根：路径计算 ----------

def test_插件根_指向本仓库():
    """插件根 = 本文件的上上级目录（测试/测试_计划路由.py → 插件根）。"""
    根 = 插件根()
    assert os.path.isdir(根)
    assert os.path.isfile(os.path.join(根, "__init__.py"))


def test_计划根_在插件根下():
    根 = 计划根()
    assert 根.endswith("计划数据")
    assert os.path.isdir(根)   # 自愈语义：不存在则创建


def test_名最长_为100():
    """钉死 _名最长=100：前端 计划数据.js 的 名最长 镜像此值，漂移会被契约锁抓到。"""
    assert _名最长 == 100
