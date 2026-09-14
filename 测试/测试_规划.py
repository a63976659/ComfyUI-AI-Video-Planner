# -*- coding: utf-8 -*-
import dataclasses
import json

import pytest

from 执行.规划 import 解析时间轴, SegmentPlan


def _json(segs):
    return json.dumps({"segments": segs}, ensure_ascii=False)


def test_解析_单段():
    raw = _json([{"task": "t2v", "prompt": "一只猫", "start": 0, "end": 5, "run": True}])
    plan = 解析时间轴(raw)
    assert len(plan.segments) == 1
    assert plan.segments[0].task == "t2v"
    assert plan.segments[0].run is True


def test_解析_缺省字段回退():
    plan = 解析时间轴(_json([{"prompt": "x"}]))
    seg = plan.segments[0]
    assert seg.task == "t2v"          # 默认任务
    assert seg.run is True            # 默认参与
    assert seg.end > seg.start        # 默认时长>0


def test_解析_非法JSON抛错():
    with pytest.raises(ValueError, match="非法 JSON"):
        解析时间轴("{bad")


def test_SegmentPlan_不可变():
    seg = SegmentPlan(index=0, task="t2v", prompt="p", refs={}, start=0.0, end=5.0, run=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        seg.task = "i2v"


def test_解析_空输入返回空Plan():
    for raw in ("", "   ", None):
        plan = 解析时间轴(raw)
        assert plan.segments == ()


def test_解析_时长非法自动补齐():
    # end == start → 用默认段秒补齐
    seg = 解析时间轴(_json([{"start": 2.0, "end": 2.0}])).segments[0]
    assert seg.start == 2.0
    assert seg.end == 7.0             # 2.0 + 默认段秒 5.0
    # end < start 同样补齐
    seg = 解析时间轴(_json([{"start": 5.0, "end": 3.0}])).segments[0]
    assert seg.end == 10.0            # 5.0 + 5.0


def test_解析_多段_index_连续():
    plan = 解析时间轴(_json([{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}]))
    assert [s.index for s in plan.segments] == [0, 1, 2]


def test_解析_run_字段语义():
    def _run(v):
        return 解析时间轴(_json([{"run": v}])).segments[0].run

    assert _run(True) is True
    assert _run(False) is False
    assert _run(None) is True          # 未设置（前端常序列化成 null）= 参与
    assert _run("no") is False
    assert _run("true") is True
    assert _run(0) is False
    assert _run(1) is True
    assert _run("TRUE") is True        # 大小写不敏感
    assert _run("") is False           # 空串 = 不参与
    assert _run("OFF") is False        # 大小写不敏感


def test_解析_refs_字段拷贝():
    raw = _json([{"refs": {"图片": ["a.png"]}}])
    seg = 解析时间轴(raw).segments[0]
    assert seg.refs == {"图片": ["a.png"]}
    # dict(...) 为浅拷贝：顶层键是新建的 dict，不与他人共享
    seg.refs["视频"] = ["c.mp4"]
    seg2 = 解析时间轴(raw).segments[0]
    assert seg2.refs == {"图片": ["a.png"]}
    # 浅不可变：refs 内容仍可改（嵌套 list 亦可在原地修改）
    seg.refs["图片"].append("b.png")
    assert seg.refs["图片"] == ["a.png", "b.png"]


def test_解析_非字符串抛错():
    for bad in (5, [1, 2], {}):
        with pytest.raises(ValueError, match="必须是字符串"):
            解析时间轴(bad)


def test_运行段_只返回run段():
    plan = 解析时间轴(_json([{"run": True}, {"run": False}, {"run": True}]))
    assert len(plan.运行段) == 2
    assert [s.index for s in plan.运行段] == [0, 2]


def test_顶层segments_非数组抛错():
    with pytest.raises(ValueError, match="segments 必须是数组"):
        解析时间轴('{"segments": 5}')
    with pytest.raises(ValueError, match="segments 必须是数组"):
        解析时间轴('{"segments": {"a":1}}')
    # 假值但非 list（0 / "" / false）不得 fail-open 成空 Plan
    for bad in ('{"segments": 0}', '{"segments": ""}', '{"segments": false}'):
        with pytest.raises(ValueError, match="segments 必须是数组"):
            解析时间轴(bad)


def test_顶层非对象抛错():
    with pytest.raises(ValueError, match="顶层必须是对象"):
        解析时间轴("[]")
    with pytest.raises(ValueError, match="顶层必须是对象"):
        解析时间轴('"just string"')
    with pytest.raises(ValueError, match="顶层必须是对象"):
        解析时间轴("5")                # JSON 标量数字
    with pytest.raises(ValueError, match="顶层必须是对象"):
        解析时间轴("null")              # JSON null 不等于空时间轴


def test_段非对象抛错():
    with pytest.raises(ValueError, match="第 0 段必须是对象"):
        解析时间轴('{"segments": [null]}')
    with pytest.raises(ValueError, match="第 0 段必须是对象"):
        解析时间轴('{"segments": [5]}')
    with pytest.raises(ValueError, match="第 0 段必须是对象"):
        解析时间轴('{"segments": ["x"]}')


def test_段字段类型错误抛ValueError():
    # N1：叶子字段类型错误必须转换为 ValueError，不能漏出 TypeError
    with pytest.raises(ValueError, match="start/end 必须是数字"):
        解析时间轴('{"segments": [{"start": [1]}]}')
    with pytest.raises(ValueError, match="start/end 必须是数字"):
        解析时间轴('{"segments": [{"end": {"a": 1}}]}')
    with pytest.raises(ValueError, match="refs 必须是对象"):
        解析时间轴('{"segments": [{"refs": [1, 2]}]}')
    with pytest.raises(ValueError, match="refs 必须是对象"):
        解析时间轴('{"segments": [{"refs": 5}]}')
    # 正面：非数字字符串也走同一条 ValueError 分支
    with pytest.raises(ValueError, match="start/end 必须是数字"):
        解析时间轴('{"segments": [{"start": "abc"}]}')
