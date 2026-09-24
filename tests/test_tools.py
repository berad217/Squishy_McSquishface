"""ffmpeg lookup and download. No network: downloads come from file:// URLs.

The real pinned download runs only with SQUISHY_LIVE_DOWNLOAD=1 (~110 MB).
"""

import hashlib
import io
import os
import re
import subprocess
import zipfile

import pytest

from squishy import tools
from squishy.tools import EXE_SUFFIX, DownloadError, download_tools, find_tools

FF = f"ffmpeg{EXE_SUFFIX}"
FP = f"ffprobe{EXE_SUFFIX}"


def make_zip(tmp_path, members):
    """Write a zip of {archive_name: bytes}; return (file:// url, sha256)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    path = tmp_path / "build.zip"
    path.write_bytes(buf.getvalue())
    return path.as_uri(), hashlib.sha256(buf.getvalue()).hexdigest()


GOOD = {
    f"ffmpeg-x-essentials_build/bin/{FF}": b"FFMPEG",
    f"ffmpeg-x-essentials_build/bin/{FP}": b"FFPROBE",
    "ffmpeg-x-essentials_build/bin/ffplay.exe": b"not wanted",
    "ffmpeg-x-essentials_build/LICENSE": b"GPL",
}


def test_find_tools_prefers_bin_over_path(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", lambda name: f"/usr/bin/{name}")
    (tmp_path / FF).write_bytes(b"x")
    found = find_tools(tmp_path)
    assert found.ffmpeg == str(tmp_path / FF)
    assert found.ffprobe == "/usr/bin/ffprobe"  # per tool: bin/ lacks ffprobe


def test_find_tools_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    assert find_tools(tmp_path) is None


def test_download_installs_only_what_we_need(tmp_path):
    url, sha = make_zip(tmp_path, GOOD)
    bin_dir = tmp_path / "bin"
    seen = []
    result = download_tools(bin_dir, url=url, sha256=sha, progress=lambda d, t: seen.append((d, t)))

    assert result.ffmpeg == str(bin_dir / FF)
    assert (bin_dir / FF).read_bytes() == b"FFMPEG"
    assert (bin_dir / FP).read_bytes() == b"FFPROBE"
    assert (bin_dir / "ffmpeg-LICENSE.txt").read_bytes() == b"GPL"
    assert sorted(p.name for p in bin_dir.iterdir()) == sorted([FF, FP, "ffmpeg-LICENSE.txt"])
    assert seen and seen[-1][0] == seen[-1][1]  # progress reached the total
    assert find_tools(bin_dir).ffmpeg == str(bin_dir / FF)


def test_checksum_mismatch_installs_nothing(tmp_path):
    url, _ = make_zip(tmp_path, GOOD)
    bin_dir = tmp_path / "bin"
    with pytest.raises(DownloadError, match="checksum mismatch"):
        download_tools(bin_dir, url=url, sha256="0" * 64)
    assert list(bin_dir.iterdir()) == []  # no exe, no leftover .part


def test_zip_without_ffprobe_is_rejected(tmp_path):
    url, sha = make_zip(tmp_path, {f"x/bin/{FF}": b"FFMPEG"})
    with pytest.raises(DownloadError, match=FP):
        download_tools(tmp_path / "bin", url=url, sha256=sha)


def test_member_paths_cannot_escape_bin(tmp_path):
    url, sha = make_zip(tmp_path, {f"../../{FF}": b"FFMPEG", f"/abs/{FP}": b"FFPROBE"})
    bin_dir = tmp_path / "deep" / "bin"
    download_tools(bin_dir, url=url, sha256=sha)
    assert (bin_dir / FF).is_file() and (bin_dir / FP).is_file()
    assert not (tmp_path / FF).exists()


def test_network_error_becomes_download_error(tmp_path):
    with pytest.raises(DownloadError):
        download_tools(tmp_path / "bin", url=(tmp_path / "nope.zip").as_uri(), sha256="0" * 64)


def test_not_a_zip_is_rejected(tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"<html>rate limited</html>")
    sha = hashlib.sha256(junk.read_bytes()).hexdigest()
    with pytest.raises(DownloadError, match="not a valid zip"):
        download_tools(tmp_path / "bin", url=junk.as_uri(), sha256=sha)


def test_pin_is_consistent():
    assert re.fullmatch(r"[0-9a-f]{64}", tools.FFMPEG_SHA256)
    assert f"/{tools.FFMPEG_VERSION}/" in tools.FFMPEG_URL
    assert tools.FFMPEG_URL.startswith("https://")


@pytest.mark.skipif(os.environ.get("SQUISHY_LIVE_DOWNLOAD") != "1" or os.name != "nt",
                    reason="set SQUISHY_LIVE_DOWNLOAD=1 to fetch the real ~110 MB build")
def test_live_pinned_download(tmp_path):
    result = download_tools(tmp_path / "bin")
    out = subprocess.run([result.ffmpeg, "-version"], capture_output=True, text=True, check=True)
    assert tools.FFMPEG_VERSION in out.stdout
    subprocess.run([result.ffprobe, "-version"], capture_output=True, check=True)
