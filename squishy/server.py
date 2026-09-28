"""Local HTTP server: serves the page, receives uploads, runs encode jobs."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .batch import Batch, Listing, build_listing
from .encoder import NO_WINDOW, EncodeJob, build_copy_args, build_ffmpeg_args, build_frame_args
from .presets import PRESETS_BY_ID, SourceInfo, plan_for, plans_for
from .picker import PickerError, pick
from .probe import ProbeError, probe_file, probe_packets
from .trim import (
    CopyPlan,
    Packet,
    RangeNotSatisfiable,
    Trim,
    copy_bytes,
    fmt_stamp,
    make_trim,
    output_stem,
    parse_range,
    safe_stem,
    snap_to_keyframe,
)

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
CHUNK = 1024 * 1024
MEDIA_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
               ".mkv": "video/x-matroska", ".webm": "video/webm", ".avi": "video/x-msvideo",
               ".ts": "video/mp2t", ".mts": "video/mp2t", ".m2ts": "video/mp2t"}
PREVIEW_WIDTH = 960  # fallback player frames: plenty for picking a cut point


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Return directory/stem+suffix, or stem-2, stem-3... if taken."""
    candidate = directory / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{n}{suffix}"
        n += 1
    return candidate


@dataclass
class Upload:
    """A received source file, and its packets once the background scan is done."""

    path: Path
    info: SourceInfo
    video_packets: list[Packet] | None = None  # None until scanned; set last
    audio_packets: list[Packet] = field(default_factory=list)
    scan_error: str | None = None

    def scan(self, ffprobe: str) -> None:
        """List packets for the Original card (keyframes, sizes). Runs in a thread."""
        try:
            audio = probe_packets(self.path, "a:0", ffprobe) if self.info.has_audio else []
            video = probe_packets(self.path, "V:0", ffprobe)
        except ProbeError as exc:
            self.scan_error = str(exc)
            log.warning("Packet scan of %s failed: %s", self.info.name, exc)
            return
        self.audio_packets = audio
        self.video_packets = video
        log.info("Scanned %s: %d keyframes", self.info.name, sum(p.key for p in video))

    @property
    def copy_ext(self) -> str:
        """Extension for the Original card: the source's own container if known."""
        ext = self.path.suffix.lower()
        return ext if ext in MEDIA_TYPES else ".mkv"


@dataclass
class AppState:
    """Everything the request handlers share."""

    temp_dir: Path
    out_dir: Path
    uploads: dict[str, Upload] = field(default_factory=dict)
    jobs: dict[str, EncodeJob] = field(default_factory=dict)
    stills: dict[str, Path] = field(default_factory=dict)
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    lock: threading.Lock = field(default_factory=threading.Lock)
    listing: Listing | None = None  # the latest picker result
    batch: Batch | None = None  # running, or finished and not yet dismissed
    picker: Callable[[str], list[Path]] = pick  # tests swap in a fake
    pick_lock: threading.Lock = field(default_factory=threading.Lock)
    log_path: Path | None = None  # the log file, if launch.py could open one

    def active_job(self) -> EncodeJob | None:
        """Return the running job, if any (one at a time by design)."""
        return next((j for j in self.jobs.values() if j.active), None)

    def busy(self) -> str | None:
        """Why new work has to wait, or None if it doesn't."""
        if self.batch is not None and self.batch.active:
            return "a batch is running; wait for it or stop it first"
        if self.active_job() is not None:
            return "an encode is running; wait or cancel it first"
        return None

    def drop_uploads(self) -> None:
        """Delete all received source files (only called with no active job)."""
        for up in self.uploads.values():
            try:
                up.path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Could not delete %s: %s", up.path, exc)
        self.uploads.clear()

    def shutdown(self) -> None:
        """Cancel running work and remove the temp directory."""
        if self.batch is not None and self.batch.active:
            self.batch.stop()
            self.batch.wait(timeout=10)
        for job in self.jobs.values():
            if job.active:
                job.cancel()
                job.wait(timeout=10)
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class SquishyServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the shared AppState."""

    daemon_threads = True
    # On Windows SO_REUSEADDR lets us bind a port another process is already listening
    # on (if it set the flag too, as Python servers do), so the busy-port fallback never
    # fires. Exclusive use makes that bind fail instead.
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        """Bind, claiming the port exclusively on Windows."""
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address: tuple[str, int], app: AppState) -> None:
        """Bind the server.

        Args:
            address: (host, port); host should be 127.0.0.1.
            app: Shared state.
        """
        super().__init__(address, Handler)
        self.app = app


class Handler(BaseHTTPRequestHandler):
    """Routes. See spec.md section 5 for the table."""

    server: SquishyServer
    protocol_version = "HTTP/1.1"

    # --- plumbing -----------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:  # noqa: D102 - quiet default logging
        log.debug("%s - %s", self.address_string(), fmt % args)

    @property
    def app(self) -> AppState:
        return self.server.app

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _origin_ok(self) -> bool:
        """Reject DNS-rebinding (bad Host) and cross-site POSTs (bad Origin)."""
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        if self.command == "POST" and origin is not None:
            return origin in {f"http://{h}" for h in allowed}
        return True

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 64 * 1024:
            raise ValueError("request too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    def _receive(self, dest: Path | None, length: int) -> tuple[int, OSError | None]:
        """Read the whole request body, saving it to dest if given.

        The body is always read to the end, even after a write fails or when dest is
        None: replying and closing with unread data makes the OS send a reset, and the
        browser then reports a dead server instead of our error message.

        Args:
            dest: File to write the body to, or None to discard it.
            length: Content-Length of the body.

        Returns:
            (bytes received, the first error opening or writing dest). Fewer bytes
            than length means the browser went away (aborted or closed the tab); the
            connection is then marked for closing and there is no one to answer.
        """
        fh, write_error = None, None
        if dest is not None:
            try:
                fh = dest.open("wb")
            except OSError as exc:
                write_error = exc
        received = 0
        try:
            while received < length:
                try:
                    chunk = self.rfile.read(min(CHUNK, length - received))
                except OSError:
                    chunk = b""
                if not chunk:
                    self.close_connection = True
                    break
                received += len(chunk)
                if fh is not None:
                    try:
                        fh.write(chunk)
                    except OSError as exc:
                        write_error = exc
                        try:
                            fh.close()
                        except OSError:
                            pass  # already failing; the first error is the one to report
                        fh = None
        finally:
            if fh is not None:
                try:
                    fh.close()
                except OSError as exc:
                    write_error = write_error or exc
        return received, write_error

    def _job_from_path(self, parts: list[str]) -> EncodeJob | None:
        job = self.app.jobs.get(parts[2]) if len(parts) >= 3 else None
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "unknown job")
        return job

    def _upload_for(self, file_id: object) -> Upload | None:
        upload = self.app.uploads.get(str(file_id))
        if upload is None:
            self._error(HTTPStatus.NOT_FOUND, "file not found; drop it again")
        return upload

    @staticmethod
    def _trim_from(data: dict, upload: Upload) -> Trim | None:
        """Read in_s/out_s from a request. Neither means untrimmed.

        Raises:
            ValueError: If only one is given, or they don't make a valid trim.
        """
        if "in_s" not in data and "out_s" not in data:
            return None
        try:
            in_s, out_s = float(data["in_s"]), float(data["out_s"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("in_s and out_s must both be numbers") from exc
        return make_trim(in_s, out_s, upload.info.duration_s)

    @staticmethod
    def _time_from(value: object, upload: Upload) -> float:
        """Read a frame time; it must fall inside the video.

        Raises:
            ValueError: If it isn't a number inside [0, duration).
        """
        try:
            t = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("t must be a number") from exc
        if not 0 <= t < upload.info.duration_s:
            raise ValueError("t is outside the video")
        return t

    @staticmethod
    def _original(upload: Upload, trim: Trim | None) -> dict | None:
        """The Original card's figures for a trim; None when untrimmed."""
        if trim is None:
            return None
        if upload.video_packets is None:
            return {"ready": False, "error": upload.scan_error, "ext": upload.copy_ext}
        start = snap_to_keyframe([p.pts for p in upload.video_packets if p.key], trim.in_s)
        est = copy_bytes([upload.video_packets, upload.audio_packets], start, trim.out_s)
        size = upload.info.size_bytes
        return {"ready": True, "ext": upload.copy_ext, "start_s": start,
                "snap_s": round(max(0.0, trim.in_s - start), 6), "est_bytes": est,
                "est_ratio": round(est / size, 4) if size > 0 else 0.0}

    def _run_ffmpeg(self, args: list[str], timeout: float) -> bytes:
        """Run a short ffmpeg command, returning stdout.

        Raises:
            RuntimeError: If it fails, times out, or can't start.
        """
        try:
            result = subprocess.run(args, capture_output=True, timeout=timeout,
                                    stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"ffmpeg failed to run: {exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "ffmpeg failed")
        return result.stdout

    # --- dispatch -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if not self._origin_ok():
            return self._error(HTTPStatus.FORBIDDEN, "forbidden")
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if path in ("/", "/index.html"):
            return self._serve_index()
        if path == "/api/ping":
            return self._send_json(HTTPStatus.OK, {"app": "squishy", "version": __version__})
        if len(parts) == 3 and parts[:2] == ["api", "job"]:
            job = self._job_from_path(parts)
            if job:
                self._send_json(HTTPStatus.OK, job.status())
            return None
        if len(parts) == 4 and parts[:2] == ["api", "job"] and parts[3] == "download":
            job = self._job_from_path(parts)
            if job:
                self._download(job)
            return None
        if len(parts) == 3 and parts[:2] == ["api", "media"]:
            return self._media(parts[2])
        if len(parts) == 3 and parts[:2] == ["api", "frame"]:
            return self._frame(parts[2])
        if len(parts) == 3 and parts[:2] == ["api", "keyframes"]:
            return self._keyframes(parts[2])
        if path == "/api/batch":
            batch = self.app.batch
            if batch is None:
                return self._send_json(HTTPStatus.OK, {"state": "none"})
            log_path = str(self.app.log_path) if self.app.log_path else None
            return self._send_json(HTTPStatus.OK, {**batch.status(), "log_path": log_path})
        return self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._origin_ok():
            return self._error(HTTPStatus.FORBIDDEN, "forbidden")
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if path == "/api/upload":
            return self._upload()
        if path == "/api/encode":
            return self._encode()
        if path == "/api/plans":
            return self._plans()
        if path == "/api/still":
            return self._still()
        if path == "/api/pick":
            return self._pick()
        if path == "/api/batch":
            return self._batch_start()
        if path == "/api/batch/stop":
            batch = self.app.batch
            if batch is None:
                return self._error(HTTPStatus.NOT_FOUND, "no batch")
            batch.stop()
            return self._send_json(HTTPStatus.OK, batch.status())
        if path == "/api/batch/reveal":
            batch = self.app.batch
            done = [i for i in batch.items if i.state == "done"] if batch else []
            if not done:
                return self._error(HTTPStatus.CONFLICT, "nothing squished yet")
            return self._reveal(self.app.out_dir / done[0].output_name)
        if path == "/api/batch/dismiss":
            with self.app.lock:
                if self.app.batch is not None and self.app.batch.active:
                    return self._error(HTTPStatus.CONFLICT, "the batch is still running")
                self.app.batch = None
            return self._send_json(HTTPStatus.OK, {"state": "none"})
        if len(parts) == 4 and parts[:2] == ["api", "job"]:
            job = self._job_from_path(parts)
            if job is None:
                return None
            if parts[3] == "cancel":
                job.cancel()
                return self._send_json(HTTPStatus.OK, {"ok": True})
            if parts[3] == "reveal":
                if job.state != "done":
                    return self._error(HTTPStatus.CONFLICT, "output not available")
                return self._reveal(job.dst)
        if len(parts) == 4 and parts[:2] == ["api", "still"] and parts[3] == "reveal":
            still = self.app.stills.get(parts[2])
            if still is None:
                return self._error(HTTPStatus.NOT_FOUND, "unknown still")
            return self._reveal(still)
        return self._error(HTTPStatus.NOT_FOUND, "not found")

    # --- handlers -----------------------------------------------------------

    def _serve_index(self) -> None:
        try:
            body = (STATIC_DIR / "index.html").read_bytes()
        except OSError as exc:
            log.error("Cannot read index.html: %s", exc)
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "index.html missing")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return None

    def _upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return self._error(HTTPStatus.LENGTH_REQUIRED, "empty upload")
        name = urllib.parse.unquote(self.headers.get("X-Filename") or "video")

        with self.app.lock:
            busy = self.app.busy()
            if not busy:
                self.app.drop_uploads()
        if busy:
            if self._receive(None, length)[0] < length:
                return None
            return self._error(HTTPStatus.CONFLICT, busy)

        file_id = secrets.token_hex(6)
        suffix = re.sub(r"[^\w.]", "", Path(name).suffix)[:10] or ".bin"
        dest = self.app.temp_dir / f"{file_id}{suffix}"
        log.info("Receiving %s (%.1f MB)", name, length / 1e6)
        received, write_error = self._receive(dest, length)
        if received < length:
            dest.unlink(missing_ok=True)
            log.info("Upload of %s abandoned by the browser at %.1f MB", name, received / 1e6)
            return None
        if write_error is not None:
            dest.unlink(missing_ok=True)
            log.error("Could not save upload of %s: %s", name, write_error)
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"could not save the upload: {write_error}")
        try:
            info = probe_file(dest, file_id=file_id, name=name, ffprobe=self.app.ffprobe)
        except (OSError, ProbeError) as exc:
            dest.unlink(missing_ok=True)
            log.error("Upload of %s rejected: %s", name, exc)
            return self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))

        upload = Upload(dest, info)
        with self.app.lock:
            self.app.uploads[file_id] = upload
        log.info("Probed %s: %dx%d %.2ffps %.1fs", name, info.width, info.height, info.fps, info.duration_s)
        threading.Thread(target=upload.scan, args=(self.app.ffprobe,), name=f"scan-{file_id}",
                         daemon=True).start()
        return self._send_json(HTTPStatus.OK, {
            "source": info.to_dict(),
            "plans": [p.to_dict() for p in plans_for(info)],
            "out_dir": str(self.app.out_dir),
        })

    def _encode(self) -> None:
        try:
            data = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        preset_id = str(data.get("preset_id"))
        original = preset_id == "original"
        preset = PRESETS_BY_ID.get(preset_id)
        if preset is None and not original:
            return self._error(HTTPStatus.BAD_REQUEST, "unknown preset")

        with self.app.lock:
            # Look up under the lock: a new upload deletes the old sources (under it too).
            upload = self._upload_for(data.get("file_id"))
            if upload is None:
                return None
            try:
                trim = self._trim_from(data, upload)
            except ValueError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            busy = self.app.busy()
            if busy:
                return self._error(HTTPStatus.CONFLICT, busy)

            stem = safe_stem(upload.info.name)
            if original:
                if trim is None:
                    return self._error(HTTPStatus.BAD_REQUEST, "Original needs a trim")
                orig = self._original(upload, trim)
                if not orig["ready"]:
                    if orig["error"]:
                        return self._error(HTTPStatus.UNPROCESSABLE_ENTITY, orig["error"])
                    return self._error(HTTPStatus.CONFLICT, "still reading keyframes; try again in a moment")
                start = orig["start_s"]
                # Named for what the file holds: it starts at the keyframe.
                name, suffix = output_stem(stem, "original", Trim(start, trim.out_s)), orig["ext"]
            else:
                name, suffix = output_stem(stem, preset.id, trim), ".mp4"
            try:
                self.app.out_dir.mkdir(parents=True, exist_ok=True)
                dst = unique_path(self.app.out_dir, name, suffix)
                dst.touch()  # reserve the name so a quick second job can't pick it
            except OSError as exc:
                log.error("Cannot write to output folder %s: %s", self.app.out_dir, exc)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                                   f"cannot write to output folder {self.app.out_dir}: {exc}")
            job_id, ff = secrets.token_hex(4), self.app.ffmpeg
            if original:
                plan = CopyPlan("original", orig["est_bytes"], orig["snap_s"])
                job = EncodeJob(job_id, upload.path, dst, plan, trim.out_s - start, ffmpeg=ff,
                                args=build_copy_args(upload.path, dst, start, trim, ff))
            elif trim is not None:
                plan = plan_for(upload.info, preset, trim)
                job = EncodeJob(job_id, upload.path, dst, plan, trim.duration_s, ffmpeg=ff,
                                args=build_ffmpeg_args(upload.path, dst, plan, ff, trim))
            else:  # untrimmed: exactly the v0.2.4 job
                job = EncodeJob(job_id, upload.path, dst, plan_for(upload.info, preset),
                                upload.info.duration_s, ffmpeg=ff)
            self.app.jobs[job.job_id] = job
            job.start()
        return self._send_json(HTTPStatus.OK, job.status())

    def _plans(self) -> None:
        try:
            data = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        upload = self._upload_for(data.get("file_id"))
        if upload is None:
            return None
        try:
            trim = self._trim_from(data, upload)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        return self._send_json(HTTPStatus.OK, {
            "plans": [p.to_dict() for p in plans_for(upload.info, trim)],
            "trim": None if trim is None else {"in_s": trim.in_s, "out_s": trim.out_s},
            "original": self._original(upload, trim),
        })

    def _pick(self) -> None:
        """Open a native picker on this machine and list what was chosen (Sprint 5).

        Paths only ever come from the picker, which a person at this PC answers; the page
        refers to files by item id. So the page can't make the server read anything else.
        """
        try:
            data = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        mode = data.get("mode")
        if mode not in ("folder", "files"):
            return self._error(HTTPStatus.BAD_REQUEST, "mode must be 'folder' or 'files'")
        with self.app.lock:
            busy = self.app.busy()
        if busy:
            return self._error(HTTPStatus.CONFLICT, busy)
        if not self.app.pick_lock.acquire(blocking=False):
            return self._error(HTTPStatus.CONFLICT, "a picker is already open; look for it on the taskbar")
        try:
            try:
                chosen = self.app.picker(mode)
            except PickerError as exc:
                log.error("Picker failed: %s", exc)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            if not chosen:
                return self._send_json(HTTPStatus.OK, {"cancelled": True})
            folder = chosen[0] if mode == "folder" else None
            try:
                paths = [p for p in folder.iterdir() if p.is_file()] if folder else chosen
            except OSError as exc:
                log.error("Cannot read folder %s: %s", folder, exc)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"cannot read {folder}: {exc}")
            listing = build_listing(paths, folder=folder, out_dir=self.app.out_dir, ffprobe=self.app.ffprobe)
        finally:
            self.app.pick_lock.release()
        with self.app.lock:
            self.app.listing = listing
        return self._send_json(HTTPStatus.OK, listing.to_dict(self.app.out_dir))

    def _batch_start(self) -> None:
        try:
            data = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        preset = PRESETS_BY_ID.get(str(data.get("preset_id")))
        if preset is None:
            return self._error(HTTPStatus.BAD_REQUEST, "unknown preset")
        ids = data.get("item_ids")
        if not isinstance(ids, list) or not ids:
            return self._error(HTTPStatus.BAD_REQUEST, "tick at least one file")
        with self.app.lock:
            listing = self.app.listing
            if listing is None or listing.listing_id != data.get("listing_id"):
                return self._error(HTTPStatus.CONFLICT, "that list is out of date; choose the files again")
            wanted = {str(i) for i in ids}
            items = [i for i in listing.items if i.item_id in wanted]
            if len(items) != len(wanted):
                return self._error(HTTPStatus.BAD_REQUEST, "a ticked file isn't in the list")
            if any(i.error for i in items):
                return self._error(HTTPStatus.BAD_REQUEST, "a ticked file can't be squished")
            busy = self.app.busy()
            if busy:
                return self._error(HTTPStatus.CONFLICT, busy)
            batch = Batch(secrets.token_hex(4), items, preset, self.app.out_dir, ffmpeg=self.app.ffmpeg)
            self.app.batch = batch
            batch.start()
        return self._send_json(HTTPStatus.OK, batch.status())

    def _still(self) -> None:
        try:
            data = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        upload = self._upload_for(data.get("file_id"))
        if upload is None:
            return None
        try:
            t = self._time_from(data.get("t"), upload)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        name = f"{safe_stem(upload.info.name)}_still_{fmt_stamp(t)}"
        try:
            self.app.out_dir.mkdir(parents=True, exist_ok=True)
            with self.app.lock:
                dst = unique_path(self.app.out_dir, name, ".jpg")
                dst.touch()
        except OSError as exc:
            log.error("Cannot write to output folder %s: %s", self.app.out_dir, exc)
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                               f"cannot write to output folder {self.app.out_dir}: {exc}")
        try:
            self._run_ffmpeg(build_frame_args(upload.path, dst, t, self.app.ffmpeg), timeout=120)
            size = dst.stat().st_size
            if size == 0:
                raise RuntimeError("no frame at that time")
        except (RuntimeError, OSError) as exc:
            dst.unlink(missing_ok=True)
            log.error("Still at %.3fs of %s failed: %s", t, upload.info.name, exc)
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"could not save the frame: {exc}")
        still_id = secrets.token_hex(4)
        self.app.stills[still_id] = dst
        log.info("Saved still %s (%d bytes)", dst.name, size)
        return self._send_json(HTTPStatus.OK, {"still_id": still_id, "name": dst.name,
                                               "path": str(dst), "bytes": size})

    def _media(self, file_id: str) -> None:
        """Serve an upload to the player, honouring single byte ranges (seeking needs them)."""
        upload = self._upload_for(file_id)
        if upload is None:
            return None
        try:
            fh = upload.path.open("rb")
            size = upload.path.stat().st_size
        except OSError:
            return self._error(HTTPStatus.NOT_FOUND, "file not found; drop it again")
        with fh:
            try:
                rng = parse_range(self.headers.get("Range"), size)
            except RangeNotSatisfiable:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            start, end = rng or (0, size - 1)
            self.send_response(HTTPStatus.PARTIAL_CONTENT if rng else HTTPStatus.OK)
            self.send_header("Content-Type", MEDIA_TYPES.get(upload.path.suffix.lower(),
                                                             "application/octet-stream"))
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                fh.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = fh.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except OSError:
                # The player dropped the connection (seeked elsewhere, or has enough buffered).
                self.close_connection = True
        return None

    def _keyframes(self, file_id: str) -> None:
        """Keyframe times for the timeline ticks; ready is false until the scan is done."""
        upload = self._upload_for(file_id)
        if upload is None:
            return None
        packets = upload.video_packets
        return self._send_json(HTTPStatus.OK, {
            "ready": packets is not None,
            "error": upload.scan_error,
            "keyframes": sorted(round(p.pts, 6) for p in packets or [] if p.key),
        })

    def _frame(self, file_id: str) -> None:
        """A scaled-down JPEG of the frame at ?t= (the fallback player)."""
        upload = self._upload_for(file_id)
        if upload is None:
            return None
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            t = self._time_from((query.get("t") or [None])[0], upload)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        args = build_frame_args(upload.path, Path("-"), t, self.app.ffmpeg, max_width=PREVIEW_WIDTH)
        try:
            body = self._run_ffmpeg(args, timeout=30)
        except RuntimeError as exc:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        if not body:
            return self._error(HTTPStatus.NOT_FOUND, "no frame at that time")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return None

    def _reveal(self, path: Path) -> None:
        if not path.exists():
            return self._error(HTTPStatus.CONFLICT, "output not available")
        try:
            # String form: explorer needs /select,"path" with the quotes inside.
            subprocess.Popen(f'explorer /select,"{path}"')
        except OSError as exc:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        return self._send_json(HTTPStatus.OK, {"ok": True})

    def _download(self, job: EncodeJob) -> None:
        if job.state != "done" or not job.dst.exists():
            return self._error(HTTPStatus.CONFLICT, "output not available")
        try:
            size = job.dst.stat().st_size
            fh = job.dst.open("rb")
        except OSError as exc:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        with fh:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", MEDIA_TYPES.get(job.dst.suffix.lower(),
                                                             "application/octet-stream"))
            self.send_header("Content-Length", str(size))
            quoted = urllib.parse.quote(job.dst.name)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
            self.end_headers()
            shutil.copyfileobj(fh, self.wfile, CHUNK)
        return None
