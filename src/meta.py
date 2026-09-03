from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Any

GRAPH = "https://graph.facebook.com/v23.0"

def _post(url: str, **kwargs: Any) -> dict[str, Any]:
    import requests
    response = requests.post(url, timeout=90, **kwargs)
    response.raise_for_status()
    return response.json()

def publish(video: Path, script: dict[str, Any], youtube_result: dict[str, str]) -> dict[str, Any]:
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    token = os.getenv("FACEBOOK_ACCESS_TOKEN", "").strip()
    instagram_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    public_url = os.getenv("PUBLIC_VIDEO_URL", "").strip()
    gap = max(0, int(os.getenv("META_POST_GAP_SECONDS", "600")))
    result: dict[str, Any] = {"facebook": {"status": "skipped"}, "instagram": {"status": "skipped"}}
    if not page_id or not token:
        result["facebook"] = {"status": "skipped", "reason": "FACEBOOK_PAGE_ID or FACEBOOK_ACCESS_TOKEN missing"}
    else:
        fb = _post(f"{GRAPH}/{page_id}/videos", params={"access_token": token}, files={"source": (video.name, video.open("rb"), "video/mp4")}, data={"title": script["title"], "description": script["description"], "published": "true"})
        result["facebook"] = {"status": "published", "id": str(fb.get("id", ""))}
    if instagram_id and token and public_url:
        time.sleep(gap)
        container = _post(f"{GRAPH}/{instagram_id}/media", params={"access_token": token}, data={"media_type": "REELS", "video_url": public_url, "caption": script["description"]})
        time.sleep(max(30, int(os.getenv("INSTAGRAM_PROCESSING_WAIT_SECONDS", "60"))))
        published = _post(f"{GRAPH}/{instagram_id}/media_publish", params={"access_token": token}, data={"creation_id": container["id"]})
        result["instagram"] = {"status": "published", "id": str(published.get("id", ""))}
    elif not instagram_id or not token:
        result["instagram"] = {"status": "skipped", "reason": "INSTAGRAM_USER_ID or FACEBOOK_ACCESS_TOKEN missing"}
    else:
        result["instagram"] = {"status": "skipped", "reason": "PUBLIC_VIDEO_URL required by Instagram Reels API"}
    return result
