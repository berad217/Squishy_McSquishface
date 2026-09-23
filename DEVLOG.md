# DEVLOG - Squishy McSquishface

Newest entries first. Decisions, rationale, and measured results; not a changelog.

---

## 2026-09-23 - Sprints 1 + 2: engine, server, UI (v0.1)

**Built:** everything in spec.md sections 5-6. 40 tests pass (`python -m pytest --tb=short -q`, ~13 s,
includes real ffmpeg runs on generated clips).

### Reference clip results (UE5 capture, 3840x2160 @ 59.985 fps, 31.1 s, 227 MB)

| Preset  | Output   | Ceiling  | Actual / ceiling | Encode time |
|---------|----------|----------|------------------|-------------|
| Light   | 18.7 MB  | 32.3 MB  | 0.58             | 21 s        |
| Medium  | 12.1 MB  | 14.4 MB  | 0.84             | 19 s        |
| Heavy   | 5.2 MB   | 6.3 MB   | 0.82             | 11 s        |
| Extreme | 2.3 MB   | 2.6 MB   | 0.88             | 10 s        |

(MB = MiB, matching Windows Explorer.) Medium reproduces the hand-run recipe byte-for-byte
in size (12.1 MB). Light sits far under its ceiling because CRF 23, not the 8 Mbps cap, is
the binding constraint on this content: the ceiling is honest but loose at the light end.

### Decisions

- **Local Python server, not a standalone HTML file.** Browsers can't spawn processes.
  Rejected ffmpeg.wasm (10-20x slower, memory-limited on 4K) and .hta (IE engine, being
  retired, AV-flagged). Stdlib only, so there's nothing to install.
- **Presets are CRF 23 + VBV maxrate, not target bitrate / two-pass.** Keeps the proven
  recipe's quality behaviour (easy content gets smaller) while giving a hard size ceiling.
- **Estimate includes the initial VBV buffer.** x264 starts the buffer 90% full, so output
  can exceed `maxrate * duration`. Measured on a 3 s noise clip at Light: 1.2x the naive
  figure. Ceiling = `maxrate * (T + 1.8 s) + audio * T`, +1% container.
- **Preset bitrate capped at the source's own video bitrate** (MODERATE; not in original
  spec). Found in UI testing: re-squishing an already-small 2.3 MB file showed "up to
  32 MB / 1402% of original". Extra bits can't add quality, so the cap costs nothing and makes
  the numbers meaningful. Card shows "Capped at the source's own bitrate".
- **Resolution cap is on the short side, not height** (MODERATE). "1080p" for a portrait phone
  video should be 1080x1920, not 608x1080.
- **Upload is kept after an encode** (MODERATE; spec originally said delete after encode).
  Lets you try another preset without re-dropping. Replaced on next drop; temp dir wiped
  on shutdown and on next launch (covers console-window-closed kills).
- **One encode at a time;** upload rejected (409) while encoding. No queue by design (spec
  section 8).
- **Default port 48123.** Uncommon on purpose: 8000/8080/8765 are where local dev tools
  tend to live. If the port is busy with something else, falls back to a
  random free port; if it's busy with Squishy, just opens the browser to it.
- **Launcher renamed `squishy.py` -> `launch.py`** so it doesn't share a name with the
  `squishy/` package.
- **Localhost hardening:** Host header must be 127.0.0.1/localhost:port (blocks DNS
  rebinding); cross-origin POSTs rejected (a random website can't drive the encoder).
- **Output filenames** come from a sanitised stem (`safe_stem`) + preset id, never from
  a client-supplied path.

### Not verified

- Double-clicking `Squishy.bat` for real (tested via `python launch.py`).
- **Open folder** button (would pop Explorer during testing). Uses
  `explorer /select,"<path>"` string form; see `server.py:_reveal`.
- Real OS drag-and-drop (tested by dispatching a synthetic drop event with a real File).
