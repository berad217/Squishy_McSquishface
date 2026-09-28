"""Native Windows pickers for batches, opened by the server (spec Sprint 5).

tkinter runs in a child Python so a picker never shares a thread (or a Tk instance) with
the server. The spike (DEVLOG 2026-09-27) found it opens in front of the browser; the
dialog is also pinned on top in case a machine refuses it the foreground.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from .batch import VIDEO_EXTS

log = logging.getLogger(__name__)

PICK_TIMEOUT_S = 3600  # someone who leaves a picker open for an hour has gone away

_CHILD = r"""
import json, sys
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
if sys.argv[1] == "folder":
    chosen = filedialog.askdirectory(parent=root, title="Squishy: choose a folder of videos", mustexist=True)
    out = [chosen] if chosen else []
else:
    chosen = filedialog.askopenfilenames(parent=root, title="Squishy: choose videos",
                                         filetypes=[("Videos", sys.argv[2]), ("All files", "*.*")])
    out = list(chosen)
print(json.dumps(out))
"""


class PickerError(Exception):
    """The picker couldn't be shown."""


def pick(mode: str, python: str = sys.executable) -> list[Path]:
    """Show a picker and wait for it.

    Args:
        mode: "folder" (one folder) or "files" (any number of files).
        python: Python to run the picker with.

    Returns:
        The chosen folder (one path) or files; empty if the picker was cancelled.

    Raises:
        PickerError: If the picker couldn't run.
    """
    if mode not in ("folder", "files"):
        raise ValueError(f"unknown picker mode {mode!r}")
    pattern = " ".join(f"*{e}" for e in sorted(VIDEO_EXTS))
    log.info("Opening the %s picker", mode)
    try:
        # Launched as in the spike (no CREATE_NO_WINDOW): the child shares Squishy's
        # console, so no extra window appears besides the picker.
        result = subprocess.run([python, "-c", _CHILD, mode, pattern], capture_output=True,
                                timeout=PICK_TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PickerError(f"the picker failed to run: {exc}") from exc
    err = result.stderr.decode("utf-8", "replace")
    if result.returncode != 0:
        if "tkinter" in err or "_tkinter" in err or "Tcl" in err:
            raise PickerError("this Python has no Tk, which the picker needs. Reinstall Python "
                              "from python.org with 'tcl/tk and IDLE' ticked.")
        raise PickerError(err.strip().splitlines()[-1] if err.strip() else "the picker failed")
    try:
        chosen = json.loads(result.stdout.decode("utf-8", "replace").strip() or "[]")
    except json.JSONDecodeError as exc:
        raise PickerError(f"the picker returned nonsense: {exc}") from exc
    log.info("Picker returned %d path(s)", len(chosen))
    return [Path(p) for p in chosen]
