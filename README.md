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

**视频规划师** 是一款 ComfyUI 自定义节点插件，把「多段时间轴」+「逐段脚本」+「参考素材」组织成一次完整的视频生成任务。它不重造扩散/采样轮子，而是**编排** ComfyUI 官方的 MiniMax H3 节点（`MiniMaxH3ImageToVideo` / `MiniMaxH3ReferenceToVideo` / `MiniMaxH3SigmaShift`），逐段生成、段间连续、拼接成片（段间锚定不再调官方 `MiniMaxH3AddGuide`，改为直接在 latent 上自建 keyframe，见下文「生成流程」）。

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
- 🔗 **段间连续性（尾帧锚定）**：由时间轴工具条「渐变过渡」开关控制，**默认关闭**（各段独立生成）；开启时把上一段尾部 22 帧（经 `规范锚帧数` 对齐 17k+5 网格，如 5/22/39/56）连同音频作为「运动/音频上下文」钉入下一段条件，采样后裁掉前缀，实现镜头/动作/声音平滑接续。
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

在 ComfyUI 工作流中新增 **`视频规划师`**（node_id：`H3DYT_Director`）。它有**两个选填模型插座**——按时间轴实际用到的任务连对应的那个即可，只跑单管线时连一个就够：

```
Model 图生视频管线(t2v/i2v/fl2v)   →  视频规划师.fl2va模型    （选填）
Model 参考生视频管线(r2v/v2v/rv2v) →  视频规划师.ref2va模型   （选填）
CLIP  (type=minimax, Qwen3-VL)     →  视频规划师.CLIP编码器
VAE   视频VAE                      →  视频规划师.视频VAE
VAE   音频VAE                      →  视频规划师.音频VAE
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
2. 执行核心解析时间轴，然后分**两个阶段**跑（“延迟解码”编排，为 16GB 级显卡而设）：
3. **Phase 1（逐段采样）**：查缓存命中 → 命中则复用 / 未命中则调官方 H3 链路跑到 KSampler 为止 → 把产出的 **latent 搬到内存**并立即原子写盘（单段 ≈45MB，而不是像素的 ≈4.7GiB）；
4. 段间连续（**仅「渐变过渡」开启时**）：直接从上段 **latent** 上切下尾部 token（含音频）自建 keyframe 钉入本段条件，**不再走 decode→encode 往返**（不再调官方 `MiniMaxH3AddGuide`）；关闭时各段独立生成、跳过此步；
5. 段间 `清理显存()`（只 gc、不还池），进度回调更新前端进度条；
6. **Phase 2（集中解码）**：全部段采完后先**释放钉住的模型**让出显存，再逐段 VAE 解码 → 按锚帧数裁掉重复前缀 → **逐段流式并入预先分配的成片**（交叉淡化，重叠帧数=4）；
7. 视频/音频拼接完成后返回成片。

> 💡 为何这么拆：解码时若采样模型仍占着显存，宿主会反复 offload/reload 权重，实测 16GB 卡跑 1.0MP@16s 时解码从 ≈52s 退化到 ≈839s。两阶段 + 解码前释放模型可避开；而逐段流式并入（而非攒全量段列表再拼）把成片阶段的内存峰值从 ≈3N 降到 ≈N+1。

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
│   ├─ 段间连续.py      锚帧数/裁前缀/交叉淡化 + latent 锚定     │
│   ├─ 段缓存.py        指纹 + 磁盘缓存（部分重跑/续跑）         │
│   ├─ 官方管线适配.py  按名取官方节点 + FUNCTION 调用           │
│   └─ 显存清理.py      段间 gc + empty_cache                    │
└────────────────────────────────────────────────────────────────┘
                │ 官方单段链路（本插件把它切成两阶段执行）
                ▼
   Phase 1（逐段）SigmaShift → 条件节点(positive + AV latent)
     → 从上段 latent 切尾自建 keyframe(等价 AddGuide 产出) → KSampler(cfg=1.0, negative=positive)
     → latent 搬 CPU + 原子落盘
   Phase 2（集中）释放钉住的模型让出显存 → 逐段 VAEDecode + VAEDecodeAudio
     → 裁前缀 → 流式并入预分配成片(crossfade)
```

**分层职责**：
- **节点层**：V3 schema 声明、widget 边界、`execute` 入口，只抛 `ValueError/RuntimeError` → ComfyUI 红面板；
- **执行层**：纯编排 + 纯函数，可脱离 GPU 单测；
- **后端路由**：HTTP 域，一律 `web.json_response({error},status=4xx/5xx)`，不抛未捕获异常；
- **前端**：widget 为唯一真源，DOM/ES 模块零构建。

### 注意事项

1. **段缓存体积**：自「延迟解码」改造后落盘的是 **latent**，单段 ≈45 MB（旧版存 float32 IMAGE 时同口径 ≈4.7 GiB，缩到约 1/108；该比值与分辨率无关）。缓存目录在 `%TEMP%/h3导演台_段缓存/<缓存版本>/`（环境变量 `H3_段缓存_DIR` 覆盖的是**基目录**，不含版本层）。✅ **自 `h3-6` 起无需手动清理**：程序启动首次取缓存目录时，会自动删掉所有旧版本子目录与分目录改造前遗留在基目录下的散缓存文件（两道正则白名单严格限定目标，`model.pt`/`vae.pt` 之类同名扩展的模型权重绝不误删）。
   ⚠️ 升级后首次运行仍会全量重算一次（缓存指纹变了，不可避免），但**这是最后一次需要重算的升级**。⚠️ 同一版本内**刻意不做容量上限淘汰**——那些文件都可能被再次命中（把参数改回去就命中），删掉就等于牺牲「已跑过的段只改其中一段、其余段直接用缓存」的部分重跑能力。
2. **成片阶段吃的是内存（RAM）不是显存**：VAE 解码输出落在 CPU，1.0MP@16s 单段 ≈5.0 GB。现版逐段解码后立刻并入预分配成片并释放本段引用，峰值约 N+1 段；若自行改造回「攒全量段列表再拼」，3 段就会到 ≈40 GB 并开始换页。
3. **强依赖官方 H3 节点**：本插件不实现扩散/采样，所有生成能力来自 `comfy_extras/nodes_minimax_h3.py`，需 ComfyUI 版本包含该文件且已下载 H3 权重。
4. **CLIP 类型必须为 `minimax`**（Qwen3-VL）：其他 CLIP 无法通过 H3 条件节点。
5. **帧率契约**：用户 widget「帧率」**只作输出容器元数据**，不参与帧数换算；实际给模型的 `length` 恒按官方基座 `FPS=24` 计算（`秒转帧数` = `round(秒 × 24)` 再对齐 `17k+5` 网格）。
6. **画布约束**：主画布 = `输出分辨率` × `百万像素` 的推导结果，**32 倍数、原样送模型**（与官方一致：`adapt_canvas` 的短边 768 / 面积 ≤768×1344 收缩**只作用于参考视频**，不作用于主画布）。故「百万像素」**真实生效**：默认 `0.4MP + 16:9` → **864×480**。面积上限由滑块上限 `4.0` 兜，调高时注意显存（如 `4.0MP + 21:9` → 3136×1344）。
7. **双模型输入（按任务自动匹配）**：节点有两个**选填**模型插座 `fl2va模型`（图生视频管线 t2v/i2v/fl2v）与 `ref2va模型`（参考生视频管线 r2v/v2v/rv2v），执行时按每段任务类型自动选用对应模型，**无需手动切换**。只跑单管线时可只连对应那个（执行前只校验时间轴实际用到的任务对应模型已连接，缺则点名报错）。⚠️ 换 checkpoint：进程内模型缓存靠对象身份自动重载，但**段缓存指纹不再感知「同一管线换了哪个 ckpt」**（旧「模型标识」widget 已移除、缓存版本已升到 `h3-6`），如需彻底重算旧段请手动清理 `%TEMP%/h3导演台_段缓存/<当前版本>`。
8. **段间连续性调参**：由时间轴工具条「渐变过渡」开关控制，**默认关闭**（各段独立生成，接缝仅保留 4 帧重叠交叉淡化）；开启后沿用 22 帧上下文锚定。若出现「花屏/幻影」，先关闭「渐变过渡」验证是否模型侧问题。
9. **中断安全**：`写缓存` 是原子的，但正在采样中的段（`_采样段` 执行到一半）会丢失，需下次重算。已完成的段全部保留。
10. **Run-select 语义**：未勾选段若命中缓存会参与拼接；若无缓存则**跳过**，下段不会锚到「两段之前」（时间轴已断裂，显式清空上段尾帧）。进度条仍会走到 100%（被跳过的段也占它自己那一步）。
11. **音频缺失告警**：视频段全量拼接、音频段过滤 `None`。若某段 audio=None 而其他段有，报告会追加 `警告: 音频段数 < 视频段数` 提示 A/V 可能错位。

### 环境要求

| 项目 | 版本/要求 |
|---|---|
| **ComfyUI** | 支持 V3 节点 API（`comfy_api.latest`）与官方 MiniMax H3 节点的版本 |
| **Python** | 3.10+（跟随 ComfyUI 主环境） |
| **PyTorch** | 由 ComfyUI 主环境提供（含 CUDA / torchaudio） |
| **模型权重** | MiniMax H3 checkpoint + Qwen3-VL CLIP（type=minimax）+ 视频 VAE + 音频 VAE |
| **GPU 显存** | 建议 ≥ 12 GB（H3 生成本身；1.0MP@16s 实测 16 GB 卡靠两阶段编排才不退化） |
| **系统内存** | 建议 ≥ 32 GB（成片阶段解码输出落 CPU，1.0MP@16s 单段 ≈5 GB，峰值 ≈N+1 段） |
| **磁盘空间** | 每段缓存 ≈ 45 MB（latent；旧版存像素时同口径 ≈ 4.7 GiB），预留 5 GB+ 供多段迭代 |

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

- ComfyUI 启动日志应出现 `[H3导演台] ...`（若节点/路由导入失败会 warning，但插件本体不会崩溃）；
- 在节点搜索框输入 `视频规划师` 或 `H3DYT_Director` 可找到主节点；
- ComfyUI 页面**底部状态栏**应出现视频规划师面板。

### 更新记录

**2026-09-15**
- 生成改为**两阶段（延迟解码）**：逐段只跑到采样并存 latent，全部段采完后释放模型再集中解码——修复 16GB 卡跑高分辨率长段时解码从 ≈52s 退化到 ≈839s 的问题。
- 段间锚定不再经「解码→重新编码」往返，直接在上段 latent 上切尾部作为上下文，接缝更保真。
- 成片改为**逐段流式并入预分配缓冲**，拼接阶段内存峰值从 ≈3N 降到 ≈N+1（1.0MP@16s 三段从 ≈40GB 降到 ≈20GB）。
- 修复：部分段被跳过且无缓存时**进度条到不了 100%**。
- 修复：后台计时日志里「①参考解码」恒为 0.00s 的统计盲区（现在各分项相加等于合计；⚠️ 合计**不含**解码耗时，旧日志的合计数不能与新日志直接比）。
- 修复：上下文帧数调到 1~4 时接缝会多重复 4 帧画面的锚定长度换算错误。
- 缓存改为**按版本分子目录**存放（`%TEMP%/h3导演台_段缓存/<版本>/`），并在进程启动时**自动删除旧版本目录**——彻底解决历史上升级后旧缓存变成永不命中的死文件、堆在 `%TEMP%` 无人清理的问题（曾积累 **27.9 GB**）。今后升级**不再需要用户手动清目录**。
- 缓存版本升 `h3-6`（旧缓存整体作废，首次运行会全量重算一次；这是最后一次需要重算的升级）。
- 修复：底部状态栏的**段级进度**（「生成中 3/7」）此前从未真正显示过——面板收到的全是采样器内部的去噪步数（几十步飞快跳）。现改走插件自有的进度通道，段级进度真实可见；多节点工作流下只显示当前正在编辑的那个节点的进度。
- 加固：段缓存文件若被外力改坏（帧数与 latent 时长对不上），现在**当场判为未命中重算**，不会拖到解码拼接阶段才报错——后者会白费已跑完的数小时采样，且重跑会在同一处反复报错、只能手动清目录。
- 测试从 196 增至 **217 passed**，说明文档全量同步。

**2026-09-14**
- 节点改为两个可选模型接口，按每段任务自动选用对应模型，无需手动切换。
- 运行前只检查时间轴实际用到的模型是否已连接，缺哪个提示哪个。
- 两个模型的缓存分开保留，混合任务不再反复重载模型。
- 调整节点接口排列顺序，编码器显示在最前。
- ⚠️ 旧工作流需重接模型连线、核对两个隐藏开关，旧缓存会自动作废一次。
- 测试与说明文档同步更新。

**2026-09-13**
- 画面尺寸改由「百万像素」真实控制，默认产出由 1376×768 变为 864×480。
- 默认步数由 25 降为 20，状态栏百万像素默认值由 1.0 降为 0.4。
- 新增界面与后端数值一致性的自动检查，防止两边参数不一致。
- 更新说明文档。

**2026-09-12**
- 修复音频素材加载失败的问题。
- 修复新增段时任务类型不正确的问题。
- 创建项目说明文档。

**v1（已完成）**
- 多段视频生成、段间平滑衔接、生成结果缓存、参考素材管理、分辨率选择、画风预设、媒体上传、时间轴编辑器。
- 162 个测试通过。

**v2（计划中）**
- AI 自动规划、提示词优化、二次精修、工程导入导出、缓存清理。

### 欢迎建议

- 🐛 **Bug 反馈**：提 Issue 时请附上 ComfyUI 版本、GPU 型号/显存、H3 权重版本、完整报错日志（红面板内容）、时间轴 JSON（可脱敏）；
- 💡 **功能建议**：欢迎在 Issue 中讨论，尤其是段间连续性调参、Refine 二采策略、Director Pack 结构；
- 🔀 **PR 提交**：请先跑通 `pytest 测试/`（217 passed 基线）与 ruff，遵循项目「ValueError-only 契约」「widget 唯一真源」「中文命名 + ASCII 白名单」等纪律（详见 `文档/技术实现/00-总览与架构.md`）；
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

**Video Planner** is a ComfyUI custom-node plugin that organizes a **multi-segment timeline**, **per-segment scripts** and **reference materials** into a single video-generation job. It does **not** reinvent diffusion or sampling — instead it **orchestrates** the official MiniMax H3 nodes (`MiniMaxH3ImageToVideo` / `MiniMaxH3ReferenceToVideo` / `MiniMaxH3SigmaShift`), running them segment by segment, chaining continuity across segments, and stitching everything into a finished film (cross-segment anchoring no longer calls the official `MiniMaxH3AddGuide` — it builds the keyframe directly on the latent; see "Generation flow" below).

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
- 🔗 **Segment continuity (tail-frame anchoring)** — controlled by the "渐变过渡" toggle on the timeline toolbar, **off by default** (segments generated independently); when on, pins the last 22 frames (aligned to the 17k+5 grid via `规范锚帧数`, e.g. 5/22/39/56) plus tail audio of the previous segment into the next segment's condition **directly on the latent** (slicing tail tokens and building the keyframe in-place — no decode→encode round trip, no official `MiniMaxH3AddGuide` call), then trims the anchored prefix after sampling for smooth shot/motion/audio handoff.
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

Add **`视频规划师`** (node_id: `H3DYT_Director`) to your workflow. It has **two optional model sockets** — connect the one(s) your timeline's tasks actually use; a single-pipeline job needs only one:

```
Model image-to-video (t2v/i2v/fl2v)     → 视频规划师.fl2va模型   (optional)
Model reference-to-video (r2v/v2v/rv2v) → 视频规划师.ref2va模型  (optional)
CLIP  (type=minimax, Qwen3-VL)          → 视频规划师.CLIP编码器
VAE (video)                             → 视频规划师.视频VAE
VAE (audio)                             → 视频规划师.音频VAE
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
2. The execution core parses the timeline, then runs in **two phases** (a "deferred decode" orchestration designed for 16GB-class cards):
3. **Phase 1 (per-segment sampling)**: check fingerprint → hit = reuse / miss = run the official H3 chain **up to KSampler only** → move the resulting **latent to RAM** and atomic-write it to disk immediately (≈45MB per segment instead of ≈4.7GiB of pixels);
4. Continuity (**only when "渐变过渡" is on**): tail tokens (video + audio) are sliced **straight off the previous segment's latent** and pinned into this segment's condition as a self-built keyframe — **no decode→encode round trip** (the official `MiniMaxH3AddGuide` is not called); when off, segments are generated independently and this step is skipped;
5. `清理显存()` between segments (gc only, pool not returned); progress callback updates the frontend bar;
6. **Phase 2 (centralised decode)**: once every segment is sampled, the pinned models are **released first** to free VRAM, then each segment is VAE-decoded → the anchored prefix is trimmed by `锚帧数` → the result is **streamed into a pre-allocated film buffer** (crossfade, overlap=4 frames);
7. Video/audio are returned as the finished film.

> 💡 Why split it: if the sampling model still occupies VRAM while decoding, the host repeatedly offloads/reloads weights — measured on a 16GB card at 1.0MP@16s, decode degraded from ≈52s to ≈839s. The two phases plus releasing models before decode avoid this; and streaming each decoded segment into a pre-allocated buffer (instead of collecting all segments then stitching) drops the peak RAM of the stitching phase from ≈3N to ≈N+1.

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
│   ├─ 段间连续.py        anchor/trim/crossfade + latent anchor   │
│   ├─ 段缓存.py          fingerprint + on-disk cache             │
│   ├─ 官方管线适配.py    fetch official node by name + invoke    │
│   └─ 显存清理.py        gc + empty_cache between segments       │
└────────────────────────────────────────────────────────────────┘
                │ Official single-segment chain (this plugin splits it into two phases)
                ▼
   Phase 1 (per segment)  SigmaShift → condition (positive + AV latent)
     → slice tail tokens off the previous latent, build the keyframe in-place (≡ AddGuide output)
     → KSampler (cfg=1.0, negative=positive) → move latent to CPU + atomic write
   Phase 2 (centralised)  release the pinned models to free VRAM → per-segment VAEDecode + VAEDecodeAudio
     → trim prefix → stream into a pre-allocated film buffer (crossfade)
```

**Layer responsibilities**:
- **Node layer** — V3 schema, widget bounds, `execute` entry; only raises `ValueError/RuntimeError` → ComfyUI red panel;
- **Execution layer** — pure orchestration + pure functions, unit-testable without GPU;
- **Backend routes** — HTTP domain; always returns `web.json_response({error}, status=4xx/5xx)`, never lets exceptions escape;
- **Frontend** — widgets are the single source of truth; DOM/ES modules, zero build.

### Notes & Caveats

1. **Cache size** — since the deferred-decode refactor the on-disk payload is the **latent**, ≈45 MB per segment (like-for-like it was ≈4.7 GiB when float32 IMAGEs were stored — about 1/108, a ratio that is independent of resolution). The cache root is `%TEMP%/h3导演台_段缓存/<cache version>/` (env `H3_段缓存_DIR` overrides the **base**, not the version layer). ✅ **Since `h3-6` no manual cleanup is needed**: on the first cache access the program automatically deletes every old-version subdirectory plus the loose cache files left in the base directory from before the versioning refactor (two strict regex whitelists bound the targets, so same-extension model weights like `model.pt`/`vae.pt` are never touched).
   ⚠️ The first run after an upgrade still recomputes everything once (the fingerprints change — unavoidable), but **this is the last upgrade that requires a recompute**. ⚠️ Within a single version there is deliberately **no size-cap eviction** — any of those files may be hit again (change a parameter back and it hits), and deleting them would sacrifice the "recompute only the one segment you edited, reuse the rest from cache" partial-rerun capability.
2. **The stitching phase consumes RAM, not VRAM** — VAE decode output lands on the CPU, ≈5.0 GB per segment at 1.0MP@16s. The current code streams each decoded segment into a pre-allocated buffer and drops the segment reference right away, so the peak is ≈N+1 segments; reverting to "collect all segments, then stitch" would reach ≈40 GB for 3 segments and start paging.
3. **Hard dependency on official H3 nodes** — this plugin does not implement diffusion/sampling; all generation flows through `comfy_extras/nodes_minimax_h3.py`. Your ComfyUI must ship that file and you must have H3 weights downloaded.
4. **CLIP type must be `minimax`** (Qwen3-VL). Other CLIP variants will fail inside the H3 condition nodes.
5. **Frame-rate contract** — the user-facing `帧率` widget is **only container metadata**; the actual `length` fed to the model always uses the official base `FPS=24` (`秒转帧数` = `round(seconds × 24)`, then aligned to the `17k+5` grid).
6. **Canvas constraints** — the main canvas is exactly what `输出分辨率` × `百万像素` resolves to: **a multiple of 32, passed to the model as-is** (matching upstream: the `adapt_canvas` short-side-768 / area ≤ 768×1344 shrink applies **only to reference videos**, never to the main canvas). So `百万像素` genuinely takes effect: the default `0.4MP + 16:9` yields **864×480**. The area ceiling is the slider's `4.0` max — watch VRAM as you raise it (`4.0MP + 21:9` → 3136×1344).
7. **Dual model inputs (auto-matched by task)** — the node has two **optional** model sockets: `fl2va模型` (image-to-video pipeline: t2v/i2v/fl2v) and `ref2va模型` (reference-to-video pipeline: r2v/v2v/rv2v). Each segment automatically uses the model for its task type at run time — **no manual switching**. When running a single pipeline you may connect only the relevant one (before execution the node validates only that models for tasks actually used in the timeline are connected, raising a named error otherwise). ⚠️ Swapping checkpoints: the in-process model cache auto-reloads by object identity, but the **segment-cache fingerprint no longer detects "a different ckpt within the same pipeline"** (the old `模型标识` widget was removed; cache version is now `h3-6`) — to fully recompute old segments, clear `%TEMP%/h3导演台_段缓存/<current version>` manually.
8. **Continuity tuning** — controlled by the "渐变过渡" toggle on the timeline toolbar, **off by default** (segments independent; seams keep only a 4-frame crossfade overlap); when on, uses 22 context frames. If you see smearing/ghosting, first turn off 渐变过渡 to isolate whether it's a model-side issue.
9. **Interruption semantics** — `写缓存` is atomic, but a segment currently mid-sampling (`_采样段` halfway) is lost and must be recomputed. Completed segments are always preserved.
10. **Run-select semantics** — unchecked segments with cache still join the stitch; unchecked segments without cache are **skipped entirely**, and the next segment does not anchor to "two segments ago" (the timeline has broken, tail context is explicitly cleared). The progress bar still reaches 100% (a skipped segment occupies its own step).
11. **Missing-audio warning** — video stitches everything, audio filters out `None`. If one segment has `audio=None` while others don't, the report appends `警告: 音频段数 < 视频段数` to flag potential A/V drift.

### Requirements

| Item | Version / Notes |
|---|---|
| **ComfyUI** | Any version supporting V3 node API (`comfy_api.latest`) and the official MiniMax H3 nodes |
| **Python** | 3.10+ (following the ComfyUI main environment) |
| **PyTorch** | Provided by ComfyUI (CUDA + torchaudio) |
| **Model weights** | MiniMax H3 checkpoint + Qwen3-VL CLIP (type=minimax) + video VAE + audio VAE |
| **GPU VRAM** | ≥ 12 GB recommended (H3 generation itself; measured at 1.0MP@16s, a 16 GB card only avoids degradation thanks to the two-phase orchestration) |
| **System RAM** | ≥ 32 GB recommended (decode output lands on the CPU during the stitching phase, ≈5 GB per segment at 1.0MP@16s, peak ≈N+1 segments) |
| **Disk** | ≈ 45 MB per cached segment (latent; like-for-like it was ≈ 4.7 GiB when pixels were stored); keep 5 GB+ free for iterative work |

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

- Startup log should contain `[H3导演台] ...` lines (warnings on node/route import failure are non-fatal);
- Search `视频规划师` or `H3DYT_Director` in the node picker;
- The **bottom status bar** should show the Video Planner panel.

### Changelog

**2026-09-15**
- Generation is now **two-phase (deferred decode)**: each segment only runs up to sampling and stores its latent; all segments are decoded together after the models are released. This fixes decode degrading from ≈52s to ≈839s when running high-resolution long segments on a 16GB card.
- Cross-segment anchoring no longer makes a decode→encode round trip — tail tokens are sliced straight off the previous segment's latent, so seams are more faithful.
- The finished film is now built by **streaming each decoded segment into a pre-allocated buffer**, dropping the stitching phase's peak memory from ≈3N to ≈N+1 (≈40GB → ≈20GB for three 1.0MP@16s segments).
- Fixed: the **progress bar could never reach 100%** when some segments were skipped and had no cache.
- Fixed: a blind spot in the backend timing log that made "① reference decode" permanently read 0.00s (the sub-items now add up to the total; ⚠️ the total **excludes** decode time, so old totals are not comparable with new ones).
- Fixed: a wrong token-count conversion that duplicated 4 extra frames at every seam when the context length was set to 1–4.
- The segment cache is now stored **per-version in a subdirectory** (`%TEMP%/h3导演台_段缓存/<version>/`), and old-version directories are **deleted automatically** at startup — this finally fixes the historical problem where upgraded-away caches became permanently unreachable dead files that nobody ever cleaned out of `%TEMP%` (**27.9 GB** had piled up). Future upgrades **no longer require the user to clear the directory by hand**.
- Cache version bumped to `h3-6` (old caches are fully invalidated — the first run recomputes everything once; this is the last upgrade that requires a recompute).
- Fixed: the bottom status bar's **per-segment progress** ("generating 3/7") had never actually been displayed — the panel was only ever receiving the sampler's internal denoising steps (dozens of them flickering by). It now travels over the plugin's own progress channel, so segment progress is genuinely visible; in multi-node workflows only the node currently being edited reports.
- Hardened: if a segment cache file gets corrupted externally (frame count disagreeing with the latent duration), it is now **rejected on the spot and recomputed** instead of blowing up later during decode/stitch — the latter wasted the hours of sampling already done, and every re-run failed at the same point until the directory was cleared by hand.
- Tests went from 196 to **217 passed**; all docs re-synced.

**2026-09-14**
- The node now has two optional model inputs and picks the right one per segment automatically, so no manual switching.
- Before running it only checks that the models actually used by the timeline are connected, naming any missing one.
- The two models keep separate caches, so mixed timelines no longer reload repeatedly.
- Reordered the node inputs so the encoder shows first.
- ⚠️ Old workflows need their model links re-plugged and two hidden toggles re-checked; old caches are invalidated once.
- Tests and docs updated.

**2026-09-13**
- Output size is now truly controlled by megapixels; the default goes from 1376×768 to 864×480.
- Default steps reduced from 25 to 20; status-bar megapixel default from 1.0 to 0.4.
- Added an automatic check that front-end and back-end values stay consistent.
- Updated docs.

**2026-09-12**
- Fixed audio reference loading failures.
- Fixed incorrect task type for new segments.
- Created project README.

**v1 (shipped)**
- Multi-segment video generation, smooth segment transitions, result caching, reference materials, resolution picker, style presets, media upload, timeline editor.
- 162 tests passing.

**v2 (planned)**
- AI planning, prompt enhancement, refine pass, project import/export, cache cleanup.

### Feedback & Contributions

- 🐛 **Bug reports** — please include ComfyUI version, GPU model/VRAM, H3 weight version, full red-panel log, and the timeline JSON (feel free to redact);
- 💡 **Feature requests** — open an Issue; continuity tuning, refine strategy and Director Pack structure are especially welcome topics;
- 🔀 **Pull requests** — please keep `pytest 测试/` at the 217-passed baseline and ruff-clean, and follow project conventions (ValueError-only contract, widgets as single source of truth, Chinese naming with an ASCII whitelist — see `文档/技术实现/00-总览与架构.md`);
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
