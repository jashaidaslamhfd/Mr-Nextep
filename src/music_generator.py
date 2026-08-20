"""AI-generated viral dark-mystery background music (Mr-Nextep, US).

2026-08-21: ported from the Neuro-Somaa viral music engine and retuned for
the US dark-mystery Shorts brand: cinematic tension piano + low dark drone
+ subtle pulse — the vibe behind viral US mystery Shorts — unique to EVERY
video (no stock repetition, no Content ID claims, royalty-free).

Engine: ModelsLab text-to-music (MODELSLAB_API_KEY in repo secrets).
Fallback: legacy synth/asset tracks or flat ambient bed — the pipeline
NEVER blocks, and a music failure can never stop a video from publishing.
"""
import json
import os
import random
import time
import urllib.parse
import urllib.request

import re

import requests

BASE_VAULT = os.path.join("assets", "music", "generated")
MAX_POLL = 8
POLL_INTERVAL = 7

_BASE_PROMPT = (
    "Cinematic dark-mystery thriller instrumental, brooding low piano ostinato "
    "over a deep sub drone, tense string swell and subtle metallic pulse, "
    "slow {bpm} BPM, ominous and intriguing, US mystery-YouTube viral "
    "aesthetic, instrumental only, no vocals, no loud drums, no "
    "percussion, smooth and seamless loop-friendly, studio quality"
)

_MUSIC_GEN_URL = "https://modelslab.com/api/v6/voice/music_gen"


def _make_prompt(theme: str, bpm: int = 68) -> str:
    clean = re.sub(r"[^\w\s]+", "", theme or "")
    words = " ".join(clean.split())[:60]
    text = _BASE_PROMPT.format(bpm=bpm)
    if words:
        text += f", inspired mood: {words}"
    return text


def generate_sad_music(theme: str = "", duration: int = 30) -> str | None:
    """Generate a unique viral dark-mystery BGM. Returns output path or None
    on failure (caller falls back to stock/synth tracks)."""
    api_key = os.environ.get("MODELSLAB_API_KEY", "").strip()
    if not api_key:
        return None
    import logging
    logger = logging.getLogger("music_generator")
    os.makedirs(BASE_VAULT, exist_ok=True)
    payload = {
        "key": api_key,
        "prompt": _make_prompt(theme),
        "duration": duration,
        "output_format": "wav",
    }
    try:
        resp = requests.post(_MUSIC_GEN_URL, json=payload, timeout=120)
    except Exception as exc:  # noqa: BLE001 - fallback is intentional
        logger.warning("Music API unreachable (%s) - using stock track", exc)
        return None
    if resp.status_code == 429:
        logger.warning("Music API rate-limited - using stock track")
        return None
    if resp.status_code != 200:
        logger.warning("Music API HTTP %s - using stock track", resp.status_code)
        return None
    data = resp.json()
    status = data.get("status")
    urls = data.get("output") or []
    if status == "success" and urls:
        return _download_track(urls[0], theme)
    if status in ("processing", "not_found") and data.get("fetch_result"):
        fetch = data["fetch_result"]
        for _ in range(MAX_POLL):
            time.sleep(POLL_INTERVAL)
            try:
                with urllib.request.urlopen(fetch, timeout=30) as r:
                    d = json.load(r)
            except Exception:  # noqa: BLE001
                continue
            out = d.get("output") or []
            if d.get("status") == "success" and out:
                return _download_track(out[0], theme)
            if d.get("status") == "failed":
                return None
        logger.warning("Music API polling timeout - using stock track")
    return None


def _download_track(url: str, theme: str) -> str:
    slug = re.sub(r"[^\w]+", "_", theme or "mystery")[:40]
    path = os.path.join(
        BASE_VAULT,
        f"viral_us_{slug}_{int(time.time())}_{random.randint(100, 999)}".strip()
        + ".wav",
    )
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
            f.write(r.read())
    except Exception:  # noqa: BLE001
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    size = os.path.getsize(path)
    if size < 100_000:  # empty/broken response
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return path


def pick_track(theme: str = "", target_duration: float = 0.0) -> str | None:
    """Public entry: try AI-generated viral track first; fall back to the
    legacy stock/synth tracks so rendering never breaks."""
    if (os.environ.get("MR_VIRAL_BGM", "true").strip().lower()
            not in ("true", "1", "yes", "on")):
        return None
    gen = generate_sad_music(
        theme=theme, duration=max(20, int(target_duration)),
    )
    return gen
