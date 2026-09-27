# Project Spec: Squishy McSquishface

## 1. Overview

**Purpose:** Drop a video into a browser page, see the estimated output size for several
compression levels, pick one, get a smaller MP4. From v0.3, optionally trim it to a clip
or save a single frame first.

**Context:** Game-engine captures (Unreal Engine 5) come out at 4K60 and ~60 Mbps
(227 MB for 31 s). The recipe below shrank one to 12.1 MB with no visible loss:

```
ffmpeg -i in.mp4 -vf scale=1920:-2 -c:v libx264 -preset slow -crf 23 \
  -maxrate 3.5M -bufsize 7M -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart out.mp4
```

This app turns that recipe into presets with up-front size estimates.

**User:** Brad, on a Windows 11 machine with Python 3.14 and ffmpeg/ffprobe on PATH.
Single user, local only. **Brad owns fitting the result to the destination**
(WhatsApp, Discord, etc.). The app reports sizes; it does not police limits.

**Why not a plain HTML file:** browsers cannot launch local processes. A tiny local
Python server serves the page and runs ffmpeg. The user experience stays "double-click,
drop file".

## 2. Visual Identity & UX Vibes

- **The Vibe:** Playful name, serious tool. Dark, single-screen, big drop zone, no clutter.
  One screen: drop zone -> source info + preset cards -> progress -> result.
- **Core Palette:** `#14161a` (bg), `#1e2127` (card), `#e8e6e3` (text), `#8a8f98` (muted),
  `#ff7a59` (accent / squish orange), `#4cc38a` (success), `#e5484d` (error).
- **Typography:** System UI stack (`system-ui, Segoe UI, sans-serif`); tabular numerals
  for sizes. No web fonts (works offline).

## 3. Success Criteria

- [ ] Double-clicking `Squishy.bat` starts the server and opens the page in the default browser.
- [x] Dropping a video (or using a file picker) shows: filename, duration, resolution, fps,
      source size.
- [x] Every preset card shows an **estimated output size in MB** before any encoding.
- [x] Estimates are an upper bound: actual output <= estimate * 1.03 on the reference
      clip for every preset.
- [x] Choosing a preset encodes with a live progress bar (percent from ffmpeg progress).
- [ ] On completion the page shows actual size, % reduction, and buttons:
      **Open folder** (Explorer with file selected) and **Download**.
- [x] Output never upscales: target short side = min(source short side, preset cap) (portrait-safe).
- [x] Encode can be cancelled; partial output is deleted.
- [x] Server binds to `127.0.0.1` only. No `shell=True` anywhere.
- [x] Uploaded temp copy is kept for re-encoding at other presets, replaced on the next drop, and deleted on shutdown (stale copies cleared at next launch).
- [x] `pytest` passes; pure logic (estimates, arg building, progress parsing) is unit
      tested without ffmpeg; one integration test encodes a generated 2 s clip.

## 4. Technical Foundation

- **Stack:** Python 3.14 **standard library only** (`http.server.ThreadingHTTPServer`,
  `subprocess`, `threading`, `json`, `webbrowser`). No pip installs to run the app.
- **Frontend:** One `index.html` with inline CSS and vanilla JS. No build step, no CDN.
- **External tools:** `ffmpeg` and `ffprobe` on PATH (checked at startup; clear error if missing).
- **Testing:** `pytest` (dev only). Run: `python -m pytest --tb=short -x`
- **Run:** `Squishy.bat` or `python launch.py [--port 48123] [--out DIR] [--no-browser]`

## 5. Architecture & Modules

```
Squishy_McSquishface/
  Squishy.bat              # double-click launcher: python launch.py
  launch.py                # entry: parse args, check ffmpeg, start server, open browser
  squishy/
    __init__.py
    presets.py             # PRESETS table, plan_for(), estimate_bytes()          [pure]
    probe.py               # parse_probe() [pure], probe_file() -> SourceInfo     [I/O]
    encoder.py             # build_ffmpeg_args() [pure], ProgressTracker [pure],
                           # EncodeJob (runs ffmpeg in thread, cancel, cleanup)   [I/O]
    server.py              # HTTP routes, upload streaming, job registry
    static/index.html      # UI
  tests/
    test_presets.py  test_probe.py  test_encoder_args.py  test_server.py
    test_integration.py    # generates noise clips via lavfi, encodes, checks size
  spec.md  onboarding.md  DEVLOG.md
```

**Flow:**
1. Browser `POST /api/upload` streams the dropped file (raw body, `X-Filename` header)
   to `%TEMP%\squishy\run-<id>\<file_id>.<ext>` (one folder per running instance; see
   `squishy/workdir.py`). Loopback copy of 227 MB takes ~1-2 s.
2. Server runs ffprobe, returns `SourceInfo` + one `Estimate` per preset.
3. Browser `POST /api/encode {file_id, preset_id}` -> `job_id`.
4. `EncodeJob` runs ffmpeg with `-progress pipe:1 -nostats`; browser polls
   `GET /api/job/<job_id>` every 500 ms.
5. Output written to the output dir (default `%USERPROFILE%\Videos\Squished`) as
   `<stem>_<preset_id>.mp4`; suffix `-2`, `-3`... if it exists.

**Routes:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | index.html |
| POST | `/api/upload` | stream file in, probe, return info + estimates |
| POST | `/api/encode` | start job |
| GET | `/api/job/<id>` | job status |
| POST | `/api/job/<id>/cancel` | kill ffmpeg, delete partial |
| POST | `/api/job/<id>/reveal` | `explorer /select,<path>` |
| GET | `/api/job/<id>/download` | stream output file |

**Estimate math** (why it's predictable): every preset is CRF 23 capped by `-maxrate`, so
the bitrate ceiling is known. Size ceiling =
`(video_kbps * (duration + 0.9 * 2 s VBV buffer) + audio_kbps * duration) / 8 * 1.01`.
The VBV term matters: x264 starts the buffer 90% full, so short clips can exceed
`maxrate * duration` (measured 1.2x on a 3 s noise clip). Easy content lands under the
ceiling; hard content approaches it. A preset's video bitrate is capped at the source's own
video bitrate (`bitrate_capped`), otherwise already-small sources get absurd ceilings.

## 6. Data Models

**Preset table (`presets.py`):**

```python
PRESETS = [
  # id,        label,     max_short_side, max_fps, video_kbps, audio_kbps
  ("light",   "Light",    1080, 60, 8000, 160),
  ("medium",  "Medium",   1080, 60, 3500, 128),   # the proven recipe
  ("heavy",   "Heavy",     720, 30, 1500,  96),
  ("extreme", "Extreme",   540, 30,  600,  64),
]
```

All presets: `libx264 -preset slow -crf 23 -bufsize 2*maxrate -pix_fmt yuv420p`,
`aac`, `-movflags +faststart`. fps cap applied only if source fps > max_fps.

**SourceInfo:**

```json
{"file_id": "a1b2c3", "name": "Unreal Engine 5 2026.09.23 - 17.21.12.03.mp4",
 "size_bytes": 238026752, "duration_s": 31.14, "width": 3840, "height": 2160,
 "fps": 59.985, "has_audio": true, "video_kbps": 60951}
```

**Plan (one per preset, returned with SourceInfo):**

```json
{"preset_id": "medium", "label": "Medium", "out_width": 1920, "out_height": 1080,
 "out_fps": 59.985, "fps_capped": false, "video_kbps": 3500, "bitrate_capped": false,
 "audio_kbps": 128, "est_bytes": 15059042, "est_ratio": 0.0633}
```

**Job status:**

```json
{"job_id": "j9", "state": "running", "percent": 42.5, "preset_id": "medium",
 "output_path": "C:\\Users\\<you>\\Videos\\Squished\\clip_medium.mp4",
 "output_bytes": null, "error": null}
```

`state` in `queued | running | done | cancelled | error`.

## 7. Sprint Plan

### Sprint 1: Core engine (pure logic + ffmpeg wrapper)

- **Goal:** Everything except HTTP and UI, fully tested.
- **Success Criteria:** `presets.py`, `probe.py`, `encoder.py` done; unit tests for
  estimates (incl. no-upscale, fps cap, no-audio source), ffmpeg arg building, progress
  parsing; integration test encodes a 2 s lavfi clip and output <= estimate * 1.03.
- **Deliverables:** code, tests passing, DEVLOG entry.

### Sprint 2: Server + UI + launcher

- **Goal:** The double-click-and-drop experience end to end.
- **Success Criteria:** all Section 3 boxes checked; manual run on the reference UE5 clip
  across all four presets with actual vs estimate recorded in DEVLOG.
- **Deliverables:** `server.py`, `index.html`, `launch.py`, `Squishy.bat`, onboarding.md,
  DEVLOG entry.

### Sprint 3: Shareable v0.2

- **Goal:** A friend can run Squishy from a GitHub release without being walked through it.
- **Success Criteria:** on a clean Windows machine with Python but no ffmpeg: unzip,
  double-click, one Y/N, squish, with no commands typed. Without Python, the .bat explains
  what to install instead of failing cryptically. Downloaded ffmpeg is pinned and
  SHA-256-verified. The README has a human section and an agent section.
- **Deliverables:** `squishy/tools.py`, `--get-ffmpeg`, Python check in `Squishy.bat`,
  README.md, RELEASE_NOTES.md, DEVLOG entry.

### Sprint 4: v0.3 trim + stills

Grilled 2026-09-27; the two load-bearing decisions are in the DEVLOG. Terms are defined in
`CONTEXT.md`.

- **Goal:** Cut a clip out of a capture and squish just that, or grab one frame, on the same
  single screen.
- **What it adds:**
  - A **player** (always visible, capped at ~40% of window height) between the source
    info and the cards, with a **trim bar** under it: drag handles, "Set start / Set end at
    playhead" buttons, keys `I`/`O` (set in/out), arrows (1 frame), Shift+arrows (1 s),
    Space (play/pause). Times shown as `mm:ss.mmm`; no typed entry.
  - The player is the browser's `<video>` on the uploaded file, served with HTTP Range.
    If the browser can't play the file, it falls back to silent frames rendered by ffmpeg
    on request. Trim and stills work in both modes.
  - Every card's estimate follows the trimmed duration, recomputed server-side so the
    math stays in `presets.py`. The Squish button lives in a bottom bar that is always visible.
  - An **Original** card, shown only when trimmed: stream copy, start snapped to the
    keyframe at or before the in-point, the card showing the snap. Keeps the source's
    container. Its size is exact (packet sizes in range), not a ceiling.
  - **Save frame**: ffmpeg extracts the displayed frame (by its presentation time) as a
    full-resolution JPEG (`-q:v 2`) into the output folder, `<stem>_still_<mm-ss.mmm>.jpg`.
  - Trimmed outputs are named `<stem>_<preset>_<in>-<out>.<ext>`; untrimmed names are unchanged.
    The trim survives across encodes of the same upload.
- **Out of v0.3:** multiple segments, a timeline, spatial crop, audio editing, GIF export,
  still batches or galleries, typed-in times.
- **Success Criteria:**
  1. Untouched trim: ffmpeg args identical to v0.2.4 (pinned by a test written first).
  2. A trimmed encode starts on the exact in-point frame and lasts `out - in` +/- 1 frame,
     every preset (integration test on a generated clip with a burned-in frame counter).
  3. Reference clip, trimmed: actual <= estimate * 1.03, every preset.
  4. Original: starts on the snapped keyframe, the card's snap equals the output's, and the container is kept.
  5. The saved still is the displayed frame, checked on the VFR reference clip.
  6. Range requests return 206 with the right bytes; seeking works in a real browser.
  7. The fallback engages on a file Chrome can't play; trim and still still work.
  8. All existing tests pass; version 0.3.0; README and RELEASE_NOTES updated.
- **Deliverables:** code, tests (pure parts test-first), DEVLOG entry with the still-frame
  measurement, GitHub release (after the user confirms).

## 8. Out of Scope

- Destination-aware limits (WhatsApp/Discord/email caps) - user's responsibility.
- Hitting an exact target size (two-pass encoding).
- Batch / multi-file queue.
- Spatial cropping, audio removal, format choices other than MP4/H.264 (the Original
  card's stream copy keeps the source's container; that is the one exception). Trimming
  was listed here until v0.3; see Sprint 4.
- Hardware encoders (NVENC/QSV).
- Packaging as a standalone .exe, bundling Python, or redistributing ffmpeg binaries
  (v0.2 downloads a pinned ffmpeg build on request instead; see DEVLOG 2026-09-24).
- Access from other devices on the network.

## Parking Lot

- **Custom slider (resolution + bitrate):** presets first; add if the four feel too coarse.
- **"Encode all presets" comparison:** useful for learning what looks acceptable; costs 4x time.
- **Sample-based estimate:** encode 3 x 2 s chunks to predict the *actual* size, not just
  the ceiling. *Spiked 2026-09-27, shelved:* only Light gains much, at about 85% of a
  Medium encode's time on a 31 s clip. Numbers and revisit condition in the DEVLOG.
- **Batch queue:** drop a folder of clips.
- **NVENC option:** much faster, somewhat worse quality per bit. *Spiked 2026-09-27, shelved:*
  under the presets' caps it scored 2-6 VMAF lower (Light: +29% size at matched quality) and
  was at most 1.6x faster. Numbers in the DEVLOG.
