"""
YouTube upload helper (refactor) — scheduling tuned for US peak engagement windows.

Scheduling changes:
- Choose a publish time in US Eastern (America/New_York) primary windows: 12:00-15:00 and 18:00-21:00.
- Apply jitter of +/- settings.schedule_jitter_minutes (default 30) or tightened to 15-30 minutes for US timing.
- Convert the chosen local time to UTC for publishAt.
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
    creds.refresh(Request())
    return creds


@retry_on_exception(max_attempts=5)
def _do_videos_insert(youtube_service, body: dict, media: MediaFileUpload) -> dict:
    request = youtube_service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("YouTube upload progress: %.2f%%", float(status.progress()) * 100.0)
    return response


def _prepare_snippet_and_status(title: str, description: str, tags: List[str], privacy: str = "public",
                                schedule_dt: Optional[datetime.datetime] = None) -> Dict[str, Any]:
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
        utc = schedule_dt.astimezone(datetime.timezone.utc)
        status_body["publishAt"] = utc.isoformat().replace("+00:00", "Z")
    return {"snippet": snippet, "status": status_body}


def _choose_us_peak_time(settings) -> datetime.datetime:
    import datetime as _dt
    from zoneinfo import ZoneInfo

    tz_name = getattr(settings, "timezone", "America/New_York")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = _dt.timezone.utc

    now = _dt.datetime.now(tz)
    # Define windows in hours (24h) in local tz (assume Eastern for definition)
    # Primary windows: 12:00-15:00 and 18:00-21:00 local (EST)
    windows = [(12, 15), (18, 21)]
    # Choose a random window to post into
    window = random.choice(windows)
    start_hour, end_hour = window
    # If current time is before today's window start, schedule today; else schedule next day
    candidate = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        # schedule next day in the same window
        candidate = candidate + _dt.timedelta(days=1)
    # pick a random minute within the window
    total_minutes = (end_hour - start_hour) * 60
    minute_offset = random.randint(0, total_minutes - 1)
    scheduled_local = candidate + _dt.timedelta(minutes=minute_offset)
    # Apply jitter of +/- settings.schedule_jitter_minutes (min 15, max 30 recommended)
    jitter = getattr(settings, "schedule_jitter_minutes", 20)
    jitter = max(15, min(30, int(jitter)))
    jitter_seconds = random.uniform(-jitter * 60, jitter * 60)
    scheduled_local = scheduled_local + _dt.timedelta(seconds=jitter_seconds)
    # Return aware datetime in tz
    return scheduled_local.astimezone(tz)


def upload(video: Path, script: dict[str, Any], settings) -> Dict[str, Any]:
    if settings.dry_run:
        logger.info("Dry run enabled; skipping YouTube upload")
        return {"status": "dry_run", "video": str(video)}

    from .seo import build_packages
    seo = build_packages(script).get("youtube", {})
    title = seo.get("title", script.get("title", "")).strip()
    description = seo.get("description", script.get("description", "")).strip()
    tags = seo.get("tags", []) or []

    suffix = unique_text_suffix(None)
    if suffix:
        title = (title + suffix)[:100]
        description = (description + suffix)[:5000]

    schedule_dt = None
    if getattr(settings, "schedule_publish", False):
        # Select a US peak time (EST primarily) with jitter
        schedule_dt = _choose_us_peak_time(settings)

    try:
        creds = _load_credentials_from_env()
    except Exception as exc:
        logger.exception("Failed to prepare YouTube credentials: %s", exc)
        raise

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = _prepare_snippet_and_status(title, description, tags, privacy=getattr(settings, "privacy", "public"),
                                       schedule_dt=schedule_dt)

    media = MediaFileUpload(str(video), chunksize=5 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    try:
        logger.info("Starting YouTube upload for %s", video)
        resp = _do_videos_insert(youtube, body, media)
        vid = resp.get("id") or resp.get("videoId") or resp.get("id")
        logger.info("YouTube upload complete, id=%s", vid)
        return {"status": "uploaded", "youtube_video_id": vid, "url": f"https://youtu.be/{vid}"}
    except HttpError as he:
        logger.exception("YouTube API HttpError during upload: %s", he)
        raise
    except Exception:
        logger.exception("Unexpected error during YouTube upload")
        raise
