"""Atomic local storage for course drafts and render jobs."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from engine import LANGUAGES, MAX_CHAPTERS, MAX_SCENES, UPLOADS, VISUAL_TYPES, allowed_voice, clean_project


ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / "projects"
JOBS = ROOT / "jobs"
PROJECTS.mkdir(exist_ok=True)
JOBS.mkdir(exist_ok=True)
LOCK = threading.RLock()
ID_RE = re.compile(r"[a-f0-9]{32}\Z")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_id(value: str) -> bool:
    return isinstance(value, str) and bool(ID_RE.fullmatch(value))


def write_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_draft(language: str, raw: dict) -> dict:
    if language not in LANGUAGES or not isinstance(raw, dict):
        raise ValueError("A course version has an invalid language or format.")
    title = str(raw.get("title", "")).strip()
    voice = str(raw.get("voice", ""))
    if len(title) > 100 or not allowed_voice(language, voice):
        raise ValueError(f"{language}: enter a title of up to 100 characters and choose a matching voice.")
    scenes = raw.get("scenes", [])
    if not isinstance(scenes, list) or len(scenes) > MAX_SCENES:
        raise ValueError(f"{language}: keep at most {MAX_SCENES} scenes.")
    cleaned_scenes = []
    chapter_count = 0
    previous_chapter = None
    for i, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ValueError(f"{language} scene {i}: invalid scene.")
        heading = str(scene.get("heading", "")).strip()
        chapter = str(scene.get("chapter", "Chapter 1")).strip()
        chapter_start = i == 1 or scene.get("chapter_start") is True or chapter != previous_chapter
        if chapter_start:
            chapter_count += 1
        previous_chapter = chapter
        if chapter_count > MAX_CHAPTERS or len(chapter) > 90:
            raise ValueError(f"{language}: use at most {MAX_CHAPTERS} chapters with short titles.")
        narration = str(scene.get("narration", "")).strip()
        points = scene.get("points", [])
        asset = str(scene.get("asset", "")).strip()
        visual_type = str(scene.get("visual_type", "diagram"))
        if len(heading) > 90 or len(narration) > 1200:
            raise ValueError(f"{language} scene {i}: heading or narration is too long.")
        if not isinstance(points, list) or len(points) > 5:
            raise ValueError(f"{language} scene {i}: use at most five visual points.")
        points = [str(point).strip() for point in points]
        if any(len(point) > 85 for point in points):
            raise ValueError(f"{language} scene {i}: a visual point is too long.")
        if visual_type not in VISUAL_TYPES:
            raise ValueError(f"{language} scene {i}: invalid visual template.")
        if asset and (not re.fullmatch(r"[a-f0-9]{32}\.jpg", asset) or not (UPLOADS / asset).is_file()):
            raise ValueError(f"{language} scene {i}: uploaded image is missing.")
        production_note = str(scene.get("production_note", "")).strip()
        if len(production_note) > 300:
            raise ValueError(f"{language} scene {i}: visual production note is too long.")
        cleaned_scenes.append({"chapter": chapter, "chapter_start": chapter_start,
                               "heading": heading, "narration": narration, "points": points,
                               "asset": asset, "visual_type": visual_type,
                               "production_note": production_note})
    draft = {"title": title, "voice": voice, "scenes": cleaned_scenes,
             "reviewed": raw.get("reviewed") is True}
    if draft["reviewed"]:
        clean_project({"title": title, "language": language, "voice": voice, "scenes": cleaned_scenes})
    return draft


def clean_course(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Course data must be an object.")
    name = str(raw.get("name", "")).strip()
    if not 1 <= len(name) <= 100:
        raise ValueError("Course name must be 1–100 characters.")
    versions = raw.get("versions", {})
    if not isinstance(versions, dict) or not versions:
        raise ValueError("Save at least one language version.")
    if set(versions) - set(LANGUAGES):
        raise ValueError("Course contains an unsupported language.")
    return {"name": name, "versions": {lang: clean_draft(lang, draft) for lang, draft in versions.items()}}


def save_project(raw: dict) -> dict:
    course = clean_course(raw)
    project_id = raw.get("id")
    with LOCK:
        if project_id is None:
            project_id = uuid.uuid4().hex
            created = now()
            revision = 1
        else:
            if not valid_id(project_id):
                raise ValueError("Invalid course ID.")
            path = PROJECTS / f"{project_id}.json"
            if not path.is_file():
                raise FileNotFoundError("Course was not found.")
            previous = read_json(path)
            expected = raw.get("revision")
            if not isinstance(expected, int) or expected != previous["revision"]:
                raise RuntimeError("This course changed elsewhere. Reload it before saving again.")
            created = previous["created_at"]
            revision = previous["revision"] + 1
        record = {"id": project_id, "revision": revision, "created_at": created,
                  "updated_at": now(), **course}
        write_json(PROJECTS / f"{project_id}.json", record)
        return record


def get_project(project_id: str) -> dict | None:
    if not valid_id(project_id):
        return None
    path = PROJECTS / f"{project_id}.json"
    with LOCK:
        return read_json(path) if path.is_file() else None


def list_projects() -> list[dict]:
    with LOCK:
        records = [read_json(path) for path in PROJECTS.glob("*.json")]
    records.sort(key=lambda item: item["updated_at"], reverse=True)
    return [{"id": item["id"], "name": item["name"], "revision": item["revision"],
             "updated_at": item["updated_at"],
             "reviewed_languages": [code for code, draft in item["versions"].items() if draft["reviewed"]]}
            for item in records]


def save_job(job_id: str, status: dict) -> None:
    if not valid_id(job_id):
        raise ValueError("Invalid job ID.")
    with LOCK:
        write_json(JOBS / f"{job_id}.json", {"id": job_id, "updated_at": now(), **status})


def get_job(job_id: str) -> dict | None:
    if not valid_id(job_id):
        return None
    path = JOBS / f"{job_id}.json"
    with LOCK:
        return read_json(path) if path.is_file() else None


def list_renders() -> list[dict]:
    with LOCK:
        records = [read_json(path) for path in JOBS.glob("*.json")]
    records = [job for job in records if job.get("kind") == "batch"]
    records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return [{
        "id": job["id"], "state": job.get("state", "unknown"),
        "course_name": job.get("course_name", "Course"),
        "languages": job.get("languages", []),
        "updated_at": job.get("updated_at", ""),
        "viewer": job.get("viewer") if job.get("state") == "complete" else None,
        "message": job.get("message", ""),
    } for job in records[:20]]


def mark_interrupted_jobs() -> None:
    with LOCK:
        for path in JOBS.glob("*.json"):
            job = read_json(path)
            if job.get("state") in {"queued", "rendering"}:
                job.update(state="interrupted", message="Rendering stopped when Studio closed. Start a new render.",
                           updated_at=now())
                write_json(path, job)
