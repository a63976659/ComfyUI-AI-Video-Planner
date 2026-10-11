# Video Planner

**Language:** [🇨🇳 简体中文](./README.md) ｜ 🇬🇧 English (current)

A ComfyUI plugin that splits a long video into a few short segments, generates them one by one, and stitches them back into a finished video.

The existing generation nodes use ComfyUI's official MiniMax H3 pipeline. The Video Production tab automatically receives the current workflow's final generated videos for editing, enhancement and finished-video export. Received videos and voice tracks are added only to production clips, keeping the AI Planning upload area unchanged. AI planning and prompt rewriting use network requests without using VRAM.

The first received video sets the canvas; subsequent clips do not change it, and manual changes are supported. Corresponding voice and subtitles follow clip trims and ordering. Background music, text overlays, picture and audio enhancement, MP4 previews, resumable exports and project backups remain available. Restart ComfyUI and refresh the browser after updating. See the [post-production guide (Chinese)](./文档/技术实现/2026-10-05-视频制作后期调整说明.md).

---

## 📑 Table of Contents

- [What it does](#what-it-does)
- [How to use](#how-to-use)
  - [Step 1: Wire up the node](#step-1-wire-up-the-node)
  - [Step 2: Open the bottom status bar](#step-2-open-the-bottom-status-bar)
  - [Step 3: AI one-click planning (optional)](#step-3-ai-one-click-planning-optional)
  - [Step 4: Edit the timeline](#step-4-edit-the-timeline)
  - [Shared material and video audio controls](#shared-material-and-video-audio-controls)
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

- **AI writes the storyboard**: describe your requirements and choose a purpose such as novel adaptation, knowledge explainers or product ads. The AI organizes the content, generates storyboards and validates them.
- **AI rewrites each segment's visual prompt**: the storyboard first lands as a "clip timeline" rehearsal draft you can trim, split, delete and reorder, and zoom into for precision; then the AI rewrites each segment's picture prompt using the unified prompt rewriting skill. When you are happy, one click writes it into the real timeline.
- **Split a long video into segments**: add as many segments as you want, each with its own prompt and duration.
- **Pick a generation mode per segment**: text-to-video, image-to-video, first-and-last-frame, reference-to-video, video-to-video, reference-plus-video — six modes, freely mixed across segments.
- **Attach reference material per segment**: images, videos or audio. Inside the prompt you can point at them with tags like `<Picture 1>`.
- **Trim shared material per segment and control video soundtracks**: reference tasks load shared video and audio from each segment's time window. A video's soundtrack is used as a reference by default; you can disable that reference and keep generated audio, or replace the output with the source soundtrack.
- **Smooth hand-off between segments**: with the "Gradient Transition" switch on, the end of the previous segment (picture plus about a second of audio) is carried into the next one so it continues naturally. Seams never blend two clips together — only the opening of the continuation gets its colour and brightness eased toward the previous tail. Switch it off and every segment is generated on its own with a hard cut.
- **Finished segments are saved automatically**: each finished segment goes to disk. Next run, unchanged segments are read back instead of regenerated — a full re-run takes tens of seconds.
- **The saved segments are visible and controllable**: the "Cache" strip on the node's timeline toolbar shows counts (version/entries/size), clears everything in one click, and a "+1" makes all old segments re-run. Replacing a material file or changing an earlier segment is detected automatically and recalculated — nothing stale is reused quietly.
- **The node's own timeline zooms too**: the timeline on the node carries the same **1–40×** zoom ("Fit / Zoom out / slider / Zoom in" at the right of its toolbar, with the live factor shown). With many segments or a narrow node you can also wheel-zoom, drag the time ruler to pan, or use the horizontal scrollbar. It is view-only: no segment length changes and the saved segments are unaffected.
- **Only run the segments you check**: every segment has a "Run" switch. Only checked ones are regenerated; unchecked ones that were saved earlier still get stitched into the final video.
- **Nothing lands in the wrong place**: if you switch nodes, delete segments or edit the draft while a slow operation (loading a plan, uploading material, AI planning) is still running, the result only goes to the target you started it on; the out-of-date result is refused and you are asked to retry.
- **Checked before running**: material, numbers, per-segment lengths and the required official nodes are checked before generation, and problems are stated plainly. The completion report gives "planned → expected → actual playback" lengths and a rough memory figure for the finished video; you can also set a cap so it stops cleanly before decoding starts instead of crashing halfway.

---

## How to use

### Step 1: Wire up the node

Add the node **长视频规划师** (Video Planner — that is its internal name too) to your workflow.

It has 5 inputs:

| Input | What it is | Required? |
|---|---|---|
| `fl2va模型` | model for text/image-to-video | optional, connect only if used |
| `ref2va模型` | model for reference-to-video | optional, connect only if used |
| `CLIP编码器` | turns your text into something the model reads; must be the minimax type (Qwen3-VL) | required |
| `视频VAE` | video decoder | required |
| `音频VAE` | reference audio encoder and generated audio decoder | required |

For the two model inputs, connect whichever your tasks need; if you use both kinds, connect both.

The first five outputs are still image, audio, frame rate, total frame count and report, so your existing save and preview links stay unchanged. The sixth output, "初采产物" (first-pass result), is only for the optional Upscale and Redraw node — leave it unplugged if you don't do a second pass.

### Step 2: Open the bottom status bar

After the plugin loads, a **长视频规划师** panel appears at the **bottom of the ComfyUI page**. Its title bar holds four tabs in this order: **AI Planning** (default), **Prompt Timeline**, **Prompt Editor** and **Video Production**. Click one to switch (clicking the active tab again collapses the panel, once more re-opens it).

The **Prompt Editor** page has:

- **Generation type** — switch between the 6 task modes
- **Preset** — pick a saved prompt snippet; its text goes into the global prompt automatically (see [Presets](#presets))
- **Prompt editor** — edit the selected segment's prompt; the global prompt inserted through presets is placed before each segment's prompt
- **Optimize prompt** — at the top of the button column to the right of the reference materials, uses the same rewriting skill as the timeline and the saved “Prompt optimization model”. It rewrites only the current editor text, using the selected task and actual first/last-frame bindings. For `fl2v`, first-only uses I2VA, last-only uses L2VA, and both use FL2VA; a single image is `<Picture 1>`. It does not upload or inspect media or infer image content from filenames. Accepted results replace the current segment text directly; failures and stale results after segment, node, content or material changes preserve the current text.
- **Audit tags (审查标签)** — below “Optimize prompt”, available in all six task modes, including text-to-video; checks the current prompt for tags without matching material. After confirmation, these tags become plain text.
- **Reference material area** — upload or drop images / videos / audio. Duplicates are handled for you: same name and same content is just reused; same name but different content is renamed and kept side by side. Dropped files go into the right box by type (images → image box, and so on); a full box (9 images / 3 videos / 3 audio) takes nothing more and unknown types are refused on the spot. Each box is a fixed three rows tall — when it overflows, scroll inside it with the wheel. To its right is a "Clear materials" button that wipes this segment's material in one click, with a confirmation dialog first. Every tile is clickable and opens a pop-up in the middle of the screen — images enlarge, video and audio play with the browser's own controls (seeking included).
- **Plan data** — save/load the whole node setup in one click (see [Plan data](#plan-data-save-and-load-full-setups))
- **Timeline** — the main working area

The matching inputs on the node itself are hidden automatically. The data lives in the node; the bottom panel is just an editor.

The **AI Planning** page has materials on the left, followed by purpose cards, settings and a single requirements box. The first card, automatic detection, is selected by default for new requirements. Choose novel adaptation, knowledge explainers, product ads, music videos and other uses through cards. All four areas share the available width equally, with consistent gaps between them. Compact purpose cards use a 3-by-3 grid so all nine options are visible together. Add images, video, audio or text with the plus tile or drag-and-drop; click a tile to preview it, and type `@` in the requirements box to reference material. During planning, the four stages—source analysis, episode planning, reference generation and storyboarding—open completed results in structured dialogs with content cards, episode lists, reference galleries and shot cards. Draft editing and per-segment prompt rewriting remain on the **Prompt Timeline** page.

### Step 3: AI one-click planning (optional)

Planning materials use the authorized Alibaba Cloud Beijing endpoint. Original images, audio and video are uploaded to the provider's model-bound temporary storage; planning requests reuse their `oss://` URLs without frame extraction, transcoding or descriptive substitutes. The existing API key is sufficient. Media snapshots and uploads are processed in chunks rather than encoded entirely in memory. TXT/MD originals use the Files API plus complete verbatim text; Omni does not directly read document file IDs. Only selected materials are processed. Local file-size, aggregate-size, extension, text-length and response-byte caps have been removed, and model names are no longer pinned; the upload service and selected model enforce their own limits and return explicit errors. Temporary media expire under the provider's lifecycle. Task exit releases local snapshots and attempts to delete its uploaded documents. Timeline rewriting and prompt optimization remain text-only; path checks, timeout, cancellation and planning validation remain active. See the [original-input record (Chinese)](文档/技术实现/2026-10-07-规划素材原件发送.md).

If you don't want to fill segments by hand, follow this path (first time needs an API model set up — see [API model setup](#api-model-setup)):

1. **Describe your requirements and select a purpose**: put ideas, source text, required content and constraints into one box. Select a card on the left or keep automatic detection. Adjust total length (minutes, default 3; **0 means automatic allocation** based on content, yielding a positive duration), suggested segment length (default 5–8 seconds), segment count (0 means automatic), task, language, style, platform and audience as needed. Old topics and body text appear together; unedited legacy requirements retain their original request fields.
2. **Click "Generate plan"** (select its model beforehand in API Model Setup): the AI selects planning references, produces storyboards, reviews them and revises them when needed. Long source text is planned in full across episodes. Available storyboards update the clip draft even after partial failure, with reasons, suggestions and missing-content notices. Cancellation or no valid storyboards preserves the original draft. Long-form episodes must cover all source ranges in order, with 1–4 actual range IDs per episode. Invalid references produce an episode-specific format error for AI revision. There is no fixed overall planning time limit, while network waits without data remain subject to the global timeout. You can stop a running task; temporary disconnections reconnect automatically.

   "Generate plan" and "Import planning" share the button row equally. Each generation creates a separate archive, including repeated requirements, and preserves earlier results. Loading a history item restores the selected episode’s original storyboards and all four stage result buttons. It always loads the archived original, including when the same project and episode are already open. The current edits remain available through "Previous step".

   The prompt timeline offers "Previous step" and "Next step", in that order, between "Enable" and "Disable subtitles". "Next step" restores an undone operation. A new content edit after going back clears the redo history; browsing or writing identical content preserves it. "Previous step" immediately undoes one draft operation, including manual edits, duration changes, adding or deleting shots, AI prompt generation and generating or loading a plan. A streamed AI run counts as one operation, including any partial results retained after failure or stopping. Up to 20 undo steps are saved with the node’s workflow properties; large drafts may retain fewer older steps. Each button is disabled when its direction has no history or an operation is running. Undo restores editor content and planning references; undoing ordinary prompt edits preserves unsubmitted requirements and duration settings. The AI planning page no longer has a "Restore previous version" button.

   Settings now includes Data Management for planning archives and saved plans. Save selected records as JSON files to share all episodes and stage results; exported plans include their associated planning archive. Import creates local access credentials and never shares API keys. "Import planning / Import plan" opens the corresponding folder: drop JSON files there and the list refreshes every three seconds. Successfully imported files move to an "Imported" subfolder. Share original image, video and audio files separately. Deleting records requires two confirmations with a reminder to finish all episodes and save a backup. Active or resumable planning projects cannot be deleted.
3. **Fine-tune on the clip timeline**: use it like an editing program — click empty space to add a segment, drag a card edge to change its length, "✂ Split" cuts at the time pointer, "🗑 Delete" removes one and the rest close the gap, multi-select and drag-to-reorder work too. The ruler above the track is always there (an empty draft still shows a 0-30 s scale) and its tick spacing follows the total length. Each card shows index / range / title / structure / subtitle / keywords.
4. **Zoom in (view-only)**: "Fit / Zoom out / slider / Zoom in" on the toolbar magnifies up to **1–40×** with the current factor next to it. You can also **wheel-zoom** on the track (hold Ctrl, or pinch on a trackpad — both are more sensitive), **drag the ruler to pan**, or use the bottom scrollbar. Ticks get finer as you zoom (hours → minutes → seconds → 0.1 s), so a long piece can still be aligned segment by segment. Zoom only changes what you see: it never touches segment start/end times, never writes the draft, and does not affect the node timeline or the saved segments; trim, split, seeking and reordering stay exact at any factor.
5. **"✨ AI Generate Prompts"**: uses the saved timeline rewriting model and the `AI生成提示词/` skill directory to rewrite existing storyboards from their task, actual reference bindings and text summaries. **No images, video or audio are uploaded or reanalyzed.** Generation runs sequentially with one model request per segment. The four reuse/repair/review/regenerate modes are removed. Quality checks and correction requirements are part of the generation rules, applied within that single request; enabled segments are rewritten, while disabled ones stay unchanged. Context contains the theme, current goal, current storyboard and its bound character/material descriptions, plus necessary style, language and sound constraints. Neighboring storyboards, previous generated prompts and the full brief are excluded. Each prompt must describe its subject, setting and actions independently. Each completed segment is written back immediately with a generated status; there is no separate review or automatic repair request. Request or parsing failures retain the original text with a visible reason. The unified rewriting skill is fixed; model choices are managed in API Model Setup.
6. **Per-segment editing and speech timing**: select a card to edit Title / Structure / Dialogue or narration / Prompt. Typing dialogue shows live slow, normal and fast speech estimates and whether the shot is tight. Open "台词估时" to adjust speech rates, punctuation pauses and padding; preview the rearrangement before applying it to the draft. Existing shot durations are preserved by default. Long dialogue is split at semantic boundaries with balanced durations. You can specify a minimum action duration and whether action follows speech. Settings persist with the draft; undo is available until later edits. Disabling on-screen subtitles does not silence dialogue.
7. **"⬆ Fill into node"**: one click writes the **enabled** draft segments into the node's `时间轴数据` field (with an overwrite confirmation). If not everything is enabled, only the enabled ones are filled and their times close up seamlessly while the disabled ones stay in the draft; with everything enabled the result is the same as before. After that it behaves like a normal timeline.

> The AI calls go over the network (same code for cloud and local). They use **zero VRAM** and never touch the generation flow. Planning failures are reported plainly — demo content is never invented.

With an existing voice recording, open "台词估时 → 按已有配音测时与试听" and select media-pool audio to read its actual duration. Recordings over 15 seconds require matching sentence timestamps in SRT or JSON. "成片使用这条配音原声" outputs slices of that recording and pads extra shot time with silence; this mode requires 24 fps. Uncheck it to use the recording for timing only. Applying timing updates the draft; click "Fill into node" to use it for generation. Text estimates are speech-rate assumptions, and recorded audio does not guarantee lip synchronization. Review actions, materials and old timing instructions after splitting. See the [timing and voice alignment guide](文档/技术实现/2026-10-02-台词估时与配音对齐.md).

### Step 4: Edit the timeline

- **Add a segment**: click an empty part of the track, or the "+" button
- **Change length**: drag a card's left/right edge, or use the time inputs under it
- **Run on/off**: the switch under each card. Only checked ones are regenerated; unchecked ones with a saved copy are reused
- **Edit prompt / attach material**: click into the card
- **Time pointer**: drag it to see which segment covers a given moment
- **Node cards expand with node height**: making the node taller allocates the available card height **1:1** between image and prompt areas. Prompt previews are no longer limited to two lines; they retain their font size and line breaks and show more text as the area grows. Horizontal card widths still follow segment durations. A browser refresh is enough when updating only this UI change.
- **Gradient Transition**: a switch on the timeline toolbar. On, segments continue smoothly (the previous ending is carried into the next one and the continuation's opening colour is eased toward it, with no overlapping picture). Off, seams are hard cuts.

The whole timeline is kept as a block of text in the node's `时间轴数据` input. You can copy and paste it, which makes archiving and sharing easy.

### Shared material and video audio controls

**Reference-to-video, video-to-video and reference-plus-video** (`r2v`, `v2v`, `rv2v`) accept reference video frames and their soundtracks. Videos with sound take the first Audio tag numbers, followed by separately uploaded audio; silent videos take no Audio number. For example, one video with sound plus one standalone audio file use `<Audio 1>` and `<Audio 2>`. Check the prompt's `@` list for the mapping. Text-to-video, image-to-video and first-and-last-frame tasks do not accept these reference video or audio inputs.

With "全段共用" (Shared across segments) enabled, shared video, its soundtrack and standalone audio are read from each segment's time window. A segment spanning 7–14 seconds starts reading at second 7 of the source; material previews still play the original file. Each video window loads at most its first 15 seconds and is further trimmed to the model's valid frame count. Its paired reference soundtrack uses the same start and the duration of the frames actually retained; standalone audio uses the full segment window. With sharing off, each segment's video and paired soundtrack start at source second 0. First-pass generation and redrawing use the same reference trimming rules.

The button column to the right of the reference area is ordered **Optimize prompt → Audit tags → Shared across segments → Clear materials → Disable soundtrack reference → Use source soundtrack**. The "全段共用" (Shared across segments) button indicates its setting through its active state, without a separate on/off label. Sharing and the two audio controls appear for the three reference task types:

- **禁用原声 (Disable soundtrack reference)**: exclude the video soundtrack from model references and save the model's generated audio.
- **原声输出 (Use source soundtrack)**: exclude the video soundtrack from model references and replace output audio with the soundtrack of the first video with sound in the material list.

Both controls are off by default, preserving soundtrack references and existing output behavior. They are mutually exclusive; click the active button again to restore the default. Shared segments inherit the audio mode from the shared source; with sharing off, each segment uses its own setting. Neither control disables separately uploaded reference audio. During execution, disabled soundtrack tags are removed and standalone Audio numbers are adjusted; stored prompts stay unchanged, so restoring the default restores their references.

"原声输出" requires the node's frame rate to be **24**. With sharing on, source audio is cropped to each segment's time window; with sharing off, it starts at source second 0 for every segment. Audio is trimmed or padded with silence to match the final pictures, without stretching or changing speed. A missing video soundtrack or an empty required source-audio window produces a clear error. These controls take precedence over existing dialogue voice replacement; subsequent Upscale and Redraw uses the final audio track. Switching between the two disabled-reference modes can reuse the same segment sampling cache.

"原声输出" already skips audio VAE encoding of the video soundtrack and decoding of generated audio. Standalone reference audio still needs encoding if present. The audio VAE input remains required, and its upstream loader may still load the model. Skipping these operations reduces preparation and output work; H3 still samples video and audio jointly, so a noticeably faster sampling progress bar is not guaranteed. GPU timing comparisons have not been performed.

Restart ComfyUI and refresh the browser after updating. Older reference-video caches that omitted soundtracks or always loaded from second 0 are invalidated and need resampling. See the [soundtrack and shared-window guide (Chinese)](./文档/技术实现/2026-10-05-参考视频音轨接入修复.md) for details.

### Step 5: Click Queue Prompt to start

Generation runs in two stages:

1. **Segments one by one**, each saved to disk as soon as it finishes (about 45 MB per segment).
2. **Once every segment is done, they are all decoded and stitched** into the final video.

Splitting it this way frees the GPU during decoding; otherwise a 16 GB card running long high-resolution segments would be more than ten times slower.

The bottom bar shows progress like "Generating 3/7".

---

## Independent upscaling and redrawing (optional)

Connect the main node's sixth output, "初采产物", to **放大和重绘** (Upscale and Redraw), then connect its result to a save node. You can keep the original first-pass save branch. Models, encoder and decoders are wired separately into the new node; the first-pass result carries no models. ⚠️ The node's internal name is still "精修与放大" (that is what saves and links use) while the interface shows "放大和重绘".

- **Upscaling only by default**: the "重绘开关" (Redraw switch) is off, so no models or encoder are needed and the redraw settings stay hidden. Turn it on and Redraw strength, Redraw steps, Redraw seed, Sampler and Scheduler appear. Strength and steps are both sliders (strength 0.1–1, one notch 0.1, default 0.20; steps 2–50, default 20). Strength cannot reach 0 — to skip redrawing entirely, leave the switch off, and the strength sent to the backend is always 0. Redrawing revisits every segment at its original size first and upscales afterwards; the whole first-pass picture is never re-encoded, and there is no third pass after upscaling.
- **Three upscaling methods, and only the matching model list appears**: "放大方式" is ordered H3 latent, pixel model, Lanczos, and **defaults to H3 latent**. H3 latent shows only "H3放大权重", pixel model shows only "像素放大模型", and Lanczos hides both because it needs no model. Scale is a slider too, 1–4, one notch 0.25 (the leftmost 1.0 means no upscaling and needs no weight). Target sizes align to 32; the report shows the actual size. H3 needs weights you supply yourself — take a `.safetensors` from <https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler> into `ComfyUI/models/latent_upscale_models/` (the same file used by Progressive resolution sampling below); nothing is downloaded for you, and the list only shows the H3 upscaling weights that can actually be loaded, so other upscalers in that folder stay hidden. Pixel models are picked on the node too: the list shows the `.pth/.ckpt/.safetensors` files in `ComfyUI/models/upscale_models/`, the same folder and the same models as the official Load Upscale Model node, so no extra loader node is needed.
- **Sound and timing unchanged**: it uses the first-pass audio, frame rate and total frame count as they are — no re-decoding, no speed change, and it never writes back into the first-pass segments or material. The new node has its own overall progress and the per-segment progress stays as it was.
- **Separate caches**: redraw and upscale caches are stored apart from the first-pass ones; the "Clear segment cache" button does not clear them. After swapping weights, increase this node's "缓存失效版本" (cache invalidate version).

### Default: straight through memory

`长视频规划师 → 放大和重绘 → Save`

Without the handoff node, the result is passed through memory inside the same host job: no handoff files, no split jobs, no global cleanup request. The host may still hold the full first-pass picture.

### Optional: insert 初采交接与清理 (First-pass Handoff and Cleanup)

`长视频规划师 → 初采交接与清理 → 放大和重绘 → Save`

Only when the output chain really contains this node does it run in three steps: **first pass and saving, segment by segment to disk → global cleanup request → after the gate passes, the second pass segment by segment and saving**. You never have to add a reader node yourself; a handoff node sitting unconnected does not split the run. Queueing no longer asks you to confirm again — you wired the node in yourself, that was already your decision.

- Use a dedicated, idle queue and don't submit from other windows or from the API at the same time. The cleanup releases host and node memory caches; it never deletes saved videos, handoff files or on-disk caches.
- If the first step fails, the next two don't start. "Cleanup requested" only means requested, not done. Second-pass model loading only begins once the gate passes.
- The handoff node has just two connection points and no buttons at all; the three steps chain automatically and nothing is needed from you in between. To stop, use the host queue panel's Stop — first-pass segments already on disk are not lost, just submit again. If the first pass never starts, the queue is usually busy or paused: clear the host queue and submit again. If the previous handoff already ended (failed, stopped, paused or finished), queueing the same graph again shows a red "the previous handoff has ended" instead of quietly looking accepted. Reloading the page does not resume anything or pick up the latest result.
- Only one clear handoff chain is supported: no batch jobs, no partial runs, no cross-phase links, and no unknown shared nodes. Ordinary queueing never splits your graph automatically; if you call it from the API, use the handoff endpoints.

**Not measured yet**: CPU-level rule checks, isolated host-executor checks and front-end behaviour checks are all in place. Real browser use, image quality and peak memory on the GPU, real global release, and combinations with actual save nodes have not been tested. Also, reading segment by segment does not remove the floor that "the finished video must sit whole in memory", and the estimate doesn't cover every model or intermediate, so it can't promise it will never crash.

---

## Progressive resolution sampling (optional)

Each segment runs its first few denoising steps at a smaller size, is lifted to the target size, and the remaining steps run at full size. **The total number of steps is the same** — what you save is the cost of those early steps. Leave it unplugged and everything is as before.

**How to wire it**: add a **SelfLift加速** node and connect its "SelfLift配置" output to the "SelfLift配置" input at the bottom of the main node. Unconnected = normal one-pass sampling, and saved segments are unaffected.

- **低清缩放** (small-size ratio, 0.25–0.95, default 0.5): small picture = target picture × this value, then aligned to a multiple of 32. At 0.5 the early steps carry about a quarter of the work.
- **高清步数** (full-size steps, default 6): how many steps run at the target size; the small-size steps = the main node's steps minus this. Both parts need at least one step.
- **The sampler must be `euler`**: anything else fails before the run starts and names the bad parameter, instead of quietly running normally.
- **Quality of the lift comes from the 放大模型 picker**: download from <https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler> (by LBH-123-AI, Apache-2.0 — take `fp16.safetensors` or `bf16.safetensors` under `minimax_h3_latent_upscaler_3d_conv_v1/`, about 691 MB each) and put it in `ComfyUI/models/latent_upscale_models/`; the plugin never downloads it. ⚠️ The list only shows the H3 upscaling weights the loader actually accepts — other upscalers in that folder (and any `.pth`) stay hidden.
- **If you don't pick a model you must tick "允许插值降级"**, which lifts by simple interpolation instead. In the reference author's own same-random-seed comparison this route shows **visible artifacts**, not merely a softer picture — use it to check framing and movement, not as a finished shot.
- **Length, frame count and audio are unaffected**: frames come from the timeline span and 24 frames per second, never from the resolution; the lift only changes the picture's size.
- **Effect on saved segments**: installing this version does not invalidate existing caches. But once connected, changing any of 低清缩放 / 高清步数 / 放大模型 makes every segment re-run — those values are counted in each segment's cache identity.
- **Invalid parameters fail before the run**: steps below 2, 高清步数 out of range, the ratio outside its interval, a ratio that after rounding means no actual reduction, or neither a model nor the fallback ticked — each one names the parameter, nothing quietly reverts.

**Is it worth it**: set the environment variable `H3_计时=1` and run the same material with the same random seed twice — once disconnected (full size + `euler`), once connected — then compare the totals in the "段N 采样计时" log lines. A connected run also prints a "段N 渐进采样细分" line splitting small-size sampling, the lift and full-size sampling. ⚠️ Speed-up, lifted quality and peak VRAM still have no GPU measurements.

---

## API Model Setup

AI planning needs a large model with an OpenAI-compatible interface (same code for cloud and local; the work happens outside the plugin and uses no VRAM).

Set it under **ComfyUI Settings → 🎬 长视频规划师 → API 模型配置**:

- **Preset model**: Kimi-K3 is built in (first row, default) — just fill in its API key.
- **Custom models**: add as many rows as you like (Name / address / Model / API key); a radio button picks the active one. Cloud = any OpenAI-compatible service (Moonshot, DeepSeek, …); local = Ollama / LM Studio with `/v1` compatibility turned on.
- **A key per model**: every model stores its own key. When saving, an empty box or one containing `****` means "keep this model's existing key". Keys are tied to the address (protocol + host + port + path): changing the address counts as a new service and needs a fresh key — an old credential is never sent to a new address, and a key is never carried along if a request is redirected somewhere else.
- **Test connectivity**: a button next to each key box sends one tiny request to check name/address/key and shows ✓/✗ on the spot — no need to save first.
- **Global request timeout**: 120–3600 seconds, default 120. Limits connection or consecutive waits without response data for each model request. Transfers can continue while data arrives; there is no overall planning time limit. Model thinking before the first response data also counts as waiting; 300–600 seconds is suggested. Queueing has a separate wait budget, retries receive a fresh network timeout, and connectivity tests remain capped at 30 seconds.

The settings live in `规划/规划器配置.json` (already in `.gitignore` — plain-text keys never get committed).

---

Three text-model choices are saved under **Settings → 🎬 长视频规划师 → API 模型配置 → AI 功能模型**: AI planning, timeline rewriting, and editor prompt optimization. Each defaults to the current model unless separately selected. Save a newly added model before assigning it; deleting an assigned model restores the default. The planning and timeline pages no longer have separate model selectors.

## Skills & Knowledge Base

AI planning designs storyboards; the prompt timeline rewrites frozen storyboards. They use two independent reference directories:

### `Skills/` (content planning references selected automatically)

AI planning selects references from the purpose card, actual input and planning stage. There are no Skill or Auxiliary selectors on the planning page. Cards express the intended use; the planner still distinguishes novels, scripts, factual material and ideas from the supplied content.

Each Chinese skill folder contains 技能卡片.json and 技能说明.md, which declare applicability, dependencies and reference paths. The source receipt lists the references actually used and any truncation. See [the Skills directory guide](Skills/目录说明.md).

### `AI生成提示词/` (shared by timeline prompt generation and editor prompt optimization)

This skill uses `SKILL.md` as its single entry point for shared fidelity, per-second timelines, sound and one-call generation rules. Only the file structure is simplified: detailed rules are retained. H3 additionally loads `参考资料/H3格式.md`, combining the full base and reference guides, terminology and six complete examples; other formats only read the main entry. The loader neither scans extra files nor truncates these references. Both prompt entry points generate each segment with one call and check requirements within that call, without a separate review or repair pass. Existing planning Skills retain responsibility for story, performance and shot design, and image analysis is unchanged. The original eight files are preserved in `文档/归档/AI生成提示词_2026-10-08_重建前.zip`.

---

## Presets

The row above the prompt editor has a **Preset** list for quickly inserting prompt snippets you use often. Whatever you pick is written into the node's "全局提示词" (global prompt) field, which is hidden on the node itself. At run time the backend puts the global prompt **in front of every segment's prompt**, so anything here applies to all segments.

### Save your own snippets as .txt files

Drop a `.txt` into `<plugin-root>/预设/` and it shows up in the Preset list automatically.

- **What gets scanned**: `.txt` files directly under `预设/`, plus `.txt` files **one sub-folder** deep (deeper levels are ignored).
- **Display name**: root files show the file name (minus `.txt`); sub-folder files show `subfolder/filename`.
- **Encoding**: tries `utf-8-sig` → `gbk` → `utf-8` in order, so a file saved from Windows Notepad as ANSI(GBK) reads fine.
- **When it re-scans**: after adding or editing a `.txt`, click the status bar title to collapse and re-open — the list refreshes on expand.

### The three examples that ship with it

| Path | Shown as | Purpose |
|---|---|---|
| `预设/nanobanana分镜.txt` | `nanobanana分镜` | Storyboard prompt template |
| `预设/视频提示词预设/动态图.txt` | `视频提示词预设/动态图` | Brings a still image to life |
| `预设/视频提示词预设/电影风格.txt` | `视频提示词预设/电影风格` | Cinematic look |

### How an old workflow is recognised

When a node is loaded from a workflow file, the global prompt is matched automatically: if the whole text is a preset, that preset is selected; anything that doesn't match stays in place as leftover text, so nothing is silently lost.

---

## Plan data (save and load full setups)

At the **far right** of the toolbar row above the prompt editor are the "Plan data" list (Load) and the "Save" button. Use them to keep the whole node setup in one file and bring it back later with one click.

### What gets saved

A plan contains:

- Every visible input on the node: task type, output resolution, megapixels, frame rate, steps, sampler, scheduler (the "缓存失效版本" is a temporary lever to force old segments to re-run and is **not** saved into plans).
- Every hidden input: global prompt (what a preset writes into it), shared reference material, gradient transition, run selection.
- The whole timeline (each segment's task / prompt / start / end / run / material).
- The reference material list (image / audio / video file names).
- The clip draft (the AI Planning rehearsal draft, form text included) is saved and restored with the plan; if a plan has no draft, an unrelated old draft on the node is cleared on load.

Location: `<plugin-root>/计划数据/<name>.json`. The folder is created when needed — you don't have to make it.

### How to save

1. Click "Save".
2. Type a plan name (without `.json`).
3. An existing name asks you to confirm the overwrite; on overwrite the original "creation time" is kept.

### How to load

1. Pick an entry from the "(Load)" list.
2. If the node already has segments, you are asked to confirm the overwrite.
3. After loading, everything re-syncs (timeline rebuilt, prompt filled back, material list refreshed).
4. The list resets to the "(Load)" placeholder, so picking the same entry again loads it again.

### Naming rules

Plan names are checked **twice** (the page checks first so you see it immediately, and the backend checks again):

- Not empty, not just spaces.
- No `\ / : * ? " < > |` and no control characters (including newlines and tabs).
- Not starting or ending with a dot or a space (Windows quietly removes them).
- Not `.` / `..` / a Windows reserved name (CON/PRN/AUX/NUL/COM1-9/LPT1-9).
- 100 characters or fewer.

### If a material file is gone

On load the backend checks against the material folder (`ComfyUI/input/`):

- A file the plan references that has since been deleted **stays where it is, it is not removed** — it is just recorded as a "missing material". (Those positions are what the `<Picture N>` tags point at; quietly dropping one would shift the rest and mis-tag them.)
- The page says "Skipped N missing reference materials: xxx, yyy", and loading is **not** aborted.
- The real block happens before generation: the pre-run check names and stops any segment that is set to run and references a missing file; other segments are unaffected.

So even when a plan points at material that no longer exists, you see the problem straight away instead of blowing up halfway after Queue Prompt.

### Common uses

- Keep a setup you use often (say "9:16 vertical + 20 steps + cinematic style + one storyboard template") as a plan and reuse it in one click.
- Share a complete recipe with teammates (together with the `.txt` templates under `预设/`).
- Archive an important timeline — more complete than copying the node's contents, because a plan also captures every hidden input.

---

## What if I cancel or hit an error halfway

Segments that already finished **are not lost** — they are on disk.

The segment that was halfway **is lost** and has to be redone.

If you just want the finished segments stitched out:

1. Open the timeline panel.
2. Turn **off** the Run switch on every segment that didn't finish and every segment that hasn't started.
3. Leave it **on** only for the segments that finished. (You can turn those off too — anything with a saved copy still gets stitched in.)
4. Click Queue Prompt again.

This run hits the saved copy for every segment and the video is ready in tens of seconds. The console report says "Segment N: cache hit" for each reused one.

---

## Hardware requirements

| Item | Recommended |
|---|---|
| GPU | 12 GB VRAM minimum, 16 GB safer |
| RAM | 32 GB minimum (stitching uses system memory) |
| Disk | 5 GB+ free for the cache |
| ComfyUI | A version supporting the V3 node interface and shipping the official MiniMax H3 nodes |
| Models | MiniMax H3 main model + Qwen3-VL encoder + video VAE + audio VAE |

---

## Installation

**Option A: git clone (recommended)**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/a63976659/ComfyUI-AI-Video-Planner
```

> The folder name is not fixed: ComfyUI scans every sub-folder of `custom_nodes/`. The repo name is recommended; rename it if you prefer.

**Option B: put it there yourself**

Download the zip, unzip it, place the whole folder at `ComfyUI/custom_nodes/ComfyUI-AI-Video-Planner/` (name is up to you), and restart ComfyUI.

**Optional dependencies** (uncomment them in `requirements.txt`, then run `pip install -r requirements.txt`):

- `imageio` + `imageio-ffmpeg` — reading reference videos (only needed by reference-to-video and video-to-video)
- `scenedetect` + `opencv-python-headless` — automatic shot splitting of a source video (only needed by smart shot detection)
- `pytest` — running the tests

**Check it worked:**

- ComfyUI's startup log has lines starting with `[长视频规划师]`
- Searching `长视频规划师` in the node picker finds the main node
- The Video Planner panel is at the bottom of the page

---

## Things to know

**Where the saved segments live**

By default `%TEMP%/长视频规划师_段缓存/`. To move it, set the environment variable `长视频规划师_段缓存_DIR`.

Old cache folders from previous versions are deleted automatically when the plugin starts — no manual cleanup.

**How the size is decided**

Two settings decide it together: "输出分辨率" (aspect ratio) and "百万像素" (how detailed). The default `0.4 megapixels + 16:9` gives **864×480**.

Bigger megapixels need more VRAM. `4.0 + 21:9` reaches 3136×1344 — know your limits.

**What "frame rate" means here**

The "帧率" box on the node is only a label written into the output video file. Generation always runs at **24 frames per second** (fixed by the official model). Want slow-motion or fast-motion? Change the frame-rate number. Want to change the real movement speed? Change the segment's length. Changing it also **does not affect saved segments** (since h3-7 the playback frame rate isn't counted in the cache identity).

**How segments join**

The "渐变过渡" switch controls it (off by default):

- **Off** (default): every segment is generated on its own, seams are plain hard cuts, no transition work at all.
- **On**: the last 22 frames and about the last second of audio of the previous segment are carried into the next as conditions (the internal data is passed straight across, without going through picture and back), so the next segment continues from the previous ending. Seams are still hard cuts with no overlapping picture — only the opening of the continuation has its tone and brightness eased toward the previous tail (the two clips are never blended).

If you see smearing, ghosting or artifacts, first turn "渐变过渡" off and check whether it's the model itself.

⚠️ **Switching this invalidates every segment's cache and re-runs all of them** (the number of frames used for continuity is part of each segment's cache identity, so it changes as soon as the switch changes). Already-finished segments are redone too — this is **not** just re-stitching the seams. Allow time for a full run before switching.

**After swapping the model**

To have every segment re-run on a new model you don't need to delete folders by hand: click "+1" beside "失效版本" on the node's timeline toolbar, or type a number and press Enter, and all old segments are invalidated. The duplicate "缓存失效版本" widget above the timeline is hidden; its value is still saved with the workflow and submitted for execution. The same strip's "Clear segment cache" button deletes the cache files on disk directly (irreversible, this machine only, never touches other files).

**Start a new creation**: click "重置" (Reset) immediately after the timeline's crop button, then confirm in the dialog. This restores the current node's default parameters and clears its segments, material references, planning, prompts, production project, and unsaved forms across all four tabs. Node position and connections, shared API settings, presets, and files on disk are preserved; other nodes are unaffected. Reset is blocked while AI, generation, or production tasks are unfinished. Stop them or wait for completion first. Reset is recorded as one workflow change for the host's Undo action, and late results from older tasks cannot populate the new project.

**Can I connect only one model input?**

Yes. The plugin only checks the models needed by **the tasks actually used in your current timeline**; if one is missing it names the exact task and model. Everything else is left alone.

**A segment without audio is padded with silence**

If one segment has no audio while others do, the audio track doesn't skip the missing one — it pads that segment with silence of the same length, so the audio total stays exactly aligned with the video and never drifts. The report adds a line: "N/M segments have no audio; padded with equal-length silence to keep A/V aligned". If no segment has audio, the output is silent.

**The memory floor for a long video**

The node outputs the finished video as one whole block of pictures, so the entire film has to sit in memory while stitching (the node interface makes this unavoidable). For scale: 180 seconds at 768×1344 needs roughly 50 GB of memory. So "32 GB RAM minimum" only covers short pieces. The pre-run "memory budget" line estimates your specific scale up front, and `H3_内存硬限额_GiB` can stop it cleanly before decoding when you're over the cap, instead of waiting for a crash.

**Seeing what's slow (off by default)**

Set the environment variable `H3_计时=1` and the log breaks each segment into four parts (reference decode / conditioning / continuity with the previous segment / sampler), plus cache read-write, decode and stitch durations, and the memory peak — for finding out "what's slow". Off by default; purely observational, it never changes any output or behaviour.

---

## Changelog

**2026-10-07**

- Completed shared operation locking across planning, prompt rewriting, dialogue timing, fill, load/import, episodes and planning materials. Prompt rewriting uses the batch snapshot submitted at click time; draft editing stays locked for the run while browsing remains available, then unlocks when the request ends. See the [lock and snapshot record (Chinese)](文档/技术实现/2026-10-07-跨页面操作锁与提示词快照.md).

- Timeline saves, subtitle toggles and speech timing no longer append the old reading-instruction template. Dialogue and timing remain in structured fields. Old drafts are cleaned on read and save without removing H3 content, dialogue, material bindings or authored descriptions; timing undo remains available.

- Timeline prompt rewriting and review now run one segment at a time, with immediate incremental updates. Context is limited to the theme, current goal and required local evidence/constraints. Added standalone-description validation and invalidated old review fingerprints. Both H3 and natural-language compilation follow the same boundary.

- Planning now returns available storyboards after partial failure. Compiled shots are saved before review; later batch, episode or review failures return existing work with a “Needs improvement” notice, reasons, suggestions and missing units/episodes. Source, material-slot, timeline and per-shot capacity checks remain active; shots are never duplicated to fill gaps. Cancellation or no valid shots still stops output. Notices persist with drafts and checkpoints. 302 backend and 29 frontend checks passed; no new cloud test was performed.

- Fixed execution-model settings being misread as a conflict with neutral JSON output. Planning requests retain actual capability constraints without model-name or proprietary-syntax settings. Resolved input type, genre and treatment now stay consistent across stages. Brief ideas support creative completion, with a general audience when unspecified. Protocol misreadings get one targeted repair without discarding genuine conflicts or restarting the episode. Added five regressions; 286 related checks passed, with no new cloud calls.

- AI planning treats total duration as a target, allowing changes needed for complete content, actions and dialogue. It no longer fails solely for exceeding the target or lacking enough shots to fill it; per-shot execution limits and user segment caps remain. The final 24-shot poetry response now compiles to 300.67 seconds offline; 128 planning/duration checks and 48 network/stage checks passed. Full cloud acceptance has not been rerun. The live-test runner now uses the production global network-wait timeout instead of separate 150-second request and 20-minute overall limits.

- Fixed nested source-ID wrappers in material-free text-to-video planning. One layer of known ID strings is unwrapped without changing order or dropping sources. Self-reported source-format errors use one targeted repair rather than restarting the episode three times. Replayed the actual poetry-planning failures offline and added 11 regressions; unknown IDs, empty wrappers, deeper nesting and real requirement conflicts still fail. No new cloud requests were made.

- Original media now use provider-issued model-bound temporary URLs and streamed uploads instead of repeated Base64 payloads. Removed local material/response size caps, text-length and input-count caps, and fixed model-name restrictions; legacy response budgets no longer block requests. Provider errors preserve their specific causes. Alibaba Cloud expires temporary media, while task exit releases local snapshots. 470 related regressions passed locally; private-material cloud testing was not performed in this run.

- Added original-material input for the configured Qwen3.8-omni planning model. Images, audio and video use original bytes; TXT/MD files are uploaded to Alibaba Cloud Files, with verbatim text supplied to Omni without paraphrasing. Transfers are restricted to the task's selected list and authorized endpoint. Added source fingerprints, changed-material recovery checks, remote-document cleanup and complete Omni stream validation. Added 19 original-input regressions; 434 related backend checks passed. Full planning was exercised through a local HTTP mock; private-material cloud testing was not performed. See the [implementation and limitations (Chinese)](文档/技术实现/2026-10-07-规划素材原件发送.md).

- Original-text understanding, chapter understanding and consolidation now select source IDs; the program restores actual ranges and verbatim quotations. Source field errors no longer masquerade as requirement conflicts, and persistent source errors stop after the existing single repair attempt rather than restarting episode planning. Runtime records include the loaded source protocol version and request diagnostics to distinguish saved UI data from accepted checkpoints. Real conflicts, source coverage and material validation remain enforced. Added 33 regressions; the latest related checks passed: 409 backend and 38 frontend. Actual failures were replayed offline without new paid requests; the real-model end-to-end run remains unverified. See the [fix and cache record (Chinese)](文档/技术实现/2026-10-07-多来源内容数量修复.md).

- Fixed chapter understanding reporting its own empty source objects as requirement conflicts. Quotation examples and structured candidates now share actual source text; verified format misclassifications use the existing single repair attempt, while real conflicts and repeated failures still stop. Added 20 regressions; 362 related local checks passed, including replay of the actual failed response without new paid requests. Restart ComfyUI to load the backend fix. See the [fix record (Chinese)](文档/技术实现/2026-10-07-多来源内容数量修复.md).

- Content summaries now select validated source IDs, with original quotations restored by the program; missing-shot errors identify the omitted units and content. Fixed false missing-lyrics errors caused by line breaks, slashes and punctuation in MV singing sections. Missing or altered words and reordered lyrics still fail, while ordinary dialogue and source-quotation checks retain their rules. Live testing reached 40 cumulative requests: replaying the first 12 shots passed backend validation after the fix, but the second batch and full semantic review remain untested. The latest 198 targeted regressions passed. See the [live-test and fix record (Chinese)](文档/技术实现/2026-10-07-多来源内容数量修复.md).

- Music-video planning does not require a separate complete lyrics file. Lyrics in a storyboard may explain visuals and singer assignments; they need not all become mandatory dialogue. Added source checks for numbered performance sections from opening to ending, with empty mandatory-dialogue lists still allowed. Lossless text wrappers and original newline restoration are supported; fabricated quotes remain invalid. All 24 authorized live requests were used: full-text understanding and episode planning passed, but the complete workflow did not. Fixed summary failures incorrectly restarting local requirements analysis; all 441 related local planning regressions passed. See the [live-test and fix record (Chinese)](文档/技术实现/2026-10-07-多来源内容数量修复.md).

- Fixed empty MV headings entering mandatory-dialogue candidates. Candidate extraction, structured output and backend validation now share nonempty-string and length rules; errors identify the unit/item, and long source speech is split without truncation. Invalid model responses are saved separately from accepted checkpoints. Added 16 regressions; 345 related planning checks passed. The real model has not been retested in this run. See the [fix record (Chinese)](文档/技术实现/2026-10-07-多来源内容数量修复.md).
- Each generation now preserves a separate history archive. An equally sized Import Planning button restores the first episode, episode selection and four stage results. Data Management supports saving planning/plan JSON packages, automatic folder imports and deletion with two confirmations. Active and resumable projects are protected; shared packages include all episodes and associated planning archives, with new local access credentials on import.
- Fixed chapter understanding mistaking text loaded in other ranges for missing uploads. Requests include an actual loaded-text inventory; explicit stage-boundary mistakes use the existing single repair attempt, while real missing inputs and content conflicts still stop planning. Added 6 regressions; 315 related backend checks passed. This new path has not yet been retested with the real model; see the [fix record (Chinese)](文档/技术实现/2026-10-07-多来源内容数量修复.md).
- Aligned content-count contracts for multi-source planning. Structured output now receives each stage's unit limits; requirements-only ranges retain constraint units and source references, and count errors report the actual returned size. Added 13 targeted regressions; 309 related backend checks passed. See the [content-count fix record (Chinese)](文档/技术实现/2026-10-07-多来源内容数量修复.md) for real-model verification status.
- All nine requirement cards passed real planning tests with the configured Qwen3.8 model. Fixed ordinary colon headings being mistaken for scripts, production instructions becoming mandatory dialogue, and missing shots in structured output. Tests used original synthetic text with automatic duration allocation (0), without uploading private materials. Related regressions passed: 296 backend and 407 frontend checks. See the [nine-type test record (Chinese)](文档/技术实现/2026-10-07-九类需求规划实测.md) for scope and limitations.
- Corrected automatic planning review misclassifying reference-to-video media capabilities. Reviews now receive the independent image, video and audio slot rules plus backend validation results. Missing character identity references and actual continuity defects still require repair; review gates and retry limits remain intact.
- Automatic reviews require verifiable source or field quotations, with actual short excerpts enumerated for the verified model. Generation difficulty, aesthetic preferences and previous errors are not current defects. Shot-only repairs retain the accepted content plan. Compiled prompts preserve existing actions, characters and camera instructions so singing assignments and POV requirements reach downstream stages.
- Batch reviews restrict issue shot numbers to the current batch, preventing repaired ending issues from contaminating other batches. Series reviews receive actual per-shot durations and check the intersection of suggested durations and model limits, avoiding false conflicts for already valid allocations.
- Restricted shot references and material-role filenames to actual uploaded files, with errors identifying the shot and unknown filenames. Aligned structured source limits, shot counts and review text lengths with the planning contract. Character and scene requirements are integrated into the script instead of creating additional introductions or repeated openings and endings.
- Fixed episode planning returning more episodes than available source ranges. Episode limits now follow the actual range count, distinguishing lyric sections and shots from episodes while retaining complete source coverage and one targeted repair.
- Added structured episode output for the verified DashScope Qwen3.8 planning model, constraining episode count, range-array length and actual IDs. Other models retain text instructions and backend validation. All 43 regression checks for that source-range fix passed.

**2026-10-06**

- Node segment cards split available height 1:1 between image and prompt areas. Prompt previews no longer stop at two lines; taller nodes show more text while preserving font size and line breaks.
- Reordered the editor controls to Optimize prompt, Audit tags, Shared across segments, Clear materials, Disable soundtrack reference and Use source soundtrack. Sharing is indicated by the button's active state. Fixed Audit tags being hidden with the reference area in text-to-video mode.
- Made the four AI Planning stage cards shorter and narrower while retaining progress and result access.
- Preserved requirements input during planning. Total length 0 explicitly means automatic allocation, fixing false zero-duration conflicts; clarified real source-range constraints and episode-specific errors for long-form planning.
- Automatically received generated videos and voice tracks enter production clips only, keeping AI Planning materials separate.
- Updated both language guides for the four tabs and model configuration. The node-card change passed nine browser size checks and 71 related regression checks.

**2026-10-05**

- Refocused Video Production on editing and exporting generated results. It receives the final actual workflow video without duplicate first-pass/redraw imports; the first import sets the canvas, and voice plus sentence subtitles follow clip trims, order and enable state. Workflow generation, entities and standalone voice generation moved out; post-production, previews, recovery and backups remain.
- Added shot purpose, performance, camera movement, spatial continuity, start/end states, reference roles and action timing, loaded by stage and content. Existing storyboards remain importable without forced story additions.
- Added dependency-based incremental prompt updates: unchanged accepted segments are reused, while changed segments and affected neighbors are rewritten. Manual edits are protected, and retries use previous review suggestions.
- Integrated 71 shot and genre rule sets into existing skills on demand, with scoped local-reference search, optional auxiliary images and target-video-model capability settings. Runtime skill text is separated from provenance; models are not downloaded automatically. See [shot design and incremental updates](文档/技术实现/2026-10-05-镜头设计增强与局部更新.md), [specialized rules](文档/技术实现/2026-10-05-七十一项专项融合与自动制作闭环.md) and [post-production changes](文档/技术实现/2026-10-05-视频制作后期调整说明.md) (Chinese).
- Added editor prompt optimization using the same skill as timeline prompt generation. It rewrites from text, task type and actual first/last-frame bindings, replacing the current segment prompt only after validation.
- Moved model selections for AI planning, timeline rewriting and editor prompt optimization into API Model Setup → AI 功能模型, with a saved choice for each function.
- Fixed missing video soundtracks in the three reference task types and the `<Audio 1>` error when only a video with sound was uploaded; first-pass generation, redrawing, AI rewriting and reference tag lists now agree.
- Shared video, paired soundtracks and standalone audio are cropped to each segment's time window. Video reads seek by presentation time, reducing repeated decoding and frame-cache memory.
- Added mutually exclusive "禁用原声" and "原声输出" controls, with existing behavior preserved by default: disable soundtrack references and keep generated audio, or replace output with cropped source audio.
- Source soundtrack output skips video-audio VAE encoding and generated-audio decoding, while keeping the required audio VAE input and joint audio/video sampling. Relevant automated regressions pass; GPU finished-video and timing comparisons remain unverified.

**2026-10-04**

- Replaced the AI Planning form with one requirements box and nine purpose cards, defaulting to automatic detection. Requirements support `@` material references, legacy plans retain their input, and stale results cannot overwrite newer edits. Four equal-width areas and a compact 3-by-3 purpose grid organize the page.
- Added four result stages: source analysis, episode planning, reference generation and storyboarding. Actual completion unlocks content cards, episode lists, reference galleries and accepted storyboards; completed results remain available after stopping or failure.
- Non-text-to-video tasks can optionally generate character, scene and prop references through a separately configured image API. Style, actual image observations and checkpoints are saved; completed images are reused, without automatic model switching or paid-request retries on failure.
- Unified timeline rewriting under the general prompt rewriting skill and removed Skill and Auxiliary selectors. Story, dialogue, timing and material bindings stay fixed; rule checks and independent semantic review determine which results are written back.
- Limited repairs to failed segments and one round, freezing accepted segments. Defaults are five segments per batch, at most four writing/review requests, 180 seconds per batch and 90 seconds per request. Timeouts, disconnections and stops preserve completed batches and original text elsewhere; repeated guide loading and review were reduced.
- Removed the fixed overall long-form planning deadline while retaining network-wait timeouts, cumulative request budgets and revision limits. See the [purpose-card guide](文档/技术实现/2026-10-04-AI规划需求卡片.md), [reference-image guide](文档/技术实现/2026-10-04-AI规划自动参考图.md) and [rewriting timeout and stop rules](文档/技术实现/2026-10-04-提示词改写耗时与停止边界修复.md) (Chinese).

**2026-10-03**

- Added full-source range-by-range understanding, layered summaries, automatic episode planning and shared character/scene information for long text. Episodes cover the source in order and undergo whole-story review; summaries do not replace the original text.
- Added persistent planning checkpoints, reconnection and compatible resume after restart, reusing saved results. Episode and whole-story reviews each allow up to three rounds; exhaustion preserves issues and checkpoints without replacing the draft. Cumulative request counts and access credentials persist with the project.
- Combined generation and stopping in one button, clearing active progress immediately on stop. Episode switching preserves edits, and replanning retains the two most recent draft versions for recovery. Removed execution-backend and duplicate shot-duration controls from planning settings.
- Added task/reference mapping checks, chapter/time/tag/dialogue rules, independent semantic review and local repairs to prompt rewriting. Text acceptance does not certify finished-video quality; the October 4 entry supersedes the original request limits.
- Added the fourth tab, Video Production, and the Video Production Output node. The initial version supported actual media, generic workflows, voice/subtitles, composition previews, MP4 export, resumable tasks and ZIP project backups. On October 5 the production page was narrowed to editing generated results; use that day's guide for current controls.
- Removed the separate on-screen subtitle field from the prompt timeline. Dialogue/narration supplies timing and spoken text; post-production subtitles are managed in Video Production, and disabling subtitles does not silence dialogue. See [long-form planning and recovery](文档/技术实现/2026-10-03-长剧自动规划与断点恢复.md) and [the initial production guide](文档/技术实现/2026-10-03-通用视频制作使用说明.md) (Chinese).

**2026-10-02**

- Added total-length 0 for automatic planning: actual duration accumulates from content-driven shot counts, actions and speech estimates rather than stretching to the default three minutes or filling the shot limit. The draft retains the automatic setting.
- Added dialogue timing to the prompt timeline, with live slow/normal/fast estimates, speech rate, punctuation pauses, padding, minimum action duration and parallel/sequential action budgets. Long dialogue splits at sentence boundaries with balanced segment lengths.
- Timing changes are previewed before confirmation and update only the draft and planning duration. Undo remains available until further editing, settings persist with the project, and Fill into node is still required before generation.
- Existing recordings can be measured and previewed; recordings over 15 seconds require sentence-level SRT or JSON timestamps. Output can use actual source windows with silence padding at 24 fps, without guaranteeing generated lip synchronization. See [dialogue timing and voice alignment](文档/技术实现/2026-10-02-台词估时与配音对齐.md) (Chinese).

**2026-10-01**

- Introduced staged Chinese Skills for requirement routing, content understanding, batched shot planning and coverage checks. References are chosen from input and genre; planning Skill/Auxiliary selectors were removed, and receipts show the references actually used.
- Planning first writes the clip draft with source ranges, character/scene information and required dialogue, leaving execution-node data unchanged until applied. Conflicts or failed reviews preserve the draft. The original long-text scope and recovery limits were superseded by full-source episodes and persistent checkpoints on October 3.
- While AI prompts are being generated, the clip timeline is no longer frozen as a whole: scrolling, zooming, panning, dragging the playhead and opening a segment card to read it all work as usual — only the actions that change structure (trim, split, delete, drag-to-reorder, the enable switch, duration and subtitle editing, Fill Nodes) are un-clickable during generation.
- Same change: the things that would have no effect if clicked during generation now dim out as well — the per-segment duration box, the three Skill/Auxiliary-style/Model dropdowns in the generate row, the "disable subtitles" switch and the drag handles at both ends of a card — so nothing looks clickable but does nothing.
- Same change: each batch is written back and its segment cards refresh as soon as that batch finishes, so you can read the results while the remaining batches are still running.
- The structure types for long videos went from 9 to 20: added Development, Transition, Explanation, Case, Evidence, Build-up, Suspense, Wind-down, Aftertaste, Summary and Teaser, each with its own background colour — the Structure dropdown in the right-hand per-segment panel, the colour bar on the card and the AI side all pick it up at once.
- The first segment is still "Hook". The last one is no longer limited to "Ending / CTA": any of the five ending-flavoured types is accepted — "Ending", "CTA", "Summary", "Aftertaste" or "Teaser" — and anything else in that slot (e.g. "Climax", "Development") is rewritten to "Ending"; middle segments are chosen by the AI from the 20.
- Fixed a problem that wasn't caused by this plugin: another custom node installed on this machine rewrites every range slider globally, which had stretched the zoom sliders above both timelines to the full row width so they covered the text on the right. The clip-timeline slider is now 61px and the in-node one 43px, and the text is no longer covered — a plain page refresh is enough, no host restart needed.
- Same change: the "Megapixels" slider on the prompt editing page was stretched the same way and pushed the "Megapixels" label onto two lines. It is back to the native slider look at 110px and the label sits on one line again.
- Same change: when a slider is greyed out and un-draggable, the mouse pointer used to be forced back into the "clickable" shape; it now shows the not-allowed pointer.

**2026-09-30**

- The zoom slider no longer sits on top of the "N segments" label: when the panel narrows it scrolls along with the rest of the toolbar (fixed on both the Prompt Timeline page and the in-node timeline).
- The AI Planning material list became square thumbnails like the Prompt Editor page: images and videos show a cover, audio shows a note, text shows a document icon, with a type mark on each corner and an × to delete; add material with the "+" tile or by dragging files in. They were briefly grouped into four type groups and that was dropped the same day on request — all four types now share one wall and the corner mark tells them apart, with no scrolling between groups.
- The AI Planning page was re-divided: material area to requirements area went from 1:1 to 2:3, and the requirements area split again — form fields on the left half, the whole right half given to the "Detailed Requirements" box, so long briefs finally have room.
- Material thumbnails are now click-to-view: on both the AI Planning and Prompt Editor pages, clicking an image / video / audio tile opens a pop-up in the middle of the screen — images enlarge, video and audio play with their own controls (seeking included); text files on the planning page open there too and show the body (first 64 KB only, with a note when longer). The × , a click on the area around it, or Esc all close it; the small × in a tile's corner still only deletes and doesn't open a preview.
- The "Content" box on the AI Planning page now supports typing `@` to reference material uploaded on the left: `@` opens the material list (a type icon per row, keep typing to filter by name, expanding upward by default), and clicking or pressing Enter inserts an `@name` reference with its own background colour, exactly like the references on the Prompt Editor page. Giving inline text a background meant changing the plain-text box into a rich-text one — the text stored in the draft and sent to the backend is unchanged character for character; the trade-off is that a wrong reference is deleted as a whole block with Backspace, and the browser's own undo only covers typed characters. Once a material is deleted, its old references fall back to plain text: coloured = the backend knows this name, plain = it doesn't.
- The type icons changed: images use a colour framed picture 🖼️ and audio a green music note ♪ (of the four, only the note is a text symbol that can be coloured; the rest are emoji). That icon table exists once and is shared by the wall marks and the `@` list. Hovering a tile now shows the full file name immediately, so long names are no longer cut off.
- A "Clear material" button sits at the right end of the planning material title row: one click removes every planning material of this node and also drops the references from the global list and from each segment's "used material"; files on disk stay. Wiping a whole wall at once is irreversible, so the button asks for confirmation, and it is greyed out when there is nothing to clear. Two points were corrected the same day on feedback — the button moved to the far right, and the view repaints straight after confirming (it used to only show a notice, which looked like nothing happened).
- The audio placeholder on the Prompt Editor page was matched to the planning wall (green ♪, its old blue backing dropped) per your ruling to "unify the two walls". A related display lag — after clearing material on another page, segment cards and old references still show the removed names — you ruled to leave as is, since fixing it would cost caret position and native undo.
- Same-day self-checks: 535 front-end checks all pass (17 added), 24 backend material checks all pass, style check clean, colour-follows-theme check now covers 15 files. No backend changes at all, so a page refresh is enough and ComfyUI needs no restart; how playback, enlargement and the `@` references actually feel is left for you to check in the browser.

**2026-09-29**

- AI prompt generation now works in batches: with many segments you no longer wait for one all-at-once request — each batch is written back as it lands with progress shown, and later batches carry the earlier text so it stays connected.
- Same-day live test: a real ComfyUI session ran a 6-segment draft through two batches — batch 1 wrote back as soon as it finished and the button showed "1/2 batches", batch 2 followed; on failure the draft was confirmed unchanged and the button restored itself.
- Same-day second round (working through everything a full impact check turned up): each batch now refreshes its own segment cards the moment it lands instead of waiting for the whole run; if an AI request is already in flight you get a dialog first instead of a second call running at the same time; the "k/N batches" N is now computed from the segments actually being generated, so duplicate or stale segment numbers can no longer inflate it; and the server side gained two safety nets (an abnormal exit still sends a closing signal, and a connection that fails to open no longer stays hung), plus an old check and old parameters left over from the pre-batching design were removed once nothing used them.
- The status bar is now three tabs: a "Prompt Timeline" tab sits between "AI Planning" and "Prompt Editing" — the clip timeline and per-segment editing moved there, timeline on the left keeping its width, the editing panel on the right filling the rest. The AI Planning page splits evenly: a material upload area on the left (images, videos, audio, text files) and a large "Detailed Requirements" box under the form on the right.
- Material and detailed requirements now go into planning: the upload list and the requirements are sent with the generate-plan request, the AI assigns used material per segment (marked 🎞 on the card), and applying the plan drops each material into the node's matching image/video/audio input; text-file bodies are truncated and put into the prompt, and material names the AI invented are filtered out and counted.
- Post-review fix: after generating a plan the grey receipt line also reports material — how many went in, how many invented names were filtered, how many bodies were truncated or missing — and it appears on its own (starting "素材使用：") when material was used without any skill doc.
- Same-day review of the page split and material feature, fixed one by one after a full impact check: the Prompt Timeline page repaints after generating a plan, the narrow-window layout no longer collapses, material names reject illegal forms and Windows reserved names, material beyond the inputs is cut to 9 images / 3 videos / 3 audio, and text files are read with a size limit with the counting corrected (the marker no longer eats into the budget, and one file hitting several limits counts once) — every change tightens or corrects; nothing was loosened.
- Same-day self-checks: 518 front-end checks all pass; the relevant backend checks pass when measured; style check clean. The full backend suite still can't run on this machine because one host module is missing, and on-screen behaviour awaits your browser test.

**2026-09-28**

- The clip timeline gained a "禁用字幕" (disable subtitles) checkbox, to the left of 台词估时: once ticked, "✨ AI generate prompts" no longer uploads your subtitles and the AI no longer puts on-screen text into the shots — the subtitle text itself still works for estimating length.
- Same-day fix: when the box has never been ticked, editing on the planning page and generating a plan no longer write a stray "禁用字幕: false" into the draft. Tests now also pin that the switch survives re-timing and plan save/load round trips.
- Second same-day review: while no segments exist at all, "禁用字幕" is greyed out just like 台词估时, so a draft holding nothing but the switch can no longer be filed as an empty plan and dropped on load.

**2026-09-27**

- Queueing the same graph after a handoff has already ended now tells you to submit again instead of looking accepted.
- The handoff node now says plainly that a late start usually means the queue is busy or paused — clear it and queue again.
- Fixed "Queue does nothing after adding the handoff node": extra options on video-saving nodes and pure display nodes at the end of the chain are no longer treated as unsupported.
- A rejected handoff now names the node and the rule it broke instead of one vague sentence.
- Queueing no longer asks you to confirm the handoff: you wired the node in yourself, so a checked graph starts straight away. (⚠️ Entries below from 2026-09-26/25 that mention this confirmation are voided by this change.)
- Fixed "the node has an input the host doesn't know" after adding the handoff node: the on-node Edit button and the embedded timeline are no longer submitted as parameters, and existing workflows still open.
- The 比例模式 dropdown on the prompt page is no longer mistaken by the self-checks for a fourth frame selector; the look is unchanged and two long-standing failures pass again.
- A Show Text node at the end of the handoff chain no longer blocks queueing, while a missing input on a node inside the chain is still named.
- "精修与放大" was renamed "放大和重绘", every "精修" label became "重绘", old saves are still recognised, a new "重绘开关" was added that defaults to off, strength and steps became sliders, the controls were reordered, and the pixel model is now picked on the node. (⚠️ Control order changed — re-check the parameters in old workflows.)
- Four follow-ups from re-reviewing that node: pasted nodes show the right values, an unreadable model folder only leaves "未选择" instead of breaking the whole node, the error names the dropdown you can actually see, and the scale floor was raised to 1.1 at the time (⚠️ that floor moved twice more the same day — trust the newest entry).
- Four more changes to the same node: scale became a slider too, one drag of the strength slider is a visible step, steps narrowed to 2–50, and the node keeps its width when you switch modes or reload (new nodes open twice as wide). (⚠️ Old workflows saved with 1 step are rejected — set it to 2 or more.)
- The scale slider's step went back to 0.25, because one notch of the 0.1 step was stored a hair too low and ended up upscaling one grid less. ⚠️ The floor moved again the same day — see the next entry.
- The scale floor was briefly raised to 1.25, since 1.0 means no upscaling and has no business on an upscaling node. (⚠️ Superseded by the next entry.)
- The scale floor went back to 1.0 as you ruled: all the way left means no upscaling, that notch needs no upscale weight, and old saves at 1.0 / 1.1 / 1.25 queue again.
- The lowest redraw strength is now 0.1 instead of 0, so "no redraw at all" has a single switch. (⚠️ An old save below 0.1 is rejected even with the switch off — move it into 0.1–1; the no-redraw result is unchanged.)
- On the prompt page the image-to-video aspect-mode dropdown now sits next to the first-frame control; nothing else moved.
- A rejected handoff now leaves the real reason in the running log and in the job status instead of one unrecognisable error; the common mistake is the audio line — when 放大和重绘 feeds the generator directly, take audio from its own output. (⚠️ The on-screen message itself didn't change this round, so the log is still where you read it.)

**2026-09-26**

- Cancelling the handoff confirmation no longer raises an error, and nothing gets queued.
- The "Overall progress" readout is display-only now and is no longer saved into workflow files.
- A cleanup failure now stops the job in a clear finished state instead of stalling silently; just submit again.
- Half-step scales such as 1.25× no longer leave a dimension unchanged; half steps always round up.
- A leftover temporary cache file can no longer mask the real error, so failures report their original cause.
- Batch queueing, timeouts and path checks were tightened; false permission-boundary rejections and reused queue numbers are fixed.
- Editing the canvas right after confirming a handoff no longer loses the task — it keeps running.
- A broken cache file is now named in the error, together with a note that the "Clear segment cache" button does not cover that folder.
- If a handoff write fails halfway, the partial output folder is only reported; nothing is deleted automatically.
- A server error from the handoff interface now leaves the full failure detail in the server log.
- Reloading this plugin without restarting ComfyUI no longer registers the same nodes twice.
- Added the optional **SelfLift加速** node: when connected, each segment denoises a few steps at a smaller size, lifts to the target size, then runs the rest — total steps stay the same. Without the connection, nothing changes.
- Enabling it requires the main node's sampler to be `euler`; invalid settings fail before the run and name the bad parameter instead of quietly falling back.
- Lift quality depends on the **放大模型** picker — the download link and folder are now written into both "Independent upscaling and redrawing" and "Progressive resolution sampling" above; with no model you must tick "允许插值降级", and that route gives visible artifacts, not just softer detail. (⚠️ Since 2026-09-27 the first section is titled "Independent upscaling and redrawing".)
- The 放大模型 list now shows only the H3 upscaling weights that can actually be loaded; unsuitable ones in the same folder are hidden. That node's label was also unified from "放大权重" to "放大模型".
- Existing saved segments are not invalidated by this change; the actual time saved has not been measured on a GPU yet.
- "⬆ Fill into node" on the AI Planning page now fills by enabled segments: unless all are enabled, only the enabled ones go into the node timeline with their times closed up seamlessly while disabled ones stay in the draft; with everything enabled the result is identical to before, and with everything disabled it says so and writes nothing.
- Image-to-video gained a **比例模式** dropdown (shown only for that task): generate at the image's own aspect, or crop to the set aspect, instead of always stretching the first frame to the output size.
- With **原图**, that segment's size follows the first frame's aspect; the global output resolution no longer applies to it, though the absolute size stays within the megapixel budget.
- With **裁剪**, the largest region of the first frame matching the set aspect is taken from the centre as input.
- This applies only to plain image-to-video; first-and-last-frame keeps the original full-frame handling so mismatched frame aspects never misalign.
- ⚠️ Cache format bumped — all previously generated segments are invalidated; the first run regenerates everything, so allow extra time.
- The descriptions of **初采交接与清理** and **精修与放大** were rewritten into four separate blocks: what the node does, how to wire and run it, each parameter with its default and when to change it, then the caveats. Behaviour, parameters and connections are unchanged. (⚠️ After the 2026-09-27 change 精修与放大 lists 17 entries; the extra one is 重绘开关.)
- Running **初采交接与清理** through an ordinary queue now fails with a plain message pointing at the handoff confirmation shown when queueing, instead of naming an entry that doesn't exist in the UI.
- The **H3放大权重** list on 精修与放大 uses the same filtered set, so only weights this plugin can load appear there — no more picking something that fails once the run starts.
- If a model saved in an older workflow has been deleted or moved, you now get "no longer in the loadable list" with what to change, instead of a bare value-not-in-list error.
- Removed the three controls on **初采交接与清理** (status, Cancel handoff, Second pass only), so the node is back to connections only.
- They were extra design: to run just one segment, set the run switches on 长视频规划师 instead; to stop, press the host's Stop. Segments already on disk survive, so re-submitting picks up where you were.
- The automatic save → global cleanup → second-pass chain and the confirmation before queueing are unchanged; nothing extra to click.
- The backend cancel and second-pass-only routes were removed with them; the status route stays for internal diagnosis only and nothing is shown in the UI.

**2026-09-25**

- Added Refine and Upscale: connect the first-pass result and it refines segment by segment before upscaling, leaving the existing first-pass links and audio unchanged.
- Optionally insert First-pass Handoff and Cleanup to save to disk, clean across jobs and run the second pass; without it the direct in-memory path is unchanged.
- The handoff node showed status and offered cancel or second-pass-only; reloading did not restore control and retries could save duplicates.
- ⚠️ Corrected 2026-09-26: those three controls and the cancel/retry routes were removed; stopping is done with the host's Stop button.
- Automated and isolated host checks exist; real browser use, finished-video quality and global cleanup effects still need testing.

**2026-09-24**

- With "Gradient Transition" on, the next segment inherits the previous ending's picture and sound and adjusts its opening colour and brightness; the actual transition still needs sample-video checking.
- Each seam no longer loses an extra 4 frames, but length alignment and trimming repeated picture can still change the total duration.
- A video with sound is padded with silence or trimmed to the actual frame count, and a single segment is also calibrated.
- Continuation checks report compatibility problems they can see, but they don't replace testing actual generation.
- ⚠️ The cache format was upgraded: all previously generated segments are invalid and the first run must be done from scratch, so allow extra time.
- Image quality and speed have not been verified on real hardware; feedback welcome.
- The "Subtitle" box in the AI planning page's right column is shorter, handing the space to the prompt box below.
- The bottom panel follows the window height within 225–260px, and clip cards show more prompt text when there's room.
- The button bars above the timeline and prompt editor stay on one row and slide sideways in a narrow window instead of stacking.
- The AI planning form leaves enough room for long messages and dropdowns without shrinking the text.
- Info messages stay on one line with the full text on hover; "Generate plan" first clears old messages and their tooltips.
- The 260px height cap reduces empty space in tall windows, but doesn't promise to remove all of it.
- Fixed the clip timeline looking blank before any plan is generated; the ruler is always shown now, so the timeline is always there.
- The first/last/middle-frame dropdowns on the prompt editor got slimmer, so the two columns are about the same width.
- The three material boxes now centre their content; the scrollbar no longer takes room inside the box, and the wheel still scrolls when there are many.
- Dropped material now sorts by file type: an image goes to the image box no matter where you drop it, likewise video and audio; unknown types are refused and a full box takes nothing more.
- A new "Clear materials" button below the shared switch wipes this segment's material in one click, but only after you confirm it in a dialog, so an accidental tap deletes nothing.
- Fixed the reference list from the "@" button sometimes flashing and vanishing before its options appear; it now opens reliably whether you click fast or slow.
- The "@" reference list can now be dismissed three ways: click "@" again, click anywhere else, or pick an item — you're never forced to select one.
- "Shared across segments" and "Clear materials" now stack in two rows instead of crowding one, saving horizontal room.
- Rearranged the AI Planning left column: Topic on its own row, then total duration + per-segment, segment count on a full-width row (input widened so the number isn't clipped), task + hook, language + style, platform + audience, skill + auxiliary, and finally model + generate plan.
- Fixed materials being wrongly cleared when reloading a node during the confirm dialog, old uploads bringing cleared material back, and holding "@" a second time leaving the list open.
- Fixed cache information being squeezed out of narrow timelines; sliding the button bar sideways now closes the "@" list.
- Fixed labels in the AI planning form; the segment-count input still spans the row.
- Hidden middle frames no longer interfere with splitting or caching for other tasks, and replacing a used file under the same name still re-checks the cache.
- Switching between mixed-task segments now shows the frame controls for the selected segment, and valid near-end middle-frame positions no longer show as 0% or 100%.
- Loading a plan also reports missing material referenced only by its clip draft, leaving references and their order unchanged.
- This middle-frame review added 23 front-end and 39 back-end regression checks; 41 isolated browser checks pass. Real image previews and finished GPU output still await checking.
- Same-day self-checks: 389 front-end checks all pass (7 added), 1067 backend checks all pass (with 2 long-standing warnings), style check clean.

**2026-09-23**

- Fixed old material still showing after "Fill into node", and it coming back when switching task type or rebinding the node.

**2026-09-21**

- The node timeline gained zoom: wheel to zoom, drag the ruler to pan — view only, nothing is changed.
- The "职能" field label on the AI planning page was renamed "结构"; content unchanged.
- Card thumbnails now follow material changes correctly and instantly; several cases of missing images were fixed.
- Same-day self-checks: 260 front-end checks all pass (up from 203), 616 backend checks all pass, style check clean.

**2026-09-20**

- The clip timeline gained zoom, up to 40× for precise segment-by-segment alignment; it only changes the view, never segment lengths.
- Fixed several defects found checking the zoom: the view jumping back, buttons vanishing mid-run, and so on.
- The cache strip moved from the bottom status bar into the node's timeline toolbar.
- The whole page was tightened to fit more on screen and buttons were unified; colours follow the theme, so light themes no longer leave dark blocks.
- "Auxiliary" and "Skill" on the AI planning page now share one source; the clip timeline keeps its own, and the two stay independent.
- Same-day self-checks: 203 front-end checks all pass (up from 164), 615 backend checks all pass, style check clean.

**2026-09-19**

- ⚠️ Segment cache rules were greatly tightened: a replaced material or a changed earlier segment is now detected and recalculated automatically; every previously generated segment is invalidated and the first run must be redone from scratch.
- A cache toolbar was added to the status bar for viewing cache stats, clearing with one click, and bumping the invalidate version.
- Uploaded files with the same name but different content no longer overwrite each other — they are renamed and kept side by side; same name plus same content is still stored once.
- Files and parameters are checked before generating, so problems are reported clearly up front instead of blowing up mid-run.
- The completion report lists planned, expected and actual durations; when memory is not enough it stops early with a reason instead of crashing.
- When a segment's prompt fails, that exact segment is flagged and keeps its original wording instead of being mixed into a batch-level message.
- The clip timeline gained "Retry selected segments", rewriting only the picked ones.
- Short segment counts are no longer padded by secretly duplicating the last segment; the real count is returned with a clear reminder.
- Source reporting became honest: only material that actually entered the request is listed.
- Backend requests were tidied up: errors are classified and reported clearly, and an overloaded server answers "busy" right away.
- A segment with no audio now gets silence filled in, so audio and video totals match strictly.
- When the output frame rate is not 24, the report now states plainly that the video is made at 24 fps and stretched at playback; durations are never changed silently.
- The AI planning page remembers what you typed per node, so switching nodes no longer loses unsaved entries.
- In narrow panels the form takes the full row and the right column collapses instead of overflowing.
- Leftover listeners are cleaned up when nodes are removed or refreshed, so the page no longer gets slower over time.

**2026-09-18**

- The AI planning page's "Skill" moved to its own folder, no longer shared with the clip timeline.
- Clip timeline rework: the track is always visible, details sit on the cards, the two timelines select independently, and the ruler auto-scales with total length.
- The toolbar gained Enable / Enable all / Disable all; prompt generation now only covers enabled segments.
- "Role" was renamed everywhere to the current field name, and the right column gained a "Prompt" box.
- The clip draft now lives in node properties, so editing it no longer forces the node to re-run, and it still saves with the workflow.
- Fixed a batch of AI planning page display and refresh problems: no more wrong-node overwrites, new prompts fill in right away, and the skill list keeps your selection.
- Cleaned the bundled plan samples, which used to fail with "unknown task type".

**2026-09-17**

- The status bar split into "AI Planning" and "Prompt Editor" pages; the planning form grew to 13 fields.
- Added skill style injection: the storyboard is written in the chosen skill's style, falling back to a generic write-up if it can't be loaded.
- Several rounds of polish on the API model settings page: one unified model list, a key per model, and a "Test connectivity" button.
- Added the clip timeline draft editor: trim, split, delete, reorder, per-segment AI prompt generation, and "Fill into node".
- Fixed a Chinese label from the planning page leaking into the run and failing with "unknown task type".

**2026-09-16**

- The AI planning page shipped: fill in a topic and it produces a multi-segment storyboard shown on a colour-coded timeline, with no impact on the existing generation flow.
- Segments missing an image now fall back to the global material; switching the task type syncs to the selected segment; the UI follows the app theme.
- API model settings became an embedded panel on the settings page, with custom models supported.

**2026-09-15**

- Generation now writes each segment to disk first and stitches at the end, greatly improving decode speed for long segments on small-memory cards.
- Segment handoff now slices directly from the previous segment's result, so seams are more faithful.
- Peak memory during stitching dropped from about 3 segments' worth to just over 1.
- Fixed the progress bar never reaching 100% when a segment was skipped without a saved copy.
- Fixed the timing log always showing 0 seconds for reference decoding.
- Fixed 4 extra duplicated frames at seams under some settings.
- Cache is now stored per version with old versions deleted at startup, so upgrades no longer need manual cache cleanup.
- Fixed per-segment progress ("Generating 3/7"), which had never actually shown before; it is now genuinely visible.
- A corrupted cache file is now rejected and redone on the spot, instead of failing hours later and wasting the run.
- Tests grew from 196 to 217, all passing.

**2026-09-14**

- The node now carries two optional model inputs and picks the right one per segment automatically.
- Before running, only the models actually used are checked, and the missing one is named.
- The two models keep separate caches, so mixed timelines no longer reload them repeatedly.
- Node fields were reordered so the encoder shows first.
- ⚠️ Old workflows need their model links re-plugged and two hidden switches re-checked; old caches are invalidated once.

**2026-09-13**

- Output size is now truly controlled by megapixels, with the default output lowered to 864×480.
- Default steps dropped from 25 to 20 and default megapixels from 1.0 to 0.4.
- Added an automatic check that front-end and back-end values stay consistent.

**2026-09-12**

- Fixed audio material loading failures.
- Fixed the wrong task type on newly added segments.
- Created the project README.

**Still planned**

- Second-pass rewriting: iterative rewrites on top of already generated segments.

> The originally planned "automatic AI storyboarding, prompt refinement, and project import/export" have all shipped (2026-09-16~18); "cache cleanup" shipped as the cache toolbar (2026-09-19).

---

## Feedback

- **Bug reports**: please include your ComfyUI version, GPU model and VRAM, H3 model version, the full error text from the red panel, and the timeline content (feel free to redact).
- **Feature requests**: open an Issue.
- **Pull requests**: please keep this repo's test suite at its baseline first (how to run it is in `文档/`), and match the existing code style.

---

## Acknowledgments

This plugin stands on the shoulders of many excellent open-source projects, models and tools. Listed below (by category) are the things we referenced, borrowed from or depend on, directly or indirectly. Thanks to every author and community — if anything was missed, please open an Issue.

### Host & official nodes

- **[Comfy-Org / ComfyUI](https://github.com/Comfy-Org/ComfyUI)** — the host environment. The whole "plan → split → run each segment → stitch back" is built on ComfyUI's V3 node interface, its executor and its caching machinery; the bottom panel, settings page and theme colours all reuse the ComfyUI front end.
- **ComfyUI's official MiniMax H3 nodes** — all actual video/audio generation, sampling and decoding (including `_empty_av_latent`, PackedLayout, `node_helpers`, …) are done by the official nodes. This plugin deliberately never changes or forks the host; it only arranges things around them and crops/stitches their outputs.

### Generation & understanding models

- **[MiniMax H3](https://github.com/MiniMax-AI/MiniMax-H3) (MiniMax / 稀宇科技)** — the base model for multi-segment video/audio generation; the six task modes and the 24-frames-per-second time base all come from it.
- **[Qwen3-VL](https://github.com/QwenLM) (Alibaba Qwen team)** — the text encoder that lets the model understand your prompt.
- **[Kimi](https://github.com/moonshotai) (Moonshot AI) / [DeepSeek](https://github.com/deepseek-ai) and other compatible services** — provide the large-model reasoning behind "one-click planning" and per-segment prompt rewriting (over the network, zero VRAM). The preset model is Kimi-K3; custom cloud/local services ([Ollama](https://github.com/ollama/ollama), [LM Studio](https://lmstudio.ai)) are also supported.

### Peer & reference open-source projects

Much of the design drew on the open-source H3 ecosystem and similar AI-video tools (see the per-project analyses under `文档/参考/`). Special thanks to:

- **[ComfyUI-Artificial-Intelligence](https://github.com/a63976659/ComfyUI-Artificial-Intelligence)** — the knowledge-base loader, the unified list that keeps a key per model, connectivity testing and error-message extraction were referenced/ported from it.
- **[AIMixer 导演台](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director)**, **[H3-Motion-Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context)**, **[H3-Multishot](https://github.com/jlucasmcrell/ComfyUI-H3-Multishot)**, **[H3-Codex-Drama](https://github.com/chiphoton/MiniMax-H3-Codex-Drama)**, **[H3-SelfLift](https://github.com/facok/comfyui-SelfLift)** — community nodes on the same MiniMax H3 pipeline; passing the internal data straight between segments, the audio continuation window, the `context_length` values, and the "check a sample segment first / don't touch the host" ideas are mutually corroborated with them.
- **[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (harry0703)**, **[video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) / [video-talkcraft](https://github.com/Vincentwei1021/video-talkcraft) / [anything2explainer](https://github.com/Vincentwei1021/anything2explainer) (based on [Remotion](https://github.com/remotion-dev/remotion))** — the reference frame for one-stop short-video pipelines and the "skill / recipe card / multi-layer checking" approach.
- **AIVideo_node**, **[NodeCraft AI](https://github.com/a63976659/ComfyUI-NodeCraft-AI) knowledge base** — sources of experience for large-model retry handling, settings persistence and linked UI patterns.

### Skills & knowledge-base material

- Content-planning references are stored in `Skills/`; timeline rewriting methods are stored in `AI生成提示词/`. See [the Skills directory guide](Skills/目录说明.md) for its structure and usage rules.

### Libraries & tools we depend on

- **[PyTorch](https://github.com/pytorch/pytorch) (torch)** — array maths, stitching and silence padding, i.e. all the numeric work.
- **[FFmpeg](https://ffmpeg.org) / [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)** — audio conversion and reading frames from reference videos.
- **[soundfile](https://github.com/bastibe/python-soundfile)** — reading audio length and samples.
- **[NumPy](https://github.com/numpy/numpy) / [Pillow](https://github.com/python-pillow/Pillow) / [aiohttp](https://github.com/aio-libs/aiohttp)** — array, image and async network capability provided by the ComfyUI main environment.
- **[PySceneDetect](https://github.com/Breakthrough/PySceneDetect) (scenedetect) + [OpenCV](https://github.com/opencv/opencv) (opencv-python-headless)** — optional automatic shot splitting of a source video.
- **[PyAV](https://github.com/PyAV-Org/PyAV) (av)** — optional video-reading backend.
- **[pytest](https://github.com/pytest-dev/pytest)** — all front and back-end tests.

### Others

- The short-video storyboarding approach (hook / opening / setup / progression / conflict / climax / twist / ending / call-to-action as the jobs each segment does) draws on patterns widely circulated in the creator community.
- Thanks to every community member who filed bugs, suggestions and code changes.

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
