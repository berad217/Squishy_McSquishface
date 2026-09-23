"""Compression presets and output-size estimation.

Pure logic: no I/O, no ffmpeg. Every preset is x264 CRF 23 capped by a VBV
maxrate, so the worst-case bitrate is known up front and the output size has a
computable ceiling.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# x264 starts the VBV buffer 90% full (vbv-init default), so the encoder may
# spend that much extra on top of maxrate * duration.
VBV_INIT_FRACTION = 0.9
BUFSIZE_SECONDS = 2  # bufsize = 2 * maxrate
CONTAINER_OVERHEAD = 1.01  # MP4 boxes + index; measured well under 1%


@dataclass(frozen=True)
class Preset:
    """One compression level.

    Attributes:
        id: Stable identifier used in URLs and output filenames.
        label: Human-readable name.
        max_short_side: Cap on the shorter frame dimension (1080 = "1080p",
            also correct for portrait video).
        max_fps: Frame-rate cap; applied only if the source is faster.
        video_kbps: VBV maxrate for video, in kilobits/s (1000-based).
        audio_kbps: AAC bitrate, in kilobits/s.
    """

    id: str
    label: str
    max_short_side: int
    max_fps: int
    video_kbps: int
    audio_kbps: int


PRESETS: tuple[Preset, ...] = (
    Preset("light", "Light", 1080, 60, 8000, 160),
    Preset("medium", "Medium", 1080, 60, 3500, 128),  # the proven recipe
    Preset("heavy", "Heavy", 720, 30, 1500, 96),
    Preset("extreme", "Extreme", 540, 30, 600, 64),
)

PRESETS_BY_ID: dict[str, Preset] = {p.id: p for p in PRESETS}


@dataclass(frozen=True)
class SourceInfo:
    """What ffprobe told us about an uploaded file (display orientation)."""

    file_id: str
    name: str
    size_bytes: int
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_kbps: int | None = None  # source video bitrate, if known

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return asdict(self)


@dataclass(frozen=True)
class Plan:
    """Concrete encode parameters for one preset applied to one source."""

    preset_id: str
    label: str
    out_width: int
    out_height: int
    out_fps: float
    fps_capped: bool
    video_kbps: int
    bitrate_capped: bool
    audio_kbps: int
    est_bytes: int
    est_ratio: float

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return asdict(self)


def _even(n: float) -> int:
    """Round to the nearest even integer >= 2 (yuv420p needs even dimensions)."""
    return max(2, int(round(n / 2.0)) * 2)


def output_dims(src_w: int, src_h: int, max_short_side: int) -> tuple[int, int]:
    """Compute output dimensions: never upscale, keep aspect, even sizes.

    Args:
        src_w: Source display width in pixels.
        src_h: Source display height in pixels.
        max_short_side: Cap on the shorter side.

    Returns:
        (width, height), both even.

    Raises:
        ValueError: If a source dimension is not positive.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"invalid source dimensions {src_w}x{src_h}")
    short = min(src_w, src_h)
    scale = min(1.0, max_short_side / short)
    return _even(src_w * scale), _even(src_h * scale)


def estimate_bytes(duration_s: float, video_kbps: int, audio_kbps: int) -> int:
    """Upper-bound output size for a CRF + VBV-capped encode.

    ceiling = (maxrate * duration + initial VBV buffer) + audio, plus container
    overhead.

    Args:
        duration_s: Clip length in seconds.
        video_kbps: Video maxrate in kbit/s.
        audio_kbps: Audio bitrate in kbit/s (0 if no audio).

    Returns:
        Estimated maximum size in bytes.
    """
    video_bits = video_kbps * 1000 * (duration_s + BUFSIZE_SECONDS * VBV_INIT_FRACTION)
    audio_bits = audio_kbps * 1000 * duration_s
    return int((video_bits + audio_bits) / 8 * CONTAINER_OVERHEAD)


def plan_for(source: SourceInfo, preset: Preset) -> Plan:
    """Resolve a preset against a source into concrete encode parameters.

    Args:
        source: Probed source info.
        preset: Preset to apply.

    Returns:
        The Plan, including the size estimate.
    """
    w, h = output_dims(source.width, source.height, preset.max_short_side)
    fps_capped = source.fps > preset.max_fps
    out_fps = float(preset.max_fps) if fps_capped else source.fps
    audio_kbps = preset.audio_kbps if source.has_audio else 0
    # Spending more bits than the source has cannot add quality; it only
    # inflates the size ceiling.
    video_kbps = preset.video_kbps
    bitrate_capped = bool(source.video_kbps) and source.video_kbps < preset.video_kbps
    if bitrate_capped:
        video_kbps = max(100, source.video_kbps)
    est = estimate_bytes(source.duration_s, video_kbps, audio_kbps)
    ratio = est / source.size_bytes if source.size_bytes > 0 else 0.0
    return Plan(
        preset_id=preset.id,
        label=preset.label,
        out_width=w,
        out_height=h,
        out_fps=out_fps,
        fps_capped=fps_capped,
        video_kbps=video_kbps,
        bitrate_capped=bitrate_capped,
        audio_kbps=audio_kbps,
        est_bytes=est,
        est_ratio=round(ratio, 4),
    )


def plans_for(source: SourceInfo) -> list[Plan]:
    """Return a Plan for every preset, lightest compression first."""
    return [plan_for(source, p) for p in PRESETS]
