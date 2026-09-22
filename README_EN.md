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

- **AI one-click storyboarding**: fill in a brief on the AI Planning tab (topic, total duration, segment count, platform, skill, etc. — 13 fields), and an LLM produces a multi-segment storyboard draft following short-video methodology. No manual per-segment typing required.
- **Per-segment AI prompt refinement**: the storyboard first lands as a "clip timeline" rehearsal draft you can trim/split/delete/reorder and zoom in on for precision, then an LLM rewrites each segment's visual prompt guided by the chosen skill docs. Only when you're happy do you "Fill into node" to commit it to the timeline.
- **Split a long video into segments**: add as many segments as you want on the timeline, each with its own prompt and duration.
- **Pick a generation mode per segment**: text-to-video, image-to-video, first-and-last-frame, reference-to-video, video-to-video, reference-plus-video — six modes in total, and you can mix them across segments.
- **Attach reference materials per segment**: images, videos or audio. Use tags like `<Picture 1>` inside the prompt to point at them.
- **Smooth handoff between segments (optional)**: turn on the "Gradient Transition" toggle and the tail of the previous segment (both picture and sound) is carried into the next one, plus a 4-frame crossfade at the seam, so seams don't jump. Turn it off and every segment is generated independently with a hard cut at the seam.
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

Node outputs: image, audio, frame rate, total frame count, and a report string. Plug them straight into `SaveVideo` or `PreviewVideo`.

### Step 2: Open the bottom status bar

Once the plugin loads, a **Video Planner** panel appears at the **bottom of the ComfyUI page**. Its title bar splits into two tabs: **AI Planning** (left, default) and **Prompt Editor** (right) — click a title to switch pages.

The **Prompt Editor** page contains:

- **Generation type** — switch between the 6 task modes
- **Preset** — pick a saved prompt snippet from a dropdown; its body is written into the global prompt automatically (details in [Presets](#presets))
- **Prompt editor** — write the global prompt, which gets prepended to every segment
- **Reference files area** — upload images / videos / audio; duplicates are detected automatically: same name + same content reuses instantly, same name + different content is auto-renamed so they coexist instead of overwriting each other
- **Plan data** — save/load the entire node setup with one click (details in [Plan data](#plan-data-save-and-load-full-setups))
- **Timeline** — the main working area

The matching inputs on the node itself are auto-hidden. All the data still lives inside the node; the status bar is only an editor.

The **AI Planning** page offers one-click storyboarding, a clip-timeline rehearsal, and per-segment AI prompt refinement — see [Step 3: AI one-click planning (optional)](#step-3-ai-one-click-planning-optional).

### Step 3: AI one-click planning (optional)

If you don't want to fill segments by hand, follow this flow (first-time users need an API model configured — see [API model setup](#api-model-setup)):

1. **Fill the brief**: Topic (required), Total duration (minutes, default 3), Segment count (0 = auto), Suggested per-segment duration (default 5-8 s, controls pacing), Platform, Default task, Hook, Language (the 11 dialogue languages H3 supports stably), Resolution, Style, Audience, Skill, Auxiliary — 13 fields in total.
2. **Pick a model, click "Generate plan"**: the backend calls the LLM to produce the storyboard JSON (first segment forced to "Hook", last one must be "Ending/CTA", each segment 5–15 s), saved into a hidden "clip draft" widget on the node. The draft **does not participate in generation** — the node timeline stays untouched. If segments come back short, the backend **automatically attempts one targeted repair** (it never duplicates one segment's footage to fake completeness); if still short, it returns an **incomplete draft** with an on-page orange warning. When a knowledge-base skill is selected, the page honestly reports the **sources that actually entered the request** (truncation / missing counts included).
3. **Polish on the clip timeline**: an editing-room-style track — click empty space to add a segment, drag card edges to trim, "✂ Split" cuts the segment at the playhead, "🗑 Delete" ripple-deletes (remaining segments close the gap), multi-select, drag to reorder. The time ruler above the track auto-adjusts its density to the total duration (seconds up to hours). Each card shows index/range/title/beat/subtitle/keywords inline.
4. **Zoom in for precision (view-only)**: the toolbar's "Fit / Zoom out / slider / Zoom in" magnifies the track up to **1–40×**, with the current factor shown right next to it. You can also **scroll-wheel to zoom** directly on the track (Ctrl+wheel / trackpad pinch is more sensitive), **drag the time ruler to pan**, or use the horizontal scrollbar. Ruler ticks auto-step down as you zoom in (hours → minutes → seconds → 0.1 s), so even a feature-length draft can be aligned segment by segment. Zoom only changes view width: it never touches segment start/end times, never writes the clip draft, the node timeline, or the cache signature — trim / split / playhead scrubbing / multi-select / reordering stay pixel-accurate at any factor.
5. **"✨ AI Generate Prompts"**: the LLM rewrites each segment's full visual prompt based on the brief and skill docs, automatically switching modes by enable state — when **all segments are enabled** it batch-generates as before, covering only *enabled* segments (managed via Enable / Enable all / Disable all on the toolbar); when **only some are enabled**, all segments are uploaded as **read-only context** and the server **rewrites only the enabled segments** (disabled segments keep their original prompts and don't need to be count-matched) — whatever segment goes out is filled back into that same segment. The Skill/Auxiliary/Model used for generation sit in the row above the track. Write-back is mapped by segment identity — if one segment fails it **keeps its original draft and is flagged** (never silently overwriting with the old wording as if it were a new result); failed segments trigger a confirmation.
6. **Per-segment fine editing**: select a card and edit Title / Structure / Subtitle / Prompt in the right column, kept in sync with the matching card blocks ("Structure" is the UI label for the narrative-beat field shown on the card).
7. **"⬆ Fill into node"**: when satisfied, one click writes the draft segments into the node's `时间轴数据` (timeline data) field (with an overwrite confirmation). From there it behaves like a normal timeline.

> LLM calls go over out-of-process HTTP (same code for cloud and local), **using zero VRAM** and never touching the sampling/execution chain. Planning failures surface as explicit errors — demo content is never fabricated.

### Step 4: Edit the timeline

- **Add a segment**: click on an empty part of the track, or click the "+" button
- **Change duration**: drag the left/right edge of a segment card, or use the time inputs below it
- **Toggle Run**: the switch below each segment card. Only checked segments get regenerated; unchecked ones with a saved copy are reused
- **Edit prompt / attach references**: click into the segment card
- **Playhead**: drag it to see which segment covers a given moment
- **Gradient Transition**: a toggle on the timeline toolbar. When on, segments blend smoothly into each other (tail-context anchoring + a 4-frame crossfade at the seam); when off, seams are hard-cut

Timeline data is stored as JSON inside the node's `Timeline Data` input. You can copy and paste it, which makes archiving and sharing easy.

### Step 5: Click Queue Prompt to start

Generation runs in two stages:

1. **Sample each segment one by one.** Every finished segment is saved to disk right away (about 45 MB per segment).
2. **After every segment is done, decode and stitch them all together** into the final video.

Splitting it this way frees up the GPU during decoding. Without it, a 16 GB card running long segments at high resolution would be more than ten times slower.

The status bar shows segment-level progress like "Generating 3/7".

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
- **On**: the last 22 frames of picture and sound from the previous segment are carried into the next one, plus a 4-frame crossfade at the seam. Handoffs look more natural, but things can also go wrong more easily.

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

**2026-09-21**

- **Node timeline zoom**: the timeline panel mounted on the node gained the same "Fit / Zoom out / slider / Zoom in" quartet on the **right side of its toolbar**, magnifying the track by **1–40×** with a live factor read-out; **wheel on the track zooms** (Ctrl+wheel / trackpad pinch is more sensitive, horizontal trackpad swipes stay with native scrolling), **dragging the time ruler pans**, and the horizontal scrollbar reaches segments outside the view — so a segment-heavy or narrow node no longer has to be dragged wider. Still **view-only**: segment start/end and durations don't change, nothing is written to the widgets, no re-execution is triggered and the cache signature is untouched; with 0 segments the controls are disabled and the view resets to full. The zoom group sits right against the "N segments" summary, matching its position on the clip timeline.
- **Segment-card thumbnails & material-source linkage**: the timeline card image now goes through a single pipeline — "resolve the effective material source first, then decide what to show by task type" — picking the image by the priority shared-material override → segment image slot → global fallback on a missing key (an explicit empty array / empty value does not fall back). Fixes reference tasks such as v2v not reading the global materials when the image key is missing, string image names being truncated to their first character, and the shared-material toggle not refreshing affected cards. Clearing the first/last frame, switching the task type, or removing a candidate image with "×" now update the card instantly; standalone preset first/last frames repopulate correctly in the dropdown and can be reused when switching back. Front-end display layer only — sampling, the segment cache and plan saving are untouched.
- Test baseline: front-end `node --test 测试/*.test.mjs` 203 → **260 passing** (12 node-timeline zoom locks + segment-card thumbnail / material-source / task-switch linkage regression locks), `pytest 测试/` 615 → **616 passing** (a new cross-file mirror lock keeping `最大缩放` and the zoom icons identical between the two timelines), ruff clean.
- **AI Planning right-column label "Beat" renamed to "Structure"** (front-end text only, better matching short-video narrative structure): the data keys `职能`/`职能色`, backend enums, the LLM output contract, and the value shown on segment cards all stay unchanged — cards still display the narrative-beat value.

**2026-09-20**

- **Timeline zoom** added to the clip timeline: the toolbar's "Fit" / "Zoom out" / slider / "Zoom in" controls magnify the track by **1–40×** and show the current factor live; **scroll-wheel on the track zooms** (Ctrl+wheel / trackpad pinch is more sensitive, and horizontal trackpad swipes are left to native scrolling), **dragging the time ruler pans**, and the horizontal scrollbar works too. Ruler ticks step down automatically as you zoom in (hours → minutes → seconds → 0.1 s), so long pieces can still be aligned precisely. It is **view-only** — no segment durations change, nothing is written to the clip draft, and neither the node timeline nor the cache signature is touched; trim / split / scrub / multi-select / reorder stay accurate at any factor.
- A self-review of that zoom work fixed six defects (1×P1, 4×P2, 1×P3): the horizontal position was lost whenever the track was rebuilt (the playhead got pushed out of view) → the view is now restored once the container is measurable, and the DOM's real scroll position is read back as the single source of truth; panning was not part of the unified drag state machine, so it fought wheel-zoom and node re-binding and leaked end-event listeners → folded into one state with proper cancellation; "✨ AI Generate Prompts" / "🔁 Retry selected segments" are now disabled in place with changing label text and restored when finished (no more lost icons or font size); a declaration-order slip where a later `font:inherit` overrode the buttons' fixed line-height was corrected; and a queued animation frame used to double-paint the ruler → pending rAF handles are now cancelled before a synchronous refresh.
- The Cache strip moved from the bottom status bar **into the node's timeline toolbar** (right after the "Gradient Transition" toggle): the invalidate version is a **node-level** fact, so keeping it in the bottom bar mismatched "which node am I editing" against "which node am I invalidating"; stats/clear are process-level facts and simply followed the control next to the cache's producer.
- Whole-page **density pass + unified buttons + theme following**: more content per screen (root font 11 px, segment cards 10 px, tighter gaps and padding, card keywords 3 → 2 lines, panel min-height 240 → 210); toolbar buttons share size/font/cursor styling and the zoom icons became `currentColor` strokes that follow the theme; node and panel skin colors now go through ComfyUI theme variables, so **light themes no longer leave dark blocks** (only the two identity colors — selection green, delete red — stay fixed, guarded by a static test).
- The AI Planning brief's "Auxiliary" now shares the **same source** as "Skill" (plugin-root `Skills/`); the clip timeline generation row's Skill/Auxiliary still use `MiniMax-H3知识库`, and the two sources remain independent.
- Test baseline: front-end `node --test 测试/*.test.mjs` 164 → **203 passing** (19 new zoom-review regression locks), `pytest 测试/` **615 passing**, ruff clean.

**2026-09-19**

- Segment cache & execution layer:
  - ⚠️ **Segment cache format bumped h3-6 → h3-7 (breaking)**: the fingerprint gains four dimensions — material content digest, previous-segment fingerprint cascade for anchored segments, provable model-chain identity + cache-invalidate version — and drops playback fps; old-version cache folders are deleted automatically at startup, so **every already-generated segment is invalidated and the first run needs a full re-sample** (budget the time). Upside: replacing material content under the same name, or changing an upstream segment, now cascades invalidation automatically instead of silently false-hitting; changing only the output frame rate no longer nukes the whole cache.
  - New "Cache" strip in the status bar: segment-cache stats (version/entries/size), one-click "Clear Segment Cache", and "invalidate version +1" / direct edit (writes the node's "缓存失效版本" widget).
  - Media upload dedup upgraded: same-name-but-different-content files no longer overwrite/confuse each other — they are auto-renamed to `name.<content-digest>.<ext>` and coexist; same-name-same-content still dedups instantly.
  - Pre-flight checks before execution: material files, key numeric values & per-segment durations, and required official nodes are validated up front with clear errors instead of blowing up mid-run.
  - The completion report gains a three-duration line (planned → projected after align/trim → actual final video) and a memory-budget line; when the budget exceeds the hard cap it aborts before decoding with a clear error instead of OOM-crashing.
- Planning quality & backend request governance (Stage 4):
  - **Per-segment prompt status is no longer masked by a whole-batch result**: when a segment returns no output it keeps its original draft and the specific failing segment is flagged (not just a total count); the front end writes back by segment identity and never silently overwrites old wording as a new result.
  - **New local retry (`/lvp/plan/prompts/retry`)**: the clip timeline's "🔁 Retry selected segments" rewrites only the selected segments; the rest go up as read-only context and the server rewrites only the targets.
  - **Short segment counts are no longer padded by silently duplicating the last segment**: at most one targeted repair is attempted; if still short, an incomplete draft is returned with valid segments plus diagnostics.
  - **Honest knowledge-base source echo**: lists only material that actually entered the request; truncation / over-budget skips / missing are visible in the UI; duration keeps the equal-split default (LLM per-segment relative durations not adopted — logged as a follow-up experiment).
  - **Backend request governance**: classified LLM errors (auth/rate-limit/client/server) mapped to HTTP status by code, whole-order timeout budget, retry only for retryable errors, 2 MiB default response-body cap, process-wide concurrency slots (busy → 503 over limit); preset scanning moved off the event loop with an mtime-invalidated bounded cache.
- Audio alignment fix: segments missing audio are now padded with equal-length silence (A/V total strictly matches) instead of being skipped (which caused cumulative per-segment drift); all-silent input → silent output.
- For non-24 fps output, the report adds an explicit line: "sampled at 24 fps, played back stretched to your frame rate" (frame rate is just a tag; the time base is never silently changed).
- The AI Planning brief form now remembers per node: switching bound nodes no longer loses unsaved edits (auto stash/restore on rebind; the draft wins after submit).
- Narrow-panel adaptation: at panel width ≤480px the brief form takes the full row and the right-hand segment-detail column collapses instead of overflowing.
- Panel teardown: leftover subscriptions are cleaned up on node removal / module hot-reload, avoiding ever-slower zombie listeners.

**2026-09-18**

- The AI Planning page's "Skill" got its own source: a new plugin-root `Skills/` folder (first-level sub-folder = skill name), no longer sharing a folder with the clip timeline generation row's skill (which still uses MiniMax-H3知识库).
- Clip timeline UI rework: the track is always visible (ruler and track render even with 0 segments); segment details now live directly on the cards (title/beat/subtitle/prompt, progressively hidden on narrow cards); clip-timeline and node-timeline selections are decoupled; new adaptive time ruler (density auto-scales from seconds to hours with total duration).
- Toolbar adds Enable / Enable all / Disable all: "AI Generate Prompts" now only covers enabled segments; the old Run/Stop button was removed (the video-generation run switch stays on the node front-end).
- Renamed "Role" to "Beat" across the whole chain (the options were always narrative functions: hook/opening/setup/progression/conflict/climax/twist/ending/CTA): UI label, LLM output contract, segment data keys (`beat`/`beat color` rendered as `职能`/`职能色`), backend enums, front-end read/write, and plan samples are now consistent (development stage, no legacy-key compatibility); dropped the 👤 prefix on cards; the right column gained a "Prompt" editor — its four fields now match the card blocks by name.
- The clip-draft source of truth moved from a hidden widget to `node.properties`: editing the draft no longer invalidates ComfyUI's execution cache or forces the node to re-run, and it still saves with the workflow (old workflows auto-migrate on load).
- Fixed a batch of AI Planning page race/refresh issues: async AI responses no longer clobber another node or a newer draft; selection and highlight stay in sync for non-bound nodes; the right column refills with the new prompt right after "AI Generate Prompts"; the brief "Skill" dropdown refreshes on every expand (reflecting skills added/removed under `Skills/`) while keeping the current selection; picking "None" no longer accidentally triggers skill-doc loading; the main + auxiliary skill docs now share one character budget (no longer doubled).
- Cleaned the bundled plan samples: the per-segment task in `测试2/测试3.json` was corrected from a Chinese label to a task code (old samples failed at execution with "unknown task type").

**2026-09-17**

- The status bar split into "AI Planning / Prompt Editor" tabs; the brief form moved inline into the AI Planning page and grew to 13 fields (minute-based total duration, suggested per-segment duration, resolution, language expanded to H3's 11 stable dialogue languages, …).
- Added H3 knowledge-base style-skill injection: pick a skill and the storyboard is written in that skill's visual language (failures degrade gracefully to generic storyboarding).
- Several rounds of polish on the API model setup panel: unified list of the preset model (Kimi-K3) plus custom models, per-model API keys, a "Test connectivity" button, full-width card layout; global timeout floor raised 30→120 s.
- Added the "clip timeline" rehearsal-draft editor: new hidden widget 剪辑草稿 (clip draft, never participates in generation), trim/split/ripple-delete/multi-select/drag-reorder, per-segment "AI Generate Prompts" (new `/lvp/plan/prompts` endpoint), and "Fill into node" to commit. The in-node timeline and the execution chain are untouched.
- Fixed: the brief's "Default task" Chinese label leaked into the execution chain and made generation fail with "unknown task type" (plans saved before the fix need re-planning).

**2026-09-16**

- **AI planning (H3 planner) shipped**: brief form → LLM multi-segment storyboard following short-video methodology → timeline colored by narrative beat, with zero changes to the sampling/execution chain.
- r2v/rv2v segment thumbnails now fall back to the global reference pool; switching the global task type syncs to the selected segment; the front-end now follows the ComfyUI theme (hard-coded colors migrated to host variables).
- API model config became an embedded settings-page panel, default model Kimi-K3, with user-defined models supported.

**2026-09-15**

- Generation is now split into two stages: sample each segment to disk first, then decode and stitch them all at the end. This fixes the case where a 16 GB card running long high-resolution segments saw decoding take 839 seconds instead of 52.
- Segment handoff no longer goes through a "decode → re-encode" round trip. It slices the tail off the previous segment's intermediate result and uses that directly, so seams are more faithful.
- Stitching now writes each decoded segment straight into a pre-allocated buffer. Peak memory dropped from about 3 segments' worth to about 1 segment plus a bit.
- Fixed: the progress bar could never reach 100% when some segments were skipped and had no cache.
- Fixed: a bug in the backend timing log that made "reference decoding" always show 0.00 seconds.
- Fixed: when the context length was set between 1 and 4, seams got 4 extra duplicated frames.
- Cache is now stored per-version in a subfolder, and old-version folders are deleted automatically at startup. This finally fixes the historical problem where upgraded-away caches became dead files nobody ever cleaned out of `%TEMP%` (27.9 GB had piled up). Future upgrades no longer require manual cleanup.
- The bottom status bar's segment-level progress ("Generating 3/7") had never actually worked before. It was receiving the sampler's internal denoising steps instead — dozens of them flickering by. It now uses the plugin's own channel, so segment progress is genuinely visible.
- Hardened: if a cache file gets corrupted externally (frame count disagrees with the actual data), it's now rejected on the spot and regenerated, instead of blowing up later during decoding/stitching — which would have wasted hours of sampling.
- Unit tests grew from 196 to 217, all passing.

**2026-09-14**

- The node now has two optional model inputs and picks the right one per segment automatically. No manual switching.
- Before running, it only checks that the models actually used by the timeline are connected, and names whichever one is missing.
- The two models keep separate caches, so mixed timelines no longer reload them repeatedly.
- Reordered node inputs so the encoder shows first.
- ⚠️ Old workflows need their model links re-plugged and two hidden toggles re-checked; old caches are invalidated once.

**2026-09-13**

- Output size is now truly controlled by megapixels. Default output changed from 1376×768 to 864×480.
- Default steps dropped from 25 to 20; default megapixels in the status bar dropped from 1.0 to 0.4.
- Added an automatic check that frontend and backend values stay consistent.

**2026-09-12**

- Fixed audio reference loading failures.
- Fixed incorrect task type for new segments.
- Created the project README.

**Still planned**

- Second-pass refinement (iterative rewrites on top of existing segments)

> The old v2 items "AI-powered automatic shot planning, prompt refinement, project file import/export" have all shipped (2026-09-16~18) as the AI Planning page, per-segment AI prompt refinement, and Plan data respectively; "cache cleanup" shipped 2026-09-19 as the Cache strip (moved into the node's timeline toolbar on 2026-09-20).

---

## Feedback

- **Bug reports**: please include your ComfyUI version, GPU model and VRAM, H3 model version, the full error text from the red panel, and the timeline JSON (feel free to redact).
- **Feature requests**: open an Issue.
- **Pull requests**: keep `pytest 测试/` at the 616-passed baseline and the front-end suite `node --test 测试/*.test.mjs` at 260 passing, and match the existing code style.

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
