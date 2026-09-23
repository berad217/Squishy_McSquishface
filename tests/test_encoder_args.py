from pathlib import Path

from squishy.encoder import ProgressTracker, build_ffmpeg_args
from squishy.presets import PRESETS_BY_ID, SourceInfo, plan_for

UE5 = SourceInfo("f1", "ue5.mp4", 238_026_752, 31.141, 3840, 2160, 60.0, True)


def _args(preset_id, source=UE5):
    plan = plan_for(source, PRESETS_BY_ID[preset_id])
    return build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), plan)


def _value(args, flag):
    return args[args.index(flag) + 1]


def test_medium_matches_proven_recipe():
    args = _args("medium")
    assert _value(args, "-vf") == "scale=1920:1080"
    assert _value(args, "-c:v") == "libx264"
    assert _value(args, "-preset") == "slow"
    assert _value(args, "-crf") == "23"
    assert _value(args, "-maxrate") == "3500k"
    assert _value(args, "-bufsize") == "7000k"
    assert _value(args, "-pix_fmt") == "yuv420p"
    assert _value(args, "-b:a") == "128k"
    assert _value(args, "-movflags") == "+faststart"
    assert args[-1] == "out.mp4"


def test_heavy_caps_fps_before_scaling():
    assert _value(_args("heavy"), "-vf") == "fps=30,scale=1280:720"


def test_mute_source_drops_audio():
    mute = SourceInfo("f3", "m.mp4", 1000, 10, 1920, 1080, 30.0, False)
    args = _args("medium", mute)
    assert "-an" in args and "-c:a" not in args


def test_progress_goes_to_stdout_and_no_shell_metachar_risk():
    args = _args("light")
    assert _value(args, "-progress") == "pipe:1"
    assert all(isinstance(a, str) for a in args)


def test_progress_tracker_percent_and_end():
    t = ProgressTracker(10.0)
    assert t.feed("out_time_us=N/A") == 0.0
    assert t.feed("out_time_us=2500000") == 25.0
    assert t.feed("frame=100") == 25.0
    assert t.feed("garbage") == 25.0
    assert t.feed("out_time_us=1000000") == 25.0  # never goes backwards
    assert t.feed("out_time_us=20000000") == 99.9  # clamped until 'end'
    assert t.feed("progress=end\n") == 100.0 and t.finished
