"""Per-instance temp folders, so two open Squishy windows can't delete each other's uploads.

Layout under the root (``%TEMP%\\squishy``): ``run-<id>/`` holds one instance's uploads, and
``run-<id>.lock`` sits beside it, held open for the instance's lifetime. A folder is stale
only when its lock can be taken: on Windows an open file can't be deleted, and elsewhere
``flock()`` says whether anyone holds it. The OS closes the handle however the process
dies (console closed, taskkill, crash), so a dead instance's folder is always sweepable.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
from pathlib import Path
from typing import TextIO

log = logging.getLogger(__name__)

LOCK_SUFFIX = ".lock"


class WorkDir:
    """A claimed per-instance temp folder and the open lock that marks it as live."""

    def __init__(self, path: Path, lock_path: Path, lock_fh: TextIO) -> None:
        """Wrap a claimed folder.

        Args:
            path: The instance's temp folder.
            lock_path: Its lock file, beside it.
            lock_fh: The open lock handle; closing it is what marks the folder stale.
        """
        self.path = path
        self.lock_path = lock_path
        self._lock_fh: TextIO | None = lock_fh

    def release(self) -> None:
        """Close the lock and delete the folder and lock (idempotent, never raises)."""
        if self._lock_fh is not None:
            try:
                self._lock_fh.close()
            except OSError:
                pass
            self._lock_fh = None
        shutil.rmtree(self.path, ignore_errors=True)
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete %s: %s", self.lock_path, exc)


def claim_work_dir(root: Path) -> WorkDir:
    """Create and lock a fresh temp folder for this instance.

    The lock is created before the folder, so a sweep never sees the folder unlocked.

    Args:
        root: Shared parent folder (created if missing).

    Returns:
        The claimed WorkDir; keep it referenced until shutdown.

    Raises:
        OSError: If the root, lock, or folder can't be created.
    """
    root.mkdir(parents=True, exist_ok=True)
    run_id = f"run-{secrets.token_hex(4)}"
    lock_path = root / f"{run_id}{LOCK_SUFFIX}"
    lock_fh = lock_path.open("x", encoding="ascii")
    try:
        lock_fh.write(f"{os.getpid()}\n")  # for a human poking around; not used for liveness
        lock_fh.flush()
        if os.name != "nt":
            import fcntl
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = root / run_id
        path.mkdir()
    except OSError:
        lock_fh.close()
        lock_path.unlink(missing_ok=True)
        raise
    return WorkDir(path, lock_path, lock_fh)


def _take_stale_lock(lock_path: Path) -> bool:
    """Delete lock_path if no live process holds it.

    Returns:
        True if the lock is gone (its owner had exited), False if it is held.
    """
    if os.name == "nt":
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:  # sharing violation: the owner still has it open
            return False
        return True
    import fcntl
    try:
        fh = lock_path.open("a", encoding="ascii")
    except FileNotFoundError:
        return True
    except OSError:
        return False
    with fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        lock_path.unlink(missing_ok=True)
    return True


def sweep_stale(root: Path) -> int:
    """Delete temp folders left by instances that have exited; leave live ones alone.

    Also removes loose files directly under root: uploads from v0.2.2 and earlier, which
    kept them there.

    Args:
        root: Shared parent folder.

    Returns:
        Number of stale folders and loose files removed.
    """
    try:
        entries = list(root.iterdir())
    except FileNotFoundError:
        return 0
    except OSError as exc:
        log.warning("Could not list %s: %s", root, exc)
        return 0

    live = set()
    for lock in (e for e in entries if e.suffix == LOCK_SUFFIX):
        if not _take_stale_lock(lock):
            live.add(lock.stem)

    removed = 0
    for entry in entries:
        if entry.suffix == LOCK_SUFFIX or entry.name in live:
            continue
        # A listing isn't a snapshot: an instance starting right now may have created its
        # lock after we listed. Its lock always predates its folder, so check once more.
        if (root / f"{entry.name}{LOCK_SUFFIX}").exists():
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            try:
                entry.unlink()
            except OSError as exc:
                log.warning("Could not delete %s: %s", entry, exc)
                continue
        removed += 1
    return removed
