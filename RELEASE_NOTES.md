# Release notes

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
