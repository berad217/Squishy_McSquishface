"""Find ffmpeg/ffprobe, and fetch a pinned, checksum-verified build when they are missing.

Lookup order: the app's own bin/ folder, then PATH. The download is a specific
gyan.dev "essentials" release from its GitHub mirror, verified against a pinned
SHA-256, and only ffmpeg.exe/ffprobe.exe (plus the licence) are kept. Windows only:
other platforms should use their package manager.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = APP_ROOT / "bin"
TOOL_NAMES = ("ffmpeg", "ffprobe")
EXE_SUFFIX = ".exe" if os.name == "nt" else ""

# To bump: take the new tag's zip digest from
#   gh api repos/GyanD/codexffmpeg/releases/tags/<ver> --jq '.assets[].digest'
# and cross-check it against gyan.dev's .sha256 file for the same package.
FFMPEG_VERSION = "9.0.2"
FFMPEG_URL = (
    "https://github.com/GyanD/codexffmpeg/releases/download/"
    f"{FFMPEG_VERSION}/ffmpeg-{FFMPEG_VERSION}-essentials_build.zip"
)
FFMPEG_SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
FFMPEG_BYTES = 114_768_076

CHUNK = 1024 * 1024
Progress = Callable[[int, int | None], None]


class DownloadError(Exception):
    """The ffmpeg download failed, or produced something we refuse to run."""


@dataclass(frozen=True)
class Tools:
    """Resolved paths to the ffmpeg executables."""

    ffmpeg: str
    ffprobe: str


def download_supported() -> bool:
    """True if the pinned build runs on this platform (it is a Windows build)."""
    return os.name == "nt"


def find_tools(bin_dir: Path = BIN_DIR) -> Tools | None:
    """Locate ffmpeg and ffprobe, preferring the app's bin/ folder over PATH.

    Args:
        bin_dir: The app-local folder checked first.

    Returns:
        Tools, or None if either executable is missing.
    """
    found: dict[str, str] = {}
    for name in TOOL_NAMES:
        local = bin_dir / f"{name}{EXE_SUFFIX}"
        path = str(local) if local.is_file() else shutil.which(name)
        if path is None:
            return None
        found[name] = path
    return Tools(**found)


def download_tools(
    bin_dir: Path = BIN_DIR,
    *,
    url: str = FFMPEG_URL,
    sha256: str = FFMPEG_SHA256,
    progress: Progress | None = None,
) -> Tools:
    """Download the pinned ffmpeg build and install its executables into bin_dir.

    Args:
        bin_dir: Destination folder (created if needed).
        url: Zip to fetch (overridable for tests).
        sha256: Expected hex digest of the zip.
        progress: Optional callback(bytes_done, bytes_total_or_None).

    Returns:
        Tools pointing into bin_dir.

    Raises:
        DownloadError: On network/disk failure, checksum mismatch, or a zip
            that lacks the executables.
    """
    part = bin_dir / "ffmpeg-download.zip.part"
    log.info("Downloading ffmpeg %s from %s", FFMPEG_VERSION, url)
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
        digest = _fetch(url, part, progress)
        if digest != sha256.lower():
            raise DownloadError(
                f"checksum mismatch (got {digest[:12]}..., expected {sha256[:12]}...); "
                "the download was corrupted or tampered with, so it was discarded"
            )
        _extract(part, bin_dir)
    except OSError as exc:  # URLError and HTTPError are OSErrors
        raise DownloadError(str(exc)) from exc
    except zipfile.BadZipFile as exc:
        raise DownloadError(f"downloaded file is not a valid zip: {exc}") from exc
    finally:
        try:
            part.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete %s: %s", part, exc)
    log.info("ffmpeg installed in %s", bin_dir)
    return Tools(*(str(bin_dir / f"{name}{EXE_SUFFIX}") for name in TOOL_NAMES))


def _fetch(url: str, dest: Path, progress: Progress | None) -> str:
    """Stream url to dest, returning the SHA-256 hex digest of the bytes."""
    hasher = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=30) as resp, dest.open("wb") as fh:
        length = resp.headers.get("Content-Length")
        total = int(length) if length and length.isdigit() else None
        done = 0
        while chunk := resp.read(CHUNK):
            fh.write(chunk)
            hasher.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return hasher.hexdigest()


def _extract(zip_path: Path, bin_dir: Path) -> None:
    """Copy the executables (and licence) out of the zip, by basename.

    Destination names are ours, never the archive's, so a hostile member path
    cannot escape bin_dir. Each file lands via a temp name + rename, so a crash
    never leaves a half-written ffmpeg.exe for find_tools() to pick up.
    """
    wanted = {f"{name}{EXE_SUFFIX}": f"{name}{EXE_SUFFIX}" for name in TOOL_NAMES}
    wanted["LICENSE"] = "ffmpeg-LICENSE.txt"
    with zipfile.ZipFile(zip_path) as zf:
        members = {Path(info.filename).name: info for info in zf.infolist() if not info.is_dir()}
        missing = [name for name in wanted if name != "LICENSE" and name not in members]
        if missing:
            raise DownloadError(f"zip does not contain {', '.join(missing)}")
        for src_name, dst_name in wanted.items():
            info = members.get(src_name)
            if info is None:
                continue
            tmp = bin_dir / f"{dst_name}.tmp"
            with zf.open(info) as src, tmp.open("wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
            os.replace(tmp, bin_dir / dst_name)
