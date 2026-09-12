"""
YouTube upload helper — scheduling tuned for US peak engagement windows.

Scheduling:
- Choose a publish time in the configured timezone within primary windows 12:00-15:00 and 18:00-21:00.
- Apply jitter of +/- settings.schedule_jitter_minutes (clamped to 15-30 minutes).
- Convert the chosen local time to UTC for publishAt.
"""
from __future__ import annotations

import datetime
import logging
import os
import random
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .utils import backoff_with_jitter, is_transient_http_error, sanitize_hashtags

logger = logging.getLogger("mrnextep.youtube")

RESUMABLE_CHUNK_ATTEMPTS = 5


def _load_credentials_from_env() -> Credentials:
    refresh_token = os.getenv("REFRESH_TOKEN", "").strip()
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    token_uri = "https://oauth2.googleapis.com/token"
    if not (refresh_token and client_id and client_secret):
        raise RuntimeError(
            "Missing YouTube credentials in environment "
            "(REFRESH_TOKEN/GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET)"
        )
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    creds.refresh(Request())
    return creds


def _do_videos_insert(youtube_service, body: dict, media: MediaFileUpload) -> dict:
    """Drive a resumable upload, retrying individual chunks.

    A resumable upload must NOT be retried by re-entering videos().insert(): the media
    object has already been partially consumed, so restarting risks a duplicate upload.
    Retries therefore happen per next_chunk() call, which is what "resumable" means.
    """
    request = youtube_service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    attempt = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            attempt = 0
            if status:
                logger.info("YouTube upload progress: %.2f%%", float(status.progress()) * 100.0)
        except Exception as exc:
            attempt += 1
            if attempt >= RESUMABLE_CHUNK_ATTEMPTS or not is_transient_http_error(exc):
                logger.exception("Resumable chunk failed permanently on attempt %d", attempt)
                raise
            wait = backoff_with_jitter(attempt)
            logger.warning(
                "Transient error on resumable chunk (attempt %d/%d): %s; resuming in %.1fs",
                attempt,
                RESUMABLE_CHUNK_ATTEMPTS,
                exc,
                wait,
            )
            import time

            time.sleep(wait)
    return response


def _prepare_snippet_and_status(
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "private",
    schedule_dt: datetime.datetime | None = None,
) -> dict[str, Any]:
    clean_tags = [t.lstrip("#") for t in sanitize_hashtags(tags, max_hashtags=15)]
    snippet = {
        "title": title[:100],
        "description": (description or "")[:5000],
        "tags": clean_tags,
        "categoryId": "28",
    }
    status_body = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
    }
    if schedule_dt:
        utc = schedule_dt.astimezone(datetime.UTC)
        status_body["publishAt"] = utc.isoformat().replace("+00:00", "Z")
    return {"snippet": snippet, "status": status_body}


def _choose_us_peak_time(settings) -> datetime.datetime:
    import datetime as _dt
    from zoneinfo import ZoneInfo

    tz_name = getattr(settings, "timezone", "America/New_York")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("Unknown timezone %r; falling back to UTC for scheduling", tz_name)
        tz = _dt.UTC

    now = _dt.datetime.now(tz)
    # Primary windows: 12:00-15:00 and 18:00-21:00 local time.
    windows = [(12, 15), (18, 21)]
    start_hour, end_hour = random.choice(windows)
    candidate = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + _dt.timedelta(days=1)
    total_minutes = (end_hour - start_hour) * 60
    minute_offset = random.randint(0, total_minutes - 1)
    scheduled_local = candidate + _dt.timedelta(minutes=minute_offset)
    jitter = getattr(settings, "schedule_jitter_minutes", 20)
    jitter = max(15, min(30, int(jitter)))
    jitter_seconds = random.uniform(-jitter * 60, jitter * 60)
    scheduled_local = scheduled_local + _dt.timedelta(seconds=jitter_seconds)
    return scheduled_local.astimezone(tz)


def build_upload_body(script: dict[str, Any], settings) -> dict[str, Any]:
    """Assemble the videos().insert body. Separated from upload() so it is testable
    without network access or credentials."""
    from .seo import build_packages

    seo = build_packages(script).get("youtube", {})
    title = seo.get("title", script.get("title", "")).strip()
    description = seo.get("description", script.get("description", "")).strip()
    tags = seo.get("tags", []) or []

    schedule_dt = None
    if getattr(settings, "schedule_publish", False):
        schedule_dt = _choose_us_peak_time(settings)

    # Read the real field name. A typo here previously fell through getattr's default
    # and forced every upload public, silently overriding YT_PRIVACY_STATUS.
    privacy = getattr(settings, "privacy_status", "private")
    return _prepare_snippet_and_status(title, description, tags, privacy=privacy, schedule_dt=schedule_dt)


def upload(video: Path, script: dict[str, Any], settings) -> dict[str, Any]:
    if settings.dry_run:
        logger.info("Dry run enabled; skipping YouTube upload")
        return {"status": "dry_run", "video": str(video)}

    body = build_upload_body(script, settings)
    logger.info("Uploading with privacyStatus=%s", body["status"]["privacyStatus"])

    try:
        creds = _load_credentials_from_env()
    except Exception as exc:
        logger.exception("Failed to prepare YouTube credentials: %s", exc)
        raise

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    media = MediaFileUpload(str(video), chunksize=5 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    try:
        logger.info("Starting YouTube upload for %s", video)
        resp = _do_videos_insert(youtube, body, media)
        vid = resp.get("id") or resp.get("videoId")
        logger.info("YouTube upload complete, id=%s", vid)
        return {"status": "uploaded", "youtube_video_id": vid, "url": f"https://youtu.be/{vid}"}
    except HttpError as he:
        logger.exception("YouTube API HttpError during upload: %s", he)
        raise
    except Exception:
        logger.exception("Unexpected error during YouTube upload")
        raise
