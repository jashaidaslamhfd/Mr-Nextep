from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://commons.wikimedia.org/w/api.php"
ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"


def _safe_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:70] or "science"


def download_clip(query: str, destination: Path) -> Path:
    """Download a real Commons video and fail loudly if none is available."""
    terms = f"{query} science nature"
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{terms} filetype:video", "gsrnamespace": 6,
        "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|mime|size",
    }
    headers = {"User-Agent": "Mr-Nextep/1.0 (stock-video-renderer; contact via GitHub)"}
    response = requests.get(API, params=params, timeout=30, headers=headers)
    candidates = []
    if response.ok:
        pages = response.json().get("query", {}).get("pages", {}).values()
        candidates = [page.get("imageinfo", [{}])[0].get("url") for page in pages if page.get("imageinfo") and page["imageinfo"][0].get("mime", "").startswith("video/")]
    if not candidates:
        search = requests.get(ARCHIVE_SEARCH, params={"q": f"mediatype:movies AND collection:opensource_movies AND ({_safe_name(query)} OR science OR nature)", "fl[]": "identifier", "rows": 8, "output": "json"}, timeout=30, headers=headers)
        search.raise_for_status()
        for doc in search.json().get("response", {}).get("docs", []):
            metadata = requests.get(f"https://archive.org/metadata/{doc['identifier']}", timeout=30, headers=headers)
            if not metadata.ok:
                continue
            for item in metadata.json().get("files", []):
                name = item.get("name", "")
                if name.lower().endswith((".mp4", ".webm", ".ogv")) and int(item.get("size", 0) or 0) < 200_000_000:
                    candidates.append(f"https://archive.org/download/{doc['identifier']}/{quote(name)}")
                    break
            if candidates:
                break
    if not candidates:
        raise RuntimeError(f"No moving video clip found for: {query}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = destination.with_suffix(".source")
    with requests.get(candidates[0], stream=True, timeout=90, headers={"User-Agent": "Mr-Nextep/1.0"}) as download:
        download.raise_for_status()
        with raw.open("wb") as handle:
            for chunk in download.iter_content(1024 * 256):
                if chunk:
                    handle.write(chunk)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(raw), "-t", "8", "-an", "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(destination),
    ], check=True, capture_output=True)
    raw.unlink(missing_ok=True)
    return destination


def query_for_scene(scene: dict[str, str]) -> str:
    return scene.get("visual_query") or scene.get("caption", "dark science")
