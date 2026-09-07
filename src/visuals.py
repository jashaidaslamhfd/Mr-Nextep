from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote
import requests

API = "https://commons.wikimedia.org/w/api.php"
ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
MAX_CLIP_BYTES = 45_000_000
MAX_CANDIDATES = 14

def _safe_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:70] or "science"

def download_clip(query: str, destination: Path, avoid_hashes: set[str] | None = None) -> Path:
    """Download stock clip and apply cinematic grading, unsharp filter, and vignette."""
    terms = f"{query} dark mystery science"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{terms} filetype:video",
        "gsrnamespace": 6,
        "gsrlimit": 30,
        "prop": "imageinfo",
        "iiprop": "url|mime|size"
    }
    headers = {"User-Agent": "Mr-Nextep/2.0 (cinematic-shorts-renderer; contact via GitHub)"}
    response = requests.get(API, params=params, timeout=30, headers=headers)
    candidates: list[str] = []
    if response.ok:
        pages = response.json().get("query", {}).get("pages", {}).values()
        candidates = [
            p.get("imageinfo", [{}])[0].get("url")
            for p in pages
            if p.get("imageinfo")
            and p["imageinfo"][0].get("mime", "").startswith("video/")
            and int(p["imageinfo"][0].get("size", 0) or 0) <= MAX_CLIP_BYTES
        ][:MAX_CANDIDATES]

    if len(candidates) < MAX_CANDIDATES:
        try:
            search = requests.get(
                ARCHIVE_SEARCH,
                params={
                    "q": f"mediatype:movies AND collection:opensource_movies AND ({_safe_name(query)} OR science OR dark)",
                    "fl[]": "identifier",
                    "rows": 30,
                    "output": "json"
                },
                timeout=30,
                headers=headers
            )
            if search.ok:
                for doc in search.json().get("response", {}).get("docs", []):
                    metadata = requests.get(f"https://archive.org/metadata/{doc['identifier']}", timeout=30, headers=headers)
                    if not metadata.ok:
                        continue
                    for item in metadata.json().get("files", []):
                        name = item.get("name", "")
                        if name.lower().endswith((".mp4", ".webm", ".ogv")) and int(item.get("size", 0) or 0) <= MAX_CLIP_BYTES:
                            url = f"https://archive.org/download/{doc['identifier']}/{quote(name)}"
                            if url not in candidates:
                                candidates.append(url)
                            break
                    if len(candidates) >= MAX_CANDIDATES:
                        break
        except Exception:
            pass

    try:
        history_path = Path(os.getenv("DATA_DIR", "data")) / "clip_history.json"
        history = json.loads(history_path.read_text(encoding="utf-8"))
        used_urls = {row.get("source_url") for row in history if isinstance(row, dict)}
        candidates = [url for url in candidates if url not in used_urls] or candidates
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    if not candidates:
        raise RuntimeError(f"No moving video clip found for: {query}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = destination.with_suffix(".source")
    avoid_hashes = avoid_hashes or set()
    salt = os.getenv("GITHUB_RUN_ID", "local")
    start = int(hashlib.sha256(f"{salt}:{query}:{destination.name}".encode()).hexdigest()[:8], 16) % len(candidates)
    ordered = (candidates[start:] + candidates[:start])[:MAX_CANDIDATES]

    # 2026 Enhanced Video Filter Graph:
    # 1. scale & crop to 1080x1920
    # 2. unsharp=5:5:0.8 to remove blurriness
    # 3. eq=contrast=1.14:saturation=1.20:brightness=-0.02 for rich Netflix documentary style
    # 4. vignette=PI/4 to center the viewer focus
    vf_filter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "unsharp=5:5:0.8:5:5:0.0,"
        "eq=contrast=1.14:saturation=1.20:brightness=-0.02,"
        "vignette=PI/4"
    )

    for source_url in ordered:
        try:
            head = requests.head(source_url, timeout=20, headers=headers, allow_redirects=True)
            content_length = int(head.headers.get("content-length", 0) or 0)
            if content_length and content_length > MAX_CLIP_BYTES:
                continue
            with requests.get(source_url, stream=True, timeout=90, headers=headers) as download:
                download.raise_for_status()
                with raw.open("wb") as handle:
                    for chunk in download.iter_content(1024 * 256):
                        if chunk:
                            handle.write(chunk)

            subprocess.run([
                "ffmpeg", "-y", "-i", str(raw),
                "-t", "8", "-an",
                "-vf", vf_filter,
                "-r", "30",
                "-c:v", "libx264", "-b:v", "6500k", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                str(destination)
            ], check=True, capture_output=True)

            clip_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
            if clip_hash in avoid_hashes:
                destination.unlink(missing_ok=True)
                raw.unlink(missing_ok=True)
                continue
            raw.unlink(missing_ok=True)
            destination.with_suffix(".source_url").write_text(source_url, encoding="utf-8")
            return destination
        except (requests.RequestException, OSError, subprocess.CalledProcessError):
            destination.unlink(missing_ok=True)
            raw.unlink(missing_ok=True)
            continue
    raise RuntimeError(f"No unique moving video clip found for: {query}")

def query_for_scene(scene: dict[str, str]) -> str:
    base = scene.get("visual_query") or scene.get("caption", "dark science")
    variants = ("silhouette slow motion", "macro close up", "night laboratory", "shadows mysterious", "brain scan neural", "uncanny abstract")
    index = int(hashlib.sha256(base.encode()).hexdigest()[:8], 16) % len(variants)
    return f"{base} {variants[index]}"
