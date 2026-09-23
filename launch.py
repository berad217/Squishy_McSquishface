"""Squishy McSquishface launcher: start the local server and open the browser.

Usage:
    python launch.py [--port 48123] [--out DIR] [--no-browser]
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
import threading
import urllib.request
import webbrowser
from pathlib import Path

from squishy.server import AppState, SquishyServer

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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        log.error("Not found on PATH: %s. Install ffmpeg (e.g. 'choco install ffmpeg').", ", ".join(missing))
        return 1

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

    app = AppState(temp_dir=TEMP_ROOT, out_dir=args.out.expanduser().resolve())
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
