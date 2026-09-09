"""
YouTube upload helper (refactor).

Improvements made:
- Robust credential refresh using google.oauth2.credentials + google.auth.transport.requests.Request.
- Resumable upload via MediaFileUpload with progress logging.
- Retry decorator (exponential backoff + jitter) around API calls to handle 429/5xx transient failures.
- Randomized scheduling window when scheduling a publishAt time to avoid fully deterministic schedule stamps.
- More explicit, structured logging for diagnostics (quota, invalid content, auth errors).
- Does NOT attempt to hide automation or web-driver fingerprints.

Environment variables expected:
- REFRESH_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
  OR use a local OAuth credentials/token file flow as implemented elsewhere in your repo.
"""
from __future__ import annotations
import os
import logging
import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import retry_on_exception, randomized_window, unique_text_suffix, sanitize_hashtags

logger = logging.getLogger("mrnextep.youtube")


def _load_credentials_from_env() -> Credentials:
    """
    Build Credentials object from environment refresh token and client id/secret if present.
    Falls back to raising if required variables missing (the rest of the repo may provide alternative auth).
    """
    refresh_token = os.getenv("REFRESH_TOKEN", "").strip()
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    token_uri = "https://oauth2.googleapis.com/token"
    if not (refresh_token and client_id and client_secret):
        raise RuntimeError("Missing YouTube credentials in environment (REFRESH_TOKEN/GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET)")
    creds = Credentials(None,
                        refresh_token=refresh_token,
                        token_uri=token_uri,
                        client_id=client_id,
                        client_secret=client_secret,
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    # Attempt a refresh now to ensure token validity; caller should handle exceptions
    creds.refresh(Request())
    return creds


@retry_on_exception(max_attempts=5)
def _do_videos_insert(youtube_service, body: dict, media: MediaFileUpload) -> dict:
    """
    Execute the resumable insert with simple progress logging and return response.
    Wrapped with retry_on_exception so transient failures are retried.
    """
    request = youtube_service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    # MediaFileUpload resumable: use next_chunk() loop
    while response is None:
        status, response = request.next_chunk()
        if status:
            # status.progress() returns fraction [0,1]
            logger.info("YouTube upload progress: %.2f%%", float(status.progress()) * 100.0)
    return response


def _prepare_snippet_and_status(title: str, description: str, tags: List[str], privacy: str = "public",
                                schedule_dt: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """
    Prepare snippet & status payload for YouTube insert.
    Apply minor unique suffix to avoid exact duplicate titles/descriptions when requested.
    """
    # Ensure tags are sanitized
    clean_tags = [t.lstrip("#") for t in sanitize_hashtags(tags, max_hashtags=15)]
    snippet = {
        "title": title[:100],
        "description": (description or "")[:5000],
        "tags": clean_tags,
        "categoryId": "28",  # Science & Technology by default; change if needed
    }
    status_body = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
    }
    if schedule_dt:
        # schedule_dt should be an aware UTC datetime. YouTube expects RFC3339 (ex: 2026-09-10T15:30:00Z)
        # We apply randomized_window externally; here we convert to Zulu
        utc = schedule_dt.astimezone(datetime.timezone.utc)
        status_body["publishAt"] = utc.isoformat().replace("+00:00", "Z")
    return {"snippet": snippet, "status": status_body}


def upload(video: Path, script: dict[str, Any], settings) -> Dict[str, Any]:
    """
    Upload video to YouTube using resumable upload.
    - settings: your repo Settings object (read-only here, only used to check dry_run and schedule_publish)
    Returns a dict with status and youtube_video_id/url when uploaded.
    """
    if settings.dry_run:
        logger.info("Dry run enabled; skipping YouTube upload")
        return {"status": "dry_run", "video": str(video)}

    # Build SEO and tags from your existing SEO builder (it exists in repo)
    from .seo import build_packages
    seo = build_packages(script).get("youtube", {})
    title = seo.get("title", script.get("title", "")).strip()
    description = seo.get("description", script.get("description", "")).strip()
    tags = seo.get("tags", []) or []

    # Light rotation/suffix to reduce exact duplicates (non-invasive)
    suffix = unique_text_suffix(None)
    if suffix:
        title = (title + suffix)[:100]
        description = (description + suffix)[:5000]

    # Scheduling: if settings.schedule_publish is truthy, choose a target and apply jitter
    schedule_dt = None
    if getattr(settings, "schedule_publish", False):
        # If your existing code picks fixed clock times, we instead allow the existing chosen time
        # to be randomized +/- settings.schedule_jitter_minutes (default 30).
        import datetime as _dt
        local_zone = getattr(settings, "local_zone", None)
        # The old code used Asia/Karachi peaks; keep original peaks but add jitter
        peaks = getattr(settings, "publish_peaks_local_hours", (3, 23))
        tz = None
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(local_zone) if local_zone else None
        except Exception:
            tz = None
        now = _dt.datetime.now(tz=_dt.timezone.utc).astimezone(tz) if tz else _dt.datetime.now(_dt.timezone.utc)
        # Find next peak time after now
        candidates = []
        for hour in peaks:
            cand = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if cand <= now:
                cand = cand + _dt.timedelta(days=1)
            candidates.append(cand)
        target = min(candidates)
        jitter_minutes = getattr(settings, "schedule_jitter_minutes", 30)
        schedule_dt = randomized_window(target, jitter_minutes)

    # Load credentials and build API client
    try:
        creds = _load_credentials_from_env()
    except Exception as exc:
        logger.exception("Failed to prepare YouTube credentials: %s", exc)
        raise

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = _prepare_snippet_and_status(title, description, tags, privacy=getattr(settings, "privacy", "public"),
                                       schedule_dt=schedule_dt)

    # MediaFileUpload - choose appropriate mimetype
    media = MediaFileUpload(str(video), chunksize=5 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    try:
        logger.info("Starting YouTube upload for %s", video)
        resp = _do_videos_insert(youtube, body, media)
        vid = resp.get("id") or resp.get("videoId") or resp.get("id")
        logger.info("YouTube upload complete, id=%s", vid)
        return {"status": "uploaded", "youtube_video_id": vid, "url": f"https://youtu.be/{vid}"}
    except HttpError as he:
        logger.exception("YouTube API HttpError during upload: %s", he)
        # Re-raise to let caller handle marking failure/state persistence
        raise
    except Exception:
        logger.exception("Unexpected error during YouTube upload")
        raise
