#!/usr/bin/env python3
"""List ALL channel uploads with privacy + publishAt, flag scheduled ones."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _token():
    payload = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=payload)
    return json.load(urllib.request.urlopen(req, timeout=30))["access_token"]


def _q(path, params, token):
    url = f"https://www.googleapis.com/youtube/v3/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def main():
    token = _token()
    chan = _q("channels", {"part": "contentDetails", "mine": "true"}, token)
    playlist = chan["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], None
    while True:
        p = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50}
        if page:
            p["pageToken"] = page
        d = _q("playlistItems", p, token)
        for it in d.get("items", []):
            ids.append(it["contentDetails"]["videoId"])
        page = d.get("nextPageToken")
        if not page:
            break
    now = datetime.now(timezone.utc)
    vids = []
    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        d = _q("videos", {"part": "snippet,status", "id": ",".join(batch)}, token)
        for it in d.get("items", []):
            snip, st = it.get("snippet", {}), it.get("status", {})
            pub = snip.get("publishedAt", "")
            try:
                pdt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                future = pdt > now
            except Exception:
                future = False
            vids.append({
                "id": it["id"], "title": snip.get("title", ""),
                "privacy": st.get("privacyStatus"), "publishAt": pub,
                "scheduled": st.get("privacyStatus") == "private" and future,
            })
    vids.sort(key=lambda v: v["publishAt"] or "")
    print(json.dumps(vids, indent=2, ensure_ascii=False))
    sched = [v for v in vids if v["scheduled"]]
    print(f"# SCHEDULED={len(sched)} TOTAL={len(vids)}", file=sys.stderr)


if __name__ == "__main__":
    main()
