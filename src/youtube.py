from __future__ import annotations
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from config import Settings
from seo import build_packages

def upload(video: Path, script: dict[str, Any], settings: Settings) -> dict[str, str]:
    if settings.dry_run: return {"status": "dry_run", "video": str(video)}
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token", client_id=os.environ["GOOGLE_CLIENT_ID"], client_secret=os.environ["GOOGLE_CLIENT_SECRET"], scopes=["https://www.googleapis.com/auth/youtube.upload"])
    creds.refresh(Request()); youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    seo = build_packages(script)["youtube"]
    status: dict[str, object] = {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    if settings.schedule_publish:
        # The channel is US-first (64.7% US viewers in the supplied analytics).
        # The supplied PKT heatmap converts to these US Eastern peak hours.
        local_zone = ZoneInfo("America/New_York")
        now_local = datetime.now(UTC).astimezone(local_zone)
        peak_hours = {0: (11, 13), 1: (11, 13), 2: (11, 13), 3: (11, 13), 4: (12, 14), 5: (10, 12), 6: (10, 12)}[now_local.weekday()]
        targets = [now_local.replace(hour=hour, minute=0, second=0, microsecond=0) for hour in peak_hours]
        target = next((item for item in targets if item > now_local), None)
        if target is None:
            next_day = now_local + timedelta(days=1)
            next_hours = {0: (11, 13), 1: (11, 13), 2: (11, 13), 3: (11, 13), 4: (12, 14), 5: (10, 12), 6: (10, 12)}[next_day.weekday()]
            target = next_day.replace(hour=next_hours[0], minute=0, second=0, microsecond=0)
        status["publishAt"] = target.astimezone(UTC).isoformat().replace("+00:00", "Z")
    result = youtube.videos().insert(part="snippet,status", body={"snippet": {"title": seo["title"], "description": seo["description"][:5000], "tags": seo["tags"], "categoryId": "28", "defaultLanguage": "en", "defaultAudioLanguage": "en"}, "status": status}, media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True)).execute()
    return {"status": "uploaded", "youtube_video_id": result["id"], "url": f"https://youtu.be/{result['id']}"}
