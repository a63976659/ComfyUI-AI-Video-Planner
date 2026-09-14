# -*- coding: utf-8 -*-
import pytest

from 执行.参考素材 import 解析槽位, 提取标签, 校验标签, 上限


# ---------- 原 4 个测试（保留，扩断言）----------

def test_上限():
    assert 上限["图片"] == 9 and 上限["音频"] == 3 and 上限["视频"] == 3


def test_解析槽位_超限截断():
    refs = {"图片": [f"p{i}.png" for i in range(12)]}
    out = 解析槽位(refs)
    assert len(out["图片"]) == 9
    assert out["图片"][0] == "p0.png"          # 锁顺序=序号契约
    assert out["图片"][-1] == "p8.png"          # 截到 p8，p9-p11 被丢
    assert set(out) == {"图片", "音频", "视频"}  # 锁形状
    assert out["音频"] == []


def test_提取标签():
    tags = 提取标签("参考 <Picture 1> 与 <Audio 2> 和 <Video 1>")
    assert tags == [("图片", 1), ("音频", 2), ("视频", 1)]


def test_提取标签_无():
    assert 提取标签("无标签") == []


# ---------- 新增测试（C1/I2/I3/M5 防回归锁）----------

def test_解析槽位_形状():
    """None 与 {} 输入均返回三键全空的字典。"""
    empty = {"图片": [], "音频": [], "视频": []}
    assert 解析槽位({}) == empty
    assert 解析槽位(None) == empty


def test_解析槽位_单文件名字符串():
    """C1 防回归锁：str 值必须包成 [str]，不能逐字符展开。"""
    out = 解析槽位({"图片": "abc.png"})
    assert out["图片"] == ["abc.png"]
    # 长文件名不再被截成单字符
    out = 解析槽位({"图片": "sub/dir/很长的文件名.png"})
    assert out["图片"] == ["sub/dir/很长的文件名.png"]


def test_解析槽位_dict值抛ValueError():
    """C1：dict 值会把键当文件名，最隐蔽，必须显式抛。"""
    with pytest.raises(ValueError, match="必须是文件名数组或文件名字符串"):
        解析槽位({"图片": {"a.png": {"size": 1}}})


def test_解析槽位_非str元素抛ValueError():
    """C1：非 str 元素会传到下游 os.path.isabs 崩 TypeError，须前置拦。"""
    with pytest.raises(ValueError, match="元素必须是文件名字符串"):
        解析槽位({"图片": [123]})
    with pytest.raises(ValueError, match="元素必须是文件名字符串"):
        解析槽位({"图片": [{"name": "x"}]})


def test_解析槽位_refs非dict抛ValueError():
    """Task 11 UI 契约：只能捕 ValueError。"""
    with pytest.raises(ValueError, match="参考素材必须是已解析的对象"):
        解析槽位('[{"图片": ["a.png"]}]')  # 忘记 json.loads 的字符串
    with pytest.raises(ValueError, match="参考素材必须是已解析的对象"):
        解析槽位(5)


def test_解析槽位_空白串过滤():
    """M1：whitespace-only 元素 strip 后为空，被丢弃。"""
    out = 解析槽位({"图片": ["   ", "a.png", "", "b.png  "]})
    assert out["图片"] == ["a.png", "b.png"]  # 尾随空白也 strip


def test_解析槽位_多槽位保序():
    out = 解析槽位({
        "图片": ["a.png", "b.png"],
        "音频": ["x.mp3"],
        "视频": ["y.mp4"],
    })
    assert out["图片"] == ["a.png", "b.png"]
    assert out["音频"] == ["x.mp3"]
    assert out["视频"] == ["y.mp4"]


def test_解析槽位_未知键被忽略():
    """首帧/尾帧/源视频 由执行核心直接读 seg.refs，不进入 Autogrow。"""
    out = 解析槽位({"图片": ["a.png"], "首帧": "cover.png", "源视频": "input.mp4"})
    assert out == {"图片": ["a.png"], "音频": [], "视频": []}


def test_提取标签_大小写与空白():
    """IGNORECASE + \\s* 目前零覆盖，Task 16 JS 依赖这两点保持一致。"""
    tags = 提取标签("<PICTURE 2> <Audio  3> <Video\t1>")
    assert tags == [("图片", 2), ("音频", 3), ("视频", 1)]


def test_提取标签_编号非法():
    """I2：N<1 或 N>上限必须抛，避免下游 [-1] 负索引静默取错素材。"""
    with pytest.raises(ValueError, match="编号非法"):
        提取标签("<Picture 0>")
    with pytest.raises(ValueError, match="编号非法"):
        提取标签("<Picture 99>")
    with pytest.raises(ValueError, match="编号非法"):
        提取标签("<Picture 999999999999>")
    with pytest.raises(ValueError, match="编号非法"):
        提取标签("<Audio 4>")     # 上限 3


def test_提取标签_非字符串抛ValueError():
    with pytest.raises(ValueError, match="提示词必须是字符串"):
        提取标签(123)


def test_提取标签_None返回空():
    assert 提取标签(None) == []


def test_校验标签_截断悬空():
    """I3：编号落在合法区间（1-上限）但超出实际留存条数 → 显式抛。"""
    槽位 = 解析槽位({"图片": ["a.png", "b.png"]})
    with pytest.raises(ValueError, match="引用第 3 个图片"):
        校验标签("<Picture 3>", 槽位)
    # refs 有 12 图 → 解析槽位 截到 9；<Picture 10> 已被 提取标签 的上下界守卫
    # （I2，编号非法）先拦下，与 校验标签 形成双保险，不会静默放行。
    槽位 = 解析槽位({"图片": [f"p{i}.png" for i in range(12)]})
    with pytest.raises(ValueError, match="编号非法"):
        校验标签("<Picture 10>", 槽位)


def test_校验标签_正常通过():
    槽位 = 解析槽位({"图片": ["a.png", "b.png"]})
    校验标签("<Picture 1> 和 <Picture 2>", 槽位)  # 不应抛


def test_校验标签_None与无标签():
    槽位 = 解析槽位({})
    校验标签(None, 槽位)      # 空 prompt → 无标签 → 不抛
    校验标签("", 槽位)
    校验标签("无标签文本", 槽位)
