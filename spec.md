# Project Spec: Squishy McSquishface

## 1. Overview

**Purpose:** Drop a video into a browser page, see the estimated output size for several
compression levels, pick one, get a smaller MP4.

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
   to `%TEMP%\squishy\<file_id>.<ext>`. Loopback copy of 227 MB takes ~1-2 s.
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

## 8. Out of Scope

- Destination-aware limits (WhatsApp/Discord/email caps) - user's responsibility.
- Hitting an exact target size (two-pass encoding).
- Batch / multi-file queue.
- Trimming, cropping, audio removal, format choices other than MP4/H.264.
- Hardware encoders (NVENC/QSV).
- Packaging as a standalone .exe or bundling ffmpeg.
- Access from other devices on the network.

## Parking Lot

- **Custom slider (resolution + bitrate):** presets first; add if the four feel too coarse.
- **"Encode all presets" comparison:** useful for learning what looks acceptable; costs 4x time.
- **Sample-based estimate:** encode 3 x 2 s chunks to predict the *actual* size, not just
  the ceiling.
- **Batch queue:** drop a folder of clips.
- **NVENC option:** much faster, somewhat worse quality per bit.
