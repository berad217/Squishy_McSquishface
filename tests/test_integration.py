"""Real ffmpeg runs on generated clips. Skipped if ffmpeg is not on PATH."""

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from squishy.encoder import EncodeJob
from squishy.presets import PRESETS_BY_ID, plan_for
from squishy.probe import probe_file

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _make_clip(path: Path, seconds: float, size: str = "1280x720", rate: int = 60) -> Path:
    """Generate temporal noise + a tone: worst case for compression, so the
    encoder is forced up against the VBV ceiling."""
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=gray:s={size}:r={rate},noise=alls=60:allf=t+u",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def noise_clip(tmp_path_factory):
    return _make_clip(tmp_path_factory.mktemp("src") / "noise.mp4", 3)


def _encode(src: Path, dst: Path, preset_id: str) -> tuple[EncodeJob, object]:
    info = probe_file(src, file_id="t", name=src.name)
    plan = plan_for(info, PRESETS_BY_ID[preset_id])
    job = EncodeJob("t", src, dst, plan, info.duration_s)
    job.start()
    job.wait(timeout=180)
    return job, plan


def _probe_out(path: Path):
    return probe_file(path, file_id="o", name=path.name)


@pytest.mark.parametrize("preset_id", ["medium", "extreme"])
def test_output_within_estimate(noise_clip, tmp_path, preset_id):
    job, plan = _encode(noise_clip, tmp_path / f"out_{preset_id}.mp4", preset_id)
    assert job.state == "done", job.error
    assert job.output_bytes <= plan.est_bytes * 1.03
    out = _probe_out(job.dst)
    assert (out.width, out.height) == (plan.out_width, plan.out_height)
    assert out.fps == pytest.approx(plan.out_fps, abs=0.1)
    assert job.status()["percent"] == 100.0


def test_cancel_deletes_partial(tmp_path):
    src = _make_clip(tmp_path / "long.mp4", 20, size="1920x1080")
    info = probe_file(src, file_id="t", name=src.name)
    plan = plan_for(info, PRESETS_BY_ID["light"])
    dst = tmp_path / "cancelled.mp4"
    job = EncodeJob("c", src, dst, plan, info.duration_s)
    job.start()
    job.cancel()
    job.wait(timeout=30)
    assert job.state == "cancelled"
    assert not dst.exists()


def test_bad_input_reports_error(tmp_path):
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"not a video")
    good = _make_clip(tmp_path / "ok.mp4", 1)
    info = probe_file(good, file_id="t", name=good.name)
    plan = plan_for(info, PRESETS_BY_ID["extreme"])
    dst = tmp_path / "err.mp4"
    job = EncodeJob("e", bogus, dst, plan, info.duration_s)
    job.start()
    job.wait(timeout=30)
    assert job.state == "error" and job.error
    assert not dst.exists()


def _boxes(buf: bytes, start: int, end: int):
    while start < end:
        size, kind = struct.unpack(">I4s", buf[start:start + 8])
        yield kind, buf[start:start + size]
        start += size


def _cover_art_first(tmp_path: Path) -> Path:
    """An MP4 whose cover art (udta/covr) is stream 0, as when a tagger writes udta
    before the traks. ffmpeg always writes it last, so move the box: same bytes, same
    moov size, and with +faststart moov precedes mdat, so chunk offsets stay valid."""
    video = _make_clip(tmp_path / "plain.mp4", 1, size="320x240", rate=30)
    cover = tmp_path / "cover.png"
    run = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run([*run, "-f", "lavfi", "-i", "color=red:s=200x200", "-frames:v", "1", str(cover)],
                   check=True)
    tagged = tmp_path / "tagged.mp4"
    subprocess.run([*run, "-i", str(video), "-i", str(cover), "-map", "0", "-map", "1", "-c", "copy",
                    "-disposition:v:1", "attached_pic", "-movflags", "+faststart", str(tagged)], check=True)
    data = tagged.read_bytes()
    out = b""
    for kind, box in _boxes(data, 0, len(data)):
        if kind == b"moov":
            kids = list(_boxes(box, 8, len(box)))
            udta = b"".join(b for k, b in kids if k == b"udta")
            assert udta, "ffmpeg wrote no udta box"
            rest = [b for k, b in kids if k != b"udta"]
            box = box[:8] + rest[0] + udta + b"".join(rest[1:])  # mvhd stays first
        out += box
    path = tmp_path / "cover_first.mp4"
    path.write_bytes(out)
    return path


def test_cover_art_first_encodes_the_real_video(tmp_path):
    src = _cover_art_first(tmp_path)
    streams = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name:stream_disposition=attached_pic",
         "-of", "json", str(src)], capture_output=True, text=True, check=True).stdout)["streams"]
    assert streams[0]["disposition"]["attached_pic"] == 1  # the setup really puts cover art first
    job, plan = _encode(src, tmp_path / "out.mp4", "light")
    assert job.state == "done", job.error  # 0:v:0 picked the cover; the mp4 muxer refused it
    out = _probe_out(job.dst)
    assert (out.width, out.height) == (plan.out_width, plan.out_height)
    assert out.duration_s == pytest.approx(1.0, abs=0.1)
