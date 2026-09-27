import http.client
import json
import os
import shutil
import socket
import threading
import time
import urllib.parse

import pytest

from squishy.server import AppState, SquishyServer, safe_stem, unique_path


def test_safe_stem_strips_paths_and_junk():
    assert safe_stem("..\\..\\evil/x.mp4") == "x"
    assert safe_stem("Unreal Engine 5 2026.09.23 - 17.21.12.03.mp4") == "Unreal Engine 5 2026.09.23 - 17.21.12.03"
    assert safe_stem('a<b>:"c|d?*.mov') == "a_b_c_d_"
    assert safe_stem("CON.mp4") == "_CON"
    assert safe_stem(".mp4") == "mp4"  # dotfile: whole name is the stem
    assert safe_stem("...") == "video"
    assert len(safe_stem("x" * 300 + ".mp4")) == 100


def test_unique_path_suffixes(tmp_path):
    (tmp_path / "a_medium.mp4").touch()
    (tmp_path / "a_medium-2.mp4").touch()
    assert unique_path(tmp_path, "a_medium", ".mp4").name == "a_medium-3.mp4"


@pytest.fixture
def server(tmp_path):
    app = AppState(temp_dir=tmp_path / "tmp", out_dir=tmp_path / "out")
    app.temp_dir.mkdir()
    srv = SquishyServer(("127.0.0.1", 0), app)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    app.shutdown()


def _req(srv, method, path, body=None, headers=None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    h = {"Host": f"127.0.0.1:{port}"}
    h.update(headers or {})
    if isinstance(body, dict):
        body = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_ping_and_index(server):
    status, data = _req(server, "GET", "/api/ping")
    assert status == 200 and json.loads(data)["app"] == "squishy"
    from squishy import __version__
    assert json.loads(data)["version"] == __version__  # launch.py's handoff check reads this
    status, data = _req(server, "GET", "/")
    assert status == 200 and b"Squishy" in data


def test_rejects_foreign_host(server):
    status, _ = _req(server, "GET", "/api/ping", headers={"Host": "evil.example:80"})
    assert status == 403


def test_rejects_cross_origin_post(server):
    status, _ = _req(server, "POST", "/api/encode", body={}, headers={"Origin": "https://evil.example"})
    assert status == 403


def test_upload_garbage_is_422(server):
    status, data = _req(server, "POST", "/api/upload", body=b"not a video",
                        headers={"X-Filename": "junk.mp4"})
    assert status == 422 and "error" in json.loads(data)
    assert not any(server.app.temp_dir.iterdir())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_upload_encode_download_roundtrip(server, tmp_path):
    from tests.test_integration import _make_clip

    clip = _make_clip(tmp_path / "clip.mp4", 2)
    name = "my clip (1).mp4"
    status, data = _req(server, "POST", "/api/upload", body=clip.read_bytes(),
                        headers={"X-Filename": urllib.parse.quote(name)})
    assert status == 200, data
    info = json.loads(data)
    assert info["source"]["name"] == name
    assert [p["preset_id"] for p in info["plans"]] == ["light", "medium", "heavy", "extreme"]

    port = server.server_address[1]
    status, data = _req(server, "POST", "/api/encode",
                        body={"file_id": info["source"]["file_id"], "preset_id": "extreme"},
                        headers={"Origin": f"http://127.0.0.1:{port}"})
    assert status == 200, data
    job_id = json.loads(data)["job_id"]

    deadline = time.monotonic() + 120
    while True:
        job = json.loads(_req(server, "GET", f"/api/job/{job_id}")[1])
        if job["state"] not in ("queued", "running") or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert job["state"] == "done", job
    assert job["output_name"] == "my clip (1)_extreme.mp4"

    status, body = _req(server, "GET", f"/api/job/{job_id}/download")
    assert status == 200 and len(body) == job["output_bytes"]


def test_unknown_job_404(server):
    assert _req(server, "GET", "/api/job/nope")[0] == 404
    assert _req(server, "POST", "/api/job/nope/cancel")[0] == 404


def test_unwritable_output_folder_is_a_500_not_a_dropped_connection(server, tmp_path, monkeypatch):
    from squishy import server as server_mod
    from squishy.presets import SourceInfo
    from squishy.server import Upload

    info = SourceInfo("f1", "clip.mp4", 1000, 2.0, 640, 360, 30.0, False)
    server.app.uploads["f1"] = Upload(tmp_path / "clip.mp4", info)
    # out_dir exists, but the reserved output name can't be created (read-only / CFA / MAX_PATH)
    monkeypatch.setattr(server_mod, "unique_path", lambda *a: tmp_path / "missing" / "x.mp4")
    status, data = _req(server, "POST", "/api/encode", body={"file_id": "f1", "preset_id": "heavy"})
    assert status == 500
    assert "cannot write to output folder" in json.loads(data)["error"]
    assert not server.app.jobs


@pytest.mark.skipif(os.name != "nt", reason="Windows SO_REUSEADDR semantics")
def test_busy_port_is_refused_even_if_owner_allows_reuse(tmp_path):
    squatter = socket.socket()
    squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as Python servers do
    squatter.bind(("127.0.0.1", 0))
    squatter.listen()
    try:
        app = AppState(temp_dir=tmp_path, out_dir=tmp_path)
        with pytest.raises(OSError):  # launch.py then falls back to a free port
            SquishyServer(("127.0.0.1", squatter.getsockname()[1]), app)
    finally:
        squatter.close()


class _BusyJob:
    """Stands in for a running EncodeJob: active_job() only looks at .active."""

    active = True

    def cancel(self):
        self.active = False

    def wait(self, timeout=None):
        return True


def test_upload_during_encode_gets_the_409_not_a_reset(server):
    # The body is unread when the 409 goes out. Closing on unread data sends an RST,
    # and the browser reports "Upload failed" instead of the reason.
    server.app.jobs["busy"] = _BusyJob()
    status, data = _req(server, "POST", "/api/upload", body=b"\0" * (32 * 1024 * 1024),
                        headers={"X-Filename": "second-tab.mp4"})
    assert status == 409
    assert "encode is running" in json.loads(data)["error"]
    assert not any(server.app.temp_dir.iterdir())


def test_unwritable_temp_gets_a_500_not_a_reset(server):
    shutil.rmtree(server.app.temp_dir)  # e.g. a temp cleaner ran while Squishy was open
    status, data = _req(server, "POST", "/api/upload", body=b"\0" * (32 * 1024 * 1024),
                        headers={"X-Filename": "clip.mp4"})
    assert status == 500
    assert "error" in json.loads(data)


def test_encode_rechecks_the_upload_under_the_lock(server, tmp_path):
    # An upload that starts while /api/encode waits on the lock deletes the source.
    # The encode must see that and 404, not start ffmpeg on a missing file.
    from squishy.presets import SourceInfo
    from squishy.server import Upload

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    server.app.uploads["f1"] = Upload(src, SourceInfo("f1", "clip.mp4", 1, 2.0, 640, 360, 30.0, False))
    result = {}
    with server.app.lock:
        t = threading.Thread(target=lambda: result.update(r=_req(
            server, "POST", "/api/encode", body={"file_id": "f1", "preset_id": "heavy"})))
        t.start()
        time.sleep(0.5)  # let the request reach the lock
        server.app.drop_uploads()
    t.join(30)
    assert result["r"][0] == 404, result
    assert not server.app.jobs


def test_upload_abandoned_mid_body_leaves_no_temp_file(server):
    # The page aborts the old upload when a new file is dropped.
    port = server.server_address[1]
    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(f"POST /api/upload HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                  f"X-Filename: big.mp4\r\nContent-Length: {10 * 1024 * 1024}\r\n\r\n".encode())
        s.sendall(b"\0" * (1024 * 1024))
        deadline = time.monotonic() + 5
        while not any(server.app.temp_dir.iterdir()) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert any(server.app.temp_dir.iterdir())  # it was receiving
    deadline = time.monotonic() + 5
    while any(server.app.temp_dir.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not any(server.app.temp_dir.iterdir())
    assert not server.app.uploads
