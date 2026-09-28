"""Keep Windows from sleeping while an encode runs (the screen may still turn off).

SetThreadExecutionState is per thread, and Windows drops a thread's request when the
thread or the process ends, so a crash can't leave the PC unable to sleep.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
from collections.abc import Iterator

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _set_state(flags: int) -> int:
    """Call SetThreadExecutionState; returns the previous state, 0 on failure."""
    if os.name != "nt":
        return 1
    fn = ctypes.windll.kernel32.SetThreadExecutionState
    fn.restype = ctypes.c_uint32
    fn.argtypes = [ctypes.c_uint32]
    return fn(flags)


@contextlib.contextmanager
def keep_awake() -> Iterator[bool]:
    """Hold off system sleep on this thread until the block ends.

    Yields:
        True if Windows accepted the request.
    """
    ok = bool(_set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
    if not ok:
        log.warning("Could not ask Windows to stay awake; a long encode may be cut short by sleep")
    try:
        yield ok
    finally:
        _set_state(ES_CONTINUOUS)
