"""ffmpeg must not outlive Squishy: closing the console skips all Python cleanup."""

import ctypes
import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Win32 job objects")

SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0

# Stands in for the Squishy server: starts a long-lived child the way EncodeJob does.
PARENT = textwrap.dedent("""
    import subprocess, sys, time
    from squishy.encoder import NO_WINDOW, kill_with_this_process
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             creationflags=NO_WINDOW)
    kill_with_this_process(child)
    print(child.pid, flush=True)
    time.sleep(60)
""")


def _exits_within(pid: int, ms: int) -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return True  # already gone
    try:
        return k32.WaitForSingleObject(ctypes.c_void_p(handle), ms) == WAIT_OBJECT_0
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))


def test_child_dies_when_parent_is_killed():
    parent = subprocess.Popen([sys.executable, "-c", PARENT], stdout=subprocess.PIPE, text=True,
                              cwd=os.path.dirname(os.path.dirname(__file__)))
    child_pid = int(parent.stdout.readline())
    try:
        assert not _exits_within(child_pid, 300), "child should be running"
        parent.kill()  # TerminateProcess: no finally blocks, like a closed console
        parent.wait(timeout=10)
        assert _exits_within(child_pid, 5000), "child outlived its parent"
    finally:
        parent.kill()
        subprocess.run(["taskkill", "/PID", str(child_pid), "/F"], capture_output=True)
