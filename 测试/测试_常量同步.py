# -*- coding: utf-8 -*-
"""前后端镜像常量同步锁（J3）。

JS 与 Python 无法共享常量，故「百万像素」这类**既有后端 widget 真源、又有前端滑块镜像**的值
各存一份。漂移不会报错，只会让 UI 与节点行为静默不一致：

- 前端滑块 `max` / `Math.min` 钳位 **>** 后端 `_百万像素上限`
  → 用户能把滑块拖到后端 V3 原生 min/max 校验拒收的值（红面板，且报错点离操作点很远）；
- 前端 **<** 后端 → 前端白白砍掉后端允许的档位，用户看不出还有余量；
- `默认百万像素` 漂移 → 「未绑定节点时的兜底显示值」与「新拖出节点的 widget default」不一致，
  表现为面板显示 0.4 而实际跑的是 1.0（或反之）。

真源恒在 **Python**（`io.Float.Input` 的 min/max/default 必须进 V3 schema 才能过校验），
前端 `网页资源/组件/提示词编辑器.js` 是镜像。

⚠️ 锚点匹配次数必须**恰为 1**：0 次 = 前端已重命名/删除，>1 次 = 出现了第二份镜像，
两种情况同步保证都已失效，一律**判失败而非跳过**——静默跳过等于没有锁。
只有 JS 文件整个不存在（如不完整检出）才 skip，见 `js源`。
"""
import re
from pathlib import Path

import pytest

comfy_api = pytest.importorskip("comfy_api")   # 导演台 依赖 V3 io；缺宿主则整文件跳过
节点公用 = pytest.importorskip("节点.节点公用")
导演台 = pytest.importorskip("节点.导演台")

_插件根 = Path(__file__).resolve().parents[1]
_提示词编辑器 = _插件根 / "网页资源" / "组件" / "提示词编辑器.js"
_状态栏入口 = _插件根 / "网页资源" / "状态栏入口.js"


# 「前端镜像 → 后端真源」对照表。**加一行即多锁一对**（正则须为单捕获组、捕获数值）。
# 真源用 lambda 惰性取值：断言时读，不在 import 期固化。
# 第 2 列是 pytest id，**故意用 ASCII**：id 会出现在控制台/CI 日志里，而 Windows GBK 控制台
# 会把非 ASCII id 打花成 `\uXXXX` 或乱码，导致「哪一条红了」无法可靠辨认；中文说明仍保留在
# 第 1 列（进断言消息，供读完整 traceback 的人看）。
镜像对照 = [
    ("滑块max", "slider-max",
     r'百万像素滑\.max\s*=\s*"?([0-9.]+)"?',
     lambda: 导演台._百万像素上限,
     "滑块可拖到的最大值 ↔ 后端 io.Float.Input 的 max"),
    ("钳位Math.min", "clamp-math-min",
     r"Math\.min\(\s*([0-9.]+)\s*,\s*Math\.max\(",
     lambda: 导演台._百万像素上限,
     "设百万像素() 程序赋值路径的钳位 ↔ 后端 max。与滑块 max 是**两处独立字面量**："
     "只改其一，回填/预设注入这条程序赋值路径仍会越过另一处"),
    ("默认百万像素", "default-megapixels",
     r"export\s+const\s+默认百万像素\s*=\s*([0-9.]+)",
     lambda: 节点公用.默认百万像素,
     "未绑定节点时的兜底显示值 ↔ 新拖出节点的 widget default"),
]


@pytest.fixture(scope="module")
def js源():
    """前端源文本。utf-8-sig：容忍 BOM，免得首行锚点被 \\ufeff 顶掉。"""
    if not _提示词编辑器.exists():
        pytest.skip(f"未找到前端源文件：{_提示词编辑器}")
    return _提示词编辑器.read_text(encoding="utf-8-sig")


def _唯一(源, 模式, 名):
    """按正则在 JS 源里取数值，要求**恰好一处**匹配（0 或 >1 均判失败，理由见模块 docstring）。"""
    命中 = re.findall(模式, 源)
    assert len(命中) == 1, (
        f"{名}：前端锚点应恰好匹配 1 次，实际 {len(命中)} 次"
        f"（0=已重命名/删除，>1=出现第二份镜像，同步保证均已失效）。模式={模式!r}"
    )
    return float(命中[0])


@pytest.mark.parametrize("名,id_,模式,取真源,说明", 镜像对照, ids=[m[1] for m in 镜像对照])
def test_前后端镜像常量同步_lock(名, id_, 模式, 取真源, 说明, js源):
    """契约锁：前端镜像值必须与后端真源逐值相等。

    按 float 比较而非字符串：JS 侧写 `max = "4"`、Python 侧是 `4.0`，字面形态不同但语义同值，
    逐字符比会制造无意义红灯（改 `4` → `4.0` 不该算漂移）。
    """
    前端 = _唯一(js源, 模式, 名)
    后端 = float(取真源())
    assert 前端 == 后端, (
        f"{名} 漂移：前端 {前端} ≠ 后端 {后端}。{说明}。\n"
        f"真源在 Python（节点/导演台.py 的 _百万像素上限 或 节点/节点公用.py 的 默认百万像素），"
        f"前端 网页资源/组件/提示词编辑器.js 是镜像——改一处必须同步另一处（11 §J3）。"
    )


def test_段级进度事件名_前后端同步():
    """字面量镜像锁（**字符串**型，故不进 镜像对照 表——那张表按 float 比数值）。

    后端 `节点/导演台.py` 的 `_进度事件名` 与前端 `网页资源/状态栏入口.js` 里 `addEventListener`
    的事件名必须逐字相等。漂移不报错，只会让状态栏**静默收不到段级进度**（后端往没人听的
    事件名上发、前端等没人发的事件名），表现与「进度条坏了」一模一样、极难定位——正是 J3 要防的
    那类静默不一致。真源在 Python（它决定 websocket 上实际发的事件名）。

    另锁一条反面：前端**不得**再监听宿主的 legacy `"progress"`。那条事件由 KSampler 的内部去噪
    步进触发（宿主 main.py 的 hijack_progress 全局 hook），node_id 取自执行上下文＝导演台节点，
    与我方段级进度同 node_id ⇒ 按 node 过滤也分不开，留着就会让状态条在「生成中 3/7」（段）与
    「5/20」（去噪步）之间来回跳（缘由详 导演台._广播进度 docstring）。"""
    if not _状态栏入口.exists():
        pytest.skip(f"未找到前端源文件：{_状态栏入口}")
    js = _状态栏入口.read_text(encoding="utf-8-sig")
    前端监听 = re.findall(r'api\.addEventListener\(\s*"([^"]+)"', js)
    后端名 = 导演台._进度事件名
    assert 前端监听.count(后端名) == 1, (
        f"段级进度事件名漂移：后端 _进度事件名={后端名!r}，前端 addEventListener 名单={前端监听}"
        f"（须恰好含它 1 次：0=已改名/删除，>1=出现第二份通道）。真源在 Python（节点/导演台.py），"
        f"前端 状态栏入口.js 是镜像——改一处必须同步另一处（11 §J3）。"
    )
    assert "progress" not in 前端监听, (
        f'前端不得监听宿主 legacy "progress"：它由 KSampler 去噪步进触发、与段级进度同 node_id，'
        f"会让状态条在「段」与「去噪步」之间来回跳。实际名单={前端监听}"
    )
