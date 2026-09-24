# Release notes

## v0.2.0 - "Now With Fewer Prerequisites"

v0.1 worked perfectly on exactly one machine, and that machine happened to have ffmpeg
installed. v0.2 is the version you can send to friends.

### New

- **Squishy fetches its own ffmpeg.** If ffmpeg isn't next to Squishy or on your PATH, the
  first launch asks one yes/no question and downloads it (110 MB download, ~200 MB on disk,
  once). It's a pinned build, **checked against a SHA-256 fingerprint before it's allowed to
  run**. If the bytes don't match, they're thrown away. We are not in the business of running
  mystery executables.
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
