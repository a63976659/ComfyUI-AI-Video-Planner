# -*- coding: utf-8 -*-
"""让测试在裸 pytest / 任意 cwd 下都能导入 规划/执行 等包与 comfy_api。"""
import sys
from pathlib import Path

_插件根 = Path(__file__).resolve().parents[1]
# 插件根（供 `import 规划`）+ ComfyUI 根（供 `import comfy_api`）
sys.path[:0] = [str(_插件根), str(_插件根.parents[1])]
