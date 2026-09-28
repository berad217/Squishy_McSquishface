"""v0.4 batch runner against real ffmpeg (spec Sprint 5, criteria 3-5 and 7)."""

import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from squishy import awake
from squishy.batch import Batch, build_listing
from squishy.presets import PRESETS_BY_ID, plan_for

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)

EXTREME = PRESETS_BY_ID["extreme"]


def _clip(path: Path, seconds: float = 1, size: str = "320x240", noise_crf: int | None = None) -> Path:
    """A test clip with audio; noise_crf makes a starved, blocky source that re-encodes bigger."""
    video = f"testsrc2=s={size}:r=30:d={seconds}"
    extra = []
    if noise_crf is not None:
        video = f"color=gray:s={size}:r=30:d={seconds},noise=alls=100:allf=t"
        extra = ["-crf", str(noise_crf)]
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", video,
         "-f", "lavfi", "-i", f"sine=f=440:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         *extra, "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


def _run(listing, out_dir, preset=EXTREME, jobs=None, ids=None):
    items = [i for i in listing.items if i.error is None and (ids is None or i.item_id in ids)]
    batch = Batch("b1", items, preset, out_dir, ffmpeg="ffmpeg",
                  on_job=(jobs.append if jobs is not None else None))
    batch.start()
    batch.wait(timeout=180)
    assert not batch.active
    return batch


@pytest.fixture
def folder(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _clip(src / "a.mp4")
    _clip(src / "b.mov")
    (src / "notes.txt").write_text("not a video")
    return src


def test_listing_sorts_videos_and_others(folder, tmp_path):
    (folder / "broken.mp4").write_bytes(b"not really")
    listing = build_listing(sorted(folder.iterdir()), folder=folder, out_dir=tmp_path / "out")
    assert [i.path.name for i in listing.items] == ["a.mp4", "b.mov", "broken.mp4"]
    assert [p.name for p in listing.others] == ["notes.txt"]
    ok = {i.path.name: i for i in listing.items}
    assert ok["a.mp4"].info.duration_s == pytest.approx(1, abs=0.1) and ok["a.mp4"].error is None
    assert "not a readable media file" in ok["broken.mp4"].error


def test_listing_refuses_files_in_the_output_folder(folder, tmp_path):
    listing = build_listing(sorted(folder.iterdir()), folder=folder, out_dir=folder)
    assert all(i.error == "in Squishy's output folder" for i in listing.items)


def test_listing_reports_existing_outputs(folder, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a_medium.mp4").touch()
    d = build_listing(sorted(folder.iterdir()), folder=folder, out_dir=out).to_dict(out)
    rows = {r["name"]: r for r in d["items"]}
    assert rows["a.mp4"]["existing"] == ["medium"]
    assert rows["b.mov"]["existing"] == []
    assert rows["a.mp4"]["ceilings"]["extreme"] > 0
    assert d["others"] == ["notes.txt"]


def test_batch_encodes_every_file_with_single_file_args(folder, tmp_path):
    out = tmp_path / "out"
    listing = build_listing(sorted(folder.iterdir()), folder=folder, out_dir=out)
    jobs = []
    batch = _run(listing, out, jobs=jobs)
    assert batch.state == "done"
    assert [i.state for i in batch.items] == ["done", "done"]
    assert sorted(p.name for p in out.iterdir()) == ["a_extreme.mp4", "b_extreme.mp4"]  # no .part left
    # Criterion 3: each job is the untrimmed single-file encode: no custom args, so
    # EncodeJob builds them from the same plan the single-file path uses.
    for job, item in zip(jobs, batch.items):
        assert job.args is None
        assert job.plan == plan_for(item.info, EXTREME)
        assert job.src == item.path and job.dst.name.endswith(".part.mp4")
    assert batch.items[0].output_bytes == (out / "a_extreme.mp4").stat().st_size


def test_existing_output_is_skipped(folder, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a_extreme.mp4").write_bytes(b"earlier result")
    batch = _run(build_listing(sorted(folder.iterdir()), folder=folder, out_dir=out), out)
    a, b = batch.items
    assert (a.state, b.state) == ("skipped", "done")
    assert "already" in a.reason
    assert (out / "a_extreme.mp4").read_bytes() == b"earlier result"


def test_a_failing_file_doesnt_stop_the_batch(folder, tmp_path):
    out = tmp_path / "out"
    listing = build_listing(sorted(folder.iterdir()), folder=folder, out_dir=out)
    (folder / "a.mp4").unlink()  # gone after listing: ffmpeg fails
    batch = _run(listing, out)
    a, b = batch.items
    assert (a.state, b.state) == ("failed", "done")
    assert a.reason
    assert batch.state == "done"
    assert sorted(p.name for p in out.iterdir()) == ["b_extreme.mp4"]


def test_no_smaller_result_is_deleted_and_skipped(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _clip(src / "starved.mp4", seconds=2, noise_crf=51)
    out = tmp_path / "out"
    batch = _run(build_listing([src / "starved.mp4"], folder=src, out_dir=out), out,
                 preset=PRESETS_BY_ID["light"])
    (item,) = batch.items
    assert item.state == "skipped", item.reason
    assert "no smaller" in item.reason
    assert not any(out.iterdir())


def test_stop_then_resume(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        _clip(src / name, seconds=8, size="1280x720")
    out = tmp_path / "out"
    listing = build_listing(sorted(src.iterdir()), folder=src, out_dir=out)
    items = listing.items
    batch = Batch("b1", items, PRESETS_BY_ID["light"], out, ffmpeg="ffmpeg")
    batch.start()
    deadline = time.monotonic() + 30
    while batch.items[0].state != "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    batch.stop()
    batch.wait(timeout=30)
    assert batch.state == "stopped"
    assert [i.state for i in batch.items] == ["stopped", "not_started", "not_started"]
    assert not any(out.iterdir())  # the partial is gone

    again = _run(listing, out, preset=PRESETS_BY_ID["heavy"], ids={items[0].item_id})
    assert [i.state for i in again.items] == ["done"]  # a fresh batch starts from the stopped file


def test_keep_awake_is_held_and_released(folder, tmp_path, monkeypatch):
    seen = []
    lock = threading.Lock()

    def record(flags):
        with lock:
            seen.append((threading.get_ident(), flags))
        return 1

    monkeypatch.setattr(awake, "_set_state", record)
    out = tmp_path / "out"
    listing = build_listing(sorted(folder.iterdir()), folder=folder, out_dir=out)
    (folder / "a.mp4").unlink()  # one failure, one success
    _run(listing, out)
    held = awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED
    threads = {t for t, _ in seen}
    assert len(threads) >= 3  # the batch thread and each file's encode thread
    for t in threads:
        flags = [f for tt, f in seen if tt == t]
        assert flags[0] == held and flags[-1] == awake.ES_CONTINUOUS, flags
