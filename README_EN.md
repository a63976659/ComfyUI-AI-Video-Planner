# Video Planner

**Language:** [🇨🇳 简体中文](./README.md) ｜ 🇬🇧 English (current)

A ComfyUI plugin that splits a long video into several short segments, generates them one by one, and stitches them back into a finished video.

All the actual generation work is done by ComfyUI's official MiniMax H3 nodes. This plugin handles the full orchestration: "AI planning → split → run each segment → glue them back together". The AI planning stage (LLM storyboarding and per-segment prompt refinement) runs out-of-process over HTTP and never touches your VRAM.

---

## 📑 Table of Contents

- [What it does](#what-it-does)
- [How to use](#how-to-use)
  - [Step 1: Wire up the node](#step-1-wire-up-the-node)
  - [Step 2: Open the bottom status bar](#step-2-open-the-bottom-status-bar)
  - [Step 3: AI one-click planning (optional)](#step-3-ai-one-click-planning-optional)
  - [Step 4: Edit the timeline](#step-4-edit-the-timeline)
  - [Step 5: Click Queue Prompt to start](#step-5-click-queue-prompt-to-start)
- [Independent upscaling and redrawing (optional)](#independent-upscaling-and-redrawing-optional)
- [Progressive resolution sampling (optional)](#progressive-resolution-sampling-optional)
- [API model setup](#api-model-setup)
- [Skills & Knowledge Base](#skills--knowledge-base)
- [Presets](#presets)
- [Plan data (save and load full setups)](#plan-data-save-and-load-full-setups)
- [What if I cancel or hit an error halfway](#what-if-i-cancel-or-hit-an-error-halfway)
- [Hardware requirements](#hardware-requirements)
- [Installation](#installation)
- [Things to know](#things-to-know)
- [Changelog](#changelog)
- [Feedback](#feedback)
- [Acknowledgments](#acknowledgments)
- [Support the author](#support-the-author)

---

## What it does

- **AI one-click storyboarding**: fill in a brief on the AI Planning tab (topic, total duration, segment count, platform, skill, etc. — 12 fields), and an LLM produces a multi-segment storyboard draft following short-video methodology. No manual per-segment typing required.
- **Per-segment AI prompt refinement**: the storyboard first lands as a "clip timeline" rehearsal draft you can trim/split/delete/reorder and zoom in on for precision, then an LLM rewrites each segment's visual prompt guided by the chosen skill docs. Only when you're happy do you "Fill into node" to commit it to the timeline.
- **Split a long video into segments**: add as many segments as you want on the timeline, each with its own prompt and duration.
- **Pick a generation mode per segment**: text-to-video, image-to-video, first-and-last-frame, reference-to-video, video-to-video, reference-plus-video — six modes in total, and you can mix them across segments.
- **Attach reference materials per segment**: images, videos or audio. Use tags like `<Picture 1>` inside the prompt to point at them.
- **Smooth handoff between segments (optional)**: turn on the "Gradient Transition" toggle and the tail of the previous segment (picture plus about a second of audio) is carried into the next one as continuation conditions; seams no longer blend two clips together — only the continuation's opening gets a light color grade, so seams don't jump. Turn it off and every segment is generated independently with a hard cut at the seam.
- **Generated segments are saved automatically**: each finished segment is written to disk. Next time you run, unchanged segments are re-used instead of regenerated — a full re-run takes only tens of seconds.
- **Segment cache is visible and controllable**: the "Cache" strip on the **node's timeline toolbar** shows segment-cache stats (version/entries/size), offers one-click "Clear Segment Cache", and a "invalidate version +1" to force a full re-sample; replacing a material file or changing an upstream segment now cascades invalidation automatically — no silent reuse of stale results.
- **The node's own timeline zooms too**: the DOM widget on the node carries the same **1–40×** zoom ("Fit" / "Zoom out" / slider / "Zoom in" on the right of its toolbar, with a live factor read-out), plus **wheel-to-zoom** on the track (Ctrl+wheel / pinch is more sensitive), **drag the time ruler to pan**, and a horizontal scrollbar for what falls outside the view — so many segments or a narrow node no longer means dragging the node wider. Still **view-only**: no segment start/end or duration changes, nothing is written to the widget, no re-execution is triggered and the cache signature stays untouched.
- **Only run the segments you check**: every segment has a "Run" toggle. Only checked ones get regenerated. Unchecked segments that were previously generated still get stitched into the final video.
- **Stale write-backs are always rejected**: if you switched nodes, deleted segments, or edited the draft while an async operation (plan loading, material upload, AI planning) was in flight, the result only recognizes its original target — the outdated write-back is refused with a retry hint instead of landing in the wrong place.
- **Pre-flight checks and a budgetable run**: materials, numeric values, per-segment durations, and required official nodes are validated before generation with clear errors; the completion report carries a three-duration line (planned → projected after align/trim → actual playback) and a finished-video memory estimate, with an optional hard cap aborting before decoding — instead of blowing up mid-run or OOM-crashing.

---

## How to use

### Step 1: Wire up the node

Add the node **长视频规划师** (Video Planner; internal node id `长视频规划师`) to your workflow.

It has 5 inputs:

| Input | What it is | Required? |
|---|---|---|
| `fl2va model` | The model used for text/image-to-video tasks | Optional, connect only if you use those tasks |
| `ref2va model` | The model used for reference-to-video tasks | Optional, connect only if you use those tasks |
| `CLIP encoder` | The text encoder. Must be the minimax type (Qwen3-VL) | Required |
| `Video VAE` | Video decoder | Required |
| `Audio VAE` | Audio decoder | Required |

For the two model inputs, connect whichever one your tasks need. If you use both kinds of tasks, connect both.

The first five outputs remain image, audio, frame rate, total frame count, and report; existing save and preview connections stay unchanged. The sixth output, `初采产物` (first-pass artifact), is for the optional Upscale and Redraw node. Leave it disconnected if you do not need a second pass.

### Step 2: Open the bottom status bar

Once the plugin loads, a **Video Planner** panel appears at the **bottom of the ComfyUI page**. Its title bar carries two tabs: **AI Planning** (left, default) and **Prompt Editor** (right) — click a tab to switch pages (clicking the active tab again collapses the panel, once more re-expands it).

The **Prompt Editor** page contains:

- **Generation type** — switch between the 6 task modes
- **Preset** — pick a saved prompt snippet from a dropdown; its body is written into the global prompt automatically (details in [Presets](#presets))
- **Prompt editor** — write the global prompt, which gets prepended to every segment
- **Reference files area** — upload or drop images / videos / audio; dropped files are sorted to the right box by file type (images → image box, and so on), unrecognized types are refused, and a full box (9 images / 3 videos / 3 audio) takes nothing more; duplicates are detected automatically: same name + same content reuses instantly, same name + different content is auto-renamed so they coexist instead of overwriting each other; each type has a fixed three-row material box — when it overflows, scroll inside the box with the wheel; below the all-segments-shared switch sits a "Clear materials" button that wipes this segment's added materials in one click, guarded by a confirmation pop-up dialog against accidental taps
- **Plan data** — save/load the entire node setup with one click (details in [Plan data](#plan-data-save-and-load-full-setups))
- **Timeline** — the main working area

The matching inputs on the node itself are auto-hidden. All the data still lives inside the node; the status bar is only an editor.

The **AI Planning** page offers one-click storyboarding, a clip-timeline rehearsal, and per-segment AI prompt refinement — see [Step 3: AI one-click planning (optional)](#step-3-ai-one-click-planning-optional).

### Step 3: AI one-click planning (optional)

If you don't want to fill segments by hand, follow this flow (first-time users need an API model configured — see [API model setup](#api-model-setup)):

1. **Fill the brief**: Topic (required), Total duration (minutes, default 3), Suggested per-segment duration (default 5-8 s, controls pacing), Segment count (0 = auto), Default task, Hook, Language (the 11 dialogue languages H3 supports stably), Style, Platform, Audience, Skill, Auxiliary — 12 fields in total.
2. **Pick a model, click "Generate plan"**: the backend calls the LLM to produce the storyboard JSON (first segment forced to "Hook", last one must be "Ending/CTA", each segment 5–15 s), saved into a hidden "clip draft" widget on the node. The draft **does not participate in generation** — the node timeline stays untouched. If segments come back short, the backend **automatically attempts one targeted repair** (it never duplicates one segment's footage to fake completeness); if still short, it returns an **incomplete draft** with an on-page orange warning. When a knowledge-base skill is selected, the page honestly reports the **sources that actually entered the request** (truncation / missing counts included).
3. **Polish on the clip timeline**: an editing-room-style track — click empty space to add a segment, drag card edges to trim, "✂ Split" cuts the segment at the playhead, "🗑 Delete" ripple-deletes (remaining segments close the gap), multi-select, drag to reorder. The time ruler above the track is always visible (an empty draft still shows a 0-30 s scale) and auto-adjusts its density to the total duration (seconds up to hours). Each card shows index/range/title/beat/subtitle/keywords inline.
4. **Zoom in for precision (view-only)**: the toolbar's "Fit / Zoom out / slider / Zoom in" magnifies the track up to **1–40×**, with the current factor shown right next to it. You can also **scroll-wheel to zoom** directly on the track (Ctrl+wheel / trackpad pinch is more sensitive), **drag the time ruler to pan**, or use the horizontal scrollbar. Ruler ticks auto-step down as you zoom in (hours → minutes → seconds → 0.1 s), so even a feature-length draft can be aligned segment by segment. Zoom only changes view width: it never touches segment start/end times, never writes the clip draft, the node timeline, or the cache signature — trim / split / playhead scrubbing / multi-select / reordering stay pixel-accurate at any factor.
5. **"✨ AI Generate Prompts"**: the LLM rewrites each segment's full visual prompt based on the brief and skill docs, automatically switching modes by enable state — when **all segments are enabled** it batch-generates as before, covering only *enabled* segments (managed via Enable / Enable all / Disable all on the toolbar); when **only some are enabled**, all segments are uploaded as **read-only context** and the server **rewrites only the enabled segments** (disabled segments keep their original prompts and don't need to be count-matched) — whatever segment goes out is filled back into that same segment. The Skill/Auxiliary/Model used for generation sit in the row above the track. Write-back is mapped by segment identity — if one segment fails it **keeps its original draft and is flagged** (never silently overwriting with the old wording as if it were a new result); failed segments trigger a confirmation.
6. **Per-segment fine editing**: select a card and edit Title / Structure / Subtitle / Prompt in the right column, kept in sync with the matching card blocks ("Structure" is the UI label for the narrative-beat field shown on the card).
7. **"⬆ Fill into node"**: when satisfied, one click writes the **enabled** draft segments into the node's `时间轴数据` (timeline data) field (with an overwrite confirmation; unless everything is enabled, only enabled segments are filled and their times closed up seamlessly, disabled ones stay in the draft — with everything enabled the result is the same as before). From there it behaves like a normal timeline.

> LLM calls go over out-of-process HTTP (same code for cloud and local), **using zero VRAM** and never touching the sampling/execution chain. Planning failures surface as explicit errors — demo content is never fabricated.

### Step 4: Edit the timeline

- **Add a segment**: click on an empty part of the track, or click the "+" button
- **Change duration**: drag the left/right edge of a segment card, or use the time inputs below it
- **Toggle Run**: the switch below each segment card. Only checked segments get regenerated; unchecked ones with a saved copy are reused
- **Edit prompt / attach references**: click into the segment card
- **Playhead**: drag it to see which segment covers a given moment
- **Gradient Transition**: a toggle on the timeline toolbar. When on, segments blend smoothly into each other (tail-context anchoring + a light opening color grade on the continuation, zero-overlap seams); when off, seams are hard-cut

Timeline data is stored as JSON inside the node's `Timeline Data` input. You can copy and paste it, which makes archiving and sharing easy.

### Step 5: Click Queue Prompt to start

Generation runs in two stages:

1. **Sample each segment one by one.** Every finished segment is saved to disk right away (about 45 MB per segment).
2. **After every segment is done, decode and stitch them all together** into the final video.

Splitting it this way frees up the GPU during decoding. Without it, a 16 GB card running long segments at high resolution would be more than ten times slower.

The status bar shows segment-level progress like "Generating 3/7".

---

## Independent upscaling and redrawing (optional)

Connect the planner's sixth output, `初采产物`, to **放大和重绘** (Upscale and Redraw), then connect its results to a save node. You can keep the original first-pass save branch. Wire models, CLIP and VAEs separately into the new node; the artifact carries no models. ⚠️ The node's internal name is still 精修与放大 — that is the name saves and links use — while the interface shows 放大和重绘.

- **Upscaling only by default**: the 重绘开关 (Redraw switch) is off, so no models or CLIP are needed and the redraw widgets stay hidden. Switch it on and 重绘强度 (strength), 重绘步数 (steps), 重绘种子 (seed), 采样器 (sampler) and 调度器 (scheduler) appear below it; strength and steps are both sliders (strength 0.1–1 in 0.1 increments, default 0.20; steps 2–50, default 20); strength no longer reaches 0 — to skip redrawing entirely you leave the switch off, which sends strength 0 to the back-end. Redrawing revisits every segment at its original size first and upscales afterwards; the first-pass full IMAGE is never re-encoded and there is no third sampling pass after upscaling.
- **Three upscaling modes, and only the matching weight list is shown**: 放大方式 is ordered H3潜空间 (H3 latent), 像素模型 (pixel model), Lanczos, and **defaults to H3潜空间**. H3 latent shows only the H3放大权重 dropdown, pixel model shows only 像素放大模型, and Lanczos hides both because it needs no model. Scale is a slider too, 1–4 in 0.25 increments (the leftmost notch, 1.0, means no upscaling and asks for no upscale weight), with target dimensions aligned to 32, and the report shows the actual dimensions. H3 mode needs compatible weights you supply yourself — take a `.safetensors` from <https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler> into `ComfyUI/models/latent_upscale_models/` (the same file the Progressive resolution sampling section below uses); nothing is downloaded automatically, and the dropdown lists only the H3 24-channel 3D `.safetensors` files this plugin can actually load, so other upscalers in that folder stay hidden. Pixel weights are picked on the node now too: the dropdown lists the `.pth/.ckpt/.safetensors` files in `ComfyUI/models/upscale_models/`, the same folder and the same models as the official Load Upscale Model node, so you no longer have to wire an extra loader node.
- **Keep sound and timing**: reuse the final first-pass audio, frame rate and frame count without audio re-decoding or speed changes; source segments and references remain unchanged. The new node has separate overall progress without replacing first-pass segment progress.
- **Separate caches**: the redraw and upscale caches are independent of the first-pass cache. The original Clear Segment Cache button does not clear them. Increase the new node's 缓存失效版本 (cache invalidation version) after replacing weights.

### Default: direct in-memory connection

`长视频规划师 → 放大和重绘 → Save`

Without a handoff node, the artifact stays in memory within one host task. No handoff files, split tasks or global deep-cleanup request are added. The host may still retain the complete first-pass IMAGE.

### Optional: insert 初采交接与清理

`长视频规划师 → 初采交接与清理 → 放大和重绘 → Save`

Only a handoff node in an effective output dependency chain enables the three phases: **A first pass, saving and per-segment disk handoff → C global-cleanup request → B gated, per-segment second pass and saving**. No manual reader node is needed; a disconnected handoff node does not enable the split. Queueing no longer asks for a second confirmation — you wired the node in yourself.

- Use a dedicated idle queue. Do not submit from other tabs or APIs concurrently. Cleanup affects host models and in-memory execution caches, not saved videos, handoff files or disk caches.
- Failure anywhere in A prevents C/B. `C_REQUESTED` means requested, not completed. Second-pass loaders and the business graph are expanded only after B's gate passes.
- The handoff node has no status display and no buttons; A→C→B runs on its own without further clicks. To stop, use the host queue panel's Stop — first-pass segments already on disk are not lost, just submit again. If phase A never starts, the host queue is blocked by other jobs or paused: clear the queue and submit again. When the previous handoff has already ended (failed, stopped, paused or succeeded), queueing the same graph again shows "the previous handoff has ended" instead of silently looking accepted. Reloading the page does not resume anything or pick up the latest artifact automatically.
- Only one explicit handoff chain is supported. Batch submissions, partial execution, cross-phase connections and unknown shared side-effect nodes are refused. Ordinary `/prompt` calls do not split automatically; API clients must use the handoff endpoints.

**Validation boundary:** CPU contracts, isolated host-executor integration and frontend runtime tests exist. Real browser interaction, GPU quality/peak memory, actual global unloading and real save-plugin combinations remain unverified. Streaming segments does not eliminate the final full IMAGE memory requirement; estimates exclude some model/activation costs and cannot guarantee freedom from OOM.

---

## Progressive resolution sampling (optional)

Each segment runs its first few denoising steps on a reduced canvas, the latent is lifted to the target resolution, and the remaining steps run at full size. **Total denoising steps stay the same** — what shrinks is the cost of those early steps. Leave it disconnected and everything behaves exactly as before.

**Wiring**: add the **SelfLift加速** (Progressive Sampling) node and connect its `SelfLift配置` output to the `SelfLift配置` input at the bottom of the main node. Disconnected = single-stage sampling, segment cache untouched.

- **低清缩放** (downscale ratio, 0.25–0.95, default 0.5): the low-resolution canvas = target canvas × this value, aligned to a multiple of 32. At 0.5 the early steps carry roughly a quarter of the video tokens.
- **高清步数** (full-res steps, default 6): how many steps run at the target resolution; the low-res steps = the main node's 步数 (steps) minus this value. Both stages need at least one step.
- **The sampler must be `euler`**: any other choice fails before sampling starts and names the offending parameter instead of quietly falling back to normal sampling.
- **Lift quality comes from the 放大模型 (Upscale model) picker**: download from <https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler> (by LBH-123-AI, Apache-2.0 — take `fp16.safetensors` or `bf16.safetensors` under `minimax_h3_latent_upscaler_3d_conv_v1/`, about 691 MB each) and put the file into `ComfyUI/models/latent_upscale_models/`; the plugin never downloads it. ⚠️ The dropdown only lists the H3 24-channel 3D `.safetensors` files the loader actually accepts — other upscalers (and any `.pth`) in that folder stay hidden.
- **Without a model you must tick 允许插值降级** (allow interpolation fallback) to lift by bilinear interpolation instead. In the reference author's own same-seed comparison this route shows **visible artifacts**, not merely a softer picture — use it to check framing and motion, not as a finished shot.
- **Duration, frame count and audio are unaffected**: frames come from the timeline span and the 24 fps base, never from resolution; the lift only changes the spatial size.
- **Cache behaviour**: installing this version does not invalidate your existing segment caches. But once connected, changing any of 低清缩放 / 高清步数 / 放大模型 re-runs every segment — those values are part of each segment's cache fingerprint.
- **Invalid parameters fail up front**: steps below 2, 高清步数 out of range, the ratio outside its interval, a ratio that rounds down to no actual reduction, or neither a model nor the fallback ticked — each error names the parameter, nothing silently reverts.

**Is it worth it**: set the `H3_计时=1` environment variable and run the same material with the same seed twice — once disconnected (full-res `euler`), once connected — then compare the 合计 (total) in the `段N 采样计时` log lines; a connected run also prints a `段N 渐进采样细分` line splitting low-res sampling, the lift and full-res sampling. ⚠️ Speed-up factor, lifted-image quality and peak VRAM still have no GPU measurements.

---

## API Model Setup

AI planning needs an OpenAI-compatible LLM (same code path for cloud and local; inference happens out-of-process and uses zero VRAM).

Configure it under **ComfyUI Settings → 🎬 长视频规划师 → API 模型配置 (API model setup)**:

- **Preset model**: Kimi-K3 is built in (first row, default) — just fill in its API Key and go.
- **Custom models**: add as many rows as you like (Name / Base URL / Model / API Key); a radio button picks the active one. Cloud = any OpenAI-compatible endpoint (Moonshot, DeepSeek, …); local = Ollama / LM Studio with `/v1` compatibility enabled.
- **Per-model API keys**: every model stores its own key. On save, an empty input or one containing `****` means "keep that model's existing key". Key reuse is bound to the normalized endpoint (scheme + host + port + effective path): changing the address counts as a new endpoint and requires a fresh key — old credentials are never sent to a new URL, and requests never follow redirects while carrying the key.
- **Test connectivity**: a button next to each row's key input sends one minimal request to verify name/base URL/key, showing ✓/✗ inline — no need to save first.
- **Global request timeout**: clamped to 120–3600 s, default 120. Thinking models (Kimi-K3, etc.) plus long skill-doc injection often need 300–600.

- The config lives in `规划/规划器配置.json` (gitignored — plaintext keys never get committed).

---

## Skills & Knowledge Base

AI planning can "write prompts according to a skill doc". There are two independent sources, and they do **not** share a folder:

### `Skills/` (the AI Planning brief's "Skill" and "Auxiliary")

The brief's "Skill" and "Auxiliary" fields list the **first-level sub-folders** of the plugin-root `Skills/` directory — folder name = option name:

```text
Skills/
└── my-skill/
    ├── SKILL.md            # or 技能说明.md — the main doc, loaded first
    └── ...                 # remaining .md/.txt files, appended in sorted order (sub-folders OK)
```

- Default is "不指定 (none)" for Skill and "无 (none)" for Auxiliary = no skill docs injected, generic storyboarding. If `Skills/` is missing or empty, Skill only offers "none" and Auxiliary only offers "无".
- Both dropdowns re-scan `Skills/` every time you open them (skills added/removed on disk show up immediately) while keeping your current selection.
- The selected docs are injected into the prompt (60k-character budget, tail-truncated with a marker when over). Load failures degrade gracefully to "none" with a logged warning — planning never fails because of them.

### `MiniMax-H3知识库/` (only the clip timeline generation row's Skill/Auxiliary)

Ships with the plugin: 9 style skills (通用H3提示词写作 / 3D动画短片 / 极简产品广告 / 纸艺定格科普 / 品牌宣传 / MV歌词字幕 / 双人游戏开场 / 纸质拼贴讲解 / 手绘实拍融合) plus reference docs. The generation row's "Skill" defaults to 通用H3提示词写作. This folder is third-party material — **do not rename, translate or reorder it** (a mismatched name degrades silently; the only symptom is "the skill had no style effect").

---

## Presets

Above the prompt editor, in the toolbar row, you'll find a **Preset** dropdown for quickly inserting commonly used prompt snippets. Whatever you pick is written back to the node's `Global Prompt` field (which is hidden on the node itself). At execution time the backend prepends the global prompt to **every segment's prompt**, so anything you put here applies to all segments.

### Save your own prompt snippets as .txt files

Drop a `.txt` file into `<plugin-root>/预设/` and it automatically shows up in the "Preset" dropdown.

- **Scan scope**: `.txt` files directly under `预设/`, plus `.txt` files **one sub-folder level** deep (deeper levels are ignored).
- **Display name**: root-level files show the filename (minus the `.txt` suffix); sub-folder files show `subfolder/filename`.
- **Encoding support**: tries `utf-8-sig` → `gbk` → `utf-8 replace` fallback in order. Windows Notepad ANSI(GBK) files also read correctly.
- **Triggering a rescan**: after adding or editing a `.txt`, click the status bar title to collapse and re-expand — the rescan fires automatically on expand.

### Three examples shipped with the project

| Path | Shown in the dropdown | Purpose |
|---|---|---|
| `预设/nanobanana分镜.txt` | `nanobanana分镜` | Storyboard prompt template |
| `预设/视频提示词预设/动态图.txt` | `视频提示词预设/动态图` | Prompts that "bring a still image to life" |
| `预设/视频提示词预设/电影风格.txt` | `视频提示词预设/电影风格` | Cinematic-look prompt |

### Refill behavior

When a node is loaded from a workflow file, the frontend reverse-parses the global prompt: if the entire text matches a preset, that preset gets selected; anything that doesn't match is kept as a "residual" chunk verbatim, so nothing gets silently lost.

---

## Plan data (save and load full setups)

At the **far right** of the same toolbar row above the prompt editor, you'll find the "Plan data" dropdown (Load) + "Save" button. Use it to snapshot the current node's entire setup into a JSON file and reload it later with one click.

### What gets saved

A plan contains:

- All regular widgets: task type, output resolution, megapixels, frame rate, steps, sampler, scheduler (the "缓存失效版本 / cache-invalidate version" is a runtime invalidation lever and is **not** saved into plans).
- All hidden widgets: global prompt (the preset body written into it), reference sharing, tail-frame anchoring, run selection.
- The full timeline JSON (each segment's task/prompt/start/end/run/refs).
- The reference material list (image/audio/video filenames).
- The clip draft (the AI Planning page's rehearsal draft, brief form content included, saved and restored with the plan; if a plan carries no draft, the node's unrelated old draft is cleared on load).

Storage location: `<plugin-root>/计划数据/<name>.json`. The backend creates the folder on demand; you don't need to make it yourself.

### How to save

1. Click the "Save" button.
2. Type a plan name (no `.json` extension).
3. If the name already exists, you'll be asked to confirm overwrite. The original `创建时间` (creation time) field is preserved on overwrite.

### How to load

1. Pick an entry from the "(Load)" dropdown.
2. If the current node already has timeline data (segment count > 0), you'll be asked to confirm overwrite.
3. After loading, every UI element auto-syncs (timeline rebuilt, prompt refilled, reference material list refreshed).
4. The dropdown resets to the "(Load)" placeholder after loading, so picking the same entry again still triggers a fresh load.

### Naming rules

Plan names are validated **on both sides** (frontend pre-validates for instant feedback; backend re-validates as the final gate):

- Cannot be empty or whitespace-only.
- Cannot contain `\ / : * ? " < > |` or control characters (including newlines and tabs).
- Cannot start or end with a dot or space (Windows silently strips them).
- Cannot be `.` / `..` / a Windows reserved name (CON/PRN/AUX/NUL/COM1-9/LPT1-9).
- Length ≤ 100 characters.

### Missing reference materials

On load, the backend cross-checks against the media pool (`ComfyUI/input/`):

- Any image/video/audio file referenced by the plan that has since been deleted is **kept in place, not dropped** — it is only registered as a "missing material" (a ref's position *is* its `<Picture N>` tag; silently filtering one would shift the remaining materials and mis-point their tags).
- The frontend toasts "Skipped N missing reference materials: xxx, yyy"; loading is **not** aborted.
- The actual blocking happens before sampling: the pre-flight check names and stops any runnable segment that references a missing material; other segments are unaffected.

This way, even if a plan points at materials that no longer exist, you get the diagnosis immediately instead of blowing up mid-run after Queue Prompt.

### Typical uses

- Save a common setup (e.g. "9:16 vertical + 20 steps + cinematic style + a specific storyboard template") as a plan and reuse it with one click.
- Share a complete generation recipe with teammates (paired with the `.txt` templates under `预设/`).
- Archive important timelines — more complete than copying the node JSON directly, because a plan also captures every hidden widget.

---

## What if I cancel or hit an error halfway

Segments that already finished **are not lost**. They're already on disk.

The segment that was halfway through **is lost** and has to be redone.

If you just want to output the segments that already finished:

1. Open the timeline panel.
2. Turn **off** the Run switch for every segment that didn't finish, plus every segment that hasn't started yet.
3. Leave the Run switch **on** only for the segments that already finished. (Actually, you can turn those off too — as long as a segment has a saved copy it will still be stitched in.)
4. Click Queue Prompt again.

This run will hit the cache for every segment. Tens of seconds later you get your video. The console report will say "Segment N: cache hit" for each reused segment.

---

## Hardware requirements

| Item | Recommended |
|---|---|
| GPU | 12 GB VRAM minimum, 16 GB preferred |
| RAM | 32 GB minimum (the stitching stage uses system memory) |
| Disk | 5 GB+ free for the cache |
| ComfyUI | A version that supports the V3 node API and ships the official MiniMax H3 nodes |
| Models | MiniMax H3 main model + Qwen3-VL encoder + video VAE + audio VAE |

---

## Installation

**Option A: git clone (recommended)**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/a63976659/ComfyUI-AI-Video-Planner
```

> Folder name is not fixed: ComfyUI scans every subdirectory under `custom_nodes/`. The default (repo name) is recommended; you can also rename it to whatever you like.

**Option B: manual drop-in**

Download the zip, unzip it, and put the whole folder at `ComfyUI/custom_nodes/ComfyUI-AI-Video-Planner/` (folder name is up to you). Restart ComfyUI.

**Optional dependencies** (uncomment them in `requirements.txt`, then run `pip install -r requirements.txt`):

- `imageio` + `imageio-ffmpeg` — for reading reference videos (needed by r2v / v2v / rv2v)
- `scenedetect` + `opencv-python-headless` — for auto-splitting a source video (needed by smart shot detection)
- `pytest` — for running the unit tests

**Check that it worked:**

- ComfyUI's startup log contains lines starting with `[长视频规划师]`
- Searching `长视频规划师` in the node picker finds the main node
- The bottom of the ComfyUI page shows the Video Planner panel

---

## Things to know

**Where the cache lives**

By default it's in `%TEMP%/长视频规划师_段缓存/`. To move it, set the environment variable `长视频规划师_段缓存_DIR`.

Old cache folders from previous versions are cleaned up automatically when the plugin starts. No manual cleanup needed.

**How the resolution is decided**

Two widgets together decide it: `Output Resolution` (aspect ratio) and `Megapixels` (how detailed). The default `0.4 megapixels + 16:9` produces **864×480**.

Bigger megapixel values need more VRAM. `4.0 + 21:9` reaches 3136×1344 — know your limits.

**What the frame rate widget does**

The `Frame Rate` input on the node is just a tag written into the output video file. The actual generation always runs at **24 frames per second** (fixed by the official model). Want slow-motion or fast-motion? Change the frame rate number. Want to change the real motion speed? Change the segment's duration. Changing it also **no longer touches the segment cache** (since h3-7 the playback fps is not part of the cache fingerprint).

**How segments join together**

Controlled by the "Gradient Transition" toggle (off by default):

- **Off** (default): each segment is generated independently. Seams are hard-cut with no transition processing.
- **On**: the last 22 frames of picture and roughly the last second of audio from the previous segment are fed into the next one as continuation conditions (latents are passed directly, with no decode→re-encode round trip), so the next segment picks up right where the previous one ended. Seams are zero-overlap hard cuts — only the opening of the continuation segment gets a light low-frequency color grade (its tone/brightness eased toward the previous segment's tail; the two clips are never blended together).

If you see smearing, ghosting, or artifacts, first turn Gradient Transition off to check whether it's the model itself.

⚠️ **Flipping this toggle invalidates every segment's cache and forces a full re-sample** (the context frame count is part of each segment's cache fingerprint, so the fingerprint changes as soon as the toggle changes). Segments that were already generated will be redone too — this is **not** just a re-stitch of the seams. Budget enough time for a full run before switching.

**After swapping the checkpoint**

To regenerate every segment with the new model you no longer need to delete cache folders by hand: bump the node's "Cache Invalidate Version" widget (or use the Cache strip on the node's timeline toolbar — "+1", or type a number and press Enter) and all old segments are invalidated for re-sampling. The strip's "Clear Segment Cache" button deletes the on-disk cache artifacts directly (irreversible; local machine only; never touches other files).

**Can I connect only one model input?**

Yes. The plugin only checks whether the models required by **the tasks actually used in your current timeline** are connected. If something is missing, the error message names the exact task and the exact model. Everything else is left alone.

**Missing audio is padded with silence**

If one segment has no audio while others do (say you plugged in the audio VAE halfway through), the audio track no longer "skips the missing segment" — instead it pads that segment with an equal-length stretch of silence, so the audio total stays strictly aligned to the video frame timeline and never drifts out of sync. The report gets an informational line: "N/M segments have no audio; padded with equal-length silence to keep A/V aligned". If no segment has audio at all, the output is a silent video.

**The memory ceiling for long videos**

The node outputs the finished video as one whole IMAGE tensor, so the entire film must live in RAM during stitching (a hard boundary set by the node interface). For reference: 180 s at 768×1344 in float32 is roughly 50 GiB. The "32 GB RAM minimum" advice therefore only covers short pieces. The pre-run "memory budget" report line estimates your specific scale up front, and `H3_内存硬限额_GiB` can abort before decoding when over the cap — instead of waiting for an OOM.

**Diagnostic timing (off by default)**

Set the environment variable `H3_计时=1` and the log breaks each segment down into the four sampling steps (reference decode / conditioning / inter-segment continuity / sampler), plus cache read-write IO, decode & stitch durations, and memory peaks — for pinpointing "what's slow". Off by default; purely observational, never changing outputs or behavior.

---

## Changelog

**2026-09-28**

- The clip timeline gained a 禁用字幕 (disable subtitles) checkbox, sitting to the left of 台词估时: once it's ticked, "✨ AI generate prompts" no longer uploads your subtitles and the AI no longer puts on-screen text into the shots — the subtitle text itself is still there for estimating line duration.
- Same-day follow-up: when the checkbox has never been ticked, editing on the planning page and 生成规划 no longer write a stray 禁用字幕: false into the draft. Two more tests now pin that the switch survives 台词估时 re-timing and plan save/load round-trips.
- Second same-day review: while the timeline has no segments at all, the 禁用字幕 checkbox is greyed out just like 台词估时, so a draft that holds nothing but the switch can no longer be filed as an empty plan and silently dropped on load.

**2026-09-27**

- Queuing the same graph after a handoff has already ended now tells you to submit again instead of looking accepted.
- The handoff node now says plainly that a late start usually means the queue is busy or paused — clear it and queue again.
- Fixed "Queue does nothing after adding the handoff node": extra options on video-saving nodes and pure display nodes at the end of the chain are no longer treated as unsupported.
- A rejected handoff now names the node and the rule it broke instead of one vague sentence.
- Queueing no longer asks you to confirm the handoff: you wired the node in yourself, so an accepted graph starts straight away. (⚠️ Entries below from 2026-09-26／25 that mention this confirmation dialog are voided by this change.)
- Fixed "the node has an input the host doesn't know" after adding the handoff node: the on-node Edit button and the embedded timeline are no longer submitted as parameters, and existing workflows still open.
- The 比例模式 dropdown on the prompt page is no longer mistaken by the self-tests for a fourth frame selector; the look is unchanged and two long-standing failures pass again (482 front-end checks, all green).
- A Show Text node at the end of the handoff chain no longer blocks Queue, while a missing input on a node inside the chain is still named. (front-end 482→484, back-end 2512→2514, all green)
- 精修与放大 is now shown as 放大和重绘 (Upscale and Redraw) with every 精修 label renamed 重绘, old saves still recognised, a new 重绘开关 that defaults to off, sliders for strength and steps, the controls regrouped, and the pixel model picked right on the node. (⚠️ Control order changed — re-check the parameters in old workflows; back-end 2514→2536, front-end 484→495, all green)
- Four follow-ups from re-reviewing that node: pasted nodes show the right controls, an unreadable model folder only leaves 未选择 instead of breaking the whole node, the error names the dropdown you can see, and the scale floor was raised to 1.1 at the time (⚠️ that floor moved twice more the same day — trust the newest entry; back-end 2536→2540, front-end 495→497, all green)
- Four more changes to the same node: the scale became a slider too, one drag of the strength slider is now a visible step, steps narrowed to 2–50, and the node keeps its width when you switch modes or reload (new nodes open twice as wide). (⚠️ Old workflows saved with 1 step are rejected — set it to 2 or more; back-end unchanged at 2540, front-end 497→499, all green)
- The scale slider's step went back to 0.25, because one notch of the 0.1 step was stored a hair too low and ended up upscaling one grid less. (back-end 2540 and front-end 499 unchanged, all green) ⚠️ The floor moved again the same day — see the next entry.
- The scale floor was briefly raised to 1.25, since 1.0 means no upscaling and has no business on an upscaling node. (⚠️ Superseded by the next entry; back-end 2540 and front-end 499 unchanged, all green)
- The scale floor went back to 1.0 as you ruled: all the way left means no upscaling, that notch needs no upscale weight, and old saves at 1.0 / 1.1 / 1.25 queue again. (back-end 2540 and front-end 499 unchanged, all green)
- The lowest redraw strength is now 0.1 instead of 0, so "no redraw at all" has a single switch. (⚠️ An old save below 0.1 is rejected even with the switch off — move it into 0.1–1 and the no-redraw result is unchanged; back-end 2540 and front-end 499 unchanged, all green)
- On the prompt page the image-to-video aspect-mode dropdown now sits next to the first-frame control; nothing else moved. (front-end unchanged at 499, all green)
- A rejected handoff now leaves the real reason in the running log and in the job status instead of one unrecognisable error; the common mistake is the audio line — when 放大和重绘 feeds the generator directly, take audio from its own output. (⚠️ The on-screen message itself did not change, so the log is still where you read it; back-end 2540→2545 all green, front-end unchanged at 499)

**2026-09-26**

- Cancelling the handoff confirmation no longer raises an error, and nothing gets queued.
- The "Overall progress" readout is display-only now and is no longer saved into workflow files.
- A cleanup failure now stops the job in a clear terminal state instead of silently stalling; just submit again.
- Half-step scales such as 1.25x no longer leave a dimension unchanged; results always round up to the 32-pixel grid.
- A leftover temporary cache file can no longer mask the real error, so failures report their original cause.
- Batch queueing, per-phase timeouts and path checks were tightened; false permission-boundary rejections and reused queue numbers are fixed.
- Editing the canvas immediately after confirming a handoff no longer loses the task — it keeps running.
- A broken cache file is now named in the error message, together with a note that the "Clear segment cache" button does not cover that folder.
- If a handoff write fails halfway, the partial output directory is only reported; nothing is deleted automatically.
- A 500 from the handoff API now leaves the full traceback in the server log for diagnosis.
- Reloading this plugin without restarting ComfyUI no longer registers the same nodes twice.
- Added the optional **SelfLift加速** (Progressive Sampling) node: when connected, each segment denoises a few steps on a low-resolution canvas, lifts to the target size, then runs the remaining steps — total steps stay the same. Without the connection nothing changes.
- Enabling it requires the planner's `采样器` (Sampler) to be `euler`; invalid settings fail before sampling and name the offending parameter instead of quietly falling back.
- Lifting quality depends on the **放大模型** (Upscale model) picker — the download link and target folder are now in both the Independent refinement and Progressive resolution sampling sections above (⚠️ since 2026-09-27 the former is titled "Independent upscaling and redrawing"); with no model selected you must tick 允许插值降级, and that route gives visible artifacts rather than just softer detail.
- The 放大模型 dropdown now lists only the H3 latent upscalers this plugin can actually load; other safetensors in the same folder are hidden instead of failing at sampling time.
- Existing segment caches are not invalidated by this change; the actual time saved has not been measured on GPU yet.
- "⬆ Fill Nodes" on the status-bar AI planning page now fills by enabled segments: unless all segments are enabled, only the enabled ones are written into the node timeline with their times closed up seamlessly, while disabled segments stay untouched in the draft; with everything enabled the result is identical to before, and with everything disabled it prompts and writes nothing.
- This change adds 3 targeted tests; the frontend async-writeback isolation suite passes 292/292 (up from 289).
- Image-to-video now has a **比例模式 (Aspect mode)** dropdown (shown only for the i2v task): choose **Generate at the image's original aspect** or **Crop to the set aspect**, instead of always stretching the first frame to the output resolution.
- With **原图 (Original)**, the segment's canvas follows the first frame's aspect ratio; the global **输出分辨率 (Output resolution)** no longer applies to that segment, while the absolute size stays bounded by the **百万像素 (Megapixels)** budget.
- With **裁剪 (Crop)**, the first frame is center-cropped to the largest region matching the set resolution's aspect before use as input.
- This applies only to pure i2v; first/last-frame (fl2v) keeps the original full-frame stretch so mismatched frame aspects never cause misalignment.
- ⚠️ Cache format bumped — all previously generated segments are invalidated; the first run must regenerate everything, so allow extra time.
- The tooltips of **初采交接与清理** (First-pass Handoff and Cleanup) and **精修与放大** (Refine and Upscale) were rewritten into four line-broken sections: what the node does, how to wire and run it, every parameter with its default and when it is needed, then the caveats. Node behaviour, parameters and sockets are unchanged.
- Running **初采交接与清理** (First-pass Handoff and Cleanup) through an ordinary queue now fails with a plain message pointing at the handoff confirmation shown when queueing, instead of naming an entry point that does not exist in the UI.
- The **H3放大权重** dropdown on 精修与放大 (Refine and Upscale) now uses that same filtered list, so only upscalers this plugin can load appear there — no more picking an entry that fails once sampling starts.
- If a model saved in an older workflow has since been deleted or moved, the message now names the loadable list and says what to change, instead of a bare English value-not-in-list error.
- Removed the three widgets on **初采交接与清理** (First-pass Handoff and Cleanup) — status, Cancel Handoff and Retry Second Pass Only — so the node is back to connections only.
- They were over-designed: to run just one segment, set the run range on 长视频规划师 (Video Planner) instead; to stop, press the host panel's Stop. Segments already written to disk survive, so re-submitting picks up where you were.
- The automatic A save → C global cleanup → B second-pass chain and the confirmation dialog before queueing are unchanged; nothing extra to click.
- The backend cancel and retry endpoints were removed along with them; the status endpoint stays as an internal diagnostic only, and no status is shown in the UI.

**2026-09-25**

- Added Refine and Upscale to refine first-pass segments before upscaling, keeping existing first-pass connections and audio unchanged.
- Optionally insert First-pass Handoff and Cleanup to save artifacts, clean across tasks and run the second pass after confirmation; without it, the direct in-memory path stays unchanged.
- The handoff node shows status and offers cancel or second-pass-only retry; reloading does not restore control automatically, and retries may save duplicates.
- ⚠️ Corrected 2026-09-26: those three widgets and the cancel/retry endpoints were removed; stopping is done with the host's Stop button.
- Automated and isolated host tests exist; real browser interaction, GPU output and global-cleanup behavior still need validation.

**2026-09-24**

- With "Gradient Transition" enabled, the next segment inherits the previous ending's picture and sound and adjusts its opening colors; the actual transition still needs sample-video validation.
- Each seam no longer loses an extra 4 frames, but frame-grid alignment and trimming repeated context can still change the total duration.
- Audio is padded with silence or trimmed to the actual video frame count, including single-segment output.
- Continuation checks report the condition-compatibility issues they cover, but do not replace testing actual generation.
- ⚠️ The cache format was upgraded: all previously generated segments are invalid and the first run must be done from scratch, so allow extra time.
- Image quality and speed have not been verified on real hardware yet; feedback welcome.
- The "Subtitle" box in the AI planning page's right column is shorter now, handing the freed space to the prompt box below.
- The bottom panel follows the window height within 225–260px, and clip cards show more prompt text when space allows.
- The button bars above the timeline and prompt editor stay on one row and slide sideways when the window is narrow, instead of stacking into rows.
- The AI planning form now leaves enough room for long messages and dropdowns without making the text smaller.
- Info messages stay on one line with full text on hover; "Generate plan" first clears old messages and their tooltips.
- The 260px height cap reduces empty space in tall windows, but does not promise to remove all of it.
- Fixed the clip timeline looking blank before any plan is generated; its ruler is always shown now, so the timeline is always there.
- The first/last/middle-frame dropdowns on the prompt editor got slimmer, so the left and right columns are now about the same width.
- The three material boxes on the prompt editor now center their content; the scrollbar no longer takes up space inside the box, and the wheel still scrolls when there are many items.
- Dropped materials now sort themselves by file type: an image goes to the image box no matter which area you drop it on, likewise video and audio; unrecognized file types are refused, and a box that's already full takes nothing more.
- A new "Clear materials" button below the all-segments-shared switch wipes this segment's materials in one click, but only after you confirm it in a pop-up dialog, so an accidental tap can't delete anything.
- Fixed the reference-material list popping up from the "@" button sometimes flashing and vanishing before its options appear; it now opens reliably whether you click fast or slow.
- The "@" reference-material list can now be dismissed three ways: click "@" again, click anywhere else on the page, or pick an item — no more being forced to select one.
- "All-segments shared" and "Clear materials" now stack in two rows instead of crowding one row, saving horizontal space in the material area.
- Rearranged the AI Planning tab's left column: Topic on its own row, then Total duration + Per-segment, Segment count on a full-width row (input widened so the number is no longer clipped), Task + Hook, Language + Style, Platform + Audience, Skill + Auxiliary, and finally Model + Generate plan.
- Fixed stale clear confirmations removing materials after node reloads, late uploads bringing cleared materials back, and holding "@" on the second click leaving its list open.
- Fixed cache information being squeezed out of narrow timelines, and sliding the button bar sideways now closes the "@" list.
- Fixed labels in the AI planning form, while the Segment count input still spans the full row.
- Hidden middle frames no longer interfere with splitting or caching for other tasks, while replacing a referenced file under the same name still triggers a cache check.
- Switching between mixed-task segments now shows frame controls for the selected segment, and valid near-endpoint middle-frame positions no longer display as 0% or 100%.
- Loading a plan also reports missing materials referenced only by its clip draft, without changing references or their order.
- This middle-frame review adds 23 frontend and 39 backend regression tests; all 412/1135 tests and 41 isolated-browser checks pass, while real image previews and GPU output remain unverified (feature baseline §3.15; earlier batch counts are retained below).
- Test baseline: frontend `node --experimental-vm-modules --test 测试/*.test.mjs` adds **7** tests, **382→389 passed / 0 failed**; `pytest 测试/` **1067 passed / 2 existing warnings**; `ruff check .` passed.

**2026-09-23**

- Fixed old materials still showing after "Fill into node", and them reappearing when switching task types or rebinding the node.

**2026-09-21**

- The node timeline gained zoom: scroll the wheel to zoom, drag the ruler to pan — view only, nothing is changed.
- The "Beat" field label on the AI planning page was renamed to "Structure"; the content is unchanged.
- Card thumbnails now follow material changes correctly and instantly; several cases of missing images were fixed.
- Test baseline: front-end `node --test 测试/*.test.mjs` 203 → **260 passing**, `pytest 测试/` 615 → **616 passing**, ruff clean.

**2026-09-20**

- The clip timeline gained zoom, up to 40x for precise segment-by-segment alignment; it only changes the view, never segment lengths.
- Fixed several defects found reviewing the zoom: the view jumping back, buttons vanishing mid-run, and so on.
- The cache strip moved from the bottom status bar into the node's timeline toolbar.
- The whole page was tightened to fit more on screen and buttons were unified; colors follow the theme, so light themes no longer leave dark blocks.
- "Auxiliary" and "Skill" on the AI planning page now share one source; the clip timeline keeps its own, and the two stay independent.
- Test baseline: front-end `node --test 测试/*.test.mjs` 164 → **203 passing**, `pytest 测试/` **615 passing**, ruff clean.

**2026-09-19**

- ⚠️ Segment cache rules were greatly tightened: a replaced material or a changed earlier segment is now detected and recalculated automatically; every previously generated segment is invalidated and the first run must be redone from scratch.
- A cache toolbar was added to the status bar for viewing cache stats, clearing with one click, and bumping the invalidate version.
- Uploaded files with the same name but different content no longer overwrite each other — they are renamed and kept side by side; same name plus same content is still stored once.
- Files and parameters are now checked before generating, so problems are reported clearly up front instead of blowing up mid-run.
- The completion report lists planned, expected, and actual durations; when memory is not enough it stops early with a clear reason instead of crashing.
- When a segment's prompt fails, the exact segment is flagged and keeps its original wording instead of being mixed into a batch-level message.
- The clip timeline gained "Retry selected segments", rewriting only the picked segments and leaving the rest alone.
- Short segment counts are no longer padded by secretly duplicating the last segment; the real segments are returned with a clear reminder.
- Source reporting became honest: only material that actually entered the request is listed.
- Backend requests were tidied up: errors are classified and reported clearly, and an overloaded server now answers "busy" right away.
- A segment with no audio now gets silence filled in, so audio and video totals match strictly.
- When the output frame rate is not 24, the report now states plainly that the video is made at 24 fps and stretched at playback; durations are never silently changed.
- The AI planning page remembers what you typed per node, so switching nodes no longer loses unsaved entries.
- In narrow panels the form takes the full row and the right column collapses instead of overflowing.
- Leftover callbacks are cleaned up when nodes are removed or refreshed, so the page no longer gets slower over time.

**2026-09-18**

- The AI planning page's "Skill" moved to its own folder, no longer shared with the clip timeline.
- Clip timeline rework: the track is always visible, details sit right on the cards, the two timelines select independently, and the ruler auto-scales with total duration.
- The toolbar gained Enable / Enable all / Disable all; prompt generation now only covers enabled segments.
- "Role" was renamed to "Beat" everywhere, and the right column gained a "Prompt" box.
- The clip draft now lives in node properties, so editing it no longer forces the node to re-run, and it still saves with the workflow.
- Fixed a batch of AI planning page display and refresh problems: no more wrong-node overwrites, new prompts fill in right away, and the skill list keeps your selection.
- Cleaned the bundled plan samples, which used to fail with "unknown task type".

**2026-09-17**

- The status bar split into "AI Planning" and "Prompt Editor" pages; the planning form grew to 13 fields.
- Added skill style injection: the storyboard is written in the chosen skill's style, falling back to a generic write-up if it can't be loaded.
- Several rounds of polish on the API model settings page: one unified model list, per-model keys, and a "Test connectivity" button.
- Added the clip timeline draft editor: trim, split, delete, reorder, per-segment AI prompt generation, and "Fill into node".
- Fixed a Chinese label from the planning page leaking into the run and failing with "unknown task type".

**2026-09-16**

- The AI planning page shipped: fill in a topic and it produces a multi-segment storyboard shown on a color-coded timeline, with no impact on the existing generation flow.
- Segments missing an image now fall back to the global materials; switching the task type syncs to the selected segment; the UI follows the app theme.
- API model settings became an embedded panel on the settings page, with custom models supported.

**2026-09-15**

- Generation now writes each segment to disk first and stitches at the end, greatly improving decode speed for long segments on small-memory cards.
- Segment handoff now slices directly from the previous segment's result, so seams are more faithful.
- Peak memory during stitching dropped from about 3 segments' worth to just over 1.
- Fixed the progress bar never reaching 100% when a segment was skipped without cache.
- Fixed the timing log always showing 0 seconds for reference decoding.
- Fixed 4 extra duplicated frames at seams under some settings.
- Cache is now stored per version with old versions deleted at startup, so upgrades no longer need manual cache cleanup.
- Fixed segment-level progress ("Generating 3/7"), which had never actually shown before; it is now genuinely visible.
- A corrupted cache file is now rejected and regenerated on the spot, instead of failing hours later and wasting the run.
- Unit tests grew from 196 to 217, all passing.

**2026-09-14**

- The node now carries two optional model inputs and picks the right one per segment automatically.
- Before running, only the models actually used are checked, and the missing one is named.
- The two models keep separate caches, so mixed timelines no longer reload them repeatedly.
- Node fields were reordered so the encoder shows first.
- ⚠️ Old workflows need their model links re-plugged and two hidden toggles re-checked; old caches are invalidated once.

**2026-09-13**

- Output size is now truly controlled by megapixels, with the default output lowered to 864×480.
- Default steps dropped from 25 to 20 and default megapixels from 1.0 to 0.4.
- Added an automatic check that frontend and backend values stay consistent.

**2026-09-12**

- Fixed audio reference loading failures.
- Fixed the wrong task type on newly added segments.
- Created the project README.

**Still planned**

- Second-pass refinement: iterative rewrites on top of already generated segments.

> The originally planned "automatic AI storyboarding, prompt refinement, and project import/export" have all shipped (2026-09-16~18); "cache cleanup" shipped as the cache toolbar (2026-09-19).

---

## Feedback

- **Bug reports**: please include your ComfyUI version, GPU model and VRAM, H3 model version, the full error text from the red panel, and the timeline JSON (feel free to redact).
- **Feature requests**: open an Issue.
- **Pull requests**: keep `pytest 测试/` at the 1067-passed baseline and the front-end suite `node --test 测试/*.test.mjs` at 389 passing, and match the existing code style.

---

## Acknowledgments

This plugin stands on the shoulders of many excellent open-source projects, models and tools. Listed below (by category) are the things we referenced, borrowed from or depend on, either directly or indirectly. Thanks to every author and community — if anything was missed, please open an Issue.

### Host & official nodes

- **[Comfy-Org / ComfyUI](https://github.com/Comfy-Org/ComfyUI)** — the host environment. The whole "plan → split → run each segment → stitch back" orchestration is built on ComfyUI's V3 node API, executor and caching machinery; the front-end panels, settings page and theme variables all reuse the ComfyUI frontend.
- **ComfyUI's official MiniMax H3 nodes** — all actual video/audio generation, sampling and VAE decoding (including `_empty_av_latent`, PackedLayout, `node_helpers`, …) are done by the official nodes. This plugin deliberately never patches or forks the host; it only orchestrates around them and crops/stitches their outputs.

### Generation & understanding models

- **[MiniMax H3](https://github.com/MiniMax-AI/MiniMax-H3) (MiniMax / 稀宇科技)** — the base model for multi-segment video/audio generation; the six task modes and the 24 fps time base all come from it.
- **[Qwen3-VL](https://github.com/QwenLM) (Alibaba Qwen team)** — serves as the CLIP text encoder, giving prompts semantic understanding.
- **[Kimi](https://github.com/moonshotai) (Moonshot AI) / [DeepSeek](https://github.com/deepseek-ai) and other OpenAI-compatible endpoints** — provide the LLM inference behind "one-click planning" and per-segment prompt refinement (out-of-process HTTP, zero VRAM). The preset model is Kimi-K3; custom cloud/local endpoints ([Ollama](https://github.com/ollama/ollama), [LM Studio](https://lmstudio.ai)) are also supported.

### Peer & reference open-source projects

Much of the design drew on the open-source H3 ecosystem and similar AI-video tools (see the per-project analyses under `文档/参考/`). Special thanks to:

- **[ComfyUI-Artificial-Intelligence](https://github.com/a63976659/ComfyUI-Artificial-Intelligence)** — the knowledge-base loader, the unified `api_models` per-model-key list, connectivity testing and API-error extraction were referenced/ported from it.
- **[AIMixer 导演台](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director)**, **[H3-Motion-Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context)**, **[H3-Multishot](https://github.com/jlucasmcrell/ComfyUI-H3-Multishot)**, **[H3-Codex-Drama](https://github.com/chiphoton/MiniMax-H3-Codex-Drama)**, **[H3-SelfLift](https://github.com/facok/comfyui-SelfLift)** — community nodes on the same MiniMax H3 generative pipeline; latent-direct tail cutting, the audio continuation window, the `context_length` values, and the "confirm a sample segment first / don't touch the host" principles are mutually corroborated with them.
- **[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (harry0703)**, **[video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) / [video-talkcraft](https://github.com/Vincentwei1021/video-talkcraft) / [anything2explainer](https://github.com/Vincentwei1021/anything2explainer) ([Remotion](https://github.com/remotion-dev/remotion)-based)** — the reference frame for one-click short-video pipelines and the "skill / recipe-card / multi-tier QA" methodology.
- **AIVideo_node**, **[NodeCraft AI](https://github.com/a63976659/ComfyUI-NodeCraft-AI) knowledge base** — sources of experience for LLM retry handling, settings persistence and linked-UI patterns.

### Skills & knowledge-base material

- **[MiniMax-H3知识库](https://github.com/MiniMax-AI/MiniMax-H3)** — the 9 style-skill docs and reference material bundled with the plugin, used by the clip timeline to "generate per-segment prompts in a given style". It is third-party material; copyright and content belong to its original authors.

### Libraries & tools we depend on

- **[PyTorch](https://github.com/pytorch/pytorch) (torch)** — tensors and all numeric work (stitching, silence padding, …).
- **[FFmpeg](https://ffmpeg.org) / [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)** — backend for audio transcoding and reference-video frame reading.
- **[soundfile](https://github.com/bastibe/python-soundfile)** — audio reference duration and sample reading.
- **[NumPy](https://github.com/numpy/numpy) / [Pillow](https://github.com/python-pillow/Pillow) / [aiohttp](https://github.com/aio-libs/aiohttp)** — array, image and async-HTTP capabilities provided by the ComfyUI main environment.
- **[PySceneDetect](https://github.com/Breakthrough/PySceneDetect) (scenedetect) + [OpenCV](https://github.com/opencv/opencv) (opencv-python-headless)** — optional automatic shot-splitting of a source video.
- **[PyAV](https://github.com/PyAV-Org/PyAV) (av)** — optional video-frame backend.
- **[pytest](https://github.com/pytest-dev/pytest)** — the whole front/back-end unit-test suite (current baseline in the Changelog above).

### Others

- The short-video storyboarding methodology (the hook / opening / setup / progression / conflict / climax / twist / ending / CTA narrative beats) draws on patterns widely circulated in the creator community.
- Thanks to every community member who filed bugs, suggestions and PRs.

---

## Support the author

If this plugin helps you:

- **Star this repo** ⭐
- **Share your work** — videos made with this plugin are welcome in the Issues.
- **Sponsor**
<img width="400" height="500" alt="微信图片_20260920163034" src="https://github.com/user-attachments/assets/47f64c6e-cc45-4395-9b9e-29f464d12df2" />
<img width="400" height="500" alt="微信图片_20260920163043" src="https://github.com/user-attachments/assets/7bfb521a-6f24-4104-89c0-016dcf74834b" />


---

<p align="center">
  <sub>Made with ❤️ for the ComfyUI community</sub>
</p>
