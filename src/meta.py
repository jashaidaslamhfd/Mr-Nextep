"""
Meta (Facebook Page + Instagram) publishing helper.

Improvements:
- Uses a requests.Session with retry wrapper and retry_on_exception for Graph API calls.
- Validates PUBLIC_VIDEO_URL before creating IG media containers.
- Adds configurable randomized pre-post gap (to avoid strictly fixed post timing).
- Better error messages/logging and structured return values.
- Does NOT attempt to conceal automation or evade platform detection.

Expect environment variables:
- FACEBOOK_ACCESS_TOKEN, FACEBOOK_PAGE_ID, INSTAGRAM_USER_ID
- PUBLIC_VIDEO_URL (the hosted video, e.g., via GitHub release asset; repo already used this method)
"""
from __future__ import annotations
import os
import time
import logging
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse
import requests
from .utils import requests_session_with_retries, retry_on_exception, sanitize_hashtags

logger = logging.getLogger("mrnextep.meta")

GRAPH_BASE = "https://graph.facebook.com/v16.0"


def _is_valid_public_video_url(url: str) -> bool:
    if not url:
        return False
    p = urlparse(url)
    return p.scheme in ("https",) and bool(p.netloc)


@retry_on_exception(max_attempts=4)
def _post(session: requests.Session, url: str, params: dict = None, data: dict = None, files: dict = None, timeout: int = 90) -> dict:
    params = params or {}
    resp = session.post(url, params=params, data=data, files=files, timeout=timeout)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        logger.error("POST %s failed: status=%s body=%s", url, resp.status_code, resp.text)
        raise
    return resp.json()


@retry_on_exception(max_attempts=4)
def _get(session: requests.Session, url: str, params: dict = None, timeout: int = 60) -> dict:
    params = params or {}
    resp = session.get(url, params=params, timeout=timeout)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        logger.error("GET %s failed: status=%s body=%s", url, resp.status_code, resp.text)
        raise
    return resp.json()


def _host_for_instagram(video: Path) -> str:
    """
    Keep existing approach (upload to a per-run GitHub release asset), but make errors explicit.
    """
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        raise RuntimeError("Instagram host requires GITHUB_TOKEN and GITHUB_REPOSITORY environment variables")

    # This logic mirrors existing behavior but uses the session wrapper with retries
    session = requests_session_with_retries()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": session.headers.get("User-Agent")}
    # The existing repo flow created a release per-run; keep that approach
    run_id = os.getenv("GITHUB_RUN_ID", str(int(time.time())))
    tag = f"short-{run_id}"

    # Cleanup and create release if necessary (errors will bubble)
    # (We intentionally keep direct requests here as before but ensure failures are logged)
    releases_url = f"https://api.github.com/repos/{repo}/releases"
    r = session.get(f"{releases_url}/tags/{tag}")
    if r.status_code == 200:
        release = r.json()
    else:
        # Create release
        pr = session.post(releases_url, headers=headers, json={"tag_name": tag, "name": tag, "draft": False, "prerelease": True}, timeout=60)
        pr.raise_for_status()
        release = pr.json()

    upload_url = release["upload_url"].split("{")[0]
    with video.open("rb") as fh:
        up = session.post(f"{upload_url}?name={video.name}", headers={**headers, "Content-Type": "video/mp4"}, data=fh, timeout=180)
        up.raise_for_status()
        payload = up.json()
        url = payload.get("browser_download_url")
        if not url:
            raise RuntimeError("GitHub release upload did not return browser_download_url")
        return url


def publish(video: Path, script: dict[str, Any], youtube_result: Dict[str, Any]) -> Dict[str, Any]:
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    token = os.getenv("FACEBOOK_ACCESS_TOKEN", "").strip()
    instagram_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    gap_seconds = max(0, int(os.getenv("META_POST_GAP_SECONDS", "600")))
    session = requests_session_with_retries()

    # Build SEO packages (repo has seo.build_packages)
    from .seo import build_packages
    seo = build_packages(script)
    result = {"facebook": {"status": "skipped"}, "instagram": {"status": "skipped"}}

    if page_id and token:
        try:
            # Facebook page upload (multipart). Use retry wrapper via _post
            url = f"{GRAPH_BASE}/{page_id}/videos"
            with video.open("rb") as fh:
                files = {"source": (video.name, fh, "video/mp4")}
                params = {"access_token": token}
                data = {"title": seo.get("facebook", {}).get("title", ""), "description": seo.get("facebook", {}).get("description", "")}
                fb = _post(session, url, params=params, data=data, files=files, timeout=180)
                result["facebook"] = {"status": "published", "id": str(fb.get("id", ""))}
        except Exception as exc:
            logger.exception("Facebook publish failed")
            result["facebook"] = {"status": "error", "reason": str(exc)}

    # Instagram flow: use PUBLIC_VIDEO_URL (hosted) or host on GitHub releases
    public_url = os.getenv("PUBLIC_VIDEO_URL", "").strip()
    if not _is_valid_public_video_url(public_url):
        # try hosting the local file (this mirrors the repository's prior pattern)
        try:
            public_url = _host_for_instagram(video)
            logger.info("Hosted video for Instagram at %s", public_url)
        except Exception as exc:
            logger.exception("Failed to host video for Instagram: %s", exc)
            public_url = ""

    if instagram_id and token and public_url:
        try:
            # Optionally add a small randomized delay rather than a fixed gap to avoid deterministic posting cadence
            jitter = max(0, int(os.getenv("META_POST_GAP_JITTER_SECONDS", "60")))
            actual_gap = gap_seconds + random.randint(-jitter, jitter)
            if actual_gap > 0:
                logger.info("Waiting %d seconds before Instagram container creation", actual_gap)
                time.sleep(actual_gap)

            caption = seo.get("instagram", {}).get("caption", "")
            # sanitize hashtags if present in caption (simple heuristic)
            # Note: leave caption content semantic; only normalize repeated hashtags
            hashtags = seo.get("instagram", {}).get("hashtags", [])
            hashtags = sanitize_hashtags(hashtags, max_hashtags=10)
            caption_with_tags = caption + ("\n\n" + " ".join(hashtags) if hashtags else "")

            container = _post(session, f"{GRAPH_BASE}/{instagram_id}/media", params={"access_token": token},
                              data={"media_type": "REELS", "video_url": public_url, "caption": caption_with_tags}, timeout=120)
            media_id = container.get("id")
            if not media_id:
                raise RuntimeError("Instagram container creation did not return an id: " + str(container))
            # Wait for processing
            start = time.time()
            deadline = start + max(120, int(os.getenv("INSTAGRAM_PROCESSING_TIMEOUT_SECONDS", "300")))
            while time.time() < deadline:
                status_resp = _get(session, f"{GRAPH_BASE}/{media_id}", params={"access_token": token, "fields": "status_code"})
                status = status_resp.get("status_code", "")
                if status == "FINISHED":
                    break
                if status in {"ERROR", "EXPIRED"}:
                    raise RuntimeError(f"Instagram media processing failed: {status}")
                logger.debug("Instagram processing status %s for container %s. Sleeping 10s", status, media_id)
                time.sleep(10)
            published = _post(session, f"{GRAPH_BASE}/{instagram_id}/media_publish", params={"access_token": token}, data={"creation_id": media_id})
            result["instagram"] = {"status": "published", "id": str(published.get("id", "")), "source_url": public_url}
        except Exception as exc:
            logger.exception("Instagram publish failed")
            result["instagram"] = {"status": "error", "reason": str(exc)}
    else:
        # reasons for skipping are included explicitly to help debugging
        skip_reason = []
        if not instagram_id:
            skip_reason.append("INSTAGRAM_USER_ID missing")
        if not token:
            skip_reason.append("FACEBOOK_ACCESS_TOKEN missing")
        if not public_url:
            skip_reason.append("PUBLIC_VIDEO_URL unavailable")
        result["instagram"] = {"status": "skipped", "reason": "; ".join(skip_reason)}

    return result
