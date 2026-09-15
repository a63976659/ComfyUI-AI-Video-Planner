# Video Planner

**Language:** [🇨🇳 简体中文](./README.md) ｜ 🇬🇧 English (current)

A ComfyUI plugin that splits a long video into several short segments, generates them one by one, and stitches them back into a finished video.

All the actual generation work is done by ComfyUI's official MiniMax H3 nodes. This plugin only handles "split → run each segment → glue them back together".

---

## 📑 Table of Contents

- [What it does](#what-it-does)
- [How to use](#how-to-use)
  - [Step 1: Wire up the node](#step-1-wire-up-the-node)
  - [Step 2: Open the bottom status bar](#step-2-open-the-bottom-status-bar)
  - [Step 3: Edit the timeline](#step-3-edit-the-timeline)
  - [Step 4: Click Queue Prompt to start](#step-4-click-queue-prompt-to-start)
- [What if I cancel or hit an error halfway](#what-if-i-cancel-or-hit-an-error-halfway)
- [Hardware requirements](#hardware-requirements)
- [Installation](#installation)
- [Things to know](#things-to-know)
- [Changelog](#changelog)
- [Feedback](#feedback)
- [Support the author](#support-the-author)

---

## What it does

- **Split a long video into segments**: add as many segments as you want on the timeline, each with its own prompt and duration.
- **Pick a generation mode per segment**: text-to-video, image-to-video, first-and-last-frame, reference-to-video, video-to-video, reference-plus-video — six modes in total, and you can mix them across segments.
- **Attach reference materials per segment**: images, videos or audio. Use tags like `<Picture 1>` inside the prompt to point at them.
- **Smooth handoff between segments (optional)**: turn on the "Gradient Transition" toggle and the tail of the previous segment (both picture and sound) is carried into the next one, so seams don't jump. Turn it off and every segment is generated independently.
- **Generated segments are saved automatically**: each finished segment is written to disk. Next time you run, unchanged segments are re-used instead of regenerated — a full re-run takes only tens of seconds.
- **Only run the segments you check**: every segment has a "Run" toggle. Only checked ones get regenerated. Unchecked segments that were previously generated still get stitched into the final video.

---

## How to use

### Step 1: Wire up the node

Add the node **Video Planner** (internal name `H3DYT_Director`) to your workflow.

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

Once the plugin loads, a **Video Planner** panel appears at the **bottom of the ComfyUI page**, containing:

- **Generation type** — switch between the 6 task modes
- **Style preset** — pick a style from a dropdown; its body is automatically inserted into the global prompt
- **Prompt editor** — write the global prompt, which gets prepended to every segment
- **Reference files area** — upload images / videos / audio; duplicates are detected automatically
- **Timeline** — the main working area

The matching inputs on the node itself are auto-hidden. All the data still lives inside the node; the status bar is only an editor.

### Step 3: Edit the timeline

- **Add a segment**: click on an empty part of the track, or click the "+" button
- **Change duration**: drag the left/right edge of a segment card, or use the time inputs below it
- **Toggle Run**: the switch below each segment card. Only checked segments get regenerated; unchecked ones with a saved copy are reused
- **Edit prompt / attach references**: click into the segment card
- **Playhead**: drag it to see which segment covers a given moment
- **Gradient Transition**: a toggle on the timeline toolbar. When on, segments blend smoothly into each other

Timeline data is stored as JSON inside the node's `Timeline Data` input. You can copy and paste it, which makes archiving and sharing easy.

### Step 4: Click Queue Prompt to start

Generation runs in two stages:

1. **Sample each segment one by one.** Every finished segment is saved to disk right away (about 45 MB per segment).
2. **After every segment is done, decode and stitch them all together** into the final video.

Splitting it this way frees up the GPU during decoding. Without it, a 16 GB card running long segments at high resolution would be more than ten times slower.

The status bar shows segment-level progress like "Generating 3/7".

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
git clone <this-repo-url> ComfyUI-AI-Edit-Video
```

**Option B: manual drop-in**

Download the zip, unzip it, and put the whole folder at `ComfyUI/custom_nodes/ComfyUI-AI-Edit-Video/`. Restart ComfyUI.

**Optional dependencies** (uncomment them in `requirements.txt`, then run `pip install -r requirements.txt`):

- `imageio` + `imageio-ffmpeg` — for reading reference videos (needed by r2v / v2v / rv2v)
- `scenedetect` + `opencv-python-headless` — for auto-splitting a source video (needed by smart shot detection)
- `pytest` — for running the unit tests

**Check that it worked:**

- ComfyUI's startup log contains lines starting with `[H3导演台]`
- Searching `视频规划师` in the node picker finds the main node
- The bottom of the ComfyUI page shows the Video Planner panel

---

## Things to know

**Where the cache lives**

By default it's in `%TEMP%/h3导演台_段缓存/`. To move it, set the environment variable `H3_段缓存_DIR`.

Old cache folders from previous versions are cleaned up automatically when the plugin starts. No manual cleanup needed.

**How the resolution is decided**

Two widgets together decide it: `Output Resolution` (aspect ratio) and `Megapixels` (how detailed). The default `0.4 megapixels + 16:9` produces **864×480**.

Bigger megapixel values need more VRAM. `4.0 + 21:9` reaches 3136×1344 — know your limits.

**What the frame rate widget does**

The `Frame Rate` input on the node is just a tag written into the output video file. The actual generation always runs at **24 frames per second** (fixed by the official model). Want slow-motion or fast-motion? Change the frame rate number. Want to change the real motion speed? Change the segment's duration.

**How segments join together**

Controlled by the "Gradient Transition" toggle:

- **Off** (default): each segment is generated independently. The seam is only a 4-frame crossfade.
- **On**: the last 22 frames of picture and sound from the previous segment are carried into the next one. Seams look more natural, but things can also go wrong more easily.

If you see smearing, ghosting, or artifacts, first turn Gradient Transition off to check whether it's the model itself.

**After swapping the checkpoint**

Old segment caches do **not** get invalidated automatically. If you want every segment to be regenerated with the new model, manually delete the subfolder for the current version inside `%TEMP%/h3导演台_段缓存/`.

**Can I connect only one model input?**

Yes. The plugin only checks whether the models required by **the tasks actually used in your current timeline** are connected. If something is missing, the error message names the exact task and the exact model. Everything else is left alone.

**Missing audio is warned about**

If one segment has no audio while others do (say you plugged in the audio VAE halfway through), the video side keeps every segment but the audio side skips the missing ones. In that case the report gets an extra line: "Warning: audio segment count < video segment count". If you see it, the final video may have audio drift.

---

## Changelog

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

**v2 (planned)**

- AI-powered automatic shot planning
- Prompt refinement
- Second-pass refinement
- Project file import/export
- Cache cleanup button

---

## Feedback

- **Bug reports**: please include your ComfyUI version, GPU model and VRAM, H3 model version, the full error text from the red panel, and the timeline JSON (feel free to redact).
- **Feature requests**: open an Issue.
- **Pull requests**: please keep `pytest 测试/` at the 217-passed baseline, and match the existing code style.

---

## Support the author

If this plugin helps you:

- **Star this repo** ⭐
- **Share your work** — videos made with this plugin are welcome in the Issues.
- **Sponsor** — (replace with your Ko-fi / Patreon / GitHub Sponsors link here).

---

<p align="center">
  <sub>Made with ❤️ for the ComfyUI community</sub>
</p>
