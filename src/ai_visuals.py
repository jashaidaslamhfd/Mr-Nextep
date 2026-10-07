from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_MODEL = "gemini-3.1-flash-image"
DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

def enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip()) and os.getenv("AI_VISUALS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}

def generate_scene_image(scene: dict[str, str], scene_index: int, destination: Path) -> Path:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    model = os.getenv("GEMINI_IMAGE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    endpoint = os.getenv("GEMINI_IMAGE_ENDPOINT", DEFAULT_ENDPOINT).strip() or DEFAULT_ENDPOINT
    visual = str(scene.get("visual_prompt") or scene.get("visual_query") or "").strip()
    narration = str(scene.get("narration") or "").strip()
    prompt = (
        "Create an original cinematic visual for a vertical YouTube Short. "
        "Show the concrete subject or action from this scene, not generic stock footage. "
        "Dark-science and AI-psychology visual identity, photorealistic, premium film still, "
        "realistic anatomy and materials, dramatic natural lighting, subtle depth of field. "
        "Scene " + str(scene_index) + ": " + visual + ". Narration context: " + narration + ". "
        "No text, logos, watermark, UI, subtitles, collage or split screen. "
        "Compose for 9:16 mobile viewing with the important subject in the center safe area."
    )
    payload = {"model": model, "input": prompt, "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "9:16", "image_size": os.getenv("GEMINI_IMAGE_SIZE", "1K")}}
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"x-goog-api-key": key, "Content-Type": "application/json", "User-Agent": "Mr-Nextep/2.0"}, method="POST")
    with urlopen(request, timeout=int(os.getenv("GEMINI_IMAGE_TIMEOUT_SECONDS", "120"))) as response:
        data = json.loads(response.read().decode("utf-8"))
    image_data = ((data.get("output_image") or {}).get("data") or "").strip()
    if not image_data:
        for item in data.get("output", []) or []:
            if isinstance(item, dict):
                candidate = item.get("data") or (item.get("image") or {}).get("data")
                if candidate:
                    image_data = str(candidate).strip()
                    break
    if not image_data:
        raise RuntimeError("Gemini returned no image data")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(base64.b64decode(image_data))
    if destination.stat().st_size < 10000:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Generated image is unexpectedly small")
    return destination
