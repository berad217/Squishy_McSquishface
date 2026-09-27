"""v0.3 routes: media with Range, trimmed plans, Original, stills, preview frames."""

import http.client
import json
import shutil
import time
import urllib.parse

import pytest

from tests.test_server import _req, server  # noqa: F401 - fixture
from tests.test_trim_integration import FPS, _make_counter_clip

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _get(srv, path, headers=None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    h = {"Host": f"127.0.0.1:{port}", **(headers or {})}
    conn.request("GET", path, headers=h)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, dict(resp.getheaders()), body


def _post(srv, path, body):
    port = srv.server_address[1]
    status, data = _req(srv, "POST", path, body=body, headers={"Origin": f"http://127.0.0.1:{port}"})
    return status, json.loads(data)


@pytest.fixture
def uploaded(server, tmp_path):  # noqa: F811
    clip = _make_counter_clip(tmp_path / "counter.mp4")
    status, data = _req(server, "POST", "/api/upload", body=clip.read_bytes(),
                        headers={"X-Filename": urllib.parse.quote("counter.mp4")})
    assert status == 200, data
    return clip, json.loads(data)["source"]["file_id"]


def _wait_job(srv, job_id):
    deadline = time.monotonic() + 120
    while True:
        job = json.loads(_req(srv, "GET", f"/api/job/{job_id}")[1])
        if job["state"] not in ("queued", "running") or time.monotonic() > deadline:
            return job
        time.sleep(0.1)


# --- media / Range (criterion 6) -------------------------------------------

def test_media_whole_file(server, uploaded):  # noqa: F811
    clip, fid = uploaded
    status, headers, body = _get(server, f"/api/media/{fid}")
    assert status == 200
    assert headers["Accept-Ranges"] == "bytes"
    assert headers["Content-Type"] == "video/mp4"
    assert body == clip.read_bytes()


def test_media_range_is_206(server, uploaded):  # noqa: F811
    clip, fid = uploaded
    data = clip.read_bytes()
    status, headers, body = _get(server, f"/api/media/{fid}", {"Range": "bytes=100-199"})
    assert status == 206
    assert headers["Content-Range"] == f"bytes 100-199/{len(data)}"
    assert headers["Content-Length"] == "100"
    assert body == data[100:200]
    status, _, body = _get(server, f"/api/media/{fid}", {"Range": "bytes=-10"})
    assert status == 206 and body == data[-10:]


def test_media_range_past_end_is_416(server, uploaded):  # noqa: F811
    clip, fid = uploaded
    size = clip.stat().st_size
    status, headers, _ = _get(server, f"/api/media/{fid}", {"Range": f"bytes={size}-"})
    assert status == 416
    assert headers["Content-Range"] == f"bytes */{size}"


def test_media_unknown_is_404(server):  # noqa: F811
    assert _get(server, "/api/media/nope")[0] == 404


# --- plans ------------------------------------------------------------------

def test_plans_follow_the_trim(server, uploaded):  # noqa: F811
    _, fid = uploaded
    status, full = _post(server, "/api/plans", {"file_id": fid, "in_s": 0, "out_s": 4})
    assert status == 200 and full["trim"] is None and full["original"] is None
    status, cut = _post(server, "/api/plans", {"file_id": fid, "in_s": 40 / FPS, "out_s": 70 / FPS})
    assert status == 200
    assert cut["trim"] == {"in_s": 40 / FPS, "out_s": 70 / FPS}
    # 1 s of 4 s. Not a quarter: the ceiling carries a fixed 1.8 s VBV-buffer term.
    assert cut["plans"][1]["est_bytes"] < full["plans"][1]["est_bytes"] / 2


def test_original_reports_snap_once_scanned(server, uploaded):  # noqa: F811
    _, fid = uploaded
    deadline = time.monotonic() + 30
    while True:
        _, cut = _post(server, "/api/plans", {"file_id": fid, "in_s": 40 / FPS, "out_s": 70 / FPS})
        if cut["original"]["ready"] or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    orig = cut["original"]
    assert orig["ready"] and orig["ext"] == ".mp4"
    assert orig["start_s"] == pytest.approx(30 / FPS, abs=1e-3)
    assert orig["snap_s"] == pytest.approx(10 / FPS, abs=1e-3)
    assert orig["est_bytes"] > 0


def test_keyframes_listed_once_scanned(server, uploaded):  # noqa: F811
    _, fid = uploaded
    deadline = time.monotonic() + 30
    while True:
        status, _, body = _get(server, f"/api/keyframes/{fid}")
        kf = json.loads(body)
        if status != 200 or kf["ready"] or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    assert status == 200 and kf["ready"] and kf["error"] is None
    assert kf["keyframes"] == pytest.approx([n / FPS for n in range(0, 4 * FPS, 15)], abs=1e-3)


def test_keyframes_unknown_is_404(server):  # noqa: F811
    assert _get(server, "/api/keyframes/nope")[0] == 404


@pytest.mark.parametrize("body", [{"in_s": 3, "out_s": 1}, {"in_s": "x", "out_s": 2},
                                  {"in_s": 1}, {"in_s": 1, "out_s": 1.01}])
def test_bad_trim_is_400(server, uploaded, body):  # noqa: F811
    _, fid = uploaded
    status, data = _post(server, "/api/plans", {"file_id": fid, **body})
    assert status == 400, data


# --- encode -------------------------------------------------------------------

def test_trimmed_encode_is_named_for_its_range(server, uploaded):  # noqa: F811
    _, fid = uploaded
    status, job = _post(server, "/api/encode", {"file_id": fid, "preset_id": "extreme",
                                                "in_s": 40 / FPS, "out_s": 70 / FPS})
    assert status == 200, job
    job = _wait_job(server, job["job_id"])
    assert job["state"] == "done", job
    assert job["output_name"] == "counter_extreme_1.333s-2.333s.mp4"


def test_original_encode(server, uploaded):  # noqa: F811
    _, fid = uploaded
    body = {"file_id": fid, "preset_id": "original", "in_s": 40 / FPS, "out_s": 70 / FPS}
    deadline = time.monotonic() + 30
    while True:  # 409 until the packet scan is done
        status, job = _post(server, "/api/encode", body)
        if status != 409 or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    assert status == 200, job
    job = _wait_job(server, job["job_id"])
    assert job["state"] == "done", job
    assert job["preset_id"] == "original"
    assert job["output_name"] == "counter_original_1.000s-2.333s.mp4"  # named for what it holds


def test_original_needs_a_trim(server, uploaded):  # noqa: F811
    _, fid = uploaded
    status, _ = _post(server, "/api/encode", {"file_id": fid, "preset_id": "original"})
    assert status == 400


# --- stills and preview frames ---------------------------------------------

def test_still_saved_as_jpeg(server, uploaded):  # noqa: F811
    _, fid = uploaded
    status, still = _post(server, "/api/still", {"file_id": fid, "t": 55 / FPS})
    assert status == 200, still
    assert still["name"] == "counter_still_1.833s.jpg"
    path = server.app.out_dir / still["name"]
    assert path.read_bytes()[:3] == b"\xff\xd8\xff"
    assert still["bytes"] == path.stat().st_size


def test_still_bad_time_is_400(server, uploaded):  # noqa: F811
    _, fid = uploaded
    assert _post(server, "/api/still", {"file_id": fid, "t": -1})[0] == 400
    assert _post(server, "/api/still", {"file_id": fid, "t": 99})[0] == 400


def test_preview_frame(server, uploaded):  # noqa: F811
    _, fid = uploaded
    status, headers, body = _get(server, f"/api/frame/{fid}?t=1.5")
    assert status == 200 and headers["Content-Type"] == "image/jpeg"
    assert body[:3] == b"\xff\xd8\xff"
    assert _get(server, f"/api/frame/{fid}?t=abc")[0] == 400
