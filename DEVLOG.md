# DEVLOG - Squishy McSquishface

Newest entries first. Decisions, rationale, and measured results; not a changelog.

---

## 2026-09-24 - Sprint 3: shareable v0.2 (ffmpeg on demand, README, release notes)

**Built:** `squishy/tools.py` (lookup + download), `--get-ffmpeg`, a Python check in
`Squishy.bat`, README.md (human + agent sections), RELEASE_NOTES.md. 49 tests pass, plus 1
opt-in live download test (`SQUISHY_LIVE_DOWNLOAD=1`).

### Decisions

- **Download ffmpeg on request; don't bundle it.** Bundling adds ~110 MB to every copy and
  makes us the redistributor of a GPL binary (x264), with the source-offer obligations that
  brings. When the friend's machine fetches it from gyan.dev's mirror, we don't redistribute.
- **Python not bundled** (user call). The friends have AI agents, so a precise agent section in
  the README beats shipping embedded Python. `Squishy.bat` now tries `py -3` then `python`
  with `--version`, which also filters out the Microsoft Store stub, and prints install
  instructions instead of failing cryptically.
- **Pinned source: GitHub mirror `GyanD/codexffmpeg` tag 9.0.2, essentials zip.** A release
  asset URL is stable per tag, while gyan.dev's "latest" URL moves. SHA-256 `60f46726...`
  cross-checked from two sources: GitHub's asset digest and gyan.dev's `.sha256` file. The
  7z is a third of the size, but the stdlib can't read 7z, and adding a dependency is worse.
- **Extract by basename into names we choose.** Archive paths are never trusted (no zip-slip),
  and each file goes to a `.tmp` name and then `os.replace`, so a crash can't leave a
  half-written `ffmpeg.exe` for lookup to find. Only ffmpeg.exe, ffprobe.exe and LICENSE are kept.
- **Lookup is per tool: `bin/`, then PATH.** `bin/` wins so a friend's odd PATH ffmpeg can't
  shadow the known-good build once they've downloaded it.
- **Tool paths are injected, not global** (MODERATE). `AppState.ffmpeg/ffprobe` feed
  `probe_file(ffprobe=)` and `EncodeJob(ffmpeg=)`, and every default is the bare name, so no
  existing test changed.
- **The prompt defaults to yes on Enter; EOF means no.** A friend presses Enter. An agent
  without a console gets exit 1 and a pointer to `--get-ffmpeg` instead of a hang or a
  surprise 110 MB download.
- **`.gitattributes` forces CRLF on `.bat`.** The index stored it as LF, the GitHub "Source code
  (zip)" is a `git archive`, and cmd.exe misparses LF-only batch files in some cases.

- **MIT for Squishy; ffmpeg stays at arm's length.** The gyan essentials build is GPLv3. We
  only exec it as a separate process and never distribute it, so GPL obligations sit with
  gyan.dev as the distributor. Bundling it into a release zip would move them onto us.

### Verified

- Live pinned download (`SQUISHY_LIVE_DOWNLOAD=1`): 6.6 s, hash matched, `-version` reports 9.0.2.
- `launch.py --get-ffmpeg` into the real `bin/`, then with PATH stripped of ffmpeg: the bin
  ffprobe probed a 1080p60 clip and the bin ffmpeg encoded it on Heavy, 607 KB vs 945 KB ceiling.
- Installed footprint is **~200 MB** (two static ~100 MB exes), not the 110 MB download size.
  The prompt and README say both.

### Not verified

- A clean machine, and Mark-of-the-Web/SmartScreen behaviour on a `.bat` from a downloaded zip.
- The v0.1 items are still open: real double-click, Open folder, real OS drag-and-drop.
- **The repo is private.** Friends can't see Releases until it's public or they're added as
  collaborators.

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
