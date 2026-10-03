"""Run a local, private browser UI for producing multilingual course clips."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import socket
import sys
import threading
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

from course_outline import build_outline
from engine import LANGUAGES, OUTPUT, UPLOADS, allowed_voice, render_project, synthesize
from studio_store import get_job, get_project, list_projects, list_renders, mark_interrupted_jobs, save_job, save_project

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
RENDER_QUEUE = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studio-render")


class StudioServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def respond(self, code: int, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/languages":
            self.respond(200, {"languages": LANGUAGES})
            return
        if path == "/api/projects":
            self.respond(200, {"projects": list_projects()})
            return
        if path == "/api/renders":
            self.respond(200, {"renders": list_renders()})
            return
        project_match = re.fullmatch(r"/api/projects/([a-f0-9]{32})", path)
        if project_match:
            project = get_project(project_match.group(1))
            self.respond(200, project) if project else self.respond(404, {"error": "Course not found"})
            return
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})", path)
        if match:
            status = get_job(match.group(1))
            self.respond(200, status) if status else self.respond(404, {"error": "Job not found"})
            return
        watch = re.fullmatch(r"/watch/([a-f0-9]{32})", path)
        if watch:
            job = get_job(watch.group(1))
            if not job or job.get("kind") != "batch" or job.get("state") != "complete":
                self.send_error(404, "Language viewer is not ready")
                return
            self.path = "/viewer.html"
            super().do_GET()
            return
        media = re.fullmatch(r"/media/([a-f0-9]{32})/(course\.mp4|subtitles\.srt|captions\.vtt|voice\.mp3)", path)
        if media:
            file = OUTPUT / media.group(1) / media.group(2)
            if not file.is_file():
                self.send_error(404)
                return
            mime = ("video/mp4" if file.suffix == ".mp4" else "audio/mpeg" if file.suffix == ".mp3"
                    else "text/vtt; charset=utf-8" if file.suffix == ".vtt" else "text/plain; charset=utf-8")
            size = file.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get("Range", "")
            if requested:
                match_range = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
                if not match_range:
                    self.send_error(416)
                    return
                start = int(match_range.group(1))
                end = min(size - 1, int(match_range.group(2))) if match_range.group(2) else size - 1
                if start >= size or end < start:
                    self.send_error(416)
                    return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with file.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining and (chunk := stream.read(min(1024 * 1024, remaining))):
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                # Browsers often cancel an old range request after a chapter seek.
                pass
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 8_000_000:
            self.respond(413, {"error": "Request is empty or too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            path = urlparse(self.path).path
            if path == "/api/upload":
                self.upload(payload)
            elif path == "/api/voice":
                self.voice(payload)
            elif path == "/api/render":
                self.render(payload)
            elif path == "/api/projects":
                self.respond(200, {"project": save_project(payload)})
            elif path == "/api/course-outline":
                self.respond(201, {"project": save_project(build_outline(payload))})
            elif path == "/api/render-batch":
                self.render_batch(payload)
            else:
                self.respond(404, {"error": "Unknown endpoint."})
        except FileNotFoundError as exc:
            self.respond(404, {"error": str(exc)})
        except RuntimeError as exc:
            self.respond(409, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            self.respond(400, {"error": str(exc)})
        except Exception as exc:
            self.respond(500, {"error": f"Operation failed: {exc}"})

    def upload(self, payload: dict) -> None:
        data = str(payload.get("data", ""))
        if not data.startswith("data:image/") or "," not in data:
            raise ValueError("Please select a PNG or JPEG image.")
        kind, encoded = data.split(",", 1)
        if kind not in {"data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"}:
            raise ValueError("Only PNG, JPEG and WebP images are supported.")
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 5_000_000:
            raise ValueError("Please use an image smaller than 5 MB.")
        image = Image.open(io.BytesIO(raw))
        image.verify()
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((2800, 2800), Image.Resampling.LANCZOS)
        name = uuid.uuid4().hex + ".jpg"
        image.save(UPLOADS / name, "JPEG", quality=90)
        self.respond(200, {"asset": name})

    def voice(self, payload: dict) -> None:
        language = str(payload.get("language", ""))
        voice = str(payload.get("voice", ""))
        text = str(payload.get("text", "")).strip()
        if not allowed_voice(language, voice) or not 1 <= len(text) <= 300:
            raise ValueError("Choose a voice and enter up to 300 characters to preview.")
        name = uuid.uuid4().hex
        folder = OUTPUT / name
        folder.mkdir(exist_ok=True)
        asyncio.run(synthesize(text, voice, folder / "voice.mp3"))
        self.respond(200, {"audio": f"/media/{name}/voice.mp3"})

    def render(self, payload: dict) -> None:
        from engine import clean_project
        project = clean_project(payload)
        job_id = uuid.uuid4().hex
        save_job(job_id, {"kind": "single", "state": "queued", "message": "Waiting for renderer"})

        def worker() -> None:
            def progress(message: str) -> None:
                save_job(job_id, {"kind": "single", "state": "rendering", "message": message})
            try:
                result = render_project(project, job_id, progress)
                save_job(job_id, {"kind": "single", "state": "complete", "message": "Video ready", **result})
            except Exception as exc:
                save_job(job_id, {"kind": "single", "state": "failed", "message": str(exc)})

        RENDER_QUEUE.submit(worker)
        self.respond(202, {"job": job_id})

    def render_batch(self, payload: dict) -> None:
        from engine import clean_project
        project_id = payload.get("project_id")
        course = get_project(project_id)
        if not course:
            raise FileNotFoundError("Save the course before rendering its languages.")
        versions = {}
        for language, draft in course["versions"].items():
            if draft["reviewed"]:
                versions[language] = clean_project({"title": draft["title"], "language": language,
                                                    "voice": draft["voice"], "scenes": draft["scenes"]})
        if not versions:
            raise ValueError("Mark at least one language script as reviewed before batch rendering.")
        job_id = uuid.uuid4().hex
        save_job(job_id, {"kind": "batch", "state": "queued", "message": "Waiting for renderer",
                          "project_id": project_id, "course_name": course["name"], "languages": list(versions), "results": {}})

        def worker() -> None:
            results = {}
            try:
                for index, (language, version) in enumerate(versions.items(), 1):
                    def progress(message: str, current=language) -> None:
                        save_job(job_id, {"kind": "batch", "state": "rendering",
                                          "message": f"{current} ({index}/{len(versions)}): {message}",
                                          "project_id": project_id, "course_name": course["name"],
                                          "languages": list(versions), "results": results})
                    output_id = uuid.uuid4().hex
                    results[language] = render_project(version, output_id, progress)
                    progress("Language video ready")
                save_job(job_id, {"kind": "batch", "state": "complete", "message": "All language videos ready",
                                  "project_id": project_id, "course_name": course["name"],
                                  "languages": list(versions), "results": results,
                                  "viewer": f"/watch/{job_id}"})
            except Exception as exc:
                save_job(job_id, {"kind": "batch", "state": "failed", "message": str(exc),
                                  "project_id": project_id, "course_name": course["name"],
                                  "languages": list(versions), "results": results})

        RENDER_QUEUE.submit(worker)
        self.respond(202, {"job": job_id})


if __name__ == "__main__":
    try:
        server = StudioServer(("127.0.0.1", 8765), Handler)
    except OSError:
        if "--open" in sys.argv:
            print("Studio may already be running at http://127.0.0.1:8765", flush=True)
            webbrowser.open("http://127.0.0.1:8765")
            sys.exit(0)
        raise
    mark_interrupted_jobs()
    print("Video Course Studio: http://127.0.0.1:8765", flush=True)
    if "--open" in sys.argv:
        threading.Timer(1, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
