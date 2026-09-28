# DEVLOG - Squishy McSquishface

Newest entries first. Decisions, rationale, and measured results; not a changelog.

---

## 2026-09-27 - v0.4.0 built: batch

196 tests pass (+32). New: `batch.py` (pure helpers, listing, runner), `picker.py`,
`awake.py`; routes in spec section 5. Tests were written before the code. The server
route tests were seen failing first; the runner's were not (both runs went green at once),
so their teeth are unproven beyond the scenarios they drive.

**Criteria (spec Sprint 5):**

1. Pickers: the spike, plus the real UI in the preview pane. A script filled the real
   dialog through window messages (no keystrokes), for both a folder and two files. **Not
   yet:** a click from Chrome on this PC and on ROG.
2. Listing: videos sorted by name, all ticked; a broken `.mp4` greyed with "not a readable
   media file"; `notes.txt` in a "Not videos, left out" line. Card totals are the sum of
   the per-file ceilings (Medium: 10.0 MB vs rows 2.5 + 2.1 + 2.1 + 3.4, each rounded).
3. `test_batch_encodes_every_file_with_single_file_args`: each job has no custom args and
   the same `plan_for` plan, so it is the untrimmed single-file encode.
4. Tests for skip-existing, a vanished source (fails, batch carries on), a starved-noise
   source that re-encodes bigger (deleted, "no smaller"), and stop-then-resume. In the UI:
   a rerun skipped the 3 files already done at that level.
5. Stop in the UI: "Stopped; partial file deleted", the rest "Not started", no `.part` or
   output left on disk.
6. Reloading the page mid-run and after the end brings the batch (and summary) back.
7. Recorded `SetThreadExecutionState` calls: every thread (the batch's and each file's
   encode) sets, then clears, including on failure. The real call is accepted.
   **Not verified at the OS level** (`powercfg /requests` needs admin).
8. Version 0.4.0; README, RELEASE_NOTES, spec routes, onboarding updated.
9. **Pending:** the user's real folder, unattended.

**Decisions made while building** (MODERATE):

- **Outputs are written as `<name>.part.mp4` and renamed when complete.** Otherwise a
  crash or power cut mid-encode leaves a half file under the final name, and the resume
  rule ("output exists, skip") would treat it as done.
- **Non-video files are one summary line, not rows.** A folder of 300 photos shouldn't bury
  the videos. Files that look like videos but can't be read *are* rows, greyed, with the
  reason (the text before ffprobe's first colon; the full text is logged).
- **Files inside Squishy's output folder are refused,** so a batch can't squish its own
  results into `clip_medium_medium.mp4`.
- The Choose buttons are disabled while a batch runs; the server refuses picks then anyway.
- `safe_stem` moved from `server.py` to `trim.py` (next to `output_stem`) so `batch.py` can
  use it without an import cycle; `server.py` re-exports it.

---

## 2026-09-27 - v0.4 planned: batch (grilled)

Plan and success criteria are in spec.md Sprint 5. The user asked for it after an 11 min,
2 GB file took ~8 min on ROG (3800X, 8 cores): batch makes encode speed matter less
than GPU encoding would (see the NVENC spike). Two decisions a later reader would question:

- **Decision (user): batch comes into scope,** reversing spec section 8 again. It stays
  one file at a time (x264 already uses every core) and one preset for all files, whole
  files only: trims are hands-on, and batch exists so nobody has to be there.
- **Decision (user, on my recommendation): files are read in place, via a picker the
  server opens,** not uploaded. A browser can't hand a local page a folder's paths, only
  copies of the files; for a folder of 2 GB captures that is tens of GB copied into temp
  before the first encode. Squishy's server runs on the same machine, so it can open a
  native Windows picker (tkinter, stdlib) and read the chosen files directly. The cost:
  this is the first time the page acts on files outside what was dropped on it, and it
  only works because the server is localhost-only (keep it that way). Rejected: a
  `webkitdirectory` folder upload (the copies), and a typed path box (clumsy, easy to
  get wrong).

Smaller calls, on my recommendations: skip files whose output exists (makes Stop +
rerun a resume); delete a result that isn't smaller and count it as skipped; one Stop
(no "after this file"); keep the PC awake during any encode, not just batches.

**Spike: does a server-spawned picker open in front?** (criterion 1, the one unknown.)
Throwaway harness: a child Python runs tkinter `askdirectory` / `askopenfilenames` on a
withdrawn root, with and without `-topmost`; the harness finds the dialog by title, checks
`GetForegroundWindow`, then sends WM_CLOSE (= cancel).

- All four variants opened in 1.5-2.0 s, **took the foreground**, and cancel returned an
  empty result (`''` / `()`).
- Worry: Windows blocks background processes from taking the foreground, and the first
  run descended from the (foreground) Claude app. The foreground lock timeout here is the
  maximum (never expires) and the user was active 24 s before. Re-run via WMI
  `Win32_Process.Create` (parent outside that tree) with Windows Terminal in front: same
  result, all four in front.
- **Decision:** use `-topmost` anyway (it puts the picker above the browser even if some
  machine does refuse focus) and show "Opening the picker..." on the page for the 1.5-2 s
  tkinter start. The server is a `ThreadingHTTPServer`, so a request can wait on the picker
  without blocking progress polls. Still to see: a real click from Chrome, on both
  machines, in the build's check.

---

## 2026-09-27 - v0.3.0 built: trim, Original, Save frame

161 tests pass (+79) at the build; 164 after the fixes below. Pure parts written test-first (`test_trim.py`, the v0.2.4 args pin);
`test_trim_integration.py` checks frame-exactness on a generated clip whose frames carry
their own number as 8 black/white blocks, so every output frame traces to its source frame.

**Success criteria (spec Sprint 4):**

1. Untrimmed args identical to v0.2.4: pinned by `test_untrimmed_args_match_v024`, written
   before any change.
2. Trimmed encodes start on the in-point frame and keep out - in +/- 1 frame, all four presets;
   an in-point between two frames starts on the later one.
3. Reference clip trimmed (5-15 s, and 2.16 s from 12.34 s): actual/ceiling 0.56-0.92.
4. Original starts on the snapped keyframe (.mp4 and .mkv), keeps the container, and the
   card's figure was within 1% at 82 MB and 21 MB. It was 1% *high*, from reusing the
   ceilings' container allowance; a copy's real overhead is 0.04%, so the figure is now the
   plain packet total. A copy takes 0.6 s.
5. Displayed frame = saved frame, on the VFR reference clip. Canvas of the browser's
   frame vs ffmpeg's frame at that time and at both neighbours, comparing only pixels that
   change between them: at 5 of 8 positions the match was clear (3-6 vs 15-23). At 2, the
   capture had a repeated frame (current = next, same picture either way); at 1, nothing
   moved. The browser's frame time also matched ffprobe's (9.990 vs 9.990422).
6. Range: 206 / 416 / whole-file tests; the real browser loads and seeks the 227 MB clip.
7. Fallback: an MPEG-4 Part 2 file (Chrome can't decode it) switched to ffmpeg frames; trim by
   keyboard, Save frame, a trimmed Extreme and an Original all ran from the UI.
8. Version 0.3.0; README, RELEASE_NOTES, spec routes, onboarding updated.

**User's desktop check, first finding:** after scrubbing to a spot, dragging a handle there
was impossible. The handle drag moves the playhead (to show the frame under the handle),
which erased the spot. Fix: on grabbing a handle, the playhead's spot stays as a dashed ghost
marker, and the handle snaps onto it within 8 px. Also, grabbing a handle without moving
it no longer changes anything; it used to jump to the pointer. Checked in the browser with
real mouse input: a release 5 px from a ghost at 3.003 set the end to 3.020 (that frame +
half a frame); a far drag doesn't snap; a click leaves the trim alone.

**Second finding: playhead and handles competed for the same click** once they sat on
top of each other. Fix (user's idea, refined): two lanes. The top lane is the timeline:
click or drag anywhere in it (or its round knob) to scrub. The bottom lane holds only the
`[` `]` brackets, and a click on its empty space does nothing. Thin guide lines cross both
lanes to show alignment and take no clicks. Rejected: a taller playhead grabbed from the
bottom (still ambiguous to a first-time user) and hidden priority rules. Checked with real
mouse input, with the playhead exactly on the end bracket: a top-lane drag moved only the
playhead, and a bottom-lane drag moved only the bracket.

**Third: the Original's keyframe was invisible.** The card said "starts X s early" but
nothing showed where keyframes were. The user's WhatsApp test clip had 4 keyframes in
37 s, and x264's default gap is 250 frames (4.2 s at 60 fps), so "early" can mean
seconds. Added:

- Keyframe ticks under the timeline (`GET /api/keyframes/<id>`, from the existing packet
  scan). Where ticks would sit closer than 0.4% of the width, some are skipped, but every
  tick drawn is a real keyframe.
- Ctrl+arrows jump to the previous/next keyframe. With the start bracket focused, the
  bracket moves too.
- A **Start on keyframe (X s earlier)** button beside the trim info. It moves the in-point
  back to the Original's start, so the presets and the Original begin on the same frame.
  It sits in the tools row, not on the card, because the card is a `<button>` and can't
  hold another.

**Rejected:** brackets catching on keyframes. On the reference clip keyframes are about
14 px apart, and the catch distance is 8 px, so almost every drag would land on a keyframe.
That breaks frame-exact preset trims. Parked in the spec as an opt-in idea.

**Snap tolerance widened to SEEK_SLACK_S (2 ms)** (MODERATE). It was 1e-6. If the player
reported a keyframe's time even a fraction of a ms low, Set start there would snap the
Original back a whole keyframe gap. The presets' seek already treats 2 ms as the same
frame, so the snap now does too. `snap_s` is clamped at 0. Checked on a generated clip with
keyframes at 0/10/20 s, in the fallback player: Ctrl+arrows landed on frame 600 exactly
(burned-in counter), the button moved a 15 s start to 10 s, and the warning cleared. In
video mode one Ctrl+arrow seek set `currentTime` to 10.0005, as intended. 164 tests pass.

Also renamed the bracket-to-scrubbed-spot behaviour from "snaps onto" to "catches on"
(README, code comment, `CATCH_PX`), so **Snap** keeps its one glossary meaning.

**Not checked here:** dragging and keys in *video* mode with the pane on screen. The
browser pane was hidden for most of the session, and `requestVideoFrameCallback` (which
reports the shown frame's time) only fires while the page paints. The time display froze
at 0:00.000 until the pane was brought forward. **Closed by the user's desktop use:**
playback, the brackets, Save frame and a trim that came out right, on this machine
and on ROG (a second desktop, cloned from GitHub).

**Found along the way:**

- **Seek slack widened to 2 ms** (MODERATE). The plan was 0.5 ms. If Chrome reports frame
  times rounded to the ms, a 0.5 ms back-off lands on the next frame. That rounding is
  unverified (it needs the pane painting), so the slack covers it anyway: 2 ms is under half
  a frame up to 240 fps. Tests cover +/- 1 ms.
- **Packet times must be relative to the file's start_time.** ffprobe prints absolute
  times, and `-ss` counts from the start. They agree only when a file starts at 0. An .mkv
  remux started its video at 0.021 s, and MPEG-TS files often start at 1.4 s.
- **A copy's video can start a few ms after its audio** (18 ms here): audio cuts on AAC
  frame boundaries. Sync is kept. A constant-rate decode pads the gap with a repeat of the
  first frame, which fooled the first version of the frame-number test.
- **Ceilings aren't proportional to length:** `maxrate * (duration + 1.8 s)`, so a 1 s cut
  keeps nearly half the ceiling of a 4 s clip. Corrected in the planning entry below.

---

## 2026-09-27 - v0.3 planned: trim + stills (grilled)

Plan and success criteria are in spec.md Sprint 4. Two decisions a later reader would
question:

- **Decision (user): trimming comes into scope,** reversing spec section 8. Trimming is
  compression by another means: every size ceiling grows with duration (plus a fixed 1.8 s
  VBV-buffer term), so a 31 s -> 10 s cut shrinks every preset ~2.8x at no quality cost. That is the app's job ("make it fit"), with
  a better lever than bitrate. It is a setting on the one screen, not a mode, and untouched
  in/out points must give v0.2.4's exact ffmpeg args. Stills ride along only because the
  player makes them nearly free; the out list (spec Sprint 4) is what keeps this from
  becoming an editor.
- **Decision (user): the Original card cuts at keyframes and says so.** A stream copy can
  only start on a keyframe (P-frames need their reference), so the start snaps *back* to the
  keyframe at or before the in-point. Nothing asked for is lost, the card shows the snap,
  and the out-point is exact. Rejected: a frame-accurate "near-lossless" re-encode (that is
  Light without the cap, not "as is"), an edit-list lead-in (player support unverified), and
  a smart cut (re-encode the first partial GOP; fragile at the seam). Snap size depends on the
  source: the UE captures have a keyframe every 0.5 s, phones 1-2 s, OBS ~2 s or more.

Test approach: pure parts test-first (the v0.2.4 args pin, Range parsing, keyframe snap,
trimmed estimates, names); the displayed-frame-equals-saved-frame question gets a spike before
it gets a test; scrubber feel and layout are checked in a real browser, not unit-tested.

---

## 2026-09-27 - Spike: NVENC vs x264 (Parking Lot)

Question: is `h264_nvenc` (RTX 3090) fast enough, at acceptable quality per byte, to offer?
Throwaway script, reference clip, same resolution / fps / VBV cap as each preset. NVENC:
`-preset p7 -tune hq -rc vbr -cq N -b:v 0`, 32-frame lookahead, spatial + temporal AQ,
3 B-frames as references. CQ swept 19-31. H.264 only (HEVC/AV1 would break playback on
some of the places the output goes). Quality is VMAF (every 4th frame) against the source
put through the same fps/scale filters.

| Preset  | x264 slow: size / VMAF / time | NVENC, best CQ: size / VMAF / time | Verdict |
|---------|-------------------------------|------------------------------------|---------|
| Light   | 18.7 MB / 92.3 / 19.6 s       | 24.1 MB at matched VMAF / 11.8 s   | +29% size |
| Medium  | 12.1 MB / 87.5 / 17.8 s       | 11.6-12.6 MB / 84.2-84.6 / 11.3 s  | -3 VMAF |
| Heavy   | 5.2 MB / 90.6 / 9.2 s         | 5.0-5.5 MB / 87.9-88.3 / 7.7 s     | -2.3 VMAF |
| Extreme | 2.3 MB / 86.6 / 8.1 s         | 2.2-2.3 MB / 80.8-82.3 / 8.6 s     | -4 to -6 VMAF |

- **The cap binds NVENC at every CQ** for Medium, Heavy and Extreme: size and VMAF barely
  move across the sweep. CQ itself works (uncapped Medium: 91.8 MB at CQ 19, 18.6 MB at
  CQ 31). So those rows are "same bit budget, which looks better", and x264 wins every one.
  Matching x264's quality would mean spending past the cap, which breaks the ceiling.
- **The speed win is small here.** It is 1.6x at the 1080p presets and nothing at the low
  ones, because CPU decoding of 4K60 and the scale dominate. GPU decode + `scale_cuda`
  might change that; unmeasured. On a 31 s clip the saving is 1-8 s per encode.
- **Gotcha, for any future VMAF work:** the source is VFR (frame gaps 16.3-23.5 ms), and
  encodes come out CFR. libvmaf pairs frames by timestamp, so it scored Light 57.6 until
  both inputs were renumbered by frame index (`settb=1/1000,setpts=N`), giving 92.3.

**Decision (user): not building it.** Inside Squishy's caps x264 gives better quality at every
preset, and the time saved is a few seconds per encode. Revisit only if GPU decode + scale
turns out several times faster *and* someone wants a "fast, slightly worse" mode.

---

## 2026-09-27 - Spike: sample-based size estimate (Parking Lot)

Question: does encoding a few short chunks predict the actual size well enough, cheaply
enough, to be worth building? Throwaway script, not in the repo. The reference clip now
lives in `samples/` (gitignored); full encodes reproduce the v0.1 table.

Method: 3 chunks centred at 1/6, 3/6, 5/6 of the clip. One ffmpeg per chunk decodes once and
`split`s to all four presets (same x264 settings as the real encode, raw `.h264` out).
Predicted video rate = chunk bytes / chunk time, optionally clamped at the preset's maxrate
(each chunk starts with a 90%-full VBV buffer, so it can burst over the cap). Size =
rate * duration + audio, +1% container.

| Preset  | Actual   | Ceiling (now)  | 3 x 2 s, clamped | 3 x 4 s, clamped |
|---------|----------|----------------|------------------|------------------|
| Light   | 18.7 MB  | 32.3 (+73%)    | 25.2 (+35%)      | 21.4 (+14%)      |
| Medium  | 12.1 MB  | 14.4 (+19%)    | 13.6 (+13%)      | 13.6 (+13%)      |
| Heavy   | 5.2 MB   | 6.3 (+23%)     | 6.0 (+16%)       | 5.5 (+6%)        |
| Extreme | 2.3 MB   | 2.6 (+14%)     | 2.5 (+8%)        | 2.5 (+8%)        |

Cost: 3 x 2 s took 9.8 s, 3 x 4 s took 15.2 s, against 17.8 s for the Medium full encode
(54.7 s for all four).

- **Chunks bias high,** every preset, every run: a keyframe and a full VBV buffer per chunk.
  Longer chunks shrink it. Without the clamp, 2 s chunks were +24-34%.
- **Chunks vary a lot:** Light's three 4 s chunks came in at 4.7, 8.7 and 3.3 Mbps. Three
  samples can land on or miss the hard part of a clip.
- **Only Light gains much.** It is the one preset whose ceiling is badly loose (CRF, not the
  cap, decides its size). The other three are already within about 20% and sampling roughly
  halves that.
- **Economics run the wrong way.** On a 31 s clip, 4 s sampling costs 85% of a Medium encode.
  It gets cheap only on long clips, where 3 x 4 s covers a few percent of the content and
  the variance above gets worse. That case is unmeasured (one clip).

**Decision (user): not building it.** The real gain is on Light alone, and on clips of this
length it costs nearly a full encode. Worth revisiting only if long captures (minutes)
become routine; re-run this measurement on one first.

---

## 2026-09-26 - v0.2.4: version-aware handoff to a running Squishy

82 tests pass (+13 `test_launch.py`; the ping test also checks the version). Fixes the open
item from the desktop check below.

- **`/api/ping` now returns `version`** (`squishy.__version__`, kept equal to pyproject by
  `test_version_matches_pyproject`). `launch.py`'s `running_version()` reads it back as
  "unknown" when a ping has no version (v0.2.3 and earlier), or None when whatever answers isn't Squishy.
- **Decision (moderate confidence):** if the running copy is older or unknown, refuse. Log
  "An older Squishy (...) is already running at URL. Close its window, then start this one
  again.", exit 1 (the `.bat` pauses, so the message stays on screen) and don't open a browser.
  If it's the same version or newer, open it as before (newer adds a note).
  Rejected: starting beside the old one on a free port. v0.2.2 and earlier `rmtree` all of
  `%TEMP%\squishy` on exit, which would take the new instance's uploads.
  Rejected: an auto-quit endpoint. Too much for this; a message the user can act on is enough.
- **Repro:** a v0.2.3 `git archive` copy on port 48210, then the new launcher on the same port.
  Before: "already running; opening", exit 0. After: the refusal, exit 1. Through
  `Squishy.bat` too: the message, "Press any key", exit 1.
- README gained an "Upgrading?" line.

**Checked by the user on the desktop, after release.** With v0.2.3 still open, a v0.2.4
double-click showed the refusal and paused. That run was from the repo checkout, on the
same commit as the tag. After closing v0.2.3: real drag-and-drop, Squish it, Open folder and
Download all worked ("works fine"). Which copy that second run used wasn't stated. That closes the
"still needs a human" list from the v0.2.3 check.

---

## 2026-09-26 - v0.2.3 checked on the real desktop

The user downloaded the release zip, got SmartScreen's unsigned-app warning, clicked through,
and double-clicked `Squishy.bat`. The browser opened.

**Found: that first run never reached v0.2.3.** A dev instance started 2026-09-23 18:12 was
still holding 48123. `already_running()` got a ping, so the new copy opened the browser to the
old one and exited. The old process's Python was pre-v0.2.0, but it served the repo's current
`index.html` (read from disk per request), so the page looked current. After the old process
was stopped, a relaunch through the `.bat` (`py -3 launch.py`) came up as v0.2.3, with its
`run-<id>` folder and lock.

Against the real v0.2.3 instance (default port and output folder, ffmpeg from PATH, no `bin/`):
- **Real clip**, 227 MiB 4K60 UE5 capture: upload 1.0 s. Medium: 12.1 MiB against a 14.4 MiB
  ceiling (0.84), 18 s.
- **Open folder:** Explorer opened `Videos\Squished` with the new file selected (seen with
  computer use).
- **Download:** 200, Content-Length matches the file, UTF-8 filename header correct.
- The upload was driven over HTTP the way the page does it, not through the page: File
  Explorer is granted click-only, so there's no drag, and the built-in browser pane never
  hands the file picker off to a native dialog.

**Still needs a human:** real drag-and-drop onto the page, and clicking the page's own
Open folder / Download buttons.

**Open (not fixed):** an older Squishy on the port silently wins the handoff, so a friend who
upgrades while the old one is open gets the old version with no hint. Candidate fix: `/api/ping`
returns the version, and `launch.py` warns on a mismatch ("an older Squishy (vX) is running;
close its window first").

---

## 2026-09-26 - v0.2.3: audit findings 6, 7, 11 (the audit list is now closed)

71 tests pass (+5 `test_workdir.py`, +2 `test_tools.py`, +1 `test_integration.py`); the 2
skips are the opt-in live downloads. Each finding was reproduced before the fix and checked after it.

### 7. Cover art first: the encode failed

Probe skipped `attached_pic` streams, but the encoder mapped `0:v:0`, the first video
stream *including* cover art. Fix: `-map 0:V:0`. Capital `V` is ffmpeg's specifier for
video that isn't an attached picture, which is exactly probe's rule.
- **The audit guessed the wrong symptom.** It isn't a frozen frame: ffmpeg carries the
  `attached_pic` disposition onto the H.264 output, and the MP4 muxer refuses it ("Could not
  find tag for codec h264"). The encode fails.
- **Reaching it needs a specific file.** ffmpeg's muxers always write cover art last (MP4 `covr`,
  MKV attachment), so no ffmpeg-made file triggers it. The MP4 *demuxer*, though, creates the
  cover stream wherever `udta` sits in `moov`. A tagger that writes `udta` before the
  traks therefore produces cover-first files. The repro moves the `udta` box to just
  after `mvhd`: same bytes, and the chunk offsets stay valid under `+faststart`.
  How common such taggers are: not checked.
  `test_cover_art_first_encodes_the_real_video` builds that file; it fails on `0:v:0` with the muxer error.

### 11. Broken HTTP responses skipped the download fallback

`_install_from` caught only `OSError`. `http.client.HTTPException` isn't one, so it escaped
`download_tools` without trying the next source. Now it's a `DownloadError`, so the next source gets tried.
- A short *fixed-length* body never raised: `read(amt)` returns short and the checksum
  catches it. That first repro passed on the unfixed code and was replaced. The escaping
  cases are a truncated *chunked* body (`IncompleteRead` mid-read) and a non-HTTP reply
  (raised inside `urlopen`). Both are tests, both failed before.

### 6. Per-instance temp folders

**Problem.** Every instance shared `%TEMP%\squishy`. Startup `rmtree`'d it, and so did shutdown,
so one instance could delete another's uploads, in either direction. A second instance is
realistic, not contrived: if something else holds 48123, the first Squishy falls back to a
free port. The next double-click then pings 48123, doesn't find Squishy, and starts another instance.
Reproduced live (two `launch.py` processes, ports 48201/48202): A uploads, B starts, and A's
encode fails with "Error opening input: No such file". After the fix: A's encode is `done`.

**Fix: `squishy/workdir.py`.** Each instance claims `run-<id>/` plus `run-<id>.lock` beside it,
holding the lock open for its lifetime. The startup sweep deletes only folders whose lock it
can take. On Windows that test is deleting the lock, which fails with a sharing violation
while the owner has it open; on POSIX it's `flock`. The OS closes the handle however the
process dies, so crash leftovers still get swept (checked: two hard-killed instances'
folders removed by the next start). Shutdown releases only its own folder.
- The lock is created before the folder, and the sweep re-checks for a lock right before
  deleting. So a folder listed mid-startup is never taken for stale.
- Rejected: PID-in-name liveness. PIDs get reused, and `os.kill(pid, 0)` on Windows
  *terminates* the process instead of probing it.
- Loose files directly under the root (the v0.2.2-and-earlier layout) are swept too.
  An old-version instance running alongside would still `rmtree` everything; can't fix that.
- Known gap, POSIX only: between `open("x")` and `flock` there's a window of microseconds
  in which a sweep could take a brand-new lock.

Also: backfilled the missing GitHub Release for v0.2.1 (the tag existed; v0.2.0 was still "Latest").

---

## 2026-09-26 - v0.2.2: upload-flow fixes (audit findings 5, 8, 9, 10)

v0.2.2. 63 tests pass (+4 in `test_server.py`), including the ffmpeg round-trip.
(Correction, v0.2.3: this entry first said the round-trip skips without `bin/` on PATH.
It doesn't on this machine: Chocolatey's ffmpeg is on PATH. The 2 skips are the opt-in live downloads.)
Each finding was reproduced before the fix and checked after it.

- **9. Errors sent before the body is read now arrive.** Before: an upload during an encode
  (second tab) and an upload into a vanished temp dir both got `ConnectionAbortedError`, so
  the browser said "Upload failed / is the console open?". Cause: replying and closing with
  unread body makes Windows send a reset. `Handler._receive()` now always reads the body to
  the end, saving it if it can and discarding it otherwise, and returns `(received, write_error)`.
  The busy upload drains and gets its 409. A write failure (temp gone, disk full) drains and
  gets a **500** "could not save the upload" (not 422: it's our fault, not the file's).
  A short body means the browser left: delete the partial file and send nothing.
  Cost, accepted: a 409 for a multi-GB file means reading it all over loopback first.
- **10. `_encode` looks up the upload under the lock.** Before: a test holding the lock
  while an upload deleted the source got a 200 and a job started on a missing file.
  After: 404 "drop it again", no job.
- **5. A new drop aborts the upload in flight** (`state.xhr`, plus a stale-handler guard).
  Before, in the browser pane: 300 MB junk dropped, then a real clip 30 ms later. The clip
  loaded, then junk's late 422 wiped it out ("last to finish wins"). After: the clip stays
  loaded and encodes. `loaded()` also clears any leftover poll interval, as a backstop.
- **8. A failed upload forgets the old file.** Before: after a 422, "Squish it" stayed
  enabled for a source the server had already deleted. After: `forget()` clears the source,
  cards and results and disables the button. The headline is "Could not read that file"
  only for a 422 and "Upload failed" otherwise.

Not exercised from the browser: the server's abandoned-mid-body path. Chrome aborted a
1.5 GB in-memory Blob before sending a byte, so the raw-socket test
`test_upload_abandoned_mid_body_leaves_no_temp_file` stands in for it.

Still open from the audit: 6 (shared temp dir wiped by a second instance), 7 (cover art
mapped as video), 11 (`HTTPException` skips the download fallback). New, minor: two tabs
uploading at once can leave the earlier-started file in temp until the next upload or exit.

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
