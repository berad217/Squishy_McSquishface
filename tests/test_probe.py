import pytest

from squishy.probe import ProbeError, parse_probe


def _data(**video_overrides):
    video = {"codec_type": "video", "width": 3840, "height": 2160, "avg_frame_rate": "60/1"}
    video.update(video_overrides)
    return {
        "streams": [video, {"codec_type": "audio"}],
        "format": {"duration": "31.141111"},
    }


def _parse(data):
    return parse_probe(data, file_id="f", name="x.mp4", size_bytes=123)


def test_parses_basic_fields():
    info = _parse(_data())
    assert (info.width, info.height, info.fps, info.duration_s) == (3840, 2160, 60.0, 31.141)
    assert info.has_audio and info.size_bytes == 123


def test_rotation_side_data_swaps_dimensions():
    info = _parse(_data(width=1920, height=1080, side_data_list=[{"rotation": -90}]))
    assert (info.width, info.height) == (1080, 1920)


def test_rotation_tag_swaps_dimensions():
    info = _parse(_data(width=1920, height=1080, tags={"rotate": "90"}))
    assert (info.width, info.height) == (1080, 1920)


def test_ntsc_rate_and_fallback_to_r_frame_rate():
    assert _parse(_data(avg_frame_rate="30000/1001")).fps == pytest.approx(29.97, abs=0.01)
    assert _parse(_data(avg_frame_rate="0/0", r_frame_rate="24/1")).fps == 24.0


def test_no_audio():
    data = _data()
    data["streams"] = data["streams"][:1]
    assert not _parse(data).has_audio


def test_cover_art_is_not_a_video():
    data = {"streams": [{"codec_type": "video", "width": 500, "height": 500,
                         "avg_frame_rate": "90000/1", "disposition": {"attached_pic": 1}},
                        {"codec_type": "audio"}],
            "format": {"duration": "200"}}
    with pytest.raises(ProbeError, match="no video"):
        _parse(data)


def test_video_bitrate_from_stream():
    assert _parse(_data(bit_rate="60951514")).video_kbps == 60951


def test_video_bitrate_from_container_minus_audio():
    data = _data()
    data["streams"][1]["bit_rate"] = "192000"
    data["format"]["bit_rate"] = "1192000"
    assert _parse(data).video_kbps == 1000


def test_video_bitrate_from_size_when_nothing_reported():
    data = _data()
    data["format"] = {"duration": "10"}
    info = parse_probe(data, file_id="f", name="x.mkv", size_bytes=1_250_000)  # 1 Mbps
    assert info.video_kbps == 1000


def test_still_image_rejected():
    data = _data()
    data["format"] = {}
    with pytest.raises(ProbeError, match="duration"):
        _parse(data)
