"""ffprobe wrapper: turn a media file into a SourceInfo."""

from __future__ import annotations

import json
import logging
import subprocess
from fractions import Fraction
from pathlib import Path

from .presets import SourceInfo

log = logging.getLogger(__name__)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProbeError(Exception):
    """The file could not be probed or is not a usable video."""


def _parse_rate(rate: str | None) -> float:
    """Parse an ffprobe frame rate like '60/1' or '30000/1001'; 0.0 if unusable."""
    if not rate:
        return 0.0
    try:
        value = Fraction(rate)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return float(value) if value > 0 else 0.0


def _rotation(stream: dict) -> int:
    """Return the display rotation in degrees (0, 90, 180, 270)."""
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            try:
                return int(round(float(side["rotation"]))) % 360
            except (TypeError, ValueError):
                pass
    try:
        return int(stream.get("tags", {}).get("rotate", 0)) % 360
    except (TypeError, ValueError):
        return 0


def _int_or_none(value) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _video_kbps(data: dict, video: dict, streams: list, duration: float, size_bytes: int) -> int | None:
    """Best-effort source video bitrate in kbit/s.

    Prefers the stream's own bit_rate; else container bitrate minus audio; else
    file size / duration minus audio.
    """
    own = _int_or_none(video.get("bit_rate"))
    if own:
        return own // 1000
    audio_bps = sum(_int_or_none(s.get("bit_rate")) or 0 for s in streams if s.get("codec_type") == "audio")
    total = _int_or_none(data.get("format", {}).get("bit_rate"))
    if total is None and duration > 0 and size_bytes > 0:
        total = int(size_bytes * 8 / duration)
    if total is None or total <= audio_bps:
        return None
    return (total - audio_bps) // 1000


def parse_probe(data: dict, *, file_id: str, name: str, size_bytes: int) -> SourceInfo:
    """Build a SourceInfo from ffprobe's JSON output.

    Args:
        data: Parsed `ffprobe -print_format json -show_format -show_streams` output.
        file_id: Upload identifier to embed.
        name: Original filename to embed.
        size_bytes: Size of the uploaded file.

    Returns:
        SourceInfo in display orientation (rotation applied).

    Raises:
        ProbeError: If there is no video stream or no usable duration.
    """
    streams = data.get("streams") or []
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise ProbeError("no video stream found")

    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ProbeError("video stream has no dimensions")
    if _rotation(video) in (90, 270):
        width, height = height, width

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    if fps <= 0:
        raise ProbeError("could not determine frame rate")

    duration = 0.0
    for candidate in (data.get("format", {}).get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            break
    if duration <= 0:
        raise ProbeError("could not determine duration (is this a still image?)")

    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return SourceInfo(
        video_kbps=_video_kbps(data, video, streams, duration, size_bytes),
        file_id=file_id,
        name=name,
        size_bytes=size_bytes,
        duration_s=round(duration, 3),
        width=width,
        height=height,
        fps=round(fps, 3),
        has_audio=has_audio,
    )


def probe_file(path: Path, *, file_id: str, name: str) -> SourceInfo:
    """Run ffprobe on a file.

    Args:
        path: File to probe.
        file_id: Upload identifier to embed.
        name: Original filename to embed.

    Returns:
        SourceInfo for the file.

    Raises:
        ProbeError: If ffprobe fails or the file is not a usable video.
    """
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    log.info("Probing %s", path.name)
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=60, creationflags=NO_WINDOW, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"ffprobe failed to run: {exc}") from exc
    if result.returncode != 0:
        msg = result.stderr.decode("utf-8", "replace").strip() or "unknown error"
        raise ProbeError(f"not a readable media file: {msg}")
    try:
        data = json.loads(result.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON: {exc}") from exc
    return parse_probe(data, file_id=file_id, name=name, size_bytes=path.stat().st_size)
