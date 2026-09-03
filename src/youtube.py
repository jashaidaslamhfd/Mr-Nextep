from __future__ import annotations
import os
from datetime import UTC, datetime, timedelta
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
    if settings.schedule_publish: status["publishAt"] = (datetime.now(UTC) + timedelta(minutes=15)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result = youtube.videos().insert(part="snippet,status", body={"snippet": {"title": script["title"][:100], "description": script["description"][:5000], "tags": script.get("tags", []), "categoryId": "28", "defaultLanguage": "en", "defaultAudioLanguage": "en"}, "status": status}, media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True)).execute()
    return {"status": "uploaded", "youtube_video_id": result["id"], "url": f"https://youtu.be/{result['id']}"}
