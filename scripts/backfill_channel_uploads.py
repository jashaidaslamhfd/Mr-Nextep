#!/usr/bin/env python3
"""Backfill channel's own uploads into data/video_history.json.

2026-08-15 gap fix: the daily analytics sync only *refreshes metrics of
videos already in history* — it never discovers new uploads. When a
generation run fails before recording (or an upload happens through any
other path), history drifts behind the real channel, starving the ML
brain of reality. This script pulls the channel's OWN uploads playlist
(via the same OAuth token) and adds any missing videos to history so
metrics refresh and ML training always see the full catalog.

Run: python scripts/backfill_channel_uploads.py [--limit 50]
"""
import os
import sys
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "data" / "video_history.json"


def _client():
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials

    token = Credentials(
        token=os.environ["REFRESH_TOKEN"] if False else None,
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        refresh_token=os.environ["REFRESH_TOKEN"],
    )
    return build("youtube", "v3", credentials=token)


def _existing_ids(history):
    seen = set()
    for entry in history:
        vid = (entry.get("youtube_video_id") or "").strip()
        if vid:
            seen.add(vid)
    return seen


def main() -> int:
    if not all(os.environ.get(k) for k in
               ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "REFRESH_TOKEN")):
        logger.error("YouTube OAuth secrets not set; skipping backfill.")
        return 0

    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8")) if HISTORY_PATH.exists() else []
    existing = _existing_ids(history)

    yt = _client()
    # 1. Resolve the channel + uploads playlist for the authenticated user.
    me = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
    items = me.get("items") or []
    if not items:
        logger.warning("Authenticated user has no YouTube channel; nothing to backfill.")
        return 0
    uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    logger.info("Backfilling uploads playlist %s", uploads_id)

    limit = int(os.environ.get("BACKFILL_LIMIT", "50"))
    added = []
    next_token = None
    fetched = 0
    while fetched < limit:
        req = yt.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=uploads_id,
            maxResults=min(50, limit - fetched),
            pageToken=next_token,
        )
        resp = req.execute()
        for item in resp.get("items") or []:
            vid = item["contentDetails"]["videoId"]
            fetched += 1
            if vid in existing:
                continue
            snippet = item.get("snippet") or {}
            added.append({
                "youtube_video_id": vid,
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "posted_at": snippet.get("publishedAt", ""),
                "views": 0,
                "source": "channel_backfill",
                "analytics_fetched_at": None,
            })
        next_token = resp.get("nextPageToken")
        if not next_token:
            break

    if added:
        logger.info("Adding %d previously untracked channel videos to history", len(added))
        history.extend(added)
        HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    else:
        logger.info("History already covers all %d fetched uploads", fetched)
    return 0


if __name__ == "__main__":
    sys.exit(main())
