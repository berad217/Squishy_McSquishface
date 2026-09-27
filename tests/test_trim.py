from pathlib import Path

import pytest

from squishy.encoder import build_copy_args, build_ffmpeg_args, build_frame_args
from squishy.presets import PRESETS_BY_ID, SourceInfo, plan_for, plans_for
from squishy.trim import (
    RangeNotSatisfiable,
    Trim,
    copy_bytes,
    fmt_stamp,
    make_trim,
    output_stem,
    parse_packets,
    parse_range,
    snap_to_keyframe,
)

UE5 = SourceInfo("f1", "ue5.mp4", 238_026_752, 31.141, 3840, 2160, 60.0, True)


# --- make_trim -------------------------------------------------------------

def test_untouched_trim_is_none():
    assert make_trim(0, 31.141, 31.141) is None
    assert make_trim(0.0004, 31.1405, 31.141) is None  # float noise from the browser


def test_trim_keeps_range_and_duration():
    t = make_trim(5.2, 12.8, 31.141)
    assert t == Trim(5.2, 12.8)
    assert t.duration_s == pytest.approx(7.6)


def test_out_point_past_end_is_clamped():
    assert make_trim(5, 40, 31.141) == Trim(5, 31.141)


@pytest.mark.parametrize("in_s,out_s", [(-1, 5), (10, 5), (5, 5), (5, 5.05),
                                        (float("nan"), 5), (0, float("inf")), (32, 40)])
def test_bad_trims_rejected(in_s, out_s):
    with pytest.raises(ValueError):
        make_trim(in_s, out_s, 31.141)


# --- snap ------------------------------------------------------------------

KEYS = [0.0, 0.107, 0.607, 1.107, 1.607]


def test_snap_goes_back_to_previous_keyframe():
    assert snap_to_keyframe(KEYS, 1.0) == 0.607


def test_snap_on_a_keyframe_stays():
    assert snap_to_keyframe(KEYS, 1.107) == 1.107
    assert snap_to_keyframe(KEYS, 1.1069999) == 1.107  # float noise counts as on it


def test_snap_in_last_gop():
    assert snap_to_keyframe(KEYS, 30.0) == 1.607


def test_snap_never_moves_forward():
    assert snap_to_keyframe([0.5, 1.0], 0.2) == 0.0  # before the first keyframe: from the start
    assert snap_to_keyframe([], 3.0) == 0.0


# --- plans with a trim -----------------------------------------------------

def test_trimmed_plan_uses_trimmed_duration():
    full = plan_for(UE5, PRESETS_BY_ID["medium"])
    cut = plan_for(UE5, PRESETS_BY_ID["medium"], Trim(0, 10))
    assert cut.est_bytes < full.est_bytes / 2.5
    assert cut.est_ratio == pytest.approx(cut.est_bytes / UE5.size_bytes, abs=1e-4)


def test_plans_for_none_trim_is_unchanged():
    assert plans_for(UE5, None) == plans_for(UE5)


# --- args ------------------------------------------------------------------

def _medium(trim=None):
    plan = plan_for(UE5, PRESETS_BY_ID["medium"], trim)
    return build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), plan, trim=trim)


def test_trimmed_args_seek_input_and_limit_duration():
    args = _medium(Trim(5.2, 12.8))
    i = args.index("-i")
    # Input-side -ss (fast + frame-accurate when transcoding), backed off half a ms so a
    # frame whose time equals the in-point is kept.
    assert args[i - 2:i] == ["-ss", "5.199500"]
    assert args[args.index("-t") + 1] == "7.600000"
    assert args.index("-t") > i


def test_untrimmed_args_have_no_seek():
    args = _medium()
    assert "-ss" not in args and "-t" not in args


def test_copy_args():
    args = build_copy_args(Path("in.mov"), Path("out.mov"), 4.607, Trim(5.2, 12.8))
    i = args.index("-i")
    # Aim just past the keyframe so the demuxer lands on it, not the one before.
    assert args[i - 2:i] == ["-ss", "4.607500"]
    assert args[args.index("-t") + 1] == "8.193000"
    assert args[args.index("-c") + 1] == "copy"
    assert "-map" in args and "0:V:0" in args
    assert args[-1] == "out.mov"
    assert "-progress" in args


def test_copy_args_faststart_only_for_mp4_family():
    assert "+faststart" in build_copy_args(Path("a.mp4"), Path("b.mp4"), 0, Trim(1, 2))
    assert "+faststart" not in build_copy_args(Path("a.mkv"), Path("b.mkv"), 0, Trim(1, 2))


def test_frame_args_full_res_jpeg():
    args = build_frame_args(Path("in.mp4"), Path("still.jpg"), 12.345)
    i = args.index("-i")
    assert args[i - 2:i] == ["-ss", "12.344500"]
    assert args[args.index("-frames:v") + 1] == "1"
    assert args[args.index("-q:v") + 1] == "2"
    assert "-vf" not in args
    assert args[-1] == "still.jpg"


def test_frame_args_preview_scaled():
    args = build_frame_args(Path("in.mp4"), Path("-"), 1.0, max_width=960)
    assert args[args.index("-vf") + 1] == "scale='min(960,iw)':-2"
    assert args[args.index("-f") + 1] == "mjpeg"


# --- names -----------------------------------------------------------------

@pytest.mark.parametrize("s,expect", [(0, "0.000s"), (5.2, "5.200s"), (65.25, "1m05.250s"),
                                      (3725.5, "1h02m05.500s"), (12.3456, "12.346s")])
def test_fmt_stamp(s, expect):
    assert fmt_stamp(s) == expect


def test_output_stem():
    assert output_stem("clip", "medium", None) == "clip_medium"
    assert output_stem("clip", "medium", Trim(5.2, 12.8)) == "clip_medium_5.200s-12.800s"


# --- Range -----------------------------------------------------------------

@pytest.mark.parametrize("header,expect", [
    (None, None),
    ("bytes=0-", (0, 999)),
    ("bytes=0-99", (0, 99)),
    ("bytes=500-", (500, 999)),
    ("bytes=-100", (900, 999)),
    ("bytes=-5000", (0, 999)),
    ("bytes=990-5000", (990, 999)),
    ("bytes=0-0", (0, 0)),
    ("bytes=0-99,200-299", None),  # multi-range: allowed to ignore, send it all
    ("items=0-99", None),
    ("bytes=abc", None),
    ("bytes=50-10", None),  # invalid: ignore
])
def test_parse_range(header, expect):
    assert parse_range(header, 1000) == expect


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5000-6000", "bytes=-0"])
def test_parse_range_unsatisfiable(header):
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 1000)


# --- packets / Original size -------------------------------------------------

PACKETS = """pts_time=0.000000,size=1000,flags=K__
pts_time=0.016667,size=100,flags=___
pts_time=N/A,size=7,flags=___
pts_time=0.033333,size=100,flags=___
pts_time=0.050000,size=900,flags=K_D
"""


def test_parse_packets():
    pk = parse_packets(PACKETS)
    assert [p.pts for p in pk] == [0.0, 0.016667, 0.033333, 0.05]
    assert [p.key for p in pk] == [True, False, False, True]
    assert pk[0].size == 1000


def test_parse_packets_relative_to_file_start():
    # An MPEG-TS style file starting at 1.4 s: -ss 0 means its first packet.
    pk = parse_packets("pts_time=1.400000,size=5,flags=K__\nstart_time=1.400000\n"
                       "pts_time=1.433333,size=5,flags=___\n")
    assert [p.pts for p in pk] == [0.0, 0.033333]
    assert parse_packets("start_time=N/A\npts_time=2.0,size=1,flags=K__\n")[0].pts == 2.0


def test_copy_bytes_counts_range_only():
    pk = parse_packets(PACKETS)
    # [0.0, 0.04): three packets; x1.01 container overhead, like the ceilings.
    assert copy_bytes([pk], 0.0, 0.04) == int(1200 * 1.01)
    assert copy_bytes([pk, pk], 0.0, 0.04) == int(2400 * 1.01)
