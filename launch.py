"""Squishy McSquishface launcher: start the local server and open the browser.

Usage:
    python launch.py [--port 48123] [--out DIR] [--no-browser]
    python launch.py --get-ffmpeg      # fetch ffmpeg into bin/ without prompting, then exit
"""

from __future__ import annotations

import sys

# Checked before the package imports so an old Python gets a sentence, not a traceback.
if sys.version_info < (3, 11):
    sys.exit(f"Squishy needs Python 3.11 or newer; this is {sys.version.split()[0]}. "
             "See README.md.")

import argparse
import json
import logging
import shutil
import tempfile
import threading
import urllib.request
import webbrowser
from pathlib import Path

from squishy.server import AppState, SquishyServer
from squishy.tools import (BIN_DIR, FFMPEG_BYTES, FFMPEG_VERSION, DownloadError, Tools,
                           download_supported, download_tools, find_tools)

log = logging.getLogger("squishy")

DEFAULT_PORT = 48123
DEFAULT_OUT = Path.home() / "Videos" / "Squished"
TEMP_ROOT = Path(tempfile.gettempdir()) / "squishy"


def already_running(port: int) -> bool:
    """Return True if a Squishy server already answers on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as resp:
            return json.load(resp).get("app") == "squishy"
    except (OSError, ValueError):
        return False


def print_progress(done: int, total: int | None) -> None:
    """Render download progress on one console line (ASCII only)."""
    mib = 1024 * 1024
    if total:
        line = f"  {done / mib:6.1f} / {total / mib:.1f} MB  ({100 * done / total:3.0f}%)"
    else:
        line = f"  {done / mib:6.1f} MB"
    end = "\n" if total and done >= total else ""
    print(f"\r{line}", end=end, flush=True)


def fetch_ffmpeg() -> Tools | None:
    """Download ffmpeg into bin/, logging instead of raising.

    Returns:
        Tools on success, None on failure.
    """
    try:
        return download_tools(progress=print_progress)
    except DownloadError as exc:
        print()
        log.error("ffmpeg download failed: %s", exc)
        log.error("Try again, or install ffmpeg yourself (see README.md).")
        return None


def resolve_tools() -> Tools | None:
    """Find ffmpeg, or offer to download it when running interactively.

    Returns:
        Tools, or None if ffmpeg is unavailable and the user declined or it failed.
    """
    tools = find_tools()
    if tools is not None:
        return tools
    if not download_supported():
        log.error("ffmpeg/ffprobe not found. Install ffmpeg with your package manager "
                  "(e.g. 'brew install ffmpeg' or 'sudo apt install ffmpeg').")
        return None

    print()
    print("Squishy needs ffmpeg to do the actual squishing, and it isn't installed.")
    print(f"It can download ffmpeg {FFMPEG_VERSION} from the gyan.dev builds on GitHub")
    print(f"({FFMPEG_BYTES / 1024**2:.0f} MB download, ~200 MB installed, one time only),")
    print("check its fingerprint, and keep it in:")
    print(f"  {BIN_DIR}")
    print()
    try:
        answer = input("Download it now? [Y/n] ").strip().lower()
    except EOFError:  # no console to ask (e.g. an agent ran us); don't hang, don't assume yes
        print()
        answer = "n"
    if answer not in ("", "y", "yes"):
        log.error("No ffmpeg, no squishing. Run 'python launch.py --get-ffmpeg', "
                  "or install ffmpeg yourself (see README.md).")
        return None
    return fetch_ffmpeg()


def main(argv: list[str] | None = None) -> int:
    """Run the app.

    Args:
        argv: Command-line arguments (defaults to sys.argv).

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--get-ffmpeg", action="store_true",
                        help="download ffmpeg into bin/ without prompting, then exit")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    if args.get_ffmpeg:
        if not download_supported():
            log.error("--get-ffmpeg fetches a Windows build; use your package manager instead.")
            return 1
        return 0 if fetch_ffmpeg() is not None else 1

    tools = resolve_tools()
    if tools is None:
        return 1
    log.info("Using ffmpeg: %s", tools.ffmpeg)

    if already_running(args.port):
        url = f"http://127.0.0.1:{args.port}/"
        log.info("Squishy is already running; opening %s", url)
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    # Leftovers from a run that was killed (console closed) are safe to remove.
    shutil.rmtree(TEMP_ROOT, ignore_errors=True)
    try:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error("Cannot create temp folder %s: %s", TEMP_ROOT, exc)
        return 1

    app = AppState(temp_dir=TEMP_ROOT, out_dir=args.out.expanduser().resolve(),
                   ffmpeg=tools.ffmpeg, ffprobe=tools.ffprobe)
    try:
        server = SquishyServer(("127.0.0.1", args.port), app)
    except OSError:
        log.warning("Port %d is busy; using a free port instead", args.port)
        server = SquishyServer(("127.0.0.1", 0), app)

    url = f"http://127.0.0.1:{server.server_address[1]}/"
    log.info("Squishy McSquishface running at %s", url)
    log.info("Output folder: %s", app.out_dir)
    log.info("Close this window (or press Ctrl+C) to quit.")
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        server.server_close()
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
