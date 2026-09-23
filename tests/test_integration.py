"""Real ffmpeg runs on generated clips. Skipped if ffmpeg is not on PATH."""

import shutil
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
