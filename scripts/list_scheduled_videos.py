#!/usr/bin/env python3
"""Diagnostic: list ALL channel uploads with privacy status + publishAt +
title, so we can see which videos are SCHEDULED (private with a future
publishAt) and detect any that duplicate a recently-uploaded video's title.

READ-ONLY. Uses the repo's OAuth env vars (GOOGLE_CLIENT_ID /
GOOGLE_CLIENT_SECRET / REFRESH_TOKEN). Prints JSON to stdout.

Usage:
  python scripts/list_scheduled_videos.py            # all videos
  python scripts/list_scheduled_videos.py --only-scheduled
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _token() -> str:
    payload = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=payload
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["access_token"]


def _query(path: str, params: dict, token: str) -> dict:
    url = f"https://www.googleapis.com/youtube/v3/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> int:
    only_scheduled = "--only-scheduled" in sys.argv
    token = _token()

    # 1. find uploads playlist id
    chan = _query("channels", {
        "part": "contentDetails", "mine": "true",
    }, token)
    playlist = chan["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # 2. page through playlistItems to get all video ids
    ids = []
    page = None
    while True:
        params = {
            "part": "contentDetails", "playlistId": playlist, "maxResults": 50,
        }
        if page:
            params["pageToken"] = page
        data = _query("playlistItems", params, token)
        for item in data.get("items", []):
            ids.append(item["contentDetails"]["videoId"])
        page = data.get("nextPageToken")
        if not page:
            break

    # 3. fetch status + snippet (title, publishAt) in batches of 50
    videos = []
    now = datetime.now(timezone.utc)
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        data = _query("videos", {
            "part": "snippet,status", "id": ",".join(batch),
        }, token)
        for it in data.get("items", []):
            snip = it.get("snippet", {})
            st = it.get("status", {})
            privacy = st.get("privacyStatus")
            publish_at = snip.get("publishedAt", "")
            title = snip.get("title", "")
            try:
                pdt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
                is_future = pdt > now
            except Exception:
                pdt, is_future = None, False
            is_scheduled = (privacy == "private" and is_future)
            videos.append({
                "id": it["id"], "title": title,
                "privacy": privacy, "publishAt": publish_at,
                "scheduled": is_scheduled,
            })

    if only_scheduled:
        videos = [v for v in videos if v["scheduled"]]

    videos.sort(key=lambda v: v.get("publishAt") or "", reverse=True)
    print(json.dumps(videos, indent=2, ensure_ascii=False))
    print(f"# TOTAL={len(videos)} SCHEDULED={sum(1 for v in videos if v['scheduled'])}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
