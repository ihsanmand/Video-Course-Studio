"""Small, reusable course-video renderer for the local Studio prototype."""

from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter


HERE = Path(__file__).resolve().parent
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
OUTPUT = HERE / "output"
UPLOADS = HERE / "uploads"
OUTPUT.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)
VISUAL_TYPES = {"diagram", "flow", "checklist", "comparison", "photo"}
MAX_CHAPTERS = 24
MAX_SCENES = 120

LANGUAGES = {
    "en-US": {
        "label": "English (US)", "native": "English", "direction": "ltr",
        "font": "Segoe UI", "voices": [
            {"id": "en-US-GuyNeural", "label": "Guy · male"},
            {"id": "en-US-AriaNeural", "label": "Aria · female"},
        ],
    },
    "ur-PK": {
        "label": "Urdu (Pakistan)", "native": "اردو", "direction": "rtl",
        "font": "Arabic Typesetting", "voices": [
            {"id": "ur-PK-AsadNeural", "label": "Asad · male"},
            {"id": "ur-IN-SalmanNeural", "label": "Salman · male (approved course voice)"},
            {"id": "ur-PK-UzmaNeural", "label": "Uzma · female"},
        ],
    },
    "de-DE": {
        "label": "German (Germany)", "native": "Deutsch", "direction": "ltr",
        "font": "Segoe UI", "voices": [
            {"id": "de-DE-ConradNeural", "label": "Conrad · male"},
            {"id": "de-DE-KatjaNeural", "label": "Katja · female"},
        ],
    },
    "ar-SA": {
        "label": "Arabic (Saudi Arabia)", "native": "العربية", "direction": "rtl",
        "font": "Arabic Typesetting", "voices": [
            {"id": "ar-SA-HamedNeural", "label": "Hamed · male"},
            {"id": "ar-SA-ZariyahNeural", "label": "Zariyah · female"},
        ],
    },
}


def allowed_voice(language: str, voice: str) -> bool:
    return language in LANGUAGES and voice in {v["id"] for v in LANGUAGES[language]["voices"]}


def clean_project(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Project data must be an object.")
    language = str(raw.get("language", ""))
    voice = str(raw.get("voice", ""))
    if not allowed_voice(language, voice):
        raise ValueError("Choose a listed language and matching voice.")
    title = str(raw.get("title", "")).strip()
    if not 1 <= len(title) <= 100:
        raise ValueError("Project title must be 1–100 characters.")
    scenes = raw.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise ValueError(f"Use 1–{MAX_SCENES} scenes per video.")
    cleaned = []
    chapter_count = 0
    previous_chapter = None
    for i, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {i} must be an object.")
        heading = str(scene.get("heading", "")).strip()
        chapter = str(scene.get("chapter", "Chapter 1")).strip()
        narration = str(scene.get("narration", "")).strip()
        points = scene.get("points", [])
        asset = str(scene.get("asset", "")).strip()
        visual_type = str(scene.get("visual_type", "diagram"))
        if not 1 <= len(heading) <= 90:
            raise ValueError(f"Scene {i}: heading must be 1–90 characters.")
        if not 1 <= len(chapter) <= 90:
            raise ValueError(f"Scene {i}: chapter title must be 1–90 characters.")
        chapter_start = i == 1 or scene.get("chapter_start") is True or chapter != previous_chapter
        if chapter_start:
            chapter_count += 1
        previous_chapter = chapter
        if chapter_count > MAX_CHAPTERS:
            raise ValueError(f"Use at most {MAX_CHAPTERS} chapters per video.")
        if not 1 <= len(narration) <= 1200:
            raise ValueError(f"Scene {i}: narration must be 1–1200 characters.")
        if not isinstance(points, list) or len(points) > 5:
            raise ValueError(f"Scene {i}: use up to five visual points.")
        points = [str(p).strip() for p in points if str(p).strip()]
        if any(len(p) > 85 for p in points):
            raise ValueError(f"Scene {i}: a visual point exceeds 85 characters.")
        if asset and not re.fullmatch(r"[a-f0-9]{32}\.jpg", asset):
            raise ValueError(f"Scene {i}: invalid image reference.")
        if asset and not (UPLOADS / asset).is_file():
            raise ValueError(f"Scene {i}: image was not found.")
        if visual_type not in VISUAL_TYPES:
            raise ValueError(f"Scene {i}: choose a listed visual template.")
        if visual_type == "photo" and not asset:
            raise ValueError(f"Scene {i}: upload an image for the photo template.")
        production_note = str(scene.get("production_note", "")).strip()
        if len(production_note) > 300:
            raise ValueError(f"Scene {i}: visual production note exceeds 300 characters.")
        cleaned.append({"chapter": chapter, "chapter_start": chapter_start,
                        "heading": heading, "narration": narration, "points": points,
                        "asset": asset, "visual_type": visual_type,
                        "production_note": production_note})
    return {"title": title, "language": language, "voice": voice, "scenes": cleaned}


async def synthesize(text: str, voice: str, dest: Path) -> list[dict]:
    cues = []
    part = dest.with_suffix(".part")
    with part.open("wb") as stream:
        async for item in edge_tts.Communicate(text, voice, rate="+0%", boundary="SentenceBoundary").stream():
            if item["type"] == "audio":
                stream.write(item["data"])
            elif item["type"] == "SentenceBoundary":
                cues.append({"text": item["text"], "offset": item["offset"], "duration": item["duration"]})
    if not part.exists() or part.stat().st_size < 1000:
        raise RuntimeError("The voice provider returned no usable audio.")
    part.replace(dest)
    return cues


def run_ffmpeg(args: list[str], cwd: Path) -> None:
    result = subprocess.run([FFMPEG, "-hide_banner", "-y", "-v", "error", *args], cwd=cwd,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-1800:] or "Video rendering failed.")


def audio_seconds(mp3: Path, wav: Path) -> float:
    run_ffmpeg(["-i", mp3.name, "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", wav.name], mp3.parent)
    with wave.open(str(wav), "rb") as sound:
        return sound.getnframes() / sound.getframerate()


def background(dest: Path, scene_no: int, total: int, asset: str, visual_type: str) -> None:
    w, h = 1920, 1080
    im = Image.new("RGB", (w, h), "#0b1b26")
    pixels = im.load()
    for y in range(h):
        t = y / h
        color = (round(9 + 10 * t), round(25 + 15 * t), round(36 + 15 * t))
        for x in range(w):
            pixels[x, y] = color
    d = ImageDraw.Draw(im)
    for x in range(70, w, 110):
        d.line((x, 130, x, 1010), fill="#17313e", width=1)
    for y in range(130, 1010, 110):
        d.line((70, y, 1850, y), fill="#17313e", width=1)
    d.rounded_rectangle((76, 57, 720, 111), 16, fill="#102d38")
    d.rectangle((76, 1020, 1844, 1027), fill="#234454")
    progress = int(1768 * scene_no / total)
    d.rectangle((76, 1020, 76 + progress, 1027), fill="#51d6bd")
    d.rounded_rectangle((1035, 252, 1840, 918), 32, fill="#183848", outline="#345a67", width=3)
    if asset:
        photo = Image.open(UPLOADS / asset).convert("RGB")
        ratio = max(760 / photo.width, 622 / photo.height)
        resized = photo.resize((math.ceil(photo.width * ratio), math.ceil(photo.height * ratio)), Image.Resampling.LANCZOS)
        crop = resized.crop(((resized.width - 760) // 2, (resized.height - 622) // 2,
                             (resized.width + 760) // 2, (resized.height + 622) // 2))
        mask = Image.new("L", (760, 622), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 759, 621), 24, fill=255)
        im.paste(crop, (1058, 274), mask)
    elif visual_type == "flow":
        for i, y in enumerate((330, 466, 602, 738), 1):
            d.rounded_rectangle((1115, y, 1760, y + 86), 17, fill="#25505a", outline="#5ddcc8", width=3)
            d.ellipse((1140, y + 16, 1196, y + 72), fill="#eec780")
            d.line((1240, y + 43, 1680, y + 43), fill="#70b9b1", width=7)
            if i < 4:
                d.line((1436, y + 91, 1436, y + 122), fill="#eec780", width=6)
                d.polygon(((1423, y + 117), (1449, y + 117), (1436, y + 136)), fill="#eec780")
    elif visual_type == "checklist":
        for i, y in enumerate((325, 458, 591, 724), 1):
            d.rounded_rectangle((1110, y, 1765, y + 95), 17, fill="#20444e", outline="#3e7880", width=2)
            d.rounded_rectangle((1141, y + 23, 1190, y + 72), 11, fill="#54dac4")
            d.line((1152, y + 47, 1163, y + 58, 1180, y + 36), fill="#0b2730", width=7, joint="curve")
            d.rounded_rectangle((1232, y + 31, 1700 - i * 48, y + 48), 8, fill="#568c93")
            d.rounded_rectangle((1232, y + 60, 1510 + i * 24, y + 71), 6, fill="#3c707a")
    elif visual_type == "comparison":
        d.rounded_rectangle((1090, 300, 1405, 864), 25, fill="#49353c", outline="#b37070", width=3)
        d.rounded_rectangle((1470, 300, 1785, 864), 25, fill="#194b48", outline="#54dac4", width=3)
        for x, color in ((1248, "#f1a1a0"), (1628, "#8de8d7")):
            d.ellipse((x - 69, 362, x + 69, 500), fill=color)
        d.line((1195, 660, 1315, 730), fill="#e89791", width=13)
        d.line((1315, 660, 1195, 730), fill="#e89791", width=13)
        d.line((1576, 704, 1610, 735, 1674, 661), fill="#8de8d7", width=14, joint="curve")
        d.rounded_rectangle((1130, 780, 1365, 803), 9, fill="#925e63")
        d.rounded_rectangle((1510, 780, 1745, 803), 9, fill="#52aa9a")
    else:
        # Editable built-in illustration for scenes without an uploaded photo.
        d.ellipse((1190, 360, 1680, 850), fill="#214b56", outline="#4dd3bb", width=5)
        d.ellipse((1325, 495, 1545, 715), fill="#48bfae")
        for x, y in ((1190, 400), (1690, 510), (1160, 770), (1610, 865)):
            d.ellipse((x, y, x + 42, y + 42), fill="#edc67e")
        d.line((1265, 475, 1435, 605, 1660, 552), fill="#94e8d8", width=6, joint="curve")
        d.line((1210, 792, 1435, 605, 1633, 880), fill="#94e8d8", width=6, joint="curve")
    im.save(dest, quality=92)


def ass_time(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    hours, rem = divmod(centis, 360000)
    mins, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{mins:02d}:{secs:02d}.{cs:02d}"


def srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rem = divmod(millis, 3600000)
    mins, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def ffmetadata_escape(value: str) -> str:
    return re.sub(r"([\\;#=])", r"\\\1", value).replace("\n", " ")


def ass_escape(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", "(").replace("}", ")").replace("\n", r"\N")


def subtitle_cues(text: str, edge_cues: list[dict], duration: float) -> list[tuple[float, float, str]]:
    result = []
    for cue in edge_cues:
        start = max(0.0, cue["offset"] / 10_000_000)
        end = min(duration, (cue["offset"] + cue["duration"]) / 10_000_000 + 0.15)
        if cue["text"].strip() and end > start:
            result.append((start, end, cue["text"].strip()))
    if not result:
        result = [(0.0, duration, text)]
    return result


def write_ass(path: Path, language: str, scene: dict, cues: list[tuple[float, float, str]], duration: float,
              index: int, total: int) -> None:
    rtl = LANGUAGES[language]["direction"] == "rtl"
    font = LANGUAGES[language]["font"]
    title_pos = r"\an9\pos(980,205)" if rtl else r"\an7\pos(137,205)"
    chapter_pos = r"\an9\pos(980,135)" if rtl else r"\an7\pos(137,135)"
    body_pos = r"\an9\pos(980,{y})" if rtl else r"\an7\pos(138,{y})"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Title,{font},60,&H00F6FAFB,&H00F6FAFB,&H00182732,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1",
        f"Style: Chapter,{font},30,&H00A9E5D9,&H00A9E5D9,&H00182732,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1",
        f"Style: Body,{font},43,&H00DDECEB,&H00DDECEB,&H00182732,&H00000000,0,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1",
        f"Style: Caption,{font},43,&H00FFFFFF,&H00FFFFFF,&H000A1520,&H000A1520,0,0,0,0,100,100,0,0,1,2,1,2,85,85,60,1",
        "Style: Label,Segoe UI,26,&H00A9E5D9,&H00A9E5D9,&H00182732,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    end = ass_time(duration)
    lines.append(f"Dialogue: 0,0:00:00.00,{end},Label,,0,0,0,,{{\\an7\\pos(100,71)}}VIDEO COURSE STUDIO    |    {index:02d} / {total:02d}")
    lines.append(f"Dialogue: 0,0:00:00.15,{end},Chapter,,0,0,0,,{{{chapter_pos}\\fad(250,0)}}{ass_escape(scene['chapter'])}")
    lines.append(f"Dialogue: 0,0:00:00.20,{end},Title,,0,0,0,,{{{title_pos}\\fad(300,0)}}{ass_escape(scene['heading'])}")
    for i, point in enumerate(scene["points"]):
        pos = body_pos.replace("{y}", str(370 + i * 112))
        label = ass_escape(point)
        appear = min(duration - 0.25, 0.7 + i * max(0.45, (duration - 1.4) / max(1, len(scene['points']))))
        lines.append(f"Dialogue: 0,{ass_time(appear)},{end},Body,,0,0,0,,{{{pos}\\fad(250,0)}}{label}")
    for start, stop, caption in cues:
        # A dark translucent caption panel improves readability over photos.
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(stop)},Caption,,0,0,0,,{ass_escape(caption)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def render_project(project: dict, job_id: str, progress) -> dict:
    project = clean_project(project)
    folder = OUTPUT / job_id
    folder.mkdir(exist_ok=True)
    (folder / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    scene_files = []
    srt_events = []
    chapter_marks = []
    elapsed = 0.0
    for i, scene in enumerate(project["scenes"], 1):
        if scene["chapter_start"]:
            chapter_marks.append({"title": scene["chapter"], "start": elapsed})
        progress(f"Scene {i}/{len(project['scenes'])}: generating narration")
        mp3 = folder / f"scene_{i:02d}.mp3"
        cues = asyncio.run(synthesize(scene["narration"], project["voice"], mp3))
        wav = folder / f"scene_{i:02d}.wav"
        duration = audio_seconds(mp3, wav) + 0.8
        visual = folder / f"scene_{i:02d}.jpg"
        background(visual, i, len(project["scenes"]), scene["asset"], scene["visual_type"])
        scene_cues = subtitle_cues(scene["narration"], cues, duration)
        for start, stop, text in scene_cues:
            srt_events.append((elapsed + start, elapsed + stop, text))
        ass = folder / f"scene_{i:02d}.ass"
        write_ass(ass, project["language"], scene, scene_cues, duration, i, len(project["scenes"]))
        progress(f"Scene {i}/{len(project['scenes'])}: rendering video")
        clip = folder / f"scene_{i:02d}.mp4"
        run_ffmpeg([
            "-loop", "1", "-framerate", "24", "-i", visual.name,
            "-i", wav.name,
            "-vf", f"ass={ass.name},fade=t=in:st=0:d=0.25,format=yuv420p",
            "-map", "0:v", "-map", "1:a", "-t", str(duration),
            "-r", "24", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", clip.name,
        ], folder)
        scene_files.append(clip)
        elapsed += duration
    progress("Combining scenes")
    concat = folder / "scenes.ffconcat"
    concat.write_text("ffconcat version 1.0\n" + "\n".join(f"file '{p.name}'" for p in scene_files) + "\n", encoding="utf-8")
    final = folder / "course.mp4"
    metadata = [";FFMETADATA1"]
    for index, mark in enumerate(chapter_marks):
        end = chapter_marks[index + 1]["start"] if index + 1 < len(chapter_marks) else elapsed
        metadata.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(mark['start'] * 1000)}",
                         f"END={round(end * 1000)}", f"title={ffmetadata_escape(mark['title'])}"])
    (folder / "chapters.ffmeta").write_text("\n".join(metadata) + "\n", encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", concat.name,
                "-f", "ffmetadata", "-i", "chapters.ffmeta", "-map_metadata", "1", "-map_chapters", "1",
                "-c", "copy", "-movflags", "+faststart", final.name], folder)
    srt = folder / "subtitles.srt"
    srt.write_text("\n\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}" for i, (a, b, text) in enumerate(srt_events, 1)) + "\n", encoding="utf-8-sig")
    vtt = folder / "captions.vtt"
    vtt.write_text("WEBVTT\n\n" + "\n\n".join(
        f"{srt_time(a).replace(',', '.')} --> {srt_time(b).replace(',', '.')}\n{text}"
        for a, b, text in srt_events) + "\n", encoding="utf-8")
    return {"video": f"/media/{job_id}/course.mp4", "subtitles": f"/media/{job_id}/subtitles.srt",
            "captions": f"/media/{job_id}/captions.vtt", "seconds": round(elapsed, 1),
            "chapters": [{"title": item["title"], "start": round(item["start"], 1)} for item in chapter_marks]}
