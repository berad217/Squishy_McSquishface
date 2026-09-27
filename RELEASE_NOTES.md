# Release notes

## v0.3.0 - "Snip Snip"

Squishy can now cut. Most captures are 90% waiting for the good bit, and throwing away
the waiting shrinks a file better than any compression level can.

### New

- **Trim.** A player now sits above the size cards. Drag the orange brackets, or play to the
  spot and click **Set start** / **Set end**. Every card's size updates as you go, and
  **Squish it** encodes just that part, starting on exactly the frame you picked.
- **Original.** Once you've trimmed, a fifth card appears. It cuts the clip out without
  re-encoding: full quality, done in a second, same format as your file. The catch: a copy
  can only start on a keyframe, so it may start before your start point. The card
  says how much. Usually that's under a second, but phone videos can be several seconds out.
- **You can see the keyframes.** Little ticks under the timeline show where an Original
  is allowed to start. Ctrl+arrows jump between them, and **Start on keyframe** moves your
  start back to the one the Original will use, so everything starts on the same frame.
- **Save frame.** Saves the frame on screen as a full-size JPEG, next to your videos.
- **Keys:** `I` / `O` set start / end, arrows step one frame, Shift+arrows one second,
  Ctrl+arrows one keyframe, Space plays and pauses.

Videos your browser can't play still work: the preview switches to frames from ffmpeg (no
sound), and trimming and Save frame carry on as normal.

### Getting it

Download **Source code (zip)** below and unzip it. **Close the old Squishy's black window
first,** then double-click `Squishy.bat`. Copy your old `bin` folder into the new one to skip
re-downloading ffmpeg.

## v0.2.4 - "Wait, Which One Is This?"

One fix, found while testing v0.2.3 for real.

### Fixed

- **Upgrading while the old Squishy is open now tells you so.** Before, double-clicking the
  new version while the old one was still running just opened the *old* one, and nothing
  told you. It looked like the upgrade had done nothing. Now the new version says "An older
  Squishy is already running. Close its window, then start this one again." If the one
  running is the same version or newer, it opens that, same as before.

### Getting it

Download **Source code (zip)** below and unzip it. **Close the old Squishy's black window
first,** then double-click `Squishy.bat`. Copy your old `bin` folder into the new one to skip
re-downloading ffmpeg.

## v0.2.3 - "Last of the Audit"

No new features. This clears the last three problems from the v0.2.1 audit. All three are
rare, and all three were annoying when they did happen.

### Fixed

- **Two Squishy windows no longer sabotage each other.** If a second copy ended up running
  (easy to do when something else is using Squishy's usual port), starting it deleted the
  first one's video. So did quitting either one. Each copy now keeps its own scratch folder
  and only tidies up after itself, or after copies that have crashed.
- **Videos with cover art squish.** Some files keep a thumbnail image inside them. If
  that image came first in the file, Squishy tried to squish the thumbnail instead of the
  video, and failed. It now skips straight to the video.
- **The backup ffmpeg download actually kicks in.** If the first download server sent back a
  broken reply of a certain kind, Squishy gave up instead of trying the second server.

### Getting it

Same as before: download **Source code (zip)** below, unzip, and double-click `Squishy.bat`.
Upgrading? Copy your old `bin` folder into the new one to skip re-downloading ffmpeg.

## v0.2.2 - "Make Up Your Mind"

No new features. This one is about changing your mind halfway through an upload, and about
Squishy being honest when an upload goes wrong.

### Fixed

- **Dropping a second video now replaces the first.** Before, both uploads kept going
  and whichever finished last won, even if it was the one you'd given up on. It could wipe
  out the video you actually wanted. Now the old upload is cancelled the moment you drop
  the new one.
- **A failed upload no longer leaves a loaded gun.** After a bad file, "Squish it" stayed
  clickable for the *previous* video, which Squishy had already thrown away. Now the page
  clears and waits for a new file.
- **Error messages actually arrive.** Uploading from a second tab mid-encode, or with the
  temp folder gone missing, used to show "Upload failed, is the console open?" (it was
  open). Now you get the real reason.
- **A tiny timing race is gone.** Starting a squish right as a new upload began could point
  ffmpeg at a file that had just been deleted. You'd have needed millisecond reflexes, but
  still.

### Getting it

Same as before: download **Source code (zip)** below, unzip, and double-click `Squishy.bat`.
Upgrading? Copy your old `bin` folder into the new one to skip re-downloading ffmpeg.

## v0.2.1 - "Tidying Up After Itself"

No new features. v0.2 got shipped, then it got audited, and the audit found a few places
where Squishy left a mess when something went wrong. It doesn't now.

### Fixed

- **Closing the window now actually stops the squishing.** Before, closing the console
  mid-encode left ffmpeg running invisibly in the background, using your CPU until it
  finished a video nobody was waiting for. Now Windows itself kills ffmpeg when Squishy
  goes, however Squishy goes.
- **"Port busy" is noticed even when the other program is polite about it.** If another
  local server was already on Squishy's port, v0.2 could move in alongside it and both
  would answer. Now it notices and uses a free port instead.
- **A hiccup no longer freezes the page.** One failed status check used to lock every button
  until you reloaded. Now a brief blip is retried; a real failure says so and hands you
  the controls back.
- **Output folder you can't write to?** You now get told that, instead of "Server not
  reachable", which was a lie.
- **`Squishy.bat` reports failure as failure.** It used to exit 0 after an error, which
  only mattered to scripts and AI agents, but they were being misled.
- **Download progress stays on its own line.** Warnings no longer print on top of the progress counter.

### Getting it

Same as before: download **Source code (zip)** below, unzip, and double-click `Squishy.bat`.
Upgrading from v0.2.0? Copy your old `bin` folder into the new one to skip re-downloading ffmpeg.

---

## v0.2.0 - "Now With Fewer Prerequisites"

v0.1 worked perfectly on exactly one machine, and that machine happened to have ffmpeg
installed. v0.2 is the version you can send to friends.

### New

- **Squishy fetches its own ffmpeg.** If ffmpeg isn't next to Squishy or on your PATH, the
  first launch asks one yes/no question and downloads it (110 MB download, ~200 MB on disk,
  once). It's a pinned build, **checked against a SHA-256 fingerprint before it's allowed to
  run**. There are two sources, so one being down doesn't strand you. If the bytes don't
  match, they're thrown away and the next source gets a turn. We are not in the business of
  running mystery executables.
- **`python launch.py --get-ffmpeg`** does the same thing without the question, for scripts,
  agents and people who don't like being asked.
- **A README for humans and for their AI agents.** The humans get a friendly version. The agents
  get numbered steps, exit codes, and a list of things not to "helpfully" fix.
- **`Squishy.bat` checks for Python first.** If Python is missing, you get a sentence telling
  you what to install instead of the Microsoft Store opening in your face.
- **MIT licensed.** ffmpeg is GPLv3 and stays at arm's length: downloaded, never bundled.

### Fixed

- `Squishy.bat` now always ships with Windows line endings, because `cmd.exe` has opinions.

### Still true

- Windows only, localhost only, one encode at a time. A feature, not a limitation. (It's a
  limitation.)
- The sizes shown are **ceilings**. If your video comes out smaller, that's the video being
  easy, not the estimate being wrong.
- You need Python 3.11+. Your AI agent can install it if you ask nicely. See the README.

### Getting it

Download **Source code (zip)** below, unzip it somewhere permanent, and double-click
`Squishy.bat`. If Windows asks whether you trust a file from the internet, the answer is
"More info -> Run anyway". The README has the full walkthrough.

---

## v0.1.0 - "It Works On My Machine"

The first version: drop a video, see four "up to" sizes, pick one, get an MP4. It needed
Python and ffmpeg already installed, and the confidence of someone who had both.
