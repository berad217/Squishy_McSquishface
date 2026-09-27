"""Trim ranges, keyframe snap, output names, HTTP Range. Pure: no I/O.

Terms (trim, in-point, snap, Original) are defined in CONTEXT.md.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .presets import CONTAINER_OVERHEAD

MIN_TRIM_S = 0.1  # shorter than this is a slip of the mouse, not a clip
UNTOUCHED_S = 0.001  # in/out this close to the ends counts as not trimmed
SEEK_SLACK_S = 0.0005  # half a ms: far below any frame interval, above float noise


@dataclass(frozen=True)
class Trim:
    """The kept part of the source, in source seconds: [in_s, out_s)."""

    in_s: float
    out_s: float

    @property
    def duration_s(self) -> float:
        """Length of the kept range."""
        return self.out_s - self.in_s


@dataclass(frozen=True)
class CopyPlan:
    """What an Original (stream copy) job reports, in place of a preset Plan."""

    preset_id: str
    est_bytes: int
    snap_s: float


def make_trim(in_s: float, out_s: float, duration_s: float) -> Trim | None:
    """Validate an in/out pair from the browser.

    Args:
        in_s: In-point, seconds from the start of the source.
        out_s: Out-point; clamped to the source duration.
        duration_s: Source duration.

    Returns:
        The Trim, or None when it covers the whole source (untouched).

    Raises:
        ValueError: If the values are not finite, out of order, or too short.
    """
    if not (math.isfinite(in_s) and math.isfinite(out_s)):
        raise ValueError("trim times must be numbers")
    out_s = min(out_s, duration_s)
    if in_s < 0 or out_s - in_s < MIN_TRIM_S:
        raise ValueError(f"trim must keep at least {MIN_TRIM_S} s inside the video")
    if in_s <= UNTOUCHED_S and out_s >= duration_s - UNTOUCHED_S:
        return None
    return Trim(in_s, out_s)


def snap_to_keyframe(keyframes: Sequence[float], in_s: float) -> float:
    """Return the latest keyframe at or before in_s; never a later one.

    Args:
        keyframes: Keyframe times of the video stream, any order.
        in_s: The in-point.

    Returns:
        The keyframe time, or 0.0 if no keyframe precedes the in-point.
    """
    before = [k for k in keyframes if k <= in_s + 1e-6]
    return max(before) if before else 0.0


def fmt_stamp(seconds: float) -> str:
    """Format a time for filenames: '5.200s', '1m05.250s', '1h02m05.500s'."""
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s = f"{rem // 1000:02d}.{rem % 1000:03d}s" if (h or m) else f"{rem // 1000}.{rem % 1000:03d}s"
    if h:
        return f"{h}h{m:02d}m{s}"
    return f"{m}m{s}" if m else s


def output_stem(stem: str, label: str, trim: Trim | None) -> str:
    """Name an output: 'clip_medium', or 'clip_medium_5.200s-12.800s' when trimmed."""
    if trim is None:
        return f"{stem}_{label}"
    return f"{stem}_{label}_{fmt_stamp(trim.in_s)}-{fmt_stamp(trim.out_s)}"


class RangeNotSatisfiable(ValueError):
    """The Range header asks for bytes the file doesn't have (HTTP 416)."""


_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single-range HTTP Range header (RFC 9110 section 14).

    Args:
        header: The Range header value, or None.
        size: File size in bytes.

    Returns:
        (first, last) byte positions, inclusive; or None to send the whole file
        (no header, several ranges, another unit, or invalid syntax, all of which
        a server may ignore).

    Raises:
        RangeNotSatisfiable: If the range starts past the end, or is an empty suffix.
    """
    if not header:
        return None
    m = _RANGE.fullmatch(header.strip())
    if not m or (not m.group(1) and not m.group(2)):
        return None
    first, last = m.group(1), m.group(2)
    if not first:  # suffix: the last N bytes
        n = int(last)
        if n == 0:
            raise RangeNotSatisfiable(header)
        return max(0, size - n), size - 1
    start = int(first)
    if last and int(last) < start:
        return None
    if start >= size:
        raise RangeNotSatisfiable(header)
    return start, min(int(last) if last else size - 1, size - 1)


@dataclass(frozen=True)
class Packet:
    """One demuxed packet: presentation time, size, keyframe flag."""

    pts: float
    size: int
    key: bool


def parse_packets(text: str) -> list[Packet]:
    """Parse `ffprobe -show_entries packet=pts_time,size,flags -of csv=p=0:nk=0` output.

    Packets without a timestamp are skipped.
    """
    out = []
    for line in text.splitlines():
        fields = dict(kv.split("=", 1) for kv in line.strip().split(",") if "=" in kv)
        try:
            out.append(Packet(float(fields["pts_time"]), int(fields["size"]),
                              fields.get("flags", "").startswith("K")))
        except (KeyError, ValueError):
            continue
    return out


def copy_bytes(streams: Iterable[Sequence[Packet]], start_s: float, end_s: float) -> int:
    """Size of a stream copy of [start_s, end_s): packet bytes plus container overhead.

    Args:
        streams: Packet lists, one per copied stream.
        start_s: Copy start (the snapped keyframe).
        end_s: Out-point.

    Returns:
        Expected output size in bytes.
    """
    total = sum(p.size for pk in streams for p in pk if start_s <= p.pts < end_s)
    return int(total * CONTAINER_OVERHEAD)
