# DEVLOG - Squishy McSquishface

Newest entries first. Decisions, rationale, and measured results; not a changelog.

---

## 2026-09-24 - v0.2.1: release smoke test, console fixes, robustness audit

Headless follow-up (user on phone). 59 tests pass: +4 `test_launch.py`, +1 `test_lifetime.py`, +2 `test_server.py`.

### Fixed

- **Log lines no longer land on the download progress line.** Root cause was wider than
  the v0.2 note: *any* log record while the `\r` line was open, including the success line
  when a server sends no Content-Length. `ProgressLine` tracks whether its line is open
  and `ConsoleHandler` closes it before emitting, so the fix is in one place, not at each call.
- **`Squishy.bat` now returns launch.py's exit code.** `pause` resets ERRORLEVEL, so an
  agent running the .bat got 0 after a failure. It now saves the code, pauses, then `exit /b`s with it.
- **EOF-at-prompt newline is flushed.** With piped output the ERROR landed on the prompt line.

### Verified (release zip, as a friend gets it)

`git archive v0.2.0` (the same way GitHub builds its "Source code" zip) -> 28 files, no `bin/`,
`.bat` all CRLF. Extracted to scratch, run from another folder, ffmpeg removed from PATH:

- No console: prompt -> EOF -> "No ffmpeg" pointer, no hang. Python 3.7/3.8/3.10 get the
  one-line version message, not a traceback.
- `Squishy.bat --get-ffmpeg`: pinned download 7 s, hash OK, ffmpeg 9.0.2 in the copy's `bin/`.
- HTTP drive of a 1080x1920 clip with audio, named `Beach day été (1).mp4`: all four presets
  done, actual/ceiling 0.54-0.81, portrait preserved (Heavy 720x1280), UTF-8 download name correct.
  Cancel leaves no partial output. Junk upload gets 422 and temp is clean. Foreign Host / cross-origin POST get 403.

### Fixed from the audit (items 1-4; each reproduced before, verified after)

1. **ffmpeg no longer outlives Squishy.** `CREATE_NO_WINDOW` gives ffmpeg its own hidden
   console, so closing ours never reached it, and a closed console skips `finally:
   app.shutdown()`. Each ffmpeg now joins a Win32 Job Object with KILL_ON_JOB_CLOSE (ctypes,
   in `encoder.py`). Its handle is never closed, so the kernel kills ffmpeg whenever Python
   dies, however it dies. Rejected: dropping `CREATE_NO_WINDOW`, which covers a console close but
   not taskkill or a crash. Best effort: if the job can't be created or assigned, it logs a
   warning and encodes anyway. Before: ffmpeg survived a hard kill of the server. After: gone.
   Test: `test_lifetime.py`.
2. **Busy port detected even when its owner set SO_REUSEADDR.** `SquishyServer` drops
   SO_REUSEADDR on Windows and claims `SO_EXCLUSIVEADDRUSE`. Before: v0.2.0 bound on top of a
   Python server on the same port. After: "busy; using a free port".
3. **Unwritable output folder gives a 500 with the reason**, not a dropped connection
   ("Server not reachable"). `unique_path` + `touch` now sit in the same try as `mkdir`.
4. **A failed poll no longer locks the UI.** A network failure gets 6 retries (3 s), and an
   HTTP error (e.g. a 404 after a server restart) gives up at once. Giving up clears
   `state.job`, so `busy()` is false and the cards and drop work again. Checked in the
   browser pane with a stubbed `fetch`: a 2 s blip is ridden out, a dead server gives up
   at 3.1 s with the cards re-enabled, and a 404 gives up at 0.5 s, then a new drop loads.

### Open findings (not fixed; ranked)

5. Second drop during an upload doesn't abort the first; last to finish wins, poll breaks.
6. A second instance's startup `rmtree` wipes the first's uploads (shared `%TEMP%\squishy`).
7. Probe skips cover-art streams but the encoder maps `0:v:0`, so cover art first gives a frozen frame.
8. After a failed upload the old "Squish it" button stays enabled.
9. 409 / 422 sent before reading the body: the client sees a connection reset, not the message
   (seen in the smoke test with a second-tab upload).
10. `_encode` looks up the upload outside the lock (millisecond race).
11. `http.client.HTTPException` (e.g. IncompleteRead) escapes `download_tools`, skipping the fallback.

### Still needs a human at the PC

Real double-click, Open folder, real drag-and-drop, SmartScreen on a downloaded zip.

---

## 2026-09-24 - Sprint 3: shareable v0.2 (ffmpeg on demand, README, release notes)

**Built:** `squishy/tools.py` (lookup + download), `--get-ffmpeg`, a Python check in
`Squishy.bat`, README.md (human + agent sections), RELEASE_NOTES.md, LICENSE (MIT). 52 tests pass,
plus 2 opt-in live download tests, one per source (`SQUISHY_LIVE_DOWNLOAD=1`).

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
- **Two sources, one hash.** The mirror goes first and gyan.dev's own `packages/` copy is the
  fallback. Both serve identical bytes (114,768,076, same digest). Any failure, a hash
  mismatch included, moves on to the next source; the hash is the trust anchor, not the host.
  The live test downloads from each source separately, because a dead fallback looks like
  cover and isn't.
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

- Live pinned download (`SQUISHY_LIVE_DOWNLOAD=1`), each source separately: GitHub 5.4 s,
  gyan.dev 9.7 s. Both hashes matched and `-version` reports 9.0.2.
- `launch.py --get-ffmpeg` into the real `bin/`, then with PATH stripped of ffmpeg: the bin
  ffprobe probed a 1080p60 clip and the bin ffmpeg encoded it on Heavy, 607 KB vs 945 KB ceiling.
- Installed footprint is **~200 MB** (two static ~100 MB exes), not the 110 MB download size.
  The prompt and README say both.

### Not verified

- Cosmetic: if a source dies mid-download, its WARNING prints on the same console line as
  the progress counter. The download still falls back correctly.
- A clean machine, and Mark-of-the-Web/SmartScreen behaviour on a `.bat` from a downloaded zip.
- The v0.1 items are still open: real double-click, Open folder, real OS drag-and-drop.

### Shipped

- Scrubbed the machine-specific details (an absolute `C:\Users\...` path in the spec, and a note
  about another local tool's port) out of **all** history with filter-branch, then made the repo
  public and released **v0.2.0**. Known residue, accepted: GitHub still serves the pre-rewrite
  commits by exact SHA until it garbage-collects them. Nothing links to them.
- Machine-specific notes now live in `CLAUDE.local.md` (gitignored). Keep them out of tracked docs.

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
