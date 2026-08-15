import os
import random
import hashlib
import threading
import requests
import logging

from image_providers import available_providers, RateLimitError
from media_validator import validate_scene_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
_fallback_lock = threading.Lock()

# Legacy fixed style kept for backward-compat references; the prompt builder now
# uses humanizer.style_suffix() so different videos get a varied visual look
# instead of one identical suffix on every scene.
DARK_STYLE_SUFFIX = (
    "clean cinematic documentary lighting, realistic human detail, sharp focus, "
    "crisp high-resolution detail, natural color, professional camera quality, "
    "vertical composition, no text, no watermark, not blurry, not dull"
)

FALLBACK_POOL_DIR = "assets/fallback_images"


def _save_bytes(content: bytes, index: int, ext: str = "jpg") -> str:
    os.makedirs("output", exist_ok=True)
    path = f"output/scene_{index}.{ext}"
    with open(path, "wb") as f:
        f.write(content)
    return path


def _build_prompt(scene_text: str, *, first_frame: bool = False, topic_seed: str = "") -> str:
    """Build a scene-specific prompt with a stronger first-frame hook.

    `topic_seed` (the video topic/title) stabilises the visual style per video
    via humanizer.style_suffix, so one video keeps a cohesive look while
    different videos don't all share the identical template.
    """
    base = (scene_text or "mystery science").strip()

    if first_frame:
        base = (
            "EXTREME FIRST-FRAME HOOK, instantly readable visual action, "
            "tight close-up of the exact body phenomenon, strong contrast, "
            "clear subject silhouette, no intro card, no generic anatomy pose: "
            + base
        )

    try:
        from humanizer import style_suffix
        suffix = style_suffix(topic_seed or scene_text or "x", first_frame=first_frame)
    except Exception:  # noqa: BLE001 - never let a style helper break generation
        suffix = DARK_STYLE_SUFFIX

    return f"{base}, {suffix}"


def _layer_ai_providers(index, scene_text, provider_names=None, topic_seed=""):
    """Try configured AI image providers in order."""
    providers = available_providers()

    if provider_names is not None:
        allowed = set(provider_names)
        providers = [p for p in providers if p["name"] in allowed]

    if not providers:
        requested = ", ".join(provider_names or []) or "configured"
        raise RuntimeError(
            f"No {requested} AI image providers available "
            "(check API keys / network)"
        )

    prompt_text = _build_prompt(
        scene_text,
        first_frame=(index == 0),
        topic_seed=topic_seed,
    )
    prompt = prompt_text.replace(" ", "_").replace(",", "")
    seed = random.randint(1, 999999)

    last_err = None

    for provider in providers:
        try:
            image_bytes, ext = provider["generate"](
                prompt,
                seed,
                prompt_text,
            )

            if not image_bytes or len(image_bytes) < 2000:
                raise RuntimeError(
                    f"{provider['name']}: empty/too-small response"
                )

            path = _save_bytes(image_bytes, index, ext=ext)

            logger.info(
                "Scene %s: AI image via %s",
                index,
                provider["name"],
            )

            return path

        except RateLimitError as exc:
            logger.warning(
                "Scene %s: %s rate-limited, trying next provider: %s",
                index,
                provider["name"],
                exc,
            )
            last_err = exc

        except Exception as exc:
            logger.warning(
                "Scene %s: %s failed, trying next provider: %s",
                index,
                provider["name"],
                exc,
            )
            last_err = exc

    raise RuntimeError(
        f"All AI providers failed for scene {index}: {last_err}"
    )


def _layer_local_pool(index, used_fallbacks: set):
    """Use a unique image from the local fallback pool."""
    if not os.path.isdir(FALLBACK_POOL_DIR):
        raise RuntimeError(
            f"No local fallback pool at {FALLBACK_POOL_DIR}"
        )

    candidates = [
        os.path.join(FALLBACK_POOL_DIR, filename)
        for filename in os.listdir(FALLBACK_POOL_DIR)
        if filename.lower().endswith((".jpg", ".jpeg", ".png"))
    ]

    if not candidates:
        raise RuntimeError(
            f"Local fallback pool at {FALLBACK_POOL_DIR} is empty"
        )

    with _fallback_lock:
        unused = [
            path for path in candidates
            if path not in used_fallbacks
        ]

        pick = random.choice(unused or candidates)
        used_fallbacks.add(pick)

    ext = pick.rsplit(".", 1)[-1]

    with open(pick, "rb") as file_handle:
        content = file_handle.read()

    return _save_bytes(content, index, ext=ext)


def _layer1_playwright_screenshot(index, scene_text):
    """Last-resort screenshot fallback."""
    from playwright.sync_api import sync_playwright

    query = (scene_text or "mystery science").strip()[:100]
    screenshot_bytes = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--no-sandbox"]
        )

        try:
            page = browser.new_page(
                viewport={"width": 1080, "height": 1920}
            )
            page.set_default_timeout(20000)

            page.goto(
                "https://html.duckduckgo.com/html/",
                wait_until="domcontentloaded",
                timeout=20000,
            )

            page.goto(
                f"https://html.duckduckgo.com/html/?q={query}",
                wait_until="domcontentloaded",
                timeout=20000,
            )

            link = page.query_selector("a.result__a")

            if not link:
                raise RuntimeError(
                    "Playwright: search result nahi mila"
                )

            target_url = link.get_attribute("href")

            if not target_url:
                raise RuntimeError(
                    "Playwright: result href empty tha"
                )

            page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=20000,
            )

            page.wait_for_timeout(1500)
            screenshot_bytes = page.screenshot(type="png")

        finally:
            browser.close()

    if not screenshot_bytes or len(screenshot_bytes) < 2000:
        raise RuntimeError(
            "Playwright: screenshot khaali/chota tha"
        )

    return _save_bytes(
        screenshot_bytes,
        index,
        ext="png",
    )


def _stock_photo_request(
    index,
    scene_text,
    source: str,
    used_fallbacks: set,
):
    raw_text = (scene_text or "human body science").strip()
    words = [w for w in raw_text.replace(",", "").replace(".", "").split() if len(w) > 3]
    query = " ".join(words[:2]) if words else "human body"

    if source == "pexels":
        key = os.environ.get("PEXELS_API_KEY")

        if not key:
            raise RuntimeError(
                "PEXELS_API_KEY not set - skipping Pexels"
            )

        response = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key},
            params={
                "query": query,
                "per_page": 15,
                "orientation": "portrait",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Pexels bad response: {response.status_code}"
            )

        photos = response.json().get("photos", [])

        if not photos:
            raise RuntimeError(
                f"Pexels: no results for '{query}'"
            )

        image_urls = [
            photo["src"].get("portrait")
            or photo["src"].get("large2x")
            or photo["src"].get("original")
            or photo["src"]["large"]
            for photo in photos
        ]

    elif source == "pixabay":
        key = os.environ.get("PIXABAY_API_KEY")

        if not key:
            raise RuntimeError(
                "PIXABAY_API_KEY not set - skipping Pixabay"
            )

        response = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": key,
                "q": query,
                "image_type": "photo",
                "orientation": "vertical",
                "per_page": 15,
                "safesearch": "true",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Pixabay bad response: {response.status_code}"
            )

        hits = response.json().get("hits", [])

        if not hits:
            raise RuntimeError(
                f"Pixabay: no results for '{query}'"
            )

        image_urls = [
            hit.get("largeImageURL")
            or hit.get("webformatURL")
            for hit in hits
        ]

    else:
        raise ValueError(
            f"Unknown stock source: {source}"
        )

    with _fallback_lock:
        unused_urls = [
            url for url in image_urls
            if url and url not in used_fallbacks
        ]

        url = random.choice(unused_urls or image_urls)

        if url:
            used_fallbacks.add(url)

    image_response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    if (
        image_response.status_code != 200
        or len(image_response.content) < 2000
    ):
        raise RuntimeError(
            f"{source}: failed to download chosen image"
        )

    return _save_bytes(
        image_response.content,
        index,
    )


def _stock_video_request(
    index,
    scene_text,
    source: str,
    used_fallbacks: set,
):
    """Download licensed stock B-roll video."""
    # Pexels and Pixabay fail on long descriptive sentences. We need 1-3 simple keywords.
    # We'll take the first 2 meaningful words longer than 3 chars to form a robust stock query.
    raw_text = (scene_text or "human body science").strip()
    words = [w for w in raw_text.replace(",", "").replace(".", "").split() if len(w) > 3]
    query = " ".join(words[:2]) if words else "human body"
    
    if source == "pexels":
        key = os.environ.get("PEXELS_API_KEY")

        if not key:
            raise RuntimeError(
                "PEXELS_API_KEY not set - skipping Pexels video"
            )

        response = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={
                "query": query,
                "per_page": 12,
                "orientation": "portrait",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Pexels video bad response: {response.status_code}"
            )

        videos = response.json().get("videos", [])
        urls = []

        for video in videos:
            files = video.get("video_files", [])

            candidates = [
                item
                for item in files
                if item.get("file_type") == "video/mp4"
                and item.get("link")
            ]

            if candidates:
                chosen = max(
                    candidates,
                    key=lambda item: (
                        item.get("width", 0)
                        * item.get("height", 0)
                    ),
                )
                urls.append(chosen["link"])

    elif source == "pixabay":
        key = os.environ.get("PIXABAY_API_KEY")

        if not key:
            raise RuntimeError(
                "PIXABAY_API_KEY not set - skipping Pixabay video"
            )

        response = requests.get(
            "https://pixabay.com/api/videos/",
            params={
                "key": key,
                "q": query,
                "per_page": 20,
                "safesearch": "true",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Pixabay video bad response: {response.status_code}"
            )

        urls = []

        for hit in response.json().get("hits", []):
            variants = hit.get("videos", {})
            chosen = (
                variants.get("large")
                or variants.get("medium")
                or variants.get("small")
            )

            if chosen and chosen.get("url"):
                urls.append(chosen["url"])

    else:
        raise ValueError(
            f"Unknown stock-video source: {source}"
        )

    if not urls:
        raise RuntimeError(
            f"{source}: no usable B-roll video for '{query}'"
        )

    with _fallback_lock:
        unused_urls = [
            url for url in urls
            if url not in used_fallbacks
        ]

        url = random.choice(unused_urls or urls)
        used_fallbacks.add(url)

    download = requests.get(
        url,
        timeout=60,
    )
    content = download.content

    if (
        download.status_code != 200
        or len(content) < 100_000
    ):
        raise RuntimeError(
            f"{source}: video download failed or was too small"
        )

    # 2026-08-15: Pexels/Pixabay occasionally serve an HTML error/redirect
    # page larger than the 100KB floor — accepted bytes were saved as .mp4
    # and then MoviePy crashed at build time ("failed to read the first
    # frame"). Verify the bytes are a real ISO-BMFF/MP4 container (ftyp or
    # moov box) before accepting.
    head = content[:64]
    if not (b"ftyp" in head or b"moov" in head):
        raise RuntimeError(
            f"{source}: downloaded bytes are not a valid MP4 container"
        )

    return (
        _save_bytes(
            content,
            index,
            ext="mp4",
        ),
        "video",
    )


def _layer_pexels_video(index, scene_text, used_fallbacks: set):
    return _stock_video_request(
        index,
        scene_text,
        "pexels",
        used_fallbacks,
    )


def _layer_pixabay_video(index, scene_text, used_fallbacks: set):
    return _stock_video_request(
        index,
        scene_text,
        "pixabay",
        used_fallbacks,
    )


def _layer2_pexels_live(index, scene_text, used_fallbacks: set):
    return _stock_photo_request(
        index,
        scene_text,
        "pexels",
        used_fallbacks,
    )


def _layer3_pixabay_live(index, scene_text, used_fallbacks: set):
    return _stock_photo_request(
        index,
        scene_text,
        "pixabay",
        used_fallbacks,
    )


def _scene_text(scene) -> str:
    if isinstance(scene, dict):
        return (
            scene.get("visual")
            or scene.get("description")
            or scene.get("scene")
            or scene.get("caption")
            or ""
        )

    return str(scene)


def _generate_one(
    index,
    scene,
    used_hashes: set,
    used_fallbacks: set,
    topic_seed: str = "",
):
    scene_text = _scene_text(scene)

    layers = [
        (
            "Other-AI-image",
            lambda: _layer_ai_providers(
                index,
                scene_text,
                [
                    "Pollinations-flux",
                    "Pollinations-turbo",
                    "HuggingFace",
                    "Gemini",
                    "DeepAI",
                    "ModelsLab",
                    "Replicate",
                ],
                topic_seed=topic_seed,
            ),
        ),
        (
            "AI-Horde-image",
            lambda: _layer_ai_providers(
                index,
                scene_text,
                ["AI-Horde"],
                topic_seed=topic_seed,
            ),
        ),
        (
            "Pexels-video-first",
            lambda: _layer_pexels_video(
                index,
                scene_text,
                used_fallbacks,
            ),
        ),
        (
            "Pixabay-video-second",
            lambda: _layer_pixabay_video(
                index,
                scene_text,
                used_fallbacks,
            ),
        ),
        (
            "Local-fallback-pool",
            lambda: _layer_local_pool(
                index,
                used_fallbacks,
            ),
        ),
        (
            "Pexels-image",
            lambda: _layer2_pexels_live(
                index,
                scene_text,
                used_fallbacks,
            ),
        ),
        (
            "Pixabay-image",
            lambda: _layer3_pixabay_live(
                index,
                scene_text,
                used_fallbacks,
            ),
        ),
    ]

    if os.environ.get(
        "ENABLE_SCREENSHOT_FALLBACK",
        "false",
    ).lower() == "true":
        layers.append(
            (
                "Playwright-screenshot",
                lambda: _layer1_playwright_screenshot(
                    index,
                    scene_text,
                ),
            )
        )

    for name, function in layers:
        try:
            result = function()

            if isinstance(result, tuple):
                path, media_type = result
            else:
                path, media_type = result, "image"

            if media_type == "image":
                validate_scene_image(path)
            else:
                if (
                    not os.path.isfile(path)
                    or os.path.getsize(path) < 100_000
                ):
                    raise RuntimeError(
                        f"{name}: invalid or too-small video clip"
                    )

            with open(path, "rb") as file_handle:
                file_hash = hashlib.sha256(
                    file_handle.read()
                ).hexdigest()

            if file_hash in used_hashes:
                raise RuntimeError(
                    f"{name}: duplicate media; trying next source"
                )

            used_hashes.add(file_hash)

            logger.info(
                "Scene %s: %s generated via %s -> %s",
                index,
                media_type,
                name,
                path,
            )

            return {
                "index": index,
                "path": path,
                "source": name,
                "media_type": media_type,
            }

        except Exception as exc:
            logger.error(
                "Scene %s: %s failed: %s",
                index,
                name,
                exc,
            )
            continue

    raise RuntimeError(
        f"Scene {index}: All generation layers failed."
    )


generate_scene_image = _generate_one
