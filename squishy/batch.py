"""Batches: one preset over a list of whole files, one after another (spec Sprint 5).

Terms (Batch, Skipped / Failed) are defined in CONTEXT.md. The files are read where they
are: their paths come only from the picker the server opens, never from the page.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .awake import keep_awake
from .encoder import EncodeJob
from .presets import PRESETS, Preset, SourceInfo, plan_for, plans_for
from .probe import ProbeError, probe_file
from .trim import output_stem, safe_stem

log = logging.getLogger(__name__)

VIDEO_EXTS = frozenset({".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv",
                        ".ts", ".mts", ".m2ts", ".mpg", ".mpeg", ".3gp"})
PROBE_WORKERS = 8
ETA_MIN_ELAPSED_S = 5  # before this, one file's speed says little about the rest


def split_videos(paths: Sequence[Path]) -> tuple[list[Path], list[Path]]:
    """Split paths into videos (by extension) and everything else, each sorted by name."""
    key = lambda p: p.name.casefold()  # noqa: E731
    videos = sorted((p for p in paths if p.suffix.lower() in VIDEO_EXTS), key=key)
    others = sorted((p for p in paths if p.suffix.lower() not in VIDEO_EXTS), key=key)
    return videos, others


def batch_stems(paths: Sequence[Path]) -> dict[Path, str]:
    """Output stem for each file; files sharing a stem also get their extension.

    Without that, clip.mov and clip.mp4 would both become clip_medium.mp4, and the
    second would be skipped as already done. Windows names ignore case, so this does too.
    """
    stems = {p: safe_stem(p.name) for p in paths}
    counts: dict[str, int] = {}
    for s in stems.values():
        counts[s.casefold()] = counts.get(s.casefold(), 0) + 1
    return {p: (f"{s}-{p.suffix.lstrip('.').lower()}" if counts[s.casefold()] > 1 else s)
            for p, s in stems.items()}


def eta_s(done_media_s: float, elapsed_s: float, remaining_media_s: float) -> float | None:
    """Seconds left, assuming the rest encodes as fast as what's done; None if unknown."""
    if done_media_s <= 0 or elapsed_s < ETA_MIN_ELAPSED_S:
        return None
    return remaining_media_s * elapsed_s / done_media_s


def output_path(out_dir: Path, stem: str, preset_id: str) -> Path:
    """Where a batch writes a file's output: the same name a single-file encode gets first."""
    return out_dir / f"{output_stem(stem, preset_id, None)}.mp4"


@dataclass
class BatchItem:
    """One file in a listing or a batch."""

    item_id: str
    path: Path
    stem: str
    info: SourceInfo | None = None
    error: str | None = None  # why it can't be squished at all (listing time)
    state: str = "waiting"  # waiting, running, done, skipped, failed, stopped, not_started
    reason: str | None = None
    output_name: str | None = None
    output_bytes: int | None = None
    job: EncodeJob | None = None

    def to_dict(self) -> dict:
        """Row for the page."""
        return {
            "item_id": self.item_id,
            "name": self.path.name,
            "size_bytes": self.info.size_bytes if self.info else _size(self.path),
            "duration_s": self.info.duration_s if self.info else None,
            "error": self.error,
            "state": self.state,
            "reason": self.reason,
            "percent": self.job.status()["percent"] if self.job else (100.0 if self.state == "done" else 0.0),
            "output_name": self.output_name,
            "output_bytes": self.output_bytes,
        }


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


@dataclass
class Listing:
    """What a picker returned: the videos (probed) and the other files."""

    listing_id: str
    folder: Path | None
    items: list[BatchItem]
    others: list[Path]

    def to_dict(self, out_dir: Path) -> dict:
        """The batch view's data: rows with each preset's ceiling and existing outputs."""
        rows = []
        for item in self.items:
            row = item.to_dict()
            row["ceilings"] = {p.preset_id: p.est_bytes for p in plans_for(item.info)} if item.info else {}
            row["existing"] = [p.id for p in PRESETS if output_path(out_dir, item.stem, p.id).exists()]
            rows.append(row)
        return {
            "listing_id": self.listing_id,
            "folder": str(self.folder) if self.folder else None,
            "items": rows,
            "others": [p.name for p in self.others],
            "presets": [dataclasses.asdict(p) for p in PRESETS],
            "out_dir": str(out_dir),
        }


def build_listing(paths: Sequence[Path], *, folder: Path | None, out_dir: Path,
                  ffprobe: str = "ffprobe") -> Listing:
    """Sort picked files into videos and others, and probe the videos (in parallel).

    Args:
        paths: Files chosen in the picker (or found in the chosen folder).
        folder: The chosen folder, if a folder was chosen.
        out_dir: Squishy's output folder; files in it are refused.
        ffprobe: Path to the ffprobe executable.

    Returns:
        The listing; items that can't be squished carry an error.
    """
    videos, others = split_videos(paths)
    stems = batch_stems(videos)
    items = [BatchItem(secrets.token_hex(4), p, stems[p]) for p in videos]

    def probe(item: BatchItem) -> None:
        try:
            if item.path.parent.resolve() == out_dir.resolve():
                item.error = "in Squishy's output folder"
                return
            item.info = probe_file(item.path, file_id=item.item_id, name=item.path.name, ffprobe=ffprobe)
        except (OSError, ProbeError) as exc:
            # ffprobe's own text names the file and the demuxer's internals; a row only
            # needs the gist. The full text goes to the log.
            log.info("Can't use %s: %s", item.path.name, exc)
            item.error = str(exc).split(":")[0]

    with ThreadPoolExecutor(PROBE_WORKERS) as pool:
        list(pool.map(probe, items))
    log.info("Listed %d videos (%d usable) and %d other files", len(items),
             sum(i.error is None for i in items), len(others))
    return Listing(secrets.token_hex(4), folder, items, others)


class Batch:
    """Encodes its items one at a time in a background thread."""

    def __init__(self, batch_id: str, items: Sequence[BatchItem], preset: Preset, out_dir: Path,
                 ffmpeg: str = "ffmpeg", on_job: Callable[[EncodeJob], None] | None = None) -> None:
        """Create (but do not start) a batch.

        Args:
            batch_id: Identifier for the page.
            items: Usable listing items, in order; the batch works on copies.
            preset: The one preset for every file.
            out_dir: Output folder.
            ffmpeg: Path to the ffmpeg executable.
            on_job: Called with each file's EncodeJob before it starts (the server
                registers it, so single-file work stays locked out).
        """
        self.batch_id = batch_id
        self.items = [dataclasses.replace(i, state="waiting", reason=None, output_name=None,
                                          output_bytes=None, job=None) for i in items]
        self.preset = preset
        self.out_dir = out_dir
        self.ffmpeg = ffmpeg
        self.on_job = on_job
        self.state = "running"  # running, done, stopped
        self.started_at = time.monotonic()
        self.finished_at: float | None = None
        self._lock = threading.Lock()
        self._stop = False
        self._current: EncodeJob | None = None
        self._thread = threading.Thread(target=self._run, name=f"batch-{batch_id}", daemon=True)

    @property
    def active(self) -> bool:
        """True until every file has been dealt with."""
        return self.state == "running"

    def start(self) -> None:
        """Start the batch thread."""
        self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the batch ends (used by tests and shutdown)."""
        self._thread.join(timeout)

    def stop(self) -> None:
        """Stop now: the current file is abandoned (its partial deleted), the rest not started."""
        with self._lock:
            self._stop = True
            job = self._current
        if job is not None:
            job.cancel()

    def _run(self) -> None:
        log.info("Batch %s start: %d files, %s", self.batch_id, len(self.items), self.preset.id)
        with keep_awake():  # held between files too, not just during each encode
            for item in self.items:
                self._one(item)
        self.finished_at = time.monotonic()
        self.state = "stopped" if self._stop else "done"
        log.info("Batch %s %s", self.batch_id, self.state)

    def _one(self, item: BatchItem) -> None:
        dst = output_path(self.out_dir, item.stem, self.preset.id)
        item.output_name = dst.name
        with self._lock:
            if self._stop:
                item.state = "not_started"
                return
            if dst.exists():
                item.state, item.reason = "skipped", f"already squished: {dst.name}"
                return
            try:
                self.out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                item.state, item.reason = "failed", f"cannot write to {self.out_dir}: {exc}"
                return
            # Written under a temporary name and renamed when complete, so "the output
            # exists" always means finished, even after a crash or a power cut.
            part = dst.with_name(f"{dst.stem}.part.mp4")
            job = EncodeJob(secrets.token_hex(4), item.path, part, plan_for(item.info, self.preset),
                            item.info.duration_s, ffmpeg=self.ffmpeg)
            item.job, item.state, self._current = job, "running", job
            if self.on_job:
                self.on_job(job)
            job.start()
        job.wait()
        with self._lock:
            self._current = None
        self._finish(item, job, part, dst)

    def _finish(self, item: BatchItem, job: EncodeJob, part: Path, dst: Path) -> None:
        if job.state == "cancelled":
            item.state = "stopped"
            return
        if job.state != "done":
            item.state = "failed"
            lines = [ln for ln in (job.error or "").splitlines() if ln.strip()]
            item.reason = lines[-1] if lines else "ffmpeg failed"
            return
        try:
            if job.output_bytes >= item.info.size_bytes:
                part.unlink()
                item.state, item.reason = "skipped", "no smaller than the original, so not kept"
                return
            os.replace(part, dst)
        except OSError as exc:
            item.state, item.reason = "failed", f"could not save {dst.name}: {exc}"
            return
        item.state, item.output_bytes = "done", job.output_bytes

    def status(self) -> dict:
        """JSON-serialisable snapshot for the page."""
        now = self.finished_at or time.monotonic()
        done_media = remaining = 0.0
        for i in self.items:
            dur = i.info.duration_s
            if i.state == "running" and i.job:
                frac = i.job.status()["percent"] / 100
                done_media += dur * frac
                remaining += dur * (1 - frac)
            elif i.state == "waiting":
                remaining += dur
            elif i.job is not None and i.job.state == "done":
                done_media += dur  # encoded, whether kept or not
        counts: dict[str, int] = {}
        for i in self.items:
            counts[i.state] = counts.get(i.state, 0) + 1
        done = [i for i in self.items if i.state == "done"]
        return {
            "batch_id": self.batch_id,
            "state": self.state,
            "preset_id": self.preset.id,
            "label": self.preset.label,
            "items": [i.to_dict() for i in self.items],
            "counts": counts,
            "bytes_before": sum(i.info.size_bytes for i in done),
            "bytes_after": sum(i.output_bytes or 0 for i in done),
            "elapsed_s": round(now - self.started_at, 1),
            "eta_s": None if not self.active else eta_s(done_media, now - self.started_at, remaining),
            "out_dir": str(self.out_dir),
        }
