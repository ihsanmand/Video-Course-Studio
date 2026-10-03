"""Render a short real sample in every supported language."""

import uuid
import sys
import subprocess
from pathlib import Path

from engine import FFMPEG, LANGUAGES, OUTPUT, clean_project, render_project, run_ffmpeg


SAMPLES = {
    "en-US": ("Find clients", "Research the business before contacting the client."),
    "ur-PK": ("صحیح کلائنٹ تلاش کریں", "کلائنٹ سے بات کرنے سے پہلے کاروبار کے بارے میں تحقیق کریں۔"),
    "de-DE": ("Passende Kunden finden", "Prüfen Sie das Unternehmen, bevor Sie den Kunden kontaktieren."),
    "ar-SA": ("ابحث عن العملاء", "ابحث عن الشركة قبل التواصل مع العميل."),
}
TEMPLATES = {"en-US": "flow", "ur-PK": "checklist", "de-DE": "comparison", "ar-SA": "diagram"}


if "--assembly-only" not in sys.argv:
    for code, (heading, narration) in SAMPLES.items():
        voice = LANGUAGES[code]["voices"][0]["id"]
        project = clean_project({"title": "Language smoke test", "language": code, "voice": voice,
                                 "scenes": [{"heading": heading, "narration": narration,
                                             "points": [heading], "visual_type": TEMPLATES[code]}]})
        job_id = uuid.uuid4().hex
        result = render_project(project, job_id, lambda message: print(code, message, flush=True))
        folder = OUTPUT / job_id
        run_ffmpeg(["-ss", "1", "-i", "course.mp4", "-frames:v", "1", "frame.jpg"], folder)
        assert (folder / "frame.jpg").stat().st_size > 5000
        print(code, result["seconds"], folder / "frame.jpg", flush=True)

project = clean_project({
    "title": "Three-scene assembly test", "language": "en-US", "voice": "en-US-GuyNeural",
    "scenes": [
        {"chapter": "Find", "heading": "Research", "narration": "Choose a relevant business to research.", "points": ["Find a business"], "visual_type": "flow"},
        {"chapter": "Find", "heading": "Qualify", "narration": "Check whether the business has a real need.", "points": ["Review the need"], "visual_type": "checklist"},
        {"chapter": "Apply", "heading": "Apply", "narration": "Confirm the next action and record the learner's progress.", "points": ["Choose the next action"], "visual_type": "comparison"},
    ],
})
job_id = uuid.uuid4().hex
result = render_project(project, job_id, lambda message: print("assembly", message, flush=True))
assert result["seconds"] > 8
assert (OUTPUT / job_id / "course.mp4").stat().st_size > 100_000
assert (OUTPUT / job_id / "subtitles.srt").read_text(encoding="utf-8-sig").count(" --> ") >= 3
assert (OUTPUT / job_id / "captions.vtt").read_text(encoding="utf-8").startswith("WEBVTT\n\n")
assert [chapter["title"] for chapter in result["chapters"]] == ["Find", "Refer"]
probe = subprocess.run([FFMPEG, "-hide_banner", "-i", str(OUTPUT / job_id / "course.mp4")],
                       capture_output=True, text=True)
assert probe.stderr.count("Chapter #0:") >= 2, probe.stderr[-1500:]
print("assembly", result, flush=True)
