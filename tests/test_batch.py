"""v0.4 batch: pure parts (file sorting, names, time left) and keep-awake."""

import threading
from pathlib import Path

import pytest

from squishy import awake
from squishy.batch import batch_stems, eta_s, split_videos


# --- which files are videos ----------------------------------------------------

def test_split_videos_by_extension_sorted_by_name():
    paths = [Path("f/b.MOV"), Path("f/notes.txt"), Path("f/A.mp4"), Path("f/c.mkv"), Path("f/pic.JPG")]
    videos, others = split_videos(paths)
    assert [p.name for p in videos] == ["A.mp4", "b.MOV", "c.mkv"]
    assert [p.name for p in others] == ["notes.txt", "pic.JPG"]


def test_split_videos_empty():
    assert split_videos([]) == ([], [])


# --- output stems ----------------------------------------------------------------

def test_stems_are_safe_stems_when_unique():
    stems = batch_stems([Path("f/clip one.mp4"), Path("f/b<c>.mov")])
    assert list(stems.values()) == ["clip one", "b_c_"]


def test_same_stem_gets_the_extension():
    # clip.mov and clip.mp4 would both become clip_medium.mp4, and the second would be
    # skipped as "already exists"; Windows names are case-insensitive, so Clip counts too.
    a, b, c = Path("f/Clip.MOV"), Path("f/clip.mp4"), Path("f/other.mp4")
    stems = batch_stems([a, b, c])
    assert stems == {a: "Clip-mov", b: "clip-mp4", c: "other"}


# --- time left --------------------------------------------------------------------

def test_eta_unknown_until_something_is_encoded():
    assert eta_s(done_media_s=0, elapsed_s=30, remaining_media_s=100) is None
    assert eta_s(done_media_s=10, elapsed_s=1, remaining_media_s=100) is None  # too early


def test_eta_scales_remaining_by_speed_so_far():
    # 60 s of video took 30 s: twice real time, so 100 s left takes 50 s.
    assert eta_s(done_media_s=60, elapsed_s=30, remaining_media_s=100) == pytest.approx(50)
    assert eta_s(done_media_s=60, elapsed_s=30, remaining_media_s=0) == 0


# --- keep awake -------------------------------------------------------------------

@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(awake, "_set_state", lambda flags: seen.append((threading.get_ident(), flags)) or 1)
    return seen


def test_keep_awake_sets_then_clears(calls):
    with awake.keep_awake():
        assert calls == [(threading.get_ident(), awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED)]
    assert calls[-1] == (threading.get_ident(), awake.ES_CONTINUOUS)


def test_keep_awake_clears_on_error(calls):
    with pytest.raises(RuntimeError), awake.keep_awake():
        raise RuntimeError("boom")
    assert [f for _, f in calls] == [awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED, awake.ES_CONTINUOUS]


def test_real_call_is_accepted():
    # Windows returns the previous state (non-zero) on success, 0 on failure.
    with awake.keep_awake() as ok:
        assert ok
