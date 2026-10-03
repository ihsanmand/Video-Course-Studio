"""Fast persistence and HTTP workflow checks without calling the speech service."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
import course_outline
import engine
import studio_store


def version(language: str, reviewed: bool = True) -> dict:
    voices = {
        "en-US": "en-US-GuyNeural",
        "ur-PK": "ur-PK-AsadNeural",
    }
    return {
        "title": f"Sample training {language}",
        "voice": voices[language],
        "reviewed": reviewed,
        "scenes": [{
            "heading": "Find a client",
            "narration": "Explain the learner's need, then introduce the recommended process.",
            "points": ["Research", "Qualify", "Refer"],
            "asset": "",
            "visual_type": "flow",
        }],
    }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.projects = patch.object(studio_store, "PROJECTS", root / "projects")
        self.jobs = patch.object(studio_store, "JOBS", root / "jobs")
        self.output = patch.object(app, "OUTPUT", root / "output")
        for item in (self.projects, self.jobs, self.output):
            item.start()
        for path in (studio_store.PROJECTS, studio_store.JOBS, app.OUTPUT):
            path.mkdir()

    def tearDown(self):
        for item in (self.output, self.jobs, self.projects):
            item.stop()
        self.temp.cleanup()

    def test_draft_review_and_revision(self):
        draft = version("en-US", reviewed=False)
        draft["scenes"][0]["narration"] = ""
        saved = studio_store.save_project({"name": "Sample course", "versions": {"en-US": draft}})
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(saved["versions"]["en-US"]["scenes"][0]["chapter"], "Chapter 1")
        self.assertFalse(studio_store.get_project(saved["id"])["versions"]["en-US"]["reviewed"])
        self.assertEqual(len(studio_store.list_projects()), 1)
        with self.assertRaises(ValueError):
            studio_store.save_project({
                "id": saved["id"], "revision": 1, "name": "Sample course",
                "versions": {"en-US": {**draft, "reviewed": True}},
            })
        updated = studio_store.save_project({
            "id": saved["id"], "revision": 1, "name": "Sample course",
            "versions": {"en-US": version("en-US")},
        })
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(RuntimeError):
            studio_store.save_project({
                "id": saved["id"], "revision": 1, "name": "Old copy",
                "versions": {"en-US": version("en-US")},
            })

    def test_interrupted_job(self):
        job_id = "a" * 32
        studio_store.save_job(job_id, {"kind": "batch", "state": "rendering", "results": {}})
        studio_store.mark_interrupted_jobs()
        self.assertEqual(studio_store.get_job(job_id)["state"], "interrupted")

    def test_second_server_cannot_bind_same_port(self):
        first = app.StudioServer(("127.0.0.1", 0), app.Handler)
        try:
            with self.assertRaises(OSError):
                app.StudioServer(("127.0.0.1", first.server_port), app.Handler)
        finally:
            first.server_close()

    def test_chapter_limits_and_legacy_scenes(self):
        legacy = version("en-US")
        cleaned = engine.clean_project({"title": legacy["title"], "language": "en-US",
                                        "voice": legacy["voice"], "scenes": legacy["scenes"]})
        self.assertEqual(cleaned["scenes"][0]["chapter"], "Chapter 1")
        repeated = engine.clean_project({
            "title": "Two sections", "language": "en-US", "voice": legacy["voice"],
            "scenes": [{**legacy["scenes"][0], "chapter": "Practice", "chapter_start": True},
                       {**legacy["scenes"][0], "chapter": "Practice", "chapter_start": True}],
        })
        self.assertEqual([scene["chapter_start"] for scene in repeated["scenes"]], [True, True])
        many = [{**legacy["scenes"][0], "chapter": f"Chapter {index}"} for index in range(1, 25)]
        engine.clean_project({"title": "Full course", "language": "en-US",
                              "voice": legacy["voice"], "scenes": many})
        full = [{**legacy["scenes"][0], "chapter": f"Chapter {index // 10 + 1}",
                 "chapter_start": index % 10 == 0} for index in range(120)]
        self.assertEqual(len(engine.clean_project({"title": "Twelve chapters", "language": "en-US",
                                                   "voice": legacy["voice"], "scenes": full})["scenes"]), 120)
        with self.assertRaisesRegex(ValueError, "at most 24 chapters"):
            engine.clean_project({"title": "Too many", "language": "en-US",
                                  "voice": legacy["voice"],
                                  "scenes": many + [{**many[0], "chapter": "Chapter 25"}]})
        with self.assertRaisesRegex(ValueError, "1–120 scenes"):
            engine.clean_project({"title": "Too long", "language": "en-US",
                                  "voice": legacy["voice"], "scenes": many * 6})

    def test_new_topic_outline_is_saved_but_not_render_ready(self):
        brief = {"topic": "Cybersecurity basics", "audience": "Small business owners",
                 "goal": "Protect accounts", "language": "en-US",
                 "sections": ["Passwords and MFA", "Phishing messages"]}
        outline = course_outline.build_outline(brief)
        saved = studio_store.save_project(outline)
        scenes = saved["versions"]["en-US"]["scenes"]
        self.assertEqual(len(scenes), 10)
        self.assertEqual(sum(scene["chapter_start"] for scene in scenes), 4)
        self.assertTrue(all(not scene["narration"] for scene in scenes))
        self.assertFalse(saved["versions"]["en-US"]["reviewed"])
        self.assertEqual(studio_store.get_project(saved["id"])["name"], brief["topic"])
        for language in engine.LANGUAGES:
            localized = course_outline.build_outline({**brief, "language": language, "sections": []})
            self.assertEqual(len(localized["versions"][language]["scenes"]), 13)
        with self.assertRaises(ValueError):
            course_outline.build_outline({**brief, "sections": ["long lesson"] * 9})
        with self.assertRaises(ValueError):
            studio_store.save_project({"id": saved["id"], "revision": 1, "name": saved["name"],
                "versions": {"en-US": {**saved["versions"]["en-US"], "reviewed": True}}})

    def test_batch_http_and_viewer(self):
        def fake_render(project, output_id, progress):
            progress("Making sample")
            folder = app.OUTPUT / output_id
            folder.mkdir()
            (folder / "course.mp4").write_bytes(b"sample-mp4")
            (folder / "subtitles.srt").write_text("sample subtitles", encoding="utf-8")
            (folder / "captions.vtt").write_text("WEBVTT\n", encoding="utf-8")
            return {
                "video": f"/media/{output_id}/course.mp4",
                "subtitles": f"/media/{output_id}/subtitles.srt",
                "captions": f"/media/{output_id}/captions.vtt",
                "seconds": 3.0,
            }

        with patch.object(app, "render_project", side_effect=fake_render):
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"

            def request(path, payload=None, headers=None):
                body = json.dumps(payload).encode("utf-8") if payload is not None else None
                req = Request(base + path, data=body, headers=headers or {})
                if body is not None:
                    req.add_header("Content-Type", "application/json")
                return urlopen(req, timeout=5)

            try:
                with request("/api/projects", {
                    "name": "Sample course",
                    "versions": {"en-US": version("en-US"), "ur-PK": version("ur-PK")},
                }) as response:
                    saved = json.load(response)["project"]
                with request("/api/render-batch", {"project_id": saved["id"]}) as response:
                    job_id = json.load(response)["job"]
                deadline = time.monotonic() + 5
                while True:
                    with request(f"/api/jobs/{job_id}") as response:
                        status = json.load(response)
                    if status["state"] in {"complete", "failed"}:
                        break
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.05)
                self.assertEqual(status["state"], "complete", status.get("message"))
                self.assertEqual(set(status["results"]), {"en-US", "ur-PK"})
                self.assertEqual(status["viewer"], f"/watch/{job_id}")
                with request("/api/renders") as response:
                    history = json.load(response)["renders"]
                self.assertEqual(history[0]["viewer"], status["viewer"])
                with request(status["viewer"]) as response:
                    self.assertIn(b"viewer.js", response.read())
                with request(status["results"]["ur-PK"]["captions"]) as response:
                    self.assertEqual(response.headers.get_content_type(), "text/vtt")
                    self.assertEqual(response.read().replace(b"\r\n", b"\n"), b"WEBVTT\n")
                with request(status["results"]["en-US"]["video"], headers={"Range": "bytes=0-5"}) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.read(), b"sample")
                with self.assertRaises(HTTPError) as error:
                    request("/watch/" + "b" * 32)
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
