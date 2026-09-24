"""Launcher console output: log lines must not land on the open progress line."""

import io
import logging

import pytest

from launch import ConsoleHandler, ProgressLine
from squishy.tools import download_tools


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
