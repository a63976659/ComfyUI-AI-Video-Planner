# 视频规划师 · Video Planner

> 一个基于 ComfyUI V3 节点 API 的多段音视频规划工具，编排官方 MiniMax H3 节点，把「时间轴 + 分段脚本 + 参考素材」变成一条完整成片。
>
> A ComfyUI V3 native multi-segment audio/video planner that orchestrates the official MiniMax H3 nodes, turning a timeline of segment scripts and reference materials into a finished film.

**语言 / Language：** [🇨🇳 简体中文](#简体中文) ｜ [🇬🇧 English](#english)

---

## 📑 目录 / Table of Contents

<details open>
<summary><b>简体中文</b></summary>

- [简介](#简介)
- [核心特性](#核心特性)
- [使用说明](#使用说明)
- [技术架构](#技术架构)
- [注意事项](#注意事项)
- [环境要求](#环境要求)
- [安装方法](#安装方法)
- [更新记录](#更新记录)
- [欢迎建议](#欢迎建议)
- [赞赏](#赞赏)

</details>

<details>
<summary><b>English</b></summary>

- [Introduction](#introduction)
- [Key Features](#key-features)
- [Usage](#usage)
- [Architecture](#architecture)
- [Notes & Caveats](#notes--caveats)
- [Requirements](#requirements)
- [Installation](#installation)
- [Changelog](#changelog)
- [Feedback & Contributions](#feedback--contributions)
- [Support](#support)

</details>

---

<a name="简体中文"></a>
## 🇨🇳 简体中文

### 简介

**视频规划师** 是一款 ComfyUI 自定义节点插件，把「多段时间轴」+「逐段脚本」+「参考素材」组织成一次完整的视频生成任务。它不重造扩散/采样轮子，而是**编排** ComfyUI 官方的 MiniMax H3 节点（`MiniMaxH3ImageToVideo` / `MiniMaxH3ReferenceToVideo` / `MiniMaxH3SigmaShift` / `MiniMaxH3AddGuide`），逐段生成、段间连续、拼接成片。

一个主节点（`H3DYT_Director`）+ 底部状态栏富编辑器 + 节点内多段时间轴，覆盖 6 种任务：

| 任务码 | 中文名 | 说明 |
|---|---|---|
| `t2v` | 文生视频 | 纯文本生成 |
| `i2v` | 图生视频 | 首帧引导 |
| `fl2v` | 首尾帧 | 首帧 + 尾帧双端锚定 |
| `r2v` | 参考生视频 | 图片/视频/音频多参考 |
| `v2v` | 视频改视频 | 源视频 + 提示词重绘 |
| `rv2v` | 参考 + 视频 | 参考素材叠加源视频 |

### 核心特性

- 🎬 **多段时间轴**：剪辑轨道式面板（标尺 + 按时长成比例的段卡 + 章节标记），拖拽编辑，所见即所得。
- 🔗 **段间连续性**：把上一段尾部 N 帧（默认 22，可选 5/22/39/56）连同音频作为「运动/音频上下文」钉入下一段条件，采样后裁掉前缀，实现镜头/动作/声音平滑接续。
- 💾 **段磁盘缓存 + Run-select 部分重跑**：每段产物即时原子落盘（`%TEMP%/h3导演台_段缓存`），指纹匹配即命中；只重采勾选段，其余复用缓存。
- 🖼️ **参考素材 + `@提及` 标签**：`<Picture N>` / `<Video K>` / `<Audio J>` 内联引用，段级/全局两级兜底。
- 🎞️ **智能分镜**（可选）：v2v/rv2v 源视频用 PySceneDetect 自动切段。
- 🧹 **段间显存清理**：`gc.collect()` + `torch.cuda.empty_cache()`，降低多段连跑 OOM 风险。
- 📐 **分辨率 → 画布推导**：`输出分辨率`（8 档宽高比）+ `百万像素`（0.1–4.0）取代原来的宽/高 widget，逐行等同官方 `ResolutionSelector.execute`，`CANVAS_MULTIPLE=32` 对齐 H3 画布。
- ⚙️ **采样参数 widget 化**：`步数` / `采样器` / `调度器` 直接暴露为节点 widget，选项来自宿主 `comfy.samplers.KSampler`，不在插件内维护副本。
- 🎨 **画风 + 预设 txt 库下拉**：`预设/视频提示词预设/*.txt` 一键注入全局提示词。
- 🌐 **后端媒体路由**：`/h3dyt/media/{list,upload,file}` 支持列表、上传（原子改名 + 文件名/大小去重）、回传；`/h3dyt/preset/options` 提供画风与预设清单。
- 🖥️ **前端零构建**：原生 ES 模块 + DOM，`WEB_DIRECTORY=./网页资源` 由 ComfyUI 注入，无打包链、无框架依赖。

### 使用说明

#### 1. 装配节点

在 ComfyUI 工作流中新增 **`视频规划师`**（node_id：`H3DYT_Director`），连接四路输入：

```
Model 模型          →  视频规划师.模型
VAE   视频VAE       →  视频规划师.视频VAE
VAE   音频VAE       →  视频规划师.音频VAE
CLIP  (type=minimax, Qwen3-VL) → 视频规划师.CLIP编码器
```

输出：`图像 [T,H,W,C]` / `音频` / `帧率 FLOAT` / `帧数 INT` / `报告 STRING`，可直接接 `SaveVideo` / `PreviewVideo` 等下游节点。

#### 2. 状态栏编辑

插件加载后，ComfyUI **底部状态栏**会自动出现「视频规划师」面板，包含：

- **生成类型选择**：切换 t2v/i2v/fl2v/r2v/v2v/rv2v；
- **提示词编辑器**：全局提示词（画风 + 预设正文自动拼接）；
- **画风预设选择**：下拉选取画风，从 `预设/视频提示词预设/*.txt` 加载正文；
- **参考文件区**：上传/管理图片、视频、音频参考素材（去重、原子写）；
- **时间轴面板**：多段编辑主界面。

节点上的对应 widget 会被自动隐藏（`hidden` + DOM 遮罩双路径），所有数据仍以 **widget 为唯一真源**，前端只是编辑器。

#### 3. 时间轴操作

- **添加段**：点击轨道空白处或「+」按钮，输入 `start` / `end`（秒）与 `prompt`；
- **Run-select**：勾选/取消每段的运行标记，只跑选中的段；未选段若有缓存也会自动读回参与拼接；
- **段卡内容**：任务类型、prompt、参考素材槽位（首帧/尾帧/图片/视频/音频）、章节标记；
- **播放头**：拖动预览当前时间点；
- **存/读**：时间轴 JSON 存在 `时间轴数据` widget（多行字符串），可复制/粘贴/导入导出。

#### 4. 生成流程

1. 点击 ComfyUI 的 **Queue Prompt**；
2. 执行核心解析时间轴 → 逐段：查缓存命中 → 命中则复用 / 未命中则调官方 H3 链路生成 → 立即原子写盘；
3. 段间连续：把上段尾帧/尾音频通过 `MiniMaxH3AddGuide` 钉入本段条件；
4. 采样后按锚帧数裁掉重复前缀，交叉淡化拼接（重叠帧数=4）；
5. 段间 `清理显存()`，进度回调更新前端进度条；
6. 全部段完成后，视频/音频统一拼接为成片返回。

**中断即安全**：`写缓存` 采用「先写 `.part` 临时文件，成功后 `os.replace` 原子改名」策略，中途 Ctrl-C / OOM / 磁盘满都不会产生半截文件；已生成段下次运行直接命中缓存跳过。

### 技术架构

```
┌─────────────── 前端（零构建原生 ES 模块，网页资源/）───────────────┐
│ 状态栏入口.js  registerExtension → 注入 .comfyui-body-bottom       │
│   ├─ 桥接/节点桥.js   状态栏 ↔ node.widgets（唯一真源桥）           │
│   ├─ 桥接/状态桥.js   前端瞬时态（选中段/展开态）                    │
│   └─ 组件/  状态栏面板 / 生成类型选择 / 提示词编辑器 / 画风预设选择  │
│             / 参考文件区 / 时间轴面板                                │
└───────────────┬────────────────────────────────┬───────────────────┘
                │ widget 为真源                    │ fetch /h3dyt/*
                ▼                                  ▼
┌── 节点层（V3 io.ComfyNode，节点/）──┐  ┌── 后端路由（后端路由/）──┐
│ 导演台.py   define_schema / execute │  │ 媒体路由.py  list/upload/file │
│ 节点公用.py 分辨率到宽高 + 选项表   │  │ 预设路由.py  options          │
└───────────────┬──────────────────────┘  └─────────────────────────────┘
                │ 执行时间轴(时间轴数据, 全局参数, 模型输入, node_id, 媒体根, 进度回调)
                ▼
┌─────────────── 执行层（执行/，编排官方 H3 节点）──────────────┐
│ 执行核心.py（主循环）                                          │
│   ├─ 规划.py         时间轴 JSON → DirectorPlan{SegmentPlan}   │
│   ├─ 条件组装.py      任务枚举 → H3ImageToVideo/ReferenceToVideo│
│   ├─ 参考素材.py      槽位归一 + <Picture N> 标签解析/校验     │
│   ├─ 采样与解码.py    画布/帧对齐纯函数 + AV latent 解码       │
│   ├─ 段间连续.py      锚帧数/裁前缀/交叉淡化 + AddGuide 钉入   │
│   ├─ 段缓存.py        指纹 + 磁盘缓存（部分重跑/续跑）         │
│   ├─ 官方管线适配.py  按名取官方节点 + FUNCTION 调用           │
│   └─ 显存清理.py      段间 gc + empty_cache                    │
└────────────────────────────────────────────────────────────────┘
                │ 官方单段链路
                ▼
   SigmaShift → 条件节点(positive + AV latent) → AddGuide(锚上段尾)
   → KSampler(cfg=1.0, negative=positive) → VAEDecode + VAEDecodeAudio
```

**分层职责**：
- **节点层**：V3 schema 声明、widget 边界、`execute` 入口，只抛 `ValueError/RuntimeError` → ComfyUI 红面板；
- **执行层**：纯编排 + 纯函数，可脱离 GPU 单测；
- **后端路由**：HTTP 域，一律 `web.json_response({error},status=4xx/5xx)`，不抛未捕获异常；
- **前端**：widget 为唯一真源，DOM/ES 模块零构建。

### 注意事项

1. **段缓存体积**：单段 float32 IMAGE ≈ 1.4 GiB，**默认无自动淘汰**，缓存目录在 `%TEMP%/h3导演台_段缓存`（可通过环境变量 `H3_段缓存_DIR` 覆盖）。多段跑完后请手动清理，或等待 Task 11「清理段缓存」按钮落地。
2. **强依赖官方 H3 节点**：本插件不实现扩散/采样，所有生成能力来自 `comfy_extras/nodes_minimax_h3.py`，需 ComfyUI 版本包含该文件且已下载 H3 权重。
3. **CLIP 类型必须为 `minimax`**（Qwen3-VL）：其他 CLIP 无法通过 H3 条件节点。
4. **帧率契约**：用户 widget「帧率」**只作输出容器元数据**，不参与帧数换算；实际给模型的 `length` 恒按官方基座 `FPS=24` 计算（`秒转帧数` = `round(秒 × 24)` 再对齐 `17k+5` 网格）。
5. **画布约束**：短边 768 / 面积 ≤ 768×1344 / 32 倍数，超出会被官方 `adapt_canvas` 自动收缩。
6. **`模型标识` widget**：io.Model 传入的 ModelPatcher 通常不带 ckpt 名，自动探测多半落空 → 换 ckpt 时指纹不变、命中旧缓存返回上个模型的旧画面。**换 checkpoint 时请手动填写此 widget**，留空则退化为自动探测。
7. **段间连续性调参**：默认 22 帧上下文 + 4 帧重叠交叉淡化。若出现「花屏/幻影」，先降低上下文帧数或关闭连续性验证是否模型侧问题。
8. **中断安全**：`写缓存` 是原子的，但正在生成中的段（`_生成段` 执行到一半）会丢失，需下次重算。已完成的段全部保留。
9. **Run-select 语义**：未勾选段若命中缓存会参与拼接；若无缓存则**跳过**，下段不会锚到「两段之前」（时间轴已断裂，显式清空上段尾帧）。
10. **音频缺失告警**：视频段全量拼接、音频段过滤 `None`。若某段 audio=None 而其他段有，报告会追加 `警告: 音频段数 < 视频段数` 提示 A/V 可能错位。

### 环境要求

| 项目 | 版本/要求 |
|---|---|
| **ComfyUI** | 支持 V3 节点 API（`comfy_api.latest`）与官方 MiniMax H3 节点的版本 |
| **Python** | 3.10+（跟随 ComfyUI 主环境） |
| **PyTorch** | 由 ComfyUI 主环境提供（含 CUDA / torchaudio） |
| **模型权重** | MiniMax H3 checkpoint + Qwen3-VL CLIP（type=minimax）+ 视频 VAE + 音频 VAE |
| **GPU 显存** | 建议 ≥ 12 GB（H3 生成 + 多段缓存累积） |
| **磁盘空间** | 每段缓存 ≈ 1.4 GiB，预留 20 GB+ 供多段迭代 |

**可选增强依赖**（在 `requirements.txt` 中按需取消注释）：

```bash
# 参考视频读帧（r2v/v2v/rv2v）
pip install imageio imageio-ffmpeg    # 或 pip install av

# 智能分镜（v2v/rv2v 源视频自动分段）
pip install scenedetect opencv-python-headless

# 开发期单测
pip install pytest
```

### 安装方法

**方式一：Git 克隆（推荐）**

```bash
cd ComfyUI/custom_nodes
git clone <本仓库地址> ComfyUI-AI-Edit-Video
cd ComfyUI-AI-Edit-Video
# 如需可选依赖
pip install -r requirements.txt
```

**方式二：手动放置**

1. 下载本仓库压缩包并解压；
2. 把整个目录放到 `ComfyUI/custom_nodes/ComfyUI-AI-Edit-Video/`；
3. 重启 ComfyUI。

**验证安装**：

- ComfyUI 启动日志应出现 `[视频规划师] ...`（若节点/路由导入失败会 warning，但插件本体不会崩溃）；
- 在节点搜索框输入 `视频规划师` 或 `H3DYT_Director` 可找到主节点；
- ComfyUI 页面**底部状态栏**应出现视频规划师面板。

### 更新记录

**2026-09-13**
- 更新技术文档。

**2026-09-12**
- 修复音频素材加载失败的问题。
- 修复新增段时任务类型不正确的问题。
- 创建项目说明文档。

**v1（已完成）**
- 多段视频生成、段间平滑衔接、生成结果缓存、参考素材管理、分辨率选择、画风预设、媒体上传、时间轴编辑器。
- 142 个测试通过。

**v2（计划中）**
- AI 自动规划、提示词优化、二次精修、工程导入导出、缓存清理。

### 欢迎建议

- 🐛 **Bug 反馈**：提 Issue 时请附上 ComfyUI 版本、GPU 型号/显存、H3 权重版本、完整报错日志（红面板内容）、时间轴 JSON（可脱敏）；
- 💡 **功能建议**：欢迎在 Issue 中讨论，尤其是段间连续性调参、Refine 二采策略、Director Pack 结构；
- 🔀 **PR 提交**：请先跑通 `pytest 测试/`（142 passed 基线）与 ruff，遵循项目「ValueError-only 契约」「widget 唯一真源」「中文命名 + ASCII 白名单」等纪律（详见 `文档/技术实现/00-总览与架构.md`）；
- 📖 **文档补全**：`示例工作流/*.json` 需 ComfyUI 实际「保存」导出（手写易失配），欢迎贡献真实工作流样例；
- 🌍 **i18n**：目前 UI 以中文为主，欢迎补齐英文/其他语言的前端词条。

### 赞赏

如果这个插件帮到了你的创作，欢迎请作者喝杯咖啡 ☕：

- **Star 本仓库** ⭐ —— 最免费的鼓励；
- **分享你的作品** —— 用本插件做出的视频，欢迎在 Issue 或社区展示；
- **赞助入口** —— （此处可替换为你的爱发电 / Ko-fi / Patreon / 微信/支付宝二维码链接）。

---

<a name="english"></a>
## 🇬🇧 English

### Introduction

**Video Planner** is a ComfyUI custom-node plugin that organizes a **multi-segment timeline**, **per-segment scripts** and **reference materials** into a single video-generation job. It does **not** reinvent diffusion or sampling — instead it **orchestrates** the official MiniMax H3 nodes (`MiniMaxH3ImageToVideo` / `MiniMaxH3ReferenceToVideo` / `MiniMaxH3SigmaShift` / `MiniMaxH3AddGuide`), running them segment by segment, chaining continuity across segments, and stitching everything into a finished film.

One main node (`H3DYT_Director`) + a bottom status-bar rich editor + an in-node multi-segment timeline, covering six task types:

| Code | Name | Description |
|---|---|---|
| `t2v` | Text-to-Video | Pure text prompt |
| `i2v` | Image-to-Video | First-frame guided |
| `fl2v` | First-Last-to-Video | Both first & last frame anchored |
| `r2v` | Reference-to-Video | Multi image/video/audio references |
| `v2v` | Video-to-Video | Source video repaint with prompt |
| `rv2v` | Reference + Video | References layered on source video |

### Key Features

- 🎬 **Multi-segment timeline** — editing-track style panel (ruler + duration-proportional cards + chapter markers), drag-and-drop, WYSIWYG.
- 🔗 **Segment continuity** — pins the last N frames (default 22; 5/22/39/56 selectable) plus tail audio of the previous segment into the next segment's condition via `MiniMaxH3AddGuide`, then trims the anchored prefix after sampling for smooth shot/motion/audio handoff.
- 💾 **On-disk segment cache + Run-select partial re-run** — every segment is atomically persisted right after generation (`%TEMP%/h3导演台_段缓存`), fingerprint-hit segments are skipped; only checked segments are re-sampled.
- 🖼️ **Reference slots + `@mention` tags** — inline `<Picture N>` / `<Video K>` / `<Audio J>` references, with segment-level and global-level fallback.
- 🎞️ **Smart shot detection** (optional) — PySceneDetect-based auto-segmentation for v2v/rv2v source videos.
- 🧹 **Inter-segment VRAM cleanup** — `gc.collect()` + `torch.cuda.empty_cache()` between segments to reduce OOM risk on long runs.
- 📐 **Resolution → canvas derivation** — `output resolution` (8 aspect ratios) + `megapixels` (0.1–4.0) replace the old width/height widgets, line-for-line equivalent to the official `ResolutionSelector.execute` with `CANVAS_MULTIPLE=32` aligned to H3.
- ⚙️ **Sampler widgets** — `steps` / `sampler_name` / `scheduler` exposed directly as node widgets, options sourced from the host's `comfy.samplers.KSampler` (no duplicated option lists).
- 🎨 **Style + preset txt library** — dropdowns that load prompt bodies from `预设/视频提示词预设/*.txt` and inject them as the global prompt prefix.
- 🌐 **Backend media routes** — `/h3dyt/media/{list,upload,file}` with atomic rename + name/size dedup; `/h3dyt/preset/options` for style/preset catalogs.
- 🖥️ **Zero-build frontend** — plain ES modules + DOM, injected via `WEB_DIRECTORY=./网页资源`, no bundler, no framework.

### Usage

#### 1. Wire the node

Add **`视频规划师`** (node_id: `H3DYT_Director`) to your workflow and connect four inputs:

```
Model              → 视频规划师.模型
VAE (video)        → 视频规划师.视频VAE
VAE (audio)        → 视频规划师.音频VAE
CLIP (type=minimax, Qwen3-VL) → 视频规划师.CLIP编码器
```

Outputs: `IMAGE [T,H,W,C]` / `AUDIO` / `FLOAT fps` / `INT frame_count` / `STRING report` — plug directly into `SaveVideo` / `PreviewVideo` etc.

#### 2. Use the status-bar editor

Once loaded, ComfyUI's **bottom status bar** shows a "Video Planner" panel containing:

- **Generation type selector** — switch among t2v/i2v/fl2v/r2v/v2v/rv2v;
- **Prompt editor** — global prompt (auto-concatenated from style + preset body);
- **Style / preset picker** — dropdown loading bodies from `预设/视频提示词预设/*.txt`;
- **Reference file area** — upload/manage image, video, audio references (dedup, atomic write);
- **Timeline panel** — the main multi-segment editor.

Corresponding widgets on the node itself are auto-hidden (both `hidden` flag and DOM mask). All data still lives in **widgets as the single source of truth**; the frontend is only an editor.

#### 3. Edit the timeline

- **Add segment** — click empty track area or the `+` button, fill `start` / `end` (seconds) and `prompt`;
- **Run-select** — toggle each segment's run flag; only checked ones are re-sampled. Unchecked segments with cache are still loaded and stitched;
- **Segment card fields** — task type, prompt, reference slots (first/last frame, images, videos, audios), chapter marker;
- **Playhead** — drag to preview the current time position;
- **Save / Load** — timeline JSON lives in the `时间轴数据` widget (multiline string), copy/paste/import/export friendly.

#### 4. Generation flow

1. Click **Queue Prompt**;
2. The execution core parses the timeline → for each segment: check fingerprint → hit = reuse / miss = run official H3 chain → immediately atomic-write to disk;
3. Continuity: previous segment's tail frames/audio are pinned into this segment's condition via `MiniMaxH3AddGuide`;
4. After sampling, the anchored prefix is trimmed by `锚帧数`, then segments are stitched with crossfade (overlap=4 frames);
5. `清理显存()` between segments; progress callback updates the frontend bar;
6. On completion, video/audio are concatenated into the final film.

**Interruption-safe**: `写缓存` writes to a `.part` temp file first and `os.replace`s atomically on success. Ctrl-C / OOM / disk-full never leaves half-written files; already-generated segments hit cache on the next run.

### Architecture

```
┌────── Frontend (zero-build ES modules, 网页资源/) ──────┐
│ 状态栏入口.js  registerExtension → .comfyui-body-bottom │
│   ├─ bridges/  node-bridge (widgets ⇄ panels)           │
│   │            state-bridge (transient UI state)        │
│   └─ components/  status-bar / gen-type / prompt-editor │
│                    / style-preset / reference-files      │
│                    / timeline-panel                      │
└───────────────┬────────────────────────┬────────────────┘
                │ widgets as truth        │ fetch /h3dyt/*
                ▼                         ▼
┌── Node layer (V3 io.ComfyNode) ──┐  ┌── Backend routes ──┐
│ 导演台.py  schema / execute      │  │ 媒体路由.py         │
│ 节点公用.py resolution + options │  │ 预设路由.py         │
└───────────────┬──────────────────┘  └─────────────────────┘
                │ execute_timeline(...)
                ▼
┌────── Execution layer (执行/, orchestrates official H3) ──────┐
│ 执行核心.py (main loop)                                        │
│   ├─ 规划.py           timeline JSON → DirectorPlan            │
│   ├─ 条件组装.py        task enum → H3 condition nodes          │
│   ├─ 参考素材.py        slot normalization + tag validation     │
│   ├─ 采样与解码.py      canvas/frame alignment + AV decode      │
│   ├─ 段间连续.py        anchor/trim/crossfade + AddGuide        │
│   ├─ 段缓存.py          fingerprint + on-disk cache             │
│   ├─ 官方管线适配.py    fetch official node by name + invoke    │
│   └─ 显存清理.py        gc + empty_cache between segments       │
└────────────────────────────────────────────────────────────────┘
                │ Official single-segment chain
                ▼
   SigmaShift → condition (positive + AV latent) → AddGuide (anchor prev tail)
   → KSampler (cfg=1.0, negative=positive) → VAEDecode + VAEDecodeAudio
```

**Layer responsibilities**:
- **Node layer** — V3 schema, widget bounds, `execute` entry; only raises `ValueError/RuntimeError` → ComfyUI red panel;
- **Execution layer** — pure orchestration + pure functions, unit-testable without GPU;
- **Backend routes** — HTTP domain; always returns `web.json_response({error}, status=4xx/5xx)`, never lets exceptions escape;
- **Frontend** — widgets are the single source of truth; DOM/ES modules, zero build.

### Notes & Caveats

1. **Cache size** — a single segment's float32 IMAGE ≈ 1.4 GiB, **no auto eviction** by default. Cache root is `%TEMP%/h3导演台_段缓存` (override via env `H3_段缓存_DIR`). Clean up manually after long sessions.
2. **Hard dependency on official H3 nodes** — this plugin does not implement diffusion/sampling; all generation flows through `comfy_extras/nodes_minimax_h3.py`. Your ComfyUI must ship that file and you must have H3 weights downloaded.
3. **CLIP type must be `minimax`** (Qwen3-VL). Other CLIP variants will fail inside the H3 condition nodes.
4. **Frame-rate contract** — the user-facing `帧率` widget is **only container metadata**; the actual `length` fed to the model always uses the official base `FPS=24` (`秒转帧数` = `round(seconds × 24)`, then aligned to the `17k+5` grid).
5. **Canvas constraints** — short side 768 / area ≤ 768×1344 / multiple of 32; oversized values are auto-shrunk by official `adapt_canvas`.
6. **`模型标识` widget** — `io.Model` typically delivers a `ModelPatcher` without a ckpt name, so auto-detection usually fails → changing the checkpoint won't invalidate the fingerprint and old cached frames will be returned. **Fill this widget manually whenever you swap the checkpoint**; leave empty to fall back to auto-detect.
7. **Continuity tuning** — default 22 context frames + 4-frame crossfade overlap. If you see smearing/ghosting, first lower context frames or disable continuity to isolate the issue.
8. **Interruption semantics** — `写缓存` is atomic, but a segment currently mid-generation (`_生成段` halfway) is lost and must be recomputed. Completed segments are always preserved.
9. **Run-select semantics** — unchecked segments with cache still join the stitch; unchecked segments without cache are **skipped entirely**, and the next segment does not anchor to "two segments ago" (the timeline has broken, tail context is explicitly cleared).
10. **Missing-audio warning** — video stitches everything, audio filters out `None`. If one segment has `audio=None` while others don't, the report appends `警告: 音频段数 < 视频段数` to flag potential A/V drift.

### Requirements

| Item | Version / Notes |
|---|---|
| **ComfyUI** | Any version supporting V3 node API (`comfy_api.latest`) and the official MiniMax H3 nodes |
| **Python** | 3.10+ (following the ComfyUI main environment) |
| **PyTorch** | Provided by ComfyUI (CUDA + torchaudio) |
| **Model weights** | MiniMax H3 checkpoint + Qwen3-VL CLIP (type=minimax) + video VAE + audio VAE |
| **GPU VRAM** | ≥ 12 GB recommended (H3 generation + multi-segment accumulation) |
| **Disk** | ≈ 1.4 GiB per cached segment; keep 20 GB+ free for iterative work |

**Optional extras** (uncomment in `requirements.txt` as needed):

```bash
# Reference-video frame reading (r2v/v2v/rv2v)
pip install imageio imageio-ffmpeg    # or: pip install av

# Smart shot detection (v2v/rv2v auto-segmentation)
pip install scenedetect opencv-python-headless

# Dev-time unit tests
pip install pytest
```

### Installation

**Option A — Git clone (recommended)**

```bash
cd ComfyUI/custom_nodes
git clone <this-repo-url> ComfyUI-AI-Edit-Video
cd ComfyUI-AI-Edit-Video
pip install -r requirements.txt   # only if you need the optional extras
```

**Option B — Manual drop-in**

1. Download and unzip this repo;
2. Move the whole directory to `ComfyUI/custom_nodes/ComfyUI-AI-Edit-Video/`;
3. Restart ComfyUI.

**Verify**:

- Startup log should contain `[视频规划师] ...` lines (warnings on node/route import failure are non-fatal);
- Search `视频规划师` or `H3DYT_Director` in the node picker;
- The **bottom status bar** should show the Video Planner panel.

### Changelog

**2026-09-13**
- Updated technical documentation.

**2026-09-12**
- Fixed audio reference loading failures.
- Fixed incorrect task type for new segments.
- Created project README.

**v1 (shipped)**
- Multi-segment video generation, smooth segment transitions, result caching, reference materials, resolution picker, style presets, media upload, timeline editor.
- 142 tests passing.

**v2 (planned)**
- AI planning, prompt enhancement, refine pass, project import/export, cache cleanup.

### Feedback & Contributions

- 🐛 **Bug reports** — please include ComfyUI version, GPU model/VRAM, H3 weight version, full red-panel log, and the timeline JSON (feel free to redact);
- 💡 **Feature requests** — open an Issue; continuity tuning, refine strategy and Director Pack structure are especially welcome topics;
- 🔀 **Pull requests** — please keep `pytest 测试/` at the 142-passed baseline and ruff-clean, and follow project conventions (ValueError-only contract, widgets as single source of truth, Chinese naming with an ASCII whitelist — see `文档/技术实现/00-总览与架构.md`);
- 📖 **Docs** — `示例工作流/*.json` must be exported by ComfyUI's own "Save" (hand-writing drifts easily); real workflow samples are highly welcome;
- 🌍 **i18n** — UI is currently Chinese-first; English/other-language frontend strings contributions are appreciated.

### Support

If this plugin helps your creative workflow, consider buying the author a coffee ☕:

- **Star this repo** ⭐ — the cheapest form of encouragement;
- **Share your work** — videos made with this plugin are welcome in Issues or community channels;
- **Sponsorship** — (replace with your Ko-fi / Patreon / GitHub Sponsors / crypto link here).

---

<p align="center">
  <sub>Made with ❤️ for the ComfyUI community · 为 ComfyUI 社区用心打造</sub>
</p>
