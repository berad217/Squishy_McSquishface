"""v0.4 routes: pickers, batch start / status / stop / dismiss, and the locks around them."""

import json
import shutil
import time

import pytest

from squishy.picker import PickerError
from tests.test_batch_run import _clip
from tests.test_server import _req, server  # noqa: F401 - fixture

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _post(srv, path, body=None):
    status, data = _req(srv, "POST", path, body=body if body is not None else {})
    return status, json.loads(data or b"{}")


def _get(srv, path):
    status, data = _req(srv, "GET", path)
    return status, json.loads(data)


def _wait(srv):
    deadline = time.monotonic() + 120
    while True:
        _, b = _get(srv, "/api/batch")
        if b["state"] != "running" or time.monotonic() > deadline:
            return b
        time.sleep(0.1)


@pytest.fixture
def folder(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _clip(src / "a.mp4")
    _clip(src / "b.mp4")
    (src / "notes.txt").write_text("x")
    return src


def _pick_returns(srv, paths):
    srv.app.picker = lambda mode: list(paths)


def test_no_batch_at_first(server):  # noqa: F811
    assert _get(server, "/api/batch") == (200, {"state": "none"})


def test_cancelled_picker(server):  # noqa: F811
    _pick_returns(server, [])
    assert _post(server, "/api/pick", {"mode": "folder"}) == (200, {"cancelled": True})


def test_bad_picker_mode(server):  # noqa: F811
    assert _post(server, "/api/pick", {"mode": "desktop"})[0] == 400


def test_picker_error_is_reported(server):  # noqa: F811
    def boom(mode):
        raise PickerError("no Tk here")
    server.app.picker = boom
    status, body = _post(server, "/api/pick", {"mode": "files"})
    assert status == 500 and "no Tk" in body["error"]


def test_folder_to_finished_batch(server, folder):  # noqa: F811
    _pick_returns(server, [folder])
    status, listing = _post(server, "/api/pick", {"mode": "folder"})
    assert status == 200
    assert listing["folder"] == str(folder)
    assert [r["name"] for r in listing["items"]] == ["a.mp4", "b.mp4"]
    assert listing["others"] == ["notes.txt"]
    assert [p["id"] for p in listing["presets"]] == ["light", "medium", "heavy", "extreme"]

    ids = [r["item_id"] for r in listing["items"]]
    status, started = _post(server, "/api/batch", {"listing_id": listing["listing_id"],
                                                   "preset_id": "extreme", "item_ids": ids[1:]})
    assert status == 200 and started["state"] == "running"
    done = _wait(server)
    assert done["state"] == "done"
    assert [(i["name"], i["state"]) for i in done["items"]] == [("b.mp4", "done")]
    assert done["bytes_after"] > 0
    assert (server.app.out_dir / "b_extreme.mp4").exists()

    server.app.out_dir.joinpath("b_extreme.mp4").unlink()  # reveal needs the file; don't open Explorer
    assert _post(server, "/api/batch/reveal")[0] == 409
    # The page reopened later still sees it, until dismissed.
    assert _get(server, "/api/batch")[1]["batch_id"] == done["batch_id"]
    assert _post(server, "/api/batch/dismiss")[0] == 200
    assert _get(server, "/api/batch")[1] == {"state": "none"}


def test_files_picker(server, folder):  # noqa: F811
    _pick_returns(server, [folder / "b.mp4", folder / "notes.txt"])
    _, listing = _post(server, "/api/pick", {"mode": "files"})
    assert listing["folder"] is None
    assert [r["name"] for r in listing["items"]] == ["b.mp4"]
    assert listing["others"] == ["notes.txt"]


@pytest.mark.parametrize("body, status", [
    ({"listing_id": "stale", "preset_id": "extreme", "item_ids": ["x"]}, 409),
    ({"preset_id": "nope", "item_ids": ["x"]}, 400),
    ({"preset_id": "extreme", "item_ids": []}, 400),
    ({"preset_id": "extreme", "item_ids": ["not-in-listing"]}, 400),
])
def test_bad_batch_requests(server, folder, body, status):  # noqa: F811
    _pick_returns(server, [folder])
    _, listing = _post(server, "/api/pick", {"mode": "folder"})
    body = {"listing_id": listing["listing_id"], **body}
    assert _post(server, "/api/batch", body)[0] == status


def test_unusable_file_cant_be_ticked(server, folder):  # noqa: F811
    (folder / "broken.mp4").write_bytes(b"nope")
    _pick_returns(server, [folder])
    _, listing = _post(server, "/api/pick", {"mode": "folder"})
    broken = next(r for r in listing["items"] if r["name"] == "broken.mp4")
    assert broken["error"]
    body = {"listing_id": listing["listing_id"], "preset_id": "extreme", "item_ids": [broken["item_id"]]}
    assert _post(server, "/api/batch", body)[0] == 400


def test_everything_else_waits_while_a_batch_runs(server, tmp_path):  # noqa: F811
    src = tmp_path / "long"
    src.mkdir()
    _clip(src / "long.mp4", seconds=8, size="1280x720")
    _pick_returns(server, [src])
    _, listing = _post(server, "/api/pick", {"mode": "folder"})
    body = {"listing_id": listing["listing_id"], "preset_id": "light",
            "item_ids": [r["item_id"] for r in listing["items"]]}
    assert _post(server, "/api/batch", body)[0] == 200

    assert _req(server, "POST", "/api/upload", body=b"x" * 10, headers={"X-Filename": "v.mp4"})[0] == 409
    assert _post(server, "/api/pick", {"mode": "folder"})[0] == 409
    assert _post(server, "/api/batch", body)[0] == 409
    assert _post(server, "/api/batch/dismiss")[0] == 409

    assert _post(server, "/api/batch/stop")[0] == 200
    stopped = _wait(server)
    assert stopped["state"] == "stopped"
    assert [i["state"] for i in stopped["items"]] == ["stopped"]
    assert not any(server.app.out_dir.glob("*.mp4"))
