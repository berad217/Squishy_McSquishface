"""Frame-exact checks of trims, the Original copy and stills (spec Sprint 4, criteria 2, 4, 5).

Every frame of the generated source carries its own number as 8 black/white column
blocks (bit b of the frame number = block b), which survives compression intact, so each
output frame can be traced back to the source frame it came from.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from squishy.encoder import EncodeJob, build_copy_args, build_ffmpeg_args, build_frame_args
from squishy.presets import PRESETS_BY_ID, plan_for
from squishy.probe import probe_file, probe_packets
from squishy.trim import CopyPlan, Trim, copy_bytes, snap_to_keyframe

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)

FPS = 30
W, H = 320, 240
GOP = 15  # keyframe every 0.5 s, like the UE captures


def _make_counter_clip(path: Path, seconds: int = 4) -> Path:
    code = f"if(bitand(N,pow(2,floor(X*8/{W}))),235,16)"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={FPS},format=yuv420p,"
                              f"geq=lum='{code}':cb=128:cr=128",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast",
         "-g", str(GOP), "-keyint_min", str(GOP), "-sc_threshold", "0",
         "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


def _codes(path: Path) -> list[int]:
    """Decode every frame and read back the source frame number it shows."""
    raw = subprocess.run(
        # passthrough: the frames actually stored. A constant-rate decode would pad a late
        # first frame (a copy's video can start a few ms after its audio) with repeats.
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:V:0",
         "-fps_mode", "passthrough",
         "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    ).stdout
    frame = W * H
    block = W // 8
    codes = []
    for off in range(0, len(raw) - frame + 1, frame):
        row = raw[off + (H // 2) * W: off + (H // 2 + 1) * W]  # middle row
        n = 0
        for b in range(8):
            mid = row[b * block + block // 4: b * block + 3 * block // 4]
            if sum(mid) / len(mid) > 128:
                n |= 1 << b
        codes.append(n)
    return codes


@pytest.fixture(scope="module")
def counter_clip(tmp_path_factory):
    return _make_counter_clip(tmp_path_factory.mktemp("src") / "counter.mp4")


def test_counter_clip_reads_back(counter_clip):
    assert _codes(counter_clip) == list(range(4 * FPS))


def _run(job: EncodeJob) -> EncodeJob:
    job.start()
    job.wait(timeout=180)
    assert job.state == "done", job.error
    return job


@pytest.mark.parametrize("preset_id", ["light", "medium", "heavy", "extreme"])
def test_trimmed_encode_is_frame_exact(counter_clip, tmp_path, preset_id):
    info = probe_file(counter_clip, file_id="c", name="counter.mp4")
    trim = Trim(40 / FPS, 70 / FPS)
    plan = plan_for(info, PRESETS_BY_ID[preset_id], trim)
    dst = tmp_path / f"{preset_id}.mp4"
    args = build_ffmpeg_args(counter_clip, dst, plan, trim=trim)
    job = _run(EncodeJob("t", counter_clip, dst, plan, trim.duration_s, args=args))

    codes = _codes(dst)
    assert codes[0] == 40  # starts on the in-point frame exactly
    assert codes == list(range(40, 40 + len(codes)))  # nothing skipped or repeated
    assert abs(len(codes) - 30) <= 1  # out - in, +/- 1 frame
    assert job.output_bytes <= plan.est_bytes * 1.03


def test_in_point_between_frames_starts_on_the_next(counter_clip, tmp_path):
    info = probe_file(counter_clip, file_id="c", name="counter.mp4")
    trim = Trim(40.5 / FPS, 60 / FPS)  # halfway between frames 40 and 41
    plan = plan_for(info, PRESETS_BY_ID["medium"], trim)
    dst = tmp_path / "half.mp4"
    _run(EncodeJob("h", counter_clip, dst, plan, trim.duration_s,
                   args=build_ffmpeg_args(counter_clip, dst, plan, trim=trim)))
    assert _codes(dst)[0] == 41


@pytest.mark.parametrize("ext", [".mp4", ".mkv"])
def test_original_copy_starts_on_snapped_keyframe(counter_clip, tmp_path, ext):
    src = counter_clip
    if ext != ".mp4":
        src = tmp_path / f"counter{ext}"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(counter_clip),
                        "-c", "copy", str(src)], check=True)
    video = probe_packets(src, "V:0")
    audio = probe_packets(src, "a:0")
    # In/out come from the file's own frame times, as the browser reports them: a remux
    # can shift video (the .mkv here starts its video at 0.021 s).
    times = sorted(p.pts for p in video)
    trim = Trim(times[40], times[70])
    start = snap_to_keyframe([p.pts for p in video if p.key], trim.in_s)
    assert start == times[30]  # keyframes every 15 frames

    est = copy_bytes([video, audio], start, trim.out_s)
    dst = tmp_path / f"original{ext}"
    plan = CopyPlan("original", est, trim.in_s - start)
    job = _run(EncodeJob("o", src, dst, plan, trim.out_s - start,
                         args=build_copy_args(src, dst, start, trim)))

    codes = _codes(dst)
    assert codes[0] == 30  # the snapped keyframe, not the one before it
    assert codes == list(range(30, 30 + len(codes)))
    assert abs(len(codes) - 40) <= 1
    fmt = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=format_name",
                          "-of", "csv=p=0", str(dst)], capture_output=True, text=True).stdout
    assert ("matroska" in fmt) == (ext == ".mkv")
    if ext == ".mp4":
        # The packet bytes plus the MP4 header and index: a few KB, which only shows on a
        # clip this tiny (17 KB). On the reference clip the gap is 0.04%.
        assert 0 <= job.output_bytes - est <= 4096 + 0.01 * est


# +/- 1 ms: a browser reporting frame times rounded to the ms still gets its frame.
@pytest.mark.parametrize("t_offset", [0.0, 0.0001, -0.0001, 0.001, -0.001])
def test_still_is_the_frame_at_t(counter_clip, tmp_path, t_offset):
    dst = tmp_path / "still.jpg"
    subprocess.run(build_frame_args(counter_clip, dst, 55 / FPS + t_offset), check=True)
    assert _codes(dst) == [55]
