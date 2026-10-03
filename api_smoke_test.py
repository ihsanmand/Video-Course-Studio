"""Check the running local API, including scene-image upload."""

import base64
import io
import json
import urllib.request

from PIL import Image

from engine import OUTPUT, UPLOADS, background, clean_project


BASE = "http://127.0.0.1:8765"
languages = json.load(urllib.request.urlopen(BASE + "/api/languages"))["languages"]
assert set(languages) == {"en-US", "ur-PK", "de-DE", "ar-SA"}

image = Image.new("RGB", (300, 200), "#228d83")
memory = io.BytesIO()
image.save(memory, "JPEG")
data = "data:image/jpeg;base64," + base64.b64encode(memory.getvalue()).decode("ascii")
request = urllib.request.Request(BASE + "/api/upload", data=json.dumps({"data": data}).encode(),
                                 headers={"Content-Type": "application/json"})
asset = json.load(urllib.request.urlopen(request))["asset"]
assert (UPLOADS / asset).is_file()

project = clean_project({"title": "Photo check", "language": "en-US", "voice": "en-US-GuyNeural",
                         "scenes": [{"heading": "Photo test", "narration": "Testing an uploaded image.",
                                     "points": [], "visual_type": "photo", "asset": asset}]})
frame = OUTPUT / "api_photo_smoke.jpg"
background(frame, 1, 1, project["scenes"][0]["asset"], "photo")
assert frame.stat().st_size > 5000
print("API_OK", asset, frame)
