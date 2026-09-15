# -*- coding: utf-8 -*-
"""段缓存测试：指纹纯函数 4 个 + 路径/入参校验 3 个 + 命中/读写/未命中 3 个 +
旧版坏文件自愈 1 个 + 损坏自愈参数化 5 例 + 逃逸类回归锁 2 例 + IO 分层 1 例 +
版本分目录与自动淘汰 3 个（共 17 个测试函数 / 22 个用例，全部 CPU 可跑）。

IO 测试一律用 monkeypatch 把 长视频规划师_段缓存_DIR 指到 tmp_path，不污染真实 %TEMP%。
⚠️ h3-6 起该环境变量覆盖的是**基**目录，文件实际落在 <基>/<缓存格式版本>/ 下：
断言落盘位置用 _注入根（返回版本目录），要操作基层（如造旧版本目录）用 _注入基。
"""
import os
import pickle
import zipfile

import pytest
import torch

from 执行.段缓存 import (_已淘汰基, _缓存根, 写缓存, 命中, 段指纹, 缓存格式版本, 缓存路径,
                     读缓存)


def _注入基(monkeypatch, tmp_path):
    """把 长视频规划师_段缓存_DIR 指到 tmp_path 下，返回**基**目录绝对路径（不含版本层）。

    只设环境变量、不触发 _缓存根()，以便调用方先在基下布置旧版本目录/散文件再验淘汰。
    """
    基 = str(tmp_path / "段缓存")
    monkeypatch.setenv("长视频规划师_段缓存_DIR", 基)
    return os.path.abspath(基)


def _注入根(monkeypatch, tmp_path):
    """把缓存指到 tmp_path 下，返回文件真正落盘的目录（<基>/<缓存格式版本>）。"""
    _注入基(monkeypatch, tmp_path)
    return _缓存根()


def _段产物():
    """按 Task 9 真实落盘结构构造：dict + Tensor，weights_only=True 可解码。"""
    return {
        "images": torch.zeros(2, 3, 4, 3),
        "audio": {"waveform": torch.zeros(1, 2, 4), "sampling_rate": 24000},
        "锚帧数": 22,
        "帧数": 39,
    }


# ---------- 指纹纯函数（既有 3 测，相对断言语义不变）----------

def test_段指纹_稳定():
    seg = {"task": "t2v", "prompt": "猫", "refs": {}, "start": 0, "end": 5}
    g = {"宽": 1344, "高": 768, "帧率": 24}
    assert 段指纹(seg, g) == 段指纹(seg, g)


def test_段指纹_改动即变():
    seg = {"task": "t2v", "prompt": "猫", "refs": {}, "start": 0, "end": 5}
    g = {"宽": 1344, "高": 768, "帧率": 24}
    h1 = 段指纹(seg, g)
    seg2 = dict(seg)
    seg2["prompt"] = "狗"
    assert 段指纹(seg2, g) != h1


def test_段指纹_键序无关():
    a = {"task": "t2v", "prompt": "猫"}
    b = {"prompt": "猫", "task": "t2v"}
    assert 段指纹(a, {}) == 段指纹(b, {})


# ---------- 指纹契约（钉 I5：数值类型敏感是 by-design）----------

def test_段指纹_数值类型敏感():
    # json 区分 1 与 1.0 → 不同指纹。调用方（Task 9）入指纹前必须统一数值类型。
    assert 段指纹({"a": 1}, {}) != 段指纹({"a": 1.0}, {})


# ---------- _缓存根 / 缓存路径 ----------

def test__缓存根_幂等且按版本分目录(monkeypatch, tmp_path):
    """h3-6：缓存根 = <基>/<缓存格式版本>，且幂等。分目录是自动淘汰的前提——
    目录名就是指纹的盐，程序据此认出「哪些文件属于代码里已不存在的旧指纹世代」。"""
    基 = _注入基(monkeypatch, tmp_path)
    第一次, 第二次 = _缓存根(), _缓存根()
    assert 第一次 == 第二次 == os.path.join(基, 缓存格式版本)
    assert os.path.isdir(第一次)


def test_缓存路径_格式(monkeypatch, tmp_path):
    根 = _注入根(monkeypatch, tmp_path)
    指纹 = 段指纹({"task": "t2v"}, {})
    p = 缓存路径("a/../b", 3, 指纹)
    assert os.path.dirname(p) == 根                     # 落在根内
    assert os.path.basename(p) == f"a..b_3_{指纹}.pt"    # node_id 白名单去分隔符
    assert p.endswith(".pt")


def test_缓存路径_拒绝非法(monkeypatch, tmp_path):
    _注入根(monkeypatch, tmp_path)
    合法 = 段指纹({"task": "t2v"}, {})
    with pytest.raises(ValueError, match="非法指纹格式"):
        缓存路径("node", 0, "ZZZ")                    # 非 hex / 长度不足
    with pytest.raises(ValueError, match="非法指纹格式"):
        缓存路径("node", 0, "../escape")              # 路径穿越（曾能写出根外）
    with pytest.raises(ValueError, match="非法指纹格式"):
        缓存路径("node", 0, 合法.upper())              # 只收小写 hex
    with pytest.raises(ValueError, match="非法指纹格式"):
        缓存路径("node", 0, 合法 + "0")                # 17 位
    with pytest.raises(ValueError, match="seg_index"):
        缓存路径("node", -1, 合法)


# ---------- 命中 / 写 / 读（磁盘 IO，CPU 可测）----------

def test_命中_写前假写后真(monkeypatch, tmp_path):
    _注入根(monkeypatch, tmp_path)
    指纹 = 段指纹({"task": "t2v", "prompt": "猫"}, {})
    assert 命中("nodeA", 0, 指纹) is False
    写缓存("nodeA", 0, 指纹, {"a": 1})
    assert 命中("nodeA", 0, 指纹) is True


def test_写读roundtrip(monkeypatch, tmp_path):
    根 = _注入根(monkeypatch, tmp_path)
    指纹 = 段指纹({"task": "t2v", "prompt": "猫"}, {})
    写缓存("nodeB", 1, 指纹, {"a": 1})
    assert 读缓存("nodeB", 1, 指纹) == {"a": 1}
    assert os.listdir(根) == [os.path.basename(缓存路径("nodeB", 1, 指纹))]  # 无 .part 残留

    段 = _段产物()
    指纹2 = 段指纹({"task": "i2v", "prompt": "狗"}, {})
    写缓存("nodeB", 2, 指纹2, 段)
    回 = 读缓存("nodeB", 2, 指纹2)
    assert set(回) == set(段)
    assert 回["images"].shape == torch.Size([2, 3, 4, 3])
    assert torch.equal(回["images"], 段["images"])
    assert torch.equal(回["audio"]["waveform"], 段["audio"]["waveform"])
    assert 回["audio"]["sampling_rate"] == 24000
    assert (回["锚帧数"], 回["帧数"]) == (22, 39)
    assert all(f.endswith(".pt") for f in os.listdir(根))  # 原子改名后无 .part 残留


def test_读缓存_未命中返回None(monkeypatch, tmp_path):
    _注入根(monkeypatch, tmp_path)
    指纹 = 段指纹({"task": "t2v"}, {})
    assert 读缓存("nodeC", 0, 指纹) is None
    assert 命中("nodeC", 0, 指纹) is False


def test_读缓存_坏文件自愈(monkeypatch, tmp_path):
    """钉 C1：半截/垃圾 .pt 不得让 读缓存 永久抛 RuntimeError，应丢弃并按未命中处理。"""
    _注入根(monkeypatch, tmp_path)

    for 名称, 造坏 in {
        "垃圾字节": lambda f: f.write(b"\x00\x01not a real pt file"),
        "空文件": lambda f: None,
        "半截文件": lambda f: f.write(torch.__version__.encode() * 64),
    }.items():
        指纹 = 段指纹({"task": "t2v", "prompt": 名称}, {})
        p = 缓存路径("nodeD", 0, 指纹)
        with open(p, "wb") as fh:
            造坏(fh)
        assert 命中("nodeD", 0, 指纹) is True          # 磁盘上有文件
        assert 读缓存("nodeD", 0, 指纹) is None         # 不抛异常，语义=未命中
        assert 命中("nodeD", 0, 指纹) is False          # 坏文件已被删除

    # 真实半截：先正常写，再截断一半字节 → 自愈后重跑能修复
    指纹 = 段指纹({"task": "t2v", "prompt": "猫"}, {})
    写缓存("nodeD", 1, 指纹, _段产物())
    p = 缓存路径("nodeD", 1, 指纹)
    with open(p, "rb+") as fh:
        数据 = fh.read()
        fh.seek(0)
        fh.write(数据[: len(数据) // 2])
        fh.truncate(len(数据) // 2)
    assert 读缓存("nodeD", 1, 指纹) is None
    assert not os.path.exists(p)
    写缓存("nodeD", 1, 指纹, _段产物())                 # 本次重跑自然修复
    assert 读缓存("nodeD", 1, 指纹)["帧数"] == 39


# ---------- 钉 N1：损坏形态跨 torch 版本极多，白名单元组不完备 ----------

# 上一轮（C1）自愈只捕获这四类；re-review 实测约 14% 损坏形态会逃逸。
_旧白名单 = (RuntimeError, EOFError, zipfile.BadZipFile, pickle.UnpicklingError)


def _裸调load(p):
    """直接调 torch.load 观察异常（不走被测代码），返回异常对象或 None。"""
    try:
        torch.load(p, map_location="cpu", weights_only=True)
    except Exception as e:  # noqa: BLE001 - 测试内探针，目的是拿到异常类型
        return e
    return None


def _xor(原始: bytes, 起: int, n: int = 16) -> bytes:
    坏 = bytearray(原始)
    for i in range(起, min(起 + n, len(坏))):
        坏[i] ^= 0xFF
    return bytes(坏)


def _变体(原始: bytes, 策略: str):
    """产出 (坏字节, 候选标签) 序列。派生自真实 .pt 的策略给**密集**候选。"""
    if 策略 == "头截断":
        for n in range(4, 257, 4):                      # 砍掉 zip 本地头 magic，保留尾部
            yield 原始[n:], f"砍前{n}字节"
    elif 策略 == "位翻转":
        for 起 in range(0, min(512, len(原始)), 16):        # 连续窗口，覆盖前 512 字节结构区
            yield _xor(原始, 起), f"翻转@{起}"
    else:
        yield {
            "非torch纯文本": b"not a torch file at all",
            "截尾半截": 原始[: len(原始) // 2],
            "空文件": b"",
        }[策略], 策略


def _试探(p, 原始: bytes, 策略: str):
    """逐候选把坏字节写入 p 并裸调 torch.load，产出 (坏字节, 标签, 异常或 None)。

    为何要逐个候选试探、而不写死一个偏移：
      1. torch.save 拿目标文件名当 zip 成员名，而 写缓存 先落 .<pid>.<序号>.part 再改名，
         所以成员名（以及各结构区偏移）随 pid / 序号位数漂；写死偏移会在某些 pid 下失灵。
      2. 张量数据区不做校验，翻转落在那里会被**静默加载**（值变错、不报错）。
      3. 不同结构区抛的类型不同（成员名区→IndexError/KeyError、pickle 字符串区→
         UnicodeDecodeError、本地头→RuntimeError…），且跨 torch 版本会变。
    实测（torch 2.10、多种名长）：砍前 4..256 与 翻转 0..496 两组密集候选在任意布局下
    都能命中多个 IndexError / KeyError / UnicodeDecodeError（即旧白名单之外的逃逸类）。
    """
    for 坏, 标签 in _变体(原始, 策略):
        with open(p, "wb") as fh:
            fh.write(坏)
        yield 坏, 标签, _裸调load(p)


def _解码类损坏(p, 原始: bytes, 策略: str):
    """返回第一个能触发非 OSError 解码异常的 (坏字节, 标签, 异常)；找不到则硬失败。"""
    见过 = []
    for 坏, 标签, 异常 in _试探(p, 原始, 策略):
        if 异常 is None or isinstance(异常, OSError):
            见过.append(f"{标签}:{type(异常).__name__ if 异常 else 'NO-RAISE'}")
            continue
        return 坏, 标签, 异常
    raise AssertionError(
        f"{策略} 语料未产生解码类异常（非 OSError）；实测 {见过[:8]}…"
        "—— torch 落盘结构可能已变，请更新语料"
    )


def _逃逸类损坏(p, 原始: bytes, 策略: str, 需要: int = 3):
    """收集最多 需要 个抛**旧白名单之外**异常（如 IndexError/KeyError/UnicodeDecodeError）
    的损坏候选；一个都没则返回空列表（由调用方断言）。"""
    结果 = []
    for 坏, 标签, 异常 in _试探(p, 原始, 策略):
        if 异常 is None or isinstance(异常, (OSError,) + _旧白名单):
            continue
        结果.append((坏, 标签, 异常))
        if len(结果) >= 需要:
            break
    return 结果


@pytest.mark.parametrize(
    "策略",
    [
        "头截断",          # 候选区内含 IndexError（旧白名单漏）
        "位翻转",          # 候选区内含 UnicodeDecodeError（旧白名单漏）
        "非torch纯文本",    # UnpicklingError（旧白名单已覆盖，仍须自愈）
        "截尾半截",        # RuntimeError(PytorchStreamReader)
        "空文件",          # EOFError
    ],
)
def test_读缓存_各类损坏均自愈(monkeypatch, tmp_path, 策略):
    """钉 N1：任一类非 IO 损坏都必须「返回 None + 删坏档」，不得原样透传异常。

    若回退到旧白名单元组，头截断/位翻转两类会直接抛到调用方且文件不删 → 命中 恒真
    → 每次读都报错，用户只能手删 %TEMP%（即 C1 初衷复发）。
    """
    _注入根(monkeypatch, tmp_path)
    指纹 = 段指纹({"task": "t2v", "prompt": 策略}, {})
    写缓存("nodeE", 0, 指纹, _段产物())
    p = 缓存路径("nodeE", 0, 指纹)
    with open(p, "rb") as fh:
        原始 = fh.read()

    _, 标签, 异常 = _解码类损坏(p, 原始, 策略)
    assert not isinstance(异常, OSError), f"{标签} 抛的是 OSError，不属解码类：{异常!r}"

    assert 命中("nodeE", 0, 指纹) is True          # 磁盘上有坏文件
    assert 读缓存("nodeE", 0, 指纹) is None         # 不抛任何异常，语义＝未命中
    assert os.path.exists(p) is False               # 坏文件已被删除


@pytest.mark.parametrize("策略", ["头截断", "位翻转"])
def test_读缓存_白名单外逃逸类损坏也已自愈(monkeypatch, tmp_path, 策略):
    """N1 专用回归锁：语料中必须存在旧白名单接不住的异常类型，且它们已全部自愈。

    把 读缓存 改回上一轮的 (RuntimeError, EOFError, BadZipFile, UnpicklingError) 元组，
    本例必定抛异常（实测 IndexError / UnicodeDecodeError）而失败。
    """
    _注入根(monkeypatch, tmp_path)
    指纹 = 段指纹({"task": "t2v", "prompt": "逃逸-" + 策略}, {})
    写缓存("nodeE", 0, 指纹, _段产物())
    p = 缓存路径("nodeE", 0, 指纹)
    with open(p, "rb") as fh:
        原始 = fh.read()

    候选 = _逃逸类损坏(p, 原始, 策略)
    assert 候选, (
        f"{策略} 未能在结构区找到旧白名单之外的逃逸类损坏：torch 落盘结构已变，"
        "请更新语料（否则本测不再钉住 N1）"
    )
    for 坏, 标签, 异常 in 候选:
        assert not isinstance(异常, _旧白名单), f"{标签} 实际在旧白名单内：{type(异常).__name__}"
        with open(p, "wb") as fh:
            fh.write(坏)                            # 重新落盘该逃逸候选
        assert 命中("nodeE", 0, 指纹) is True
        assert 读缓存("nodeE", 0, 指纹) is None, f"{标签} 未自愈"
        assert os.path.exists(p) is False, f"{标签} 坏档未被删除"


def test_读缓存_IO失败抛ValueError(monkeypatch, tmp_path):
    """钉分层：OSError = 真 IO 失败 → 不自愈、不删档，转 ValueError 上抛（I2 语义）。

    磁盘故障时若按损坏处理会把整批完好缓存删光，故这一支必须与自愈分支分开。
    跨平台造“文件存在但不可读”不稳，故 monkeypatch 外部边界 torch.load 抛 OSError。
    """
    _注入根(monkeypatch, tmp_path)
    指纹 = 段指纹({"task": "t2v", "prompt": "IO失败"}, {})
    写缓存("nodeF", 0, 指纹, _段产物())
    p = 缓存路径("nodeF", 0, 指纹)

    def 炸(*args, **kwargs):
        raise OSError("模拟磁盘读失败")

    monkeypatch.setattr(torch, "load", 炸)
    with pytest.raises(ValueError, match="段缓存读取失败"):
        读缓存("nodeF", 0, 指纹)
    assert os.path.exists(p) is True                # 关键：IO 失败不得删缓存

    # 我方路径解析异常不得被自愈吞掉：非法指纹仍按 ValueError 上抛（try 体外）
    with pytest.raises(ValueError, match="非法指纹格式"):
        读缓存("nodeF", 0, "ZZZ")


# ---------- h3-6：版本分目录 + 自动淘汰旧世代死文件 ----------

def test_淘汰旧版本_删旧世代但绝不碰无关内容(monkeypatch, tmp_path):
    """h3-6 自动清理锁：升版后用户**无需再手动清 %TEMP%**。

    必须删：① 非当前版本的 h3-<数字> 子目录（整目录）；② 基 根下分目录改造前遗留的散
    缓存文件（.pt 与 .part 临时名）。必须留：③ 无关目录/无关文件；④ **model.pt 之类同扩展名
    的模型权重**——两个正则白名单是纵深防御，防 长视频规划师_段缓存_DIR 被误设到重要目录时误删。
    真实背景：h3-3→h3-4 升版曾因无此机制在 %TEMP% 留下 27.9GB 永不命中的旧 images 段。
    """
    基 = _注入基(monkeypatch, tmp_path)
    os.makedirs(基, exist_ok=True)

    def 造(相对路径, 内容=b"x"):
        p = os.path.join(基, *相对路径.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(内容)
        return p

    造("h3-5/30_0_5fccbf803e23c402.pt")          # ① 旧版本目录
    造("h3-3/13_1_a7349031ecf16e73.pt")          # ① 更早的旧版本目录
    散pt = 造("149_0_3c7506ae8f38753c.pt")        # ② 根下遗留散缓存
    散part = 造("149_0_3c7506ae8f38753c.pt.12345.0.part")   # ② 强杀遗留的 .part 孤儿
    无关目录 = os.path.join(基, "我的项目")        # ③ 无关目录
    os.makedirs(无关目录, exist_ok=True)
    无关文件 = 造("说明.txt")                     # ③ 无关文件
    权重 = 造("model.pt")                        # ④ 同扩展名但名字形态不符白名单
    近似名 = os.path.join(基, "h3-abc")          # ④ h3- 开头但不是 h3-<数字>
    os.makedirs(近似名, exist_ok=True)

    根 = _缓存根()                               # ← 触发淘汰

    assert not os.path.exists(os.path.join(基, "h3-5")), "旧版本目录未删"
    assert not os.path.exists(os.path.join(基, "h3-3")), "更早版本目录未删"
    assert not os.path.exists(散pt), "分目录改造前遗留的散 .pt 未删"
    assert not os.path.exists(散part), "遗留的 .part 孤儿未删"
    assert os.path.isdir(无关目录), "误删无关目录"
    assert os.path.exists(无关文件), "误删无关文件"
    assert os.path.exists(权重), "model.pt 不符白名单正则，绝不能被当散缓存删掉"
    assert os.path.isdir(近似名), "h3-abc 不是版本目录，不得删"
    assert 根 == os.path.join(基, 缓存格式版本)
    assert os.path.isdir(根)


def test_淘汰旧版本_同版本活缓存一个不动(monkeypatch, tmp_path):
    """**部分重跑能力的命根子**：淘汰只清「代码里已不存在的旧指纹世代」，同版本文件
    都可能被再次命中（用户把参数改回去就命中），一个都不能删。若这里被误删，
    「已跑过的段只改其中一段、其余段直接用缓存」就失效了（那意味着数小时重算）。
    同时验证进程重启（_已淘汰基 清空）后重扫也不会误伤。
    """
    基 = _注入基(monkeypatch, tmp_path)
    指纹 = 段指纹({"task": "t2v", "prompt": "猫"}, {})
    写缓存("nodeG", 0, 指纹, _段产物())            # 先落一份当前版本的活缓存
    活文件 = 缓存路径("nodeG", 0, 指纹)
    assert os.path.exists(活文件)

    _已淘汰基.discard(基)                          # 模拟进程重启后再次取根
    根 = _缓存根()

    assert os.path.exists(活文件), "同版本活缓存被误删 = 部分重跑能力被破坏"
    assert 读缓存("nodeG", 0, 指纹)["帧数"] == 39, "活缓存必须仍可读回"
    assert 根 == os.path.dirname(活文件)


def test_淘汰旧版本_每个基进程内只扫一遍(monkeypatch, tmp_path):
    """性能锁：_缓存根 经 缓存路径 被**每段每轮**调用，不得反复 scandir + rmtree。
    锁 _已淘汰基 的去重：第二次取根后新造的旧版本目录**不会**被删（因为不再扫）。
    这不是漏删——生产中 基 固定且旧目录只会在取根前就已存在，一次扫描即足够。
    """
    基 = _注入基(monkeypatch, tmp_path)
    _缓存根()
    assert 基 in _已淘汰基

    迟到的旧目录 = os.path.join(基, "h3-1")
    os.makedirs(迟到的旧目录)
    _缓存根()                                     # 第二次：已去重，不再扫
    assert os.path.isdir(迟到的旧目录), "去重失效 = 每段每轮都扫目录，白付 IO"
