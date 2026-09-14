# -*- coding: utf-8 -*-
"""Task 8 条件组装：六任务路由 + 帧需求 + 官方参考入参键名。纯逻辑，无 ComfyUI/GPU 依赖。"""
import pytest

from 执行.条件组装 import 选管线, 选模型槽, 需要首帧, 需要尾帧, 图生视频任务, 参考生视频任务, 组装参考入参


def test_选管线_图生视频族():
    for t in ("t2v", "i2v", "fl2v"):
        assert 选管线(t) == "MiniMaxH3ImageToVideo"


def test_选管线_参考生视频族():
    for t in ("r2v", "v2v", "rv2v"):
        assert 选管线(t) == "MiniMaxH3ReferenceToVideo"


def test_选管线_非法任务抛错():
    with pytest.raises(ValueError, match="未知任务类型"):
        选管线("x2x")


def test_选管线_非字符串抛ValueError():
    """I-2：非字符串真值（123 / 列表 / 对象）必须包成 ValueError，不能逃逸 AttributeError，
    以维持 Task 11 UI 边界 `except (ValueError, RuntimeError)` 的完整覆盖。"""
    for 坏 in (123, ["t2v"], object()):
        with pytest.raises(ValueError, match="任务类型必须是字符串"):
            选管线(坏)


def test_选模型槽():
    """双模型：task → 模型槽，与 选管线 同源分组（图生视频族→fl2va、参考生视频族→ref2va）。
    导演台据此按段任务自动匹配 fl2va模型 / ref2va模型；执行核心以 f"{槽}_model" 取对应模型。"""
    for t in ("t2v", "i2v", "fl2v"):
        assert 选模型槽(t) == "fl2va"
    for t in ("r2v", "v2v", "rv2v"):
        assert 选模型槽(t) == "ref2va"
    # 与 选管线 同源：同族任务必落同槽（防 _管线表/_槽表 两表分组漂移）
    assert {选模型槽(t) for t in 图生视频任务} == {"fl2va"}
    assert {选模型槽(t) for t in 参考生视频任务} == {"ref2va"}
    # 非法/非字符串：走 _规范任务，与 选管线 契约一致（ValueError-only）
    with pytest.raises(ValueError, match="未知任务类型"):
        选模型槽("x2x")
    with pytest.raises(ValueError, match="任务类型必须是字符串"):
        选模型槽(123)


def test_需要首帧_尾帧_非字符串抛ValueError():
    """同 I-2 家族：需要首帧/需要尾帧 也走 _规范任务，与 选管线 契约一致。
    注：None 在新实现下也抛 ValueError（旧 `task or ""` 会吐 falsy→False）。本项与
    选管线 行为对齐：None 作为任务类入参本就非法，Task 9 消费前应保证非 None（先过 选管线）。"""
    with pytest.raises(ValueError, match="任务类型必须是字符串"):
        需要首帧(123)
    with pytest.raises(ValueError, match="任务类型必须是字符串"):
        需要尾帧(None)


def test_帧需求():
    assert 需要首帧("i2v") is True and 需要首帧("t2v") is False
    assert 需要尾帧("fl2v") is True and 需要尾帧("i2v") is False


def test_任务族覆盖六任务():
    assert 图生视频任务 | 参考生视频任务 == {"t2v", "i2v", "fl2v", "r2v", "v2v", "rv2v"}


def test_组装参考入参_官方键名前缀():
    kw = 组装参考入参(图片列表=["a", "b"], 视频列表=["v"], 视频音频列表=["va"], 音频列表=["au"])
    assert kw["ref_images"] == {"ref_image_0": "a", "ref_image_1": "b"}
    assert kw["ref_videos"] == {"ref_video_0": "v"}
    assert kw["ref_video_audios"] == {"ref_video_audio_0": "va"}
    assert kw["ref_audios"] == {"ref_audio_0": "au"}


def test_组装参考入参_空入参不预置空键():
    """Task 9 消费侧契约：空/None 入参对应键不出现，而不是被塞成 {}；官方 execute 里
    `(ref_images or {}).values()` 靠 or 兜底 None，若我们主动预置 {}，日后可能踩坑。"""
    assert 组装参考入参() == {}
    assert 组装参考入参(图片列表=[], 音频列表=None) == {}


def test_组装参考入参_None过滤保留原index():
    """§接口约束 #2 语义回归锁：dict 推导保留原 enumerate 索引，None 位置产生间隙而非紧凑化。
    Task 9 消费侧必须保证列表来自 解析槽位 输出（已 _规范列表 剔 None）；若从其他路径拼装，
    须先紧凑化再传入。此测把「保留原 index」钉死，防止日后有人「顺手紧凑化」破坏 C-4 约定。"""
    kw = 组装参考入参(图片列表=["a", None, "c"])
    assert kw["ref_images"] == {"ref_image_0": "a", "ref_image_2": "c"}
    # 视频与音频的配对：即便音频中间 None，也不移动其他音频的 index
    kw2 = 组装参考入参(视频列表=["v0", "v1"], 视频音频列表=["va0", None, "va2"])
    assert kw2["ref_videos"] == {"ref_video_0": "v0", "ref_video_1": "v1"}
    assert kw2["ref_video_audios"] == {"ref_video_audio_0": "va0", "ref_video_audio_2": "va2"}
