# Squishy McSquishface

Drop a video in, pick how hard to squish it, get a smaller MP4. Optionally trim it to just
the part you want first, or save a single frame as a picture. Or point it at a whole
folder and let it work through them while you're away.

Squishy runs on your own computer: it's a tiny local web page driven by ffmpeg. Nothing is
uploaded anywhere. Before you encode, it shows the **largest** file each compression level can
produce, so you can tell up front whether it'll fit under Discord's or email's limit.

| Level   | Resolution | Frame rate | Video bitrate cap |
|---------|------------|------------|-------------------|
| Light   | 1080p      | up to 60   | 8 Mbps            |
| Medium  | 1080p      | up to 60   | 3.5 Mbps          |
| Heavy   | 720p       | up to 30   | 1.5 Mbps          |
| Extreme | 540p       | up to 30   | 0.6 Mbps          |

Squishy never scales up: a 720p source stays 720p on Light.

---

## For humans

**You need:** Windows 10/11 and [Python 3.11 or newer](https://www.python.org/downloads/).
When you install Python, tick **"Add python.exe to PATH"**. You don't need to install ffmpeg:
Squishy offers to download it the first time you run it.

1. Download the latest release zip from the **Releases** page and unzip it somewhere permanent
   (for example Documents, not Downloads).
2. Double-click **`Squishy.bat`**.
   - If Windows warns that the file came from the internet, click **More info -> Run anyway**.
     To stop the warnings for good, right-click the zip, choose **Properties**, tick **Unblock**,
     then unzip it again.
3. **First run only:** it asks `Download it now? [Y/n]`. Press Enter. This fetches ffmpeg
   (a 110 MB download that takes ~200 MB on disk, once) into a `bin` folder next to `Squishy.bat`.
4. Your browser opens. Drop a video in, pick a level, and click **Squish it**.
   - **To keep only part of it,** drag the orange [ ] brackets under the timeline, or play to the
     right spot and click **Set start** / **Set end** (keys `I` / `O`; arrow keys step one
     frame, Shift+arrows one second). Scrubbed to the right spot first? Drag a bracket
     toward it and the bracket catches on it. The sizes update as you go. An extra **Original** card
     appears that cuts the clip without re-encoding at all.
   - **The ticks under the timeline are keyframes,** the only places an Original can start
     (see below). Ctrl+arrows jump between them. If the Original would start early,
     **Start on keyframe** moves your start back to it, so every card starts on the same frame.
   - **Save frame** saves the frame you're looking at as a full-size JPEG.
   - **Got a pile of videos?** Click **Choose folder...** (or **Choose files...**), untick any
     you don't want, pick a level, and click **Squish**. Squishy does them one at a time
     while you do something else, and your PC won't go to sleep halfway. You can close the
     browser tab; reopen Squishy's page to check on it. Batches squish whole videos (no
     trimming). Stopped partway? Choose the same folder again: videos already done are
     skipped.
5. Your files go to **`Videos\Squished`**. Click **Open folder** to jump there. Trimmed clips
   and frames have their time range in the name, e.g. `clip_medium_5.200s-12.800s.mp4`.

To quit, close the black console window. To uninstall, delete the folder. Your squished videos
stay in `Videos\Squished`.

**Upgrading?** Close the old Squishy's console window first. If it's still open, the new one
says so and stops, rather than quietly opening the old version.

### Things that look like bugs but aren't

- **The actual file is smaller than the size shown.** The number is a ceiling ("up to"), not a
  prediction. Easy footage (talking heads, static screens) comes in well under it.
- **A level says "capped at the source's own bitrate".** Your video is already small, and
  adding bits can't add quality back.
- **MB here means the same as in Windows Explorer**, so the numbers match what Explorer shows.
- **The Original card starts a little before your start point.** Copying without re-encoding
  can only start on a *keyframe* (a frame stored whole; the ones between are stored as
  changes). The card says how early: under a second for many cameras, but some recordings
  (phone and chat-app videos, for example) have keyframes several seconds apart. The squish
  levels start exactly where you set. Click **Start on keyframe** to make them all match.
- **A batch "skipped" a video.** Either it was already squished at that level (its file is in
  `Videos\Squished`), or squishing it didn't make it any smaller, so Squishy threw the
  result away rather than hand you a bigger file.
- **The folder picker doesn't appear.** It opens on the PC Squishy runs on and can take a
  second or two. If it's hiding, look for it on the taskbar.
- **The preview is a still picture with no sound, and Play is greyed out.** Your browser
  can't play that kind of video, so Squishy shows frames from ffmpeg instead. Trimming and
  Save frame still work.

### Troubleshooting

| You see | Do this |
|---|---|
| "Squishy needs Python 3.11 or newer" | Install Python from python.org, ticking **Add python.exe to PATH**, then try again. |
| "ffmpeg download failed" | Check your internet connection and run it again. A "checksum mismatch" means the download was corrupted, and Squishy threw it away rather than run it. |
| The browser didn't open | Open the address printed in the console window, e.g. `http://127.0.0.1:48123/`. |
| A batch video failed | The row says why in short; the full story is in `logs\squishy.log` next to `Squishy.bat`. |
| Anything else | Hand this README to your AI agent (next section), or send `logs\squishy.log` (or the console text) to whoever gave you Squishy. |

---

## For AI agents

You're setting this up for a human on **Windows**. Follow these steps in order, check each
one, and ask the human before installing anything system-wide.

1. **Python >= 3.11.** Run `py -3 --version`, falling back to `python --version`. If it's missing
   or older, ask the human, then run `winget install -e --id Python.Python.3.13` (any 3.11+ id
   works). Open a new shell afterwards so PATH picks up the change. Treat the Microsoft Store
   `python` alias (it prints "Python was not found") as missing.
2. **No pip install step.** Squishy uses only the standard library. Don't create a venv for it.
3. **ffmpeg.** From the repo root, run `python launch.py --get-ffmpeg`. It downloads a pinned
   ffmpeg build (gyan.dev 9.0.2 essentials: its GitHub mirror first, then gyan.dev itself),
   checks it against a hard-coded SHA-256, and puts `ffmpeg.exe` and `ffprobe.exe` in `./bin/`. Exit code 0 means it
   worked. If `ffmpeg` and `ffprobe` are already on PATH you can skip this step: lookup order is
   `./bin/`, then PATH.
4. **Verify (optional, ~15 s).** Run `python -m pytest -q` (needs `pip install pytest`). The
   integration tests run real ffmpeg.
5. **Launch.** Have the human double-click `Squishy.bat`, or run
   `python launch.py --no-browser` and give them the URL it prints. It serves on
   `127.0.0.1:48123` and falls back to a random free port if that one is busy.

Constraints, so you don't "fix" the wrong thing:

- **Localhost only.** Don't bind it to `0.0.0.0` or expose it on the network. The server rejects
  other Host headers and cross-origin POSTs on purpose. Batches read files where they are,
  chosen in a Windows picker that the server opens on this PC, which is only safe because
  nobody else can reach the server.
- **Batches need tkinter** (included with the python.org installer by default). Without it,
  single videos still work and the picker says what's missing.
- **The size estimates are ceilings on purpose.** Don't tune them down to match actual outputs.
- **Run `--get-ffmpeg` before launching from a non-interactive shell.** If ffmpeg is missing,
  a plain launch prompts, reads EOF, treats that as "no", and exits 1. It won't hang.
- **`launch.py` blocks until it's killed** (it's a server), so run it in the background.
- **The log is `logs/squishy.log`** (dated lines, rotates at 1 MB, keeps 3 old files).
  It holds the user's filenames and folder paths; it never leaves the PC.
- Architecture, design decisions and a map of the code live in `onboarding.md`, `spec.md`
  and `DEVLOG.md`.

---

## Licence

Squishy is [MIT](LICENSE).

**ffmpeg isn't part of Squishy,** and that's deliberate. On request, Squishy downloads an
unmodified build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/). That build is
**GPLv3**, and its licence is saved as `bin/ffmpeg-LICENSE.txt`. Squishy only runs it as a
separate program over the command line and never links to it. gyan.dev distributes the build
and publishes the source it was built from.

If you fork this and put ffmpeg in the zip yourself, you become an ffmpeg distributor and GPLv3
applies to you: ship the licence and provide the corresponding source. That's the main reason
Squishy downloads ffmpeg instead of bundling it.
