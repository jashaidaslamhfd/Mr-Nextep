from __future__ import annotations
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from config import Settings

def upload(video: Path, script: dict[str, Any], settings: Settings) -> dict[str, str]:
    if settings.dry_run: return {"status": "dry_run", "video": str(video)}
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token", client_id=os.environ["GOOGLE_CLIENT_ID"], client_secret=os.environ["GOOGLE_CLIENT_SECRET"], scopes=["https://www.googleapis.com/auth/youtube.upload"])
    creds.refresh(Request()); youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    status: dict[str, object] = {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    if settings.schedule_publish:
        # Heatmap display is the operator's PKT local time. Schedule at the
        # selected daily peak, not merely at the workflow start time.
        local_zone = ZoneInfo("Asia/Karachi")
        now_local = datetime.now(UTC).astimezone(local_zone)
        peak_hour = {0: 20, 1: 20, 2: 20, 3: 20, 4: 21, 5: 19, 6: 19}[now_local.weekday()]
        target = now_local.replace(hour=peak_hour, minute=0, second=0, microsecond=0)
        if target <= now_local: target += timedelta(days=1)
        status["publishAt"] = target.astimezone(UTC).isoformat().replace("+00:00", "Z")
    result = youtube.videos().insert(part="snippet,status", body={"snippet": {"title": script["title"][:100], "description": script["description"][:5000], "tags": script.get("tags", []), "categoryId": "28", "defaultLanguage": "en", "defaultAudioLanguage": "en"}, "status": status}, media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True)).execute()
    return {"status": "uploaded", "youtube_video_id": result["id"], "url": f"https://youtu.be/{result['id']}"}
