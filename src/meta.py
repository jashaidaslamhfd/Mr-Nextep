from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Any
import requests
from seo import build_packages

GRAPH = "https://graph.facebook.com/v23.0"


def _post(url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.post(url, timeout=90, **kwargs)
    response.raise_for_status()
    return response.json()


def _cleanup_short_releases(headers: dict[str, str], repo: str, keep_tag: str) -> None:
    page = 1
    while True:
        response = requests.get(f"https://api.github.com/repos/{repo}/releases", headers=headers, params={"per_page": 100, "page": page}, timeout=60)
        response.raise_for_status()
        releases = response.json()
        if not releases:
            break
        for release in releases:
            tag = release.get("tag_name", "")
            if tag.startswith("short-") and tag != keep_tag:
                requests.delete(f"https://api.github.com/repos/{repo}/releases/{release['id']}", headers=headers, timeout=60).raise_for_status()
                requests.delete(f"https://api.github.com/repos/{repo}/git/refs/tags/{tag}", headers=headers, timeout=60)
        page += 1


def _host_for_instagram(video: Path) -> str:
    """Host this run's MP4 on one short-lived public GitHub Release asset."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", str(int(time.time())))
    if not token or not repo:
        raise RuntimeError("Instagram requires GITHUB_TOKEN and GITHUB_REPOSITORY for per-run hosting")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    tag = f"short-{run_id}"
    _cleanup_short_releases(headers, repo, tag)
    existing = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers=headers, timeout=60)
    if existing.status_code == 200:
        release = existing.json()
        for asset in release.get("assets", []):
            requests.delete(f"https://api.github.com/repos/{repo}/releases/assets/{asset['id']}", headers=headers, timeout=60)
    else:
        response = requests.post(f"https://api.github.com/repos/{repo}/releases", headers=headers, json={"tag_name": tag, "name": tag, "draft": False, "prerelease": True}, timeout=60)
        response.raise_for_status()
        release = response.json()
    upload_url = release["upload_url"].split("{")[0]
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
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram media processing failed: {status}")
        time.sleep(10)
    raise TimeoutError("Instagram media processing timed out")


def publish(video: Path, script: dict[str, Any], youtube_result: dict[str, str]) -> dict[str, Any]:
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    token = os.getenv("FACEBOOK_ACCESS_TOKEN", "").strip()
    instagram_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    gap = max(0, int(os.getenv("META_POST_GAP_SECONDS", "600")))
    seo = build_packages(script)
    result: dict[str, Any] = {"facebook": {"status": "skipped"}, "instagram": {"status": "skipped"}}

    if page_id and token:
        try:
            with video.open("rb") as handle:
                fb = _post(f"{GRAPH}/{page_id}/videos", params={"access_token": token}, files={"source": (video.name, handle, "video/mp4")}, data={"title": seo["facebook"]["title"], "description": seo["facebook"]["description"], "published": "true"})
            result["facebook"] = {"status": "published", "id": str(fb.get("id", ""))}
        except Exception as exc:
            result["facebook"] = {"status": "error", "reason": str(exc)}
    else:
        result["facebook"] = {"status": "skipped", "reason": "FACEBOOK_PAGE_ID or FACEBOOK_ACCESS_TOKEN missing"}

    if instagram_id and token:
        try:
            time.sleep(gap)
            public_url = _host_for_instagram(video)
            container = _post(f"{GRAPH}/{instagram_id}/media", params={"access_token": token}, data={"media_type": "REELS", "video_url": public_url, "caption": seo["instagram"]["caption"]})
            _wait_for_instagram_ready(container["id"], token)
            published = _post(f"{GRAPH}/{instagram_id}/media_publish", params={"access_token": token}, data={"creation_id": container["id"]})
            result["instagram"] = {"status": "published", "id": str(published.get("id", "")), "source_url": public_url}
        except Exception as exc:
            result["instagram"] = {"status": "error", "reason": str(exc)}
    else:
        result["instagram"] = {"status": "skipped", "reason": "INSTAGRAM_USER_ID or FACEBOOK_ACCESS_TOKEN missing"}
    return result
