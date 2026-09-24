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
    result = download_tools(bin_dir, urls=[url], sha256=sha, progress=lambda d, t: seen.append((d, t)))

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
        download_tools(bin_dir, urls=[url], sha256="0" * 64)
    assert list(bin_dir.iterdir()) == []  # no exe, no leftover .part


def test_zip_without_ffprobe_is_rejected(tmp_path):
    url, sha = make_zip(tmp_path, {f"x/bin/{FF}": b"FFMPEG"})
    with pytest.raises(DownloadError, match=FP):
        download_tools(tmp_path / "bin", urls=[url], sha256=sha)


def test_member_paths_cannot_escape_bin(tmp_path):
    url, sha = make_zip(tmp_path, {f"../../{FF}": b"FFMPEG", f"/abs/{FP}": b"FFPROBE"})
    bin_dir = tmp_path / "deep" / "bin"
    download_tools(bin_dir, urls=[url], sha256=sha)
    assert (bin_dir / FF).is_file() and (bin_dir / FP).is_file()
    assert not (tmp_path / FF).exists()


def test_network_error_becomes_download_error(tmp_path):
    with pytest.raises(DownloadError):
        download_tools(tmp_path / "bin", urls=[(tmp_path / "nope.zip").as_uri()], sha256="0" * 64)


def test_not_a_zip_is_rejected(tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"<html>rate limited</html>")
    sha = hashlib.sha256(junk.read_bytes()).hexdigest()
    with pytest.raises(DownloadError, match="not a valid zip"):
        download_tools(tmp_path / "bin", urls=[junk.as_uri()], sha256=sha)


def test_pin_is_consistent():
    assert re.fullmatch(r"[0-9a-f]{64}", tools.FFMPEG_SHA256)
    assert len(tools.FFMPEG_URLS) >= 2
    for url in tools.FFMPEG_URLS:
        assert url.startswith("https://")
        assert f"ffmpeg-{tools.FFMPEG_VERSION}-essentials_build.zip" in url


def test_falls_back_to_next_source(tmp_path):
    url, sha = make_zip(tmp_path, GOOD)
    dead = (tmp_path / "gone.zip").as_uri()
    bin_dir = tmp_path / "bin"
    result = download_tools(bin_dir, urls=[dead, url], sha256=sha)
    assert (bin_dir / FF).read_bytes() == b"FFMPEG"
    assert result.ffprobe == str(bin_dir / FP)


def test_bad_hash_source_is_skipped_for_good_one(tmp_path):
    good_url, sha = make_zip(tmp_path, GOOD)
    evil = tmp_path / "evil"
    evil.mkdir()
    evil_url, _ = make_zip(evil, {f"x/{FF}": b"EVIL", f"x/{FP}": b"EVIL"})
    bin_dir = tmp_path / "bin"
    download_tools(bin_dir, urls=[evil_url, good_url], sha256=sha)
    assert (bin_dir / FF).read_bytes() == b"FFMPEG"


def test_all_sources_failing_reports_each(tmp_path):
    a, b = (tmp_path / "a.zip").as_uri(), (tmp_path / "b.zip").as_uri()
    with pytest.raises(DownloadError) as info:
        download_tools(tmp_path / "bin", urls=[a, b], sha256="0" * 64)
    assert str(info.value).count(";") == 1  # one failure per source
    assert list((tmp_path / "bin").iterdir()) == []


@pytest.mark.skipif(os.environ.get("SQUISHY_LIVE_DOWNLOAD") != "1" or os.name != "nt",
                    reason="set SQUISHY_LIVE_DOWNLOAD=1 to fetch the real ~110 MB build")
@pytest.mark.parametrize("url", tools.FFMPEG_URLS)
def test_live_pinned_download(tmp_path, url):
    """Each source on its own: a dead fallback is worse than none, since it looks like cover."""
    result = download_tools(tmp_path / "bin", urls=[url])
    out = subprocess.run([result.ffmpeg, "-version"], capture_output=True, text=True, check=True)
    assert tools.FFMPEG_VERSION in out.stdout
    subprocess.run([result.ffprobe, "-version"], capture_output=True, check=True)
