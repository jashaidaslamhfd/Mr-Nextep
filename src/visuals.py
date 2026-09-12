from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests

logger = logging.getLogger("mrnextep.visuals")

API = "https://commons.wikimedia.org/w/api.php"
ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
MAX_CLIP_BYTES = 45_000_000
MAX_CANDIDATES = 16
CLIP_SECONDS = 8

GRADE_FILTER = (
    "scale=1080:1920:force_original_aspect_ratio=increase,"
    "crop=1080:1920,"
    "unsharp=5:5:0.8:5:5:0.0,"
    "eq=contrast=1.14:saturation=1.20:brightness=-0.02,"
    "vignette=PI/4"
)

GUARANTEED_TOPICS = [
    "dark science",
    "space galaxy",
    "night darkness",
    "time lapse nature",
    "abstract motion",
    "laboratory science",
    "neural brain",
    "shadows mystery",
]


def _safe_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:70] or "science"


def _clean_keywords(text: str) -> str:
    """Extract 2-4 clean, high-signal keyword search terms."""
    clean = re.sub(r"[^a-zA-Z\s]", " ", text).lower()
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "of", "and", "in", "to", "for",
        "with", "that", "this", "it", "at", "by", "from", "up", "about", "into", "over",
        "after", "scene", "video", "clip", "feel", "feeling", "completely", "very", "can",
        "your", "you", "our", "their", "why", "how", "what", "when", "where", "does"
    }
    words = [w for w in clean.split() if len(w) > 2 and w not in stop_words]
    if len(words) >= 2:
        return " ".join(words[:3])
    return "dark science"


def _fetch_wikimedia_candidates(query_terms: str, headers: dict) -> list[str]:
    candidates: list[str] = []
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query_terms} filetype:video",
        "gsrnamespace": 6,
        "gsrlimit": 25,
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
    }
    try:
        response = requests.get(API, params=params, timeout=20, headers=headers)
        if not response.ok:
            logger.warning("Wikimedia search returned HTTP %s for %r", response.status_code, query_terms)
        if response.ok:
            pages = response.json().get("query", {}).get("pages", {}).values()
            for p in pages:
                info = p.get("imageinfo", [{}])[0]
                url = info.get("url")
                mime = info.get("mime", "")
                size = int(info.get("size", 0) or 0)
                if url and mime.startswith("video/") and (size <= MAX_CLIP_BYTES or size == 0):
                    candidates.append(url)
    except Exception:
        logger.warning("Stock provider %s failed; continuing with other sources", "wikimedia", exc_info=True)
    return candidates


def _fetch_archive_candidates(query: str, headers: dict) -> list[str]:
    candidates: list[str] = []
    try:
        search = requests.get(
            ARCHIVE_SEARCH,
            params={
                "q": f"mediatype:movies AND collection:opensource_movies AND ({_safe_name(query)} OR science OR dark OR space)",
                "fl[]": "identifier",
                "rows": 25,
                "output": "json",
            },
            timeout=20,
            headers=headers,
        )
        if search.ok:
            for doc in search.json().get("response", {}).get("docs", []):
                metadata = requests.get(f"https://archive.org/metadata/{doc['identifier']}", timeout=20, headers=headers)
                if not metadata.ok:
                    continue
                for item in metadata.json().get("files", []):
                    name = item.get("name", "")
                    size = int(item.get("size", 0) or 0)
                    if name.lower().endswith((".mp4", ".webm", ".ogv")) and (size <= MAX_CLIP_BYTES or size == 0):
                        url = f"https://archive.org/download/{doc['identifier']}/{quote(name)}"
                        if url not in candidates:
                            candidates.append(url)
                        break
                if len(candidates) >= 8:
                    break
    except Exception:
        logger.warning("Stock provider %s failed; continuing with other sources", "archive.org", exc_info=True)
    return candidates


def _fetch_pexels_candidates(keywords: str) -> list[str]:
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return []
    candidates: list[str] = []
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": keywords, "orientation": "portrait", "per_page": 15},
            headers={"Authorization": key, "User-Agent": "Mr-Nextep/2.0"},
            timeout=20,
        )
        if resp.ok:
            for vid in resp.json().get("videos", []):
                for vf in vid.get("video_files", []):
                    if vf.get("file_type") == "video/mp4" and vf.get("link"):
                        width = vf.get("width", 0) or 0
                        if width <= 1080 or not width:
                            candidates.append(vf["link"])
                            break
    except Exception:
        logger.warning("Stock provider %s failed; continuing with other sources", "pexels", exc_info=True)
    return candidates


def _fetch_pixabay_candidates(keywords: str) -> list[str]:
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return []
    candidates: list[str] = []
    try:
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": key, "q": keywords, "video_type": "film", "per_page": 15},
            headers={"User-Agent": "Mr-Nextep/2.0"},
            timeout=20,
        )
        if resp.ok:
            for hit in resp.json().get("hits", []):
                videos = hit.get("videos", {})
                link = (
                    videos.get("medium", {}).get("url")
                    or videos.get("small", {}).get("url")
                    or videos.get("tiny", {}).get("url")
                )
                if link and link not in candidates:
                    candidates.append(link)
    except Exception:
        logger.warning("Stock provider %s failed; continuing with other sources", "pixabay", exc_info=True)
    return candidates


def _try_candidate(
    source_url: str,
    destination: Path,
    avoid_hashes: set[str],
    headers: dict,
    check_size: bool = True,
) -> bool:
    """Download one candidate, grade it, and keep it unless its hash collides.

    Returns True when destination now holds a usable graded clip. Leaves no partial
    files behind on failure. This body used to exist twice, near-verbatim.
    """
    raw = destination.with_suffix(".source")
    try:
        if check_size:
            head = requests.head(source_url, timeout=20, headers=headers, allow_redirects=True)
            content_length = int(head.headers.get("content-length", 0) or 0)
            if content_length and content_length > MAX_CLIP_BYTES:
                logger.debug("Skipping %s: %d bytes exceeds cap", source_url, content_length)
                return False

        with requests.get(source_url, stream=True, timeout=90, headers=headers) as download:
            download.raise_for_status()
            with raw.open("wb") as handle:
                for chunk in download.iter_content(1024 * 256):
                    if chunk:
                        handle.write(chunk)

        subprocess.run([
            "ffmpeg", "-y", "-i", str(raw),
            "-t", str(CLIP_SECONDS), "-an",
            "-vf", GRADE_FILTER,
            "-r", "30",
            "-c:v", "libx264", "-b:v", "6500k", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            str(destination),
        ], check=True, capture_output=True)

        clip_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
        if clip_hash in avoid_hashes:
            logger.debug("Discarding %s: duplicate of a clip already used in this video", source_url)
            destination.unlink(missing_ok=True)
            return False

        destination.with_suffix(".source_url").write_text(source_url, encoding="utf-8")
        return True
    except (requests.RequestException, OSError, subprocess.CalledProcessError) as exc:
        logger.warning("Candidate %s unusable: %s", source_url, exc)
        destination.unlink(missing_ok=True)
        return False
    finally:
        raw.unlink(missing_ok=True)


def download_clip(query: str, destination: Path, avoid_hashes: set[str] | None = None) -> Path:
    """Download a stock clip and apply cinematic grading, unsharp filter, and vignette."""
    headers = {"User-Agent": "Mr-Nextep/2.0 (cinematic-shorts-renderer; contact via GitHub)"}
    clean_kw = _clean_keywords(query)

    candidates: list[str] = []

    # 1. Pexels (if API key provided)
    candidates.extend(_fetch_pexels_candidates(clean_kw))

    # 2. Pixabay (if API key provided)
    if len(candidates) < MAX_CANDIDATES:
        candidates.extend(_fetch_pixabay_candidates(clean_kw))

    # 3. Wikimedia Commons with clean keywords
    if len(candidates) < MAX_CANDIDATES:
        candidates.extend(_fetch_wikimedia_candidates(clean_kw, headers))

    # 4. If still few candidates, try guaranteed science/mystery topics on Wikimedia
    if len(candidates) < 4:
        topic_idx = int(hashlib.sha256(query.encode()).hexdigest()[:4], 16) % len(GUARANTEED_TOPICS)
        candidates.extend(_fetch_wikimedia_candidates(GUARANTEED_TOPICS[topic_idx], headers))

    # 5. Archive.org as additional pool
    if len(candidates) < MAX_CANDIDATES:
        candidates.extend(_fetch_archive_candidates(query, headers))

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            deduped.append(c)
    candidates = deduped[:MAX_CANDIDATES]

    try:
        history_path = Path(os.getenv("DATA_DIR", "data")) / "clip_history.json"
        history = json.loads(history_path.read_text(encoding="utf-8"))
        used_urls = {row.get("source_url") for row in history if isinstance(row, dict)}
        candidates = [url for url in candidates if url not in used_urls] or candidates
    except FileNotFoundError:
        logger.info("No clip history yet; not filtering previously used clips")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning("Could not read clip history; not filtering previously used clips", exc_info=True)

    if not candidates:
        for topic in GUARANTEED_TOPICS:
            extra = _fetch_wikimedia_candidates(topic, headers)
            if extra:
                candidates.extend([u for u in extra if u not in seen])
            if candidates:
                break

    if not candidates:
        raise RuntimeError(f"No moving video clip found for: {query}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    avoid_hashes = avoid_hashes or set()

    salt = os.getenv("GITHUB_RUN_ID", "local")
    start = int(hashlib.sha256(f"{salt}:{query}:{destination.name}".encode()).hexdigest()[:8], 16) % len(candidates)
    ordered = candidates[start:] + candidates[:start]

    logger.info("Trying %d candidate clips for %r", len(ordered), query)
    for source_url in ordered:
        if _try_candidate(source_url, destination, avoid_hashes, headers):
            return destination

    # Fallback to guaranteed topics if every candidate failed or collided.
    logger.warning("All %d primary candidates failed for %r; falling back to guaranteed topics", len(ordered), query)
    attempted = set(ordered)
    for fallback_topic in GUARANTEED_TOPICS:
        for fb_url in _fetch_wikimedia_candidates(fallback_topic, headers):
            if fb_url in attempted:
                continue
            attempted.add(fb_url)
            if _try_candidate(fb_url, destination, avoid_hashes, headers, check_size=False):
                return destination

    raise RuntimeError(f"No unique moving video clip found for: {query}")


def query_for_scene(scene: dict[str, str], scene_index: int = 1) -> str:
    base = scene.get("visual_query") or scene.get("caption", "dark science")
    variants = (
        "silhouette slow motion",
        "macro close up",
        "night laboratory",
        "shadows mysterious",
        "brain scan neural",
        "uncanny abstract",
        "deep space cosmos",
        "infinite loop geometry",
    )
    index = (int(hashlib.sha256(base.encode()).hexdigest()[:8], 16) + scene_index) % len(variants)
    return f"{base} {variants[index]}"
