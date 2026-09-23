"""Build ffmpeg commands, parse progress, and run encode jobs in the background."""

from __future__ import annotations

import collections
import logging
import subprocess
import threading
import time
from pathlib import Path

from .presets import Plan

log = logging.getLogger(__name__)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

X264_PRESET = "slow"
X264_CRF = 23


def build_ffmpeg_args(src: Path, dst: Path, plan: Plan) -> list[str]:
    """Build the ffmpeg argv for one encode. Pure function.

    Args:
        src: Input file.
        dst: Output .mp4 path.
        plan: Resolved preset parameters.

    Returns:
        Argument list suitable for subprocess (no shell).
    """
    filters = []
    if plan.fps_capped:
        filters.append(f"fps={plan.out_fps:g}")
    filters.append(f"scale={plan.out_width}:{plan.out_height}")

    args = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", X264_PRESET, "-crf", str(X264_CRF),
        "-maxrate", f"{plan.video_kbps}k", "-bufsize", f"{plan.video_kbps * 2}k",
        "-pix_fmt", "yuv420p",
    ]
    if plan.audio_kbps > 0:
        args += ["-c:a", "aac", "-b:a", f"{plan.audio_kbps}k"]
    else:
        args += ["-an"]
    args += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(dst)]
    return args


class ProgressTracker:
    """Turn ffmpeg `-progress` key=value lines into a percentage."""

    def __init__(self, duration_s: float) -> None:
        """Create a tracker.

        Args:
            duration_s: Expected output duration, for the percentage.
        """
        self.duration_s = duration_s
        self.percent = 0.0
        self.finished = False

    def feed(self, line: str) -> float:
        """Consume one progress line.

        Args:
            line: A line such as 'out_time_us=1234567' or 'progress=end'.

        Returns:
            Current percentage, 0-100.
        """
        key, sep, value = line.strip().partition("=")
        if not sep:
            return self.percent
        if key == "out_time_us" and self.duration_s > 0:
            try:
                seconds = int(value) / 1_000_000
            except ValueError:  # 'N/A' before the first frame
                return self.percent
            self.percent = max(self.percent, min(99.9, 100.0 * seconds / self.duration_s))
        elif key == "progress" and value == "end":
            self.finished = True
            self.percent = 100.0
        return self.percent


class EncodeJob:
    """One ffmpeg run in a background thread, with cancel and cleanup."""

    def __init__(self, job_id: str, src: Path, dst: Path, plan: Plan, duration_s: float) -> None:
        """Create (but do not start) a job.

        Args:
            job_id: Identifier for status polling.
            src: Input file.
            dst: Output path; deleted on failure or cancel.
            plan: Resolved preset parameters.
            duration_s: Source duration for progress.
        """
        self.job_id = job_id
        self.src = src
        self.dst = dst
        self.plan = plan
        self.state = "queued"
        self.error: str | None = None
        self.output_bytes: int | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self._tracker = ProgressTracker(duration_s)
        self._proc: subprocess.Popen | None = None
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
        self._lock = threading.Lock()
        self._cancel_requested = False
        self._thread = threading.Thread(target=self._run, name=f"encode-{job_id}", daemon=True)

    @property
    def active(self) -> bool:
        """True while queued or running."""
        return self.state in ("queued", "running")

    def start(self) -> None:
        """Start the encode thread."""
        self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the job finishes (used by tests)."""
        self._thread.join(timeout)

    def cancel(self) -> None:
        """Kill ffmpeg; the run thread handles cleanup and final state."""
        with self._lock:
            self._cancel_requested = True
            proc = self._proc
        if proc is not None and proc.poll() is None:
            log.info("Cancelling job %s", self.job_id)
            proc.kill()

    def status(self) -> dict:
        """Return a JSON-serialisable status snapshot."""
        elapsed = None
        if self.started_at is not None:
            elapsed = round((self.finished_at or time.monotonic()) - self.started_at, 1)
        return {
            "job_id": self.job_id,
            "state": self.state,
            "percent": round(self._tracker.percent, 1),
            "preset_id": self.plan.preset_id,
            "est_bytes": self.plan.est_bytes,
            "output_path": str(self.dst),
            "output_name": self.dst.name,
            "output_bytes": self.output_bytes,
            "elapsed_s": elapsed,
            "error": self.error,
        }

    def _drain_stderr(self, stream) -> None:
        for raw in stream:
            self._stderr_tail.append(raw.decode("utf-8", "replace").rstrip())

    def _delete_partial(self) -> None:
        try:
            self.dst.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete partial output %s: %s", self.dst, exc)

    def _run(self) -> None:
        args = build_ffmpeg_args(self.src, self.dst, self.plan)
        log.info("Job %s start: %s -> %s", self.job_id, self.plan.preset_id, self.dst.name)
        self.started_at = time.monotonic()
        try:
            with self._lock:
                if self._cancel_requested:
                    raise _Cancelled
                self.state = "running"
                self._proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    creationflags=NO_WINDOW,
                )
            drain = threading.Thread(target=self._drain_stderr, args=(self._proc.stderr,), daemon=True)
            drain.start()
            for raw in self._proc.stdout:
                self._tracker.feed(raw.decode("ascii", "replace"))
            code = self._proc.wait()
            drain.join(timeout=5)

            if self._cancel_requested:
                raise _Cancelled
            if code != 0:
                tail = "\n".join(self._stderr_tail) or f"ffmpeg exited with code {code}"
                raise RuntimeError(tail)

            self.output_bytes = self.dst.stat().st_size
            self._tracker.percent = 100.0
            self.state = "done"
            log.info("Job %s done: %d bytes (estimate %d)", self.job_id, self.output_bytes, self.plan.est_bytes)
        except _Cancelled:
            self._delete_partial()
            self.state = "cancelled"
            log.info("Job %s cancelled", self.job_id)
        except (OSError, RuntimeError) as exc:
            self._delete_partial()
            self.error = str(exc)
            self.state = "error"
            log.error("Job %s failed: %s", self.job_id, exc)
        finally:
            self.finished_at = time.monotonic()


class _Cancelled(Exception):
    """Internal signal: the job was cancelled."""
