"""Launcher console output: log lines must not land on the open progress line."""

import http.server
import io
import json
import logging
import re
import socket
import threading
from pathlib import Path

import pytest

import launch
from launch import ConsoleHandler, ProgressLine
from squishy.tools import Tools, download_tools


@pytest.fixture
def console():
    """One shared stream for progress and logs, as on a real console."""
    stream = io.StringIO()
    progress = ProgressLine(stream)
    handler = ConsoleHandler(progress, stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("test_launch")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    yield stream, progress, logger
    logger.removeHandler(handler)


def test_log_mid_download_starts_on_a_fresh_line(console):
    stream, progress, logger = console
    progress(50 * 1024 * 1024, 100 * 1024 * 1024)
    logger.warning("source died")
    assert stream.getvalue().endswith("%)\nWARNING source died\n")


def test_finished_download_closes_its_own_line(console):
    stream, progress, logger = console
    progress(10, 10)
    logger.info("installed")
    assert "\n\n" not in stream.getvalue()  # no stray blank line
    assert stream.getvalue().endswith("%)\nINFO installed\n")


def test_unknown_total_is_closed_before_logging(console):
    stream, progress, logger = console
    progress(3 * 1024 * 1024, None)  # no Content-Length: never "finished"
    logger.info("installed")
    assert stream.getvalue().endswith(" MB\nINFO installed\n")


def test_failed_source_warning_is_on_its_own_line(tmp_path, console, monkeypatch):
    """End to end through download_tools: a dead source's warning after partial progress."""
    stream, progress, logger = console
    monkeypatch.setattr("squishy.tools.log", logger)

    def fetch_then_die(url, dest, prog):
        prog(40, 100)
        raise OSError("connection reset")

    monkeypatch.setattr("squishy.tools._fetch", fetch_then_die)
    with pytest.raises(Exception):
        download_tools(tmp_path, urls=["https://example.invalid/a.zip"], sha256="0", progress=progress)
    lines = stream.getvalue().split("\n")
    assert lines[0].startswith("INFO Downloading ffmpeg")
    assert lines[1].endswith("( 40%)")
    assert lines[2].startswith("WARNING ffmpeg from example.invalid failed")


# --- a Squishy already on the port ---------------------------------------------

def _ping_server(body: bytes):
    class Ping(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Ping)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize(("body", "expected"), [
    (json.dumps({"app": "squishy", "version": "0.2.4"}).encode(), "0.2.4"),
    (b'{"app": "squishy"}', "unknown"),  # v0.2.3 and earlier
    (b'{"app": "something else"}', None),
    (b"<html>not json</html>", None),
])
def test_running_version(body, expected):
    srv = _ping_server(body)
    try:
        assert launch.running_version(srv.server_address[1]) == expected
    finally:
        srv.shutdown()
        srv.server_close()


def test_running_version_when_nothing_listens():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # closed again before the ping
    assert launch.running_version(port) is None


@pytest.fixture
def handoff(monkeypatch, tmp_path):
    """main() up to the handoff: tools found, the browser recorded, no server may start."""
    opened = []
    monkeypatch.setattr(launch, "resolve_tools", lambda: Tools("ffmpeg", "ffprobe"))
    monkeypatch.setattr(launch.webbrowser, "open", opened.append)
    monkeypatch.setattr(launch, "SquishyServer", lambda *a, **k: pytest.fail("started a server"))

    def run(running):
        monkeypatch.setattr(launch, "running_version", lambda port: running)
        return launch.main(["--port", "48999", "--out", str(tmp_path)]), opened

    return run


@pytest.mark.parametrize("running", ["0.2.3", "unknown", "0.1"])
def test_older_squishy_on_the_port_is_refused(handoff, running, caplog):
    code, opened = handoff(running)
    assert code == 1 and opened == []
    assert "Close its window" in caplog.text


@pytest.mark.parametrize("running", [launch.__version__, "9.9.9"])
def test_same_or_newer_squishy_on_the_port_is_opened(handoff, running):
    code, opened = handoff(running)
    assert code == 0 and opened == ["http://127.0.0.1:48999/"]


def test_version_matches_pyproject():
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{launch.__version__}"' in pyproject


# --- log file (v0.4: an unattended batch should leave a record) ---------------

def test_file_log_has_dates_and_rotates(tmp_path):
    handler = launch.add_file_log(tmp_path / "logs")
    assert handler is not None
    logger = logging.getLogger("squishy.test_file_log")
    logger.setLevel(logging.INFO)
    try:
        logger.warning("batch item %s failed", "clip.mp4")
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    text = (tmp_path / "logs" / "squishy.log").read_text(encoding="utf-8")
    assert re.search(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d WARNING squishy.test_file_log "
                     r"batch item clip.mp4 failed$", text, re.M)
    assert handler.maxBytes == launch.LOG_BYTES and handler.backupCount == launch.LOG_BACKUPS


def test_unwritable_log_folder_is_not_fatal(tmp_path):
    (tmp_path / "a-file").write_text("x")
    assert launch.add_file_log(tmp_path / "a-file" / "logs") is None
