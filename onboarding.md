# Onboarding - Squishy McSquishface

**What it is:** A local web page for shrinking videos. Double-click `Squishy.bat`, drop a
video, see the maximum output size for four compression levels, pick one, get an MP4.
Python stdlib + ffmpeg. Single user, Windows, localhost only.

## Office tour

| Where | What |
|---|---|
| `spec.md` | What to build, success criteria, out-of-scope list, parking lot |
| `DEVLOG.md` | What was built and why; measured results on the reference clip |
| `README.md` / `RELEASE_NOTES.md` | User-facing: install steps for humans + agents; cheeky per-release notes |
| `Squishy.bat` -> `launch.py` | Entry point: finds Python, finds/offers ffmpeg, starts server on 127.0.0.1:48123, opens browser |
| `squishy/tools.py` | ffmpeg lookup (`bin/` then PATH) + pinned, SHA-256-verified download |
| `squishy/presets.py` | **The knobs.** Preset table + size-ceiling math. Pure. |
| `squishy/probe.py` | ffprobe JSON -> `SourceInfo` (handles rotation, missing bitrates) |
| `squishy/encoder.py` | ffmpeg argv builder, progress parser, `EncodeJob` thread |
| `squishy/server.py` | HTTP routes (table in spec.md section 5) |
| `squishy/static/index.html` | Whole UI: inline CSS + vanilla JS, no build step |
| `tests/` | pytest; `test_integration.py` and `test_server.py` run real ffmpeg |

## Commands

```bash
python -m pytest --tb=short -q
python launch.py --no-browser --out <scratch dir>
```

## Things that will bite you

- **Estimates are ceilings, not predictions.** The UI says "up to". Don't "fix" an estimate
  because the actual size came in lower; that's by design (CRF under a VBV cap).
- **Changing x264 settings changes the ceiling math.** `bufsize` and the VBV-init fraction are
  both in `estimate_bytes()`. Keep `BUFSIZE_SECONDS` in sync with `build_ffmpeg_args()`.
- **MB in the UI = MiB** (1024^2), to match Windows Explorer.
- **Default port is 48123,** uncommon on purpose; 8000/8080/8765 are where local dev
  tools tend to live. Don't "simplify" it to one of those.
- **ffmpeg is pinned** (`FFMPEG_VERSION`/`FFMPEG_SHA256` in `tools.py`). To bump it, update both
  together; the comment there shows how to get and cross-check the digest. `bin/` is gitignored.
- **`.gitattributes` forces CRLF on `.bat`.** The release zip is `git archive`, and LF-only
  batch files misbehave in cmd.exe.
- Editing `server.py` / Python code requires restarting the server; `index.html` is read
  per request (just refresh).
