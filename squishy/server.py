"""Local HTTP server: serves the page, receives uploads, runs encode jobs."""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import subprocess
import threading
import urllib.parse
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .encoder import EncodeJob
from .presets import PRESETS_BY_ID, SourceInfo, plan_for, plans_for
from .probe import ProbeError, probe_file

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
CHUNK = 1024 * 1024
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}


def safe_stem(filename: str) -> str:
    """Turn an arbitrary uploaded filename into a safe Windows file stem.

    Args:
        filename: Name as sent by the browser (may contain anything).

    Returns:
        A non-empty stem of at most 100 chars with no path separators.
    """
    stem = Path(filename.replace("\\", "/").split("/")[-1]).stem
    stem = re.sub(r"[^\w\-. ()\[\]]+", "_", stem).strip(" .")[:100]
    if not stem:
        stem = "video"
    if stem.upper() in WINDOWS_RESERVED:
        stem = f"_{stem}"
    return stem


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
    """A received source file."""

    path: Path
    info: SourceInfo


@dataclass
class AppState:
    """Everything the request handlers share."""

    temp_dir: Path
    out_dir: Path
    uploads: dict[str, Upload] = field(default_factory=dict)
    jobs: dict[str, EncodeJob] = field(default_factory=dict)
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    lock: threading.Lock = field(default_factory=threading.Lock)

    def active_job(self) -> EncodeJob | None:
        """Return the running job, if any (one at a time by design)."""
        return next((j for j in self.jobs.values() if j.active), None)

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
        for job in self.jobs.values():
            if job.active:
                job.cancel()
                job.wait(timeout=10)
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class SquishyServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the shared AppState."""

    daemon_threads = True

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

    def _job_from_path(self, parts: list[str]) -> EncodeJob | None:
        job = self.app.jobs.get(parts[2]) if len(parts) >= 3 else None
        if job is None:
            self._error(HTTPStatus.NOT_FOUND, "unknown job")
        return job

    # --- dispatch -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if not self._origin_ok():
            return self._error(HTTPStatus.FORBIDDEN, "forbidden")
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if path in ("/", "/index.html"):
            return self._serve_index()
        if path == "/api/ping":
            return self._send_json(HTTPStatus.OK, {"app": "squishy"})
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
        if len(parts) == 4 and parts[:2] == ["api", "job"]:
            job = self._job_from_path(parts)
            if job is None:
                return None
            if parts[3] == "cancel":
                job.cancel()
                return self._send_json(HTTPStatus.OK, {"ok": True})
            if parts[3] == "reveal":
                return self._reveal(job)
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
            if self.app.active_job():
                # Body is unread; close so the client is not left hanging.
                self.close_connection = True
                return self._error(HTTPStatus.CONFLICT, "an encode is running; wait or cancel it first")
            self.app.drop_uploads()

        file_id = secrets.token_hex(6)
        suffix = re.sub(r"[^\w.]", "", Path(name).suffix)[:10] or ".bin"
        dest = self.app.temp_dir / f"{file_id}{suffix}"
        log.info("Receiving %s (%.1f MB)", name, length / 1e6)
        try:
            remaining = length
            with dest.open("wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        raise OSError("client disconnected mid-upload")
                    fh.write(chunk)
                    remaining -= len(chunk)
            info = probe_file(dest, file_id=file_id, name=name, ffprobe=self.app.ffprobe)
        except (OSError, ProbeError) as exc:
            dest.unlink(missing_ok=True)
            log.error("Upload of %s rejected: %s", name, exc)
            self.close_connection = True
            return self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))

        with self.app.lock:
            self.app.uploads[file_id] = Upload(dest, info)
        log.info("Probed %s: %dx%d %.2ffps %.1fs", name, info.width, info.height, info.fps, info.duration_s)
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
        upload = self.app.uploads.get(str(data.get("file_id")))
        preset = PRESETS_BY_ID.get(str(data.get("preset_id")))
        if upload is None:
            return self._error(HTTPStatus.NOT_FOUND, "file not found; drop it again")
        if preset is None:
            return self._error(HTTPStatus.BAD_REQUEST, "unknown preset")

        with self.app.lock:
            if self.app.active_job():
                return self._error(HTTPStatus.CONFLICT, "an encode is already running")
            try:
                self.app.out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"cannot create output folder: {exc}")
            dst = unique_path(self.app.out_dir, f"{safe_stem(upload.info.name)}_{preset.id}", ".mp4")
            dst.touch()  # reserve the name so a quick second job can't pick it
            job = EncodeJob(secrets.token_hex(4), upload.path, dst, plan_for(upload.info, preset),
                            upload.info.duration_s, ffmpeg=self.app.ffmpeg)
            self.app.jobs[job.job_id] = job
            job.start()
        return self._send_json(HTTPStatus.OK, job.status())

    def _reveal(self, job: EncodeJob) -> None:
        if job.state != "done" or not job.dst.exists():
            return self._error(HTTPStatus.CONFLICT, "output not available")
        try:
            # String form: explorer needs /select,"path" with the quotes inside.
            subprocess.Popen(f'explorer /select,"{job.dst}"')
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
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            quoted = urllib.parse.quote(job.dst.name)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
            self.end_headers()
            shutil.copyfileobj(fh, self.wfile, CHUNK)
        return None
