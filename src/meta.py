from __future__ import annotations
import os
import time
import requests
from pathlib import Path
from typing import Any
from seo import build_packages

GRAPH = "https://graph.facebook.com/v23.0"

def _post(url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.post(url, timeout=90, **kwargs)
    response.raise_for_status()
    return response.json()

def _host_for_instagram(video: Path) -> str:
    """Upload this run's MP4 to a public GitHub Release asset."""
    configured = os.getenv("PUBLIC_VIDEO_URL", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", str(int(time.time())))
    if not token or not repo:
        if configured:
            raise RuntimeError("Static PUBLIC_VIDEO_URL is disabled; configure GITHUB_TOKEN/GITHUB_REPOSITORY")
        raise RuntimeError("Instagram requires GITHUB_TOKEN and GITHUB_REPOSITORY for per-run hosting")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    tag = f"short-{run_id}"
    release = requests.post(f"https://api.github.com/repos/{repo}/releases", headers=headers, json={"tag_name": tag, "name": tag, "draft": False, "prerelease": True}, timeout=60)
    release.raise_for_status()
    upload_url = release.json()["upload_url"].split("{")[0]
    with video.open("rb") as handle:
        uploaded = requests.post(f"{upload_url}?name={video.name}", headers={**headers, "Content-Type": "video/mp4"}, data=handle, timeout=180)
    uploaded.raise_for_status()
    return uploaded.json()["browser_download_url"]

def _wait_for_instagram_ready(media_id: str, token: str) -> None:
    deadline = time.time() + max(120, int(os.getenv("INSTAGRAM_PROCESSING_TIMEOUT_SECONDS", "300")))
    while time.time() < deadline:
        response = requests.get(f"{GRAPH}/{media_id}", params={"access_token": token, "fields": "status_code"}, timeout=60)
        response.raise_for_status()
        status = response.json().get("status_code", "")
        if status == "FINISHED": return
        if status in {"ERROR", "EXPIRED"}: raise RuntimeError(f"Instagram media processing failed: {status}")
        time.sleep(10)
    raise TimeoutError("Instagram media processing timed out")

def publish(video: Path, script: dict[str, Any], youtube_result: dict[str, str]) -> dict[str, Any]:
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    token = os.getenv("FACEBOOK_ACCESS_TOKEN", "").strip()
    instagram_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    gap = max(0, int(os.getenv("META_POST_GAP_SECONDS", "600")))
    seo = build_packages(script)
    result: dict[str, Any] = {"facebook": {"status": "skipped"}, "instagram": {"status": "skipped"}}
    if not page_id or not token:
        result["facebook"] = {"status": "skipped", "reason": "FACEBOOK_PAGE_ID or FACEBOOK_ACCESS_TOKEN missing"}
    else:
        fb = _post(f"{GRAPH}/{page_id}/videos", params={"access_token": token}, files={"source": (video.name, video.open("rb"), "video/mp4")}, data={"title": seo["facebook"]["title"], "description": seo["facebook"]["description"], "published": "true"})
        result["facebook"] = {"status": "published", "id": str(fb.get("id", ""))}
    if instagram_id and token:
        time.sleep(gap)
        public_url = _host_for_instagram(video)
        container = _post(f"{GRAPH}/{instagram_id}/media", params={"access_token": token}, data={"media_type": "REELS", "video_url": public_url, "caption": seo["instagram"]["caption"]})
        _wait_for_instagram_ready(container["id"], token)
        published = _post(f"{GRAPH}/{instagram_id}/media_publish", params={"access_token": token}, data={"creation_id": container["id"]})
        result["instagram"] = {"status": "published", "id": str(published.get("id", ""))}
    elif not instagram_id or not token:
        result["instagram"] = {"status": "skipped", "reason": "INSTAGRAM_USER_ID or FACEBOOK_ACCESS_TOKEN missing"}
    else:
        result["instagram"] = {"status": "skipped", "reason": "INSTAGRAM_USER_ID or FACEBOOK_ACCESS_TOKEN missing"}
    return result
