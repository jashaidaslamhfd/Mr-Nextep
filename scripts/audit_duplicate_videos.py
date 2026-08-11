#!/usr/bin/env python3
"""Diagnostic: list ALL channel uploads with view counts, grouped by
(normalised) title, so we can see duplicate-title videos and pick the best
performer to keep. READ-ONLY.

Uses the repo's OAuth env vars (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET /
REFRESH_TOKEN). Writes data/duplicate_audit.json (committed by workflow).

Usage:
  python scripts/audit_duplicate_videos.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request


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


def _norm(title: str) -> str:
    """Normalise a title: lower, strip punctuation/emoji/whitespace."""
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", " ", title or "")
    t = re.sub(r"[^a-z0-9 ]", "", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def main() -> int:
    token = _token()
    chan = _query("channels", {"part": "contentDetails", "mine": "true"}, token)
    playlist = chan["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    ids = []
    page = None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50}
        if page:
            params["pageToken"] = page
        data = _query("playlistItems", params, token)
        for item in data.get("items", []):
            ids.append(item["contentDetails"]["videoId"])
        page = data.get("nextPageToken")
        if not page:
            break

    videos = []
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        data = _query("videos", {
            "part": "snippet,status,statistics", "id": ",".join(batch),
        }, token)
        for it in data.get("items", []):
            snip = it.get("snippet", {})
            st = it.get("status", {})
            stats = it.get("statistics", {})
            videos.append({
                "id": it["id"],
                "title": snip.get("title", ""),
                "privacy": st.get("privacyStatus"),
                "publishAt": snip.get("publishedAt", ""),
                "views": int(stats.get("viewCount") or 0),
                "likes": int(stats.get("likeCount") or 0),
                "comments": int(stats.get("commentCount") or 0),
                "norm_title": _norm(snip.get("title", "")),
            })

    # group by norm_title
    groups = {}
    for v in videos:
        groups.setdefault(v["norm_title"], []).append(v)

    # duplicate groups only
    dups = {nt: members for nt, members in groups.items()
            if len(members) > 1}

    out = {
        "total_videos": len(videos),
        "duplicate_groups": len(dups),
        "duplicate_extra_count": sum(len(m) - 1 for m in dups.values()),
        "groups": [],
    }
    for nt, members in sorted(dups.items(), key=lambda kv: -len(kv[1])):
        # best = most views; tie -> most recent
        ranked = sorted(members, key=lambda v: (v["views"], v["publishAt"]), reverse=True)
        keep = ranked[0]
        out["groups"].append({
            "title": ranked[0]["title"],
            "normalized": nt,
            "count": len(members),
            "keep": {"id": keep["id"], "views": keep["views"],
                     "publishAt": keep["publishAt"]},
            "delete": [{"id": v["id"], "views": v["views"],
                        "publishAt": v["publishAt"]} for v in ranked[1:]],
        })

    out_path = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "duplicate_audit.json"
    ))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    print(f"TOTAL={len(videos)} DUP_GROUPS={len(dups)} EXTRA_TO_DELETE={out['duplicate_extra_count']}")
    for g in out["groups"]:
        print(f"  [{g['count']}x] {g['title'][:50]!r} | keep={g['keep']['id']}({g['keep']['views']}v) "
              f"delete=" + ",".join(f"{d['id']}({d['views']}v)" for d in g["delete"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
