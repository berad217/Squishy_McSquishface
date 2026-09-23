import pytest

from squishy.presets import (
    PRESETS,
    PRESETS_BY_ID,
    SourceInfo,
    estimate_bytes,
    output_dims,
    plan_for,
    plans_for,
)

UE5 = SourceInfo("f1", "ue5.mp4", 238_026_752, 31.141, 3840, 2160, 60.0, True)


def test_output_dims_downscales_4k_to_1080p():
    assert output_dims(3840, 2160, 1080) == (1920, 1080)


def test_output_dims_never_upscales():
    assert output_dims(1280, 720, 1080) == (1280, 720)


def test_output_dims_portrait_uses_short_side():
    assert output_dims(2160, 3840, 1080) == (1080, 1920)


def test_output_dims_are_even():
    w, h = output_dims(1001, 563, 1080)
    assert w % 2 == 0 and h % 2 == 0


def test_output_dims_odd_aspect_downscale_even():
    w, h = output_dims(2560, 1080, 720)  # ultrawide
    assert h == 720 and w % 2 == 0 and abs(w - 1706.7) < 2


def test_output_dims_rejects_zero():
    with pytest.raises(ValueError):
        output_dims(0, 1080, 1080)


def test_estimate_includes_vbv_buffer_and_audio():
    # 3500k * (31.141 + 1.8) + 128k * 31.141 = 115,293,500 + 3,986,048 bits
    est = estimate_bytes(31.141, 3500, 128)
    assert est == int((3500_000 * 32.941 + 128_000 * 31.141) / 8 * 1.01)


def test_medium_estimate_bounds_the_real_result():
    # The hand-run encode of this clip produced 12.1 MiB.
    medium = plan_for(UE5, PRESETS_BY_ID["medium"])
    assert medium.est_bytes > 12.1 * 1024 * 1024
    assert medium.est_bytes < 16 * 1000 * 1000


def test_fps_cap_only_when_source_faster():
    heavy = plan_for(UE5, PRESETS_BY_ID["heavy"])
    assert heavy.fps_capped and heavy.out_fps == 30.0
    slow_src = SourceInfo("f2", "a.mp4", 1000, 10, 1920, 1080, 24.0, True)
    heavy24 = plan_for(slow_src, PRESETS_BY_ID["heavy"])
    assert not heavy24.fps_capped and heavy24.out_fps == 24.0


def test_no_audio_source_has_zero_audio_bitrate():
    mute = SourceInfo("f3", "m.mp4", 1000, 10, 1920, 1080, 30.0, False)
    plan = plan_for(mute, PRESETS_BY_ID["medium"])
    assert plan.audio_kbps == 0
    assert plan.est_bytes == estimate_bytes(10, 3500, 0)


def test_bitrate_capped_at_source_bitrate():
    small = SourceInfo("f4", "s.mp4", 2_400_000, 31.1, 960, 540, 30.0, True, video_kbps=550)
    light = plan_for(small, PRESETS_BY_ID["light"])
    assert light.bitrate_capped and light.video_kbps == 550
    extreme = plan_for(small, PRESETS_BY_ID["extreme"])  # 600 > 550 -> capped too
    assert extreme.bitrate_capped and extreme.video_kbps == 550


def test_no_cap_when_source_bitrate_unknown_or_higher():
    assert not plan_for(UE5, PRESETS_BY_ID["light"]).bitrate_capped
    hi = SourceInfo("f5", "h.mp4", 1, 10, 3840, 2160, 60.0, True, video_kbps=60_000)
    assert plan_for(hi, PRESETS_BY_ID["light"]).video_kbps == 8000


def test_plans_ordered_light_to_extreme_and_shrinking():
    plans = plans_for(UE5)
    assert [p.preset_id for p in plans] == [p.id for p in PRESETS]
    sizes = [p.est_bytes for p in plans]
    assert sizes == sorted(sizes, reverse=True)
