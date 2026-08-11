#!/usr/bin/env python3
"""Delete a batch of duplicate YouTube videos (keep the best performer).

Reads the video ids to delete from a newline/comma separated env var
DELETE_VIDEO_IDS, or from data/duplicate_audit.json (the "delete" entries).
DESTRUCTIVE. Uses repo OAuth env vars.

Usage:
  DELETE_VIDEO_IDS="id1,id2" python scripts/delete_duplicate_batch.py
  python scripts/delete_duplicate_batch.py --from-audit   # use duplicate_audit.json
"""
from __future__ import annotations

import json
import os
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


def main() -> int:
    ids = []
    if "--from-audit" in sys.argv:
        root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        with open(os.path.join(root, "data", "duplicate_audit.json"), encoding="utf-8") as fh:
            audit = json.load(fh)
        for g in audit.get("groups", []):
            ids.extend(d["id"] for d in g.get("delete", []))
    else:
        raw = os.environ.get("DELETE_VIDEO_IDS", "")
        ids = [x.strip() for x in raw.replace("\n", ",").split(",") if x.strip()]

    ids = list(dict.fromkeys(ids))  # dedupe, keep order
    if not ids:
        print("No video ids to delete.", file=sys.stderr)
        return 2

    print(f"Will delete {len(ids)} videos: {', '.join(ids)}")
    token = _token()
    ok, fail = 0, 0
    for vid in ids:
        url = f"https://www.googleapis.com/youtube/v3/videos?id={vid}"
        req = urllib.request.Request(url, method="DELETE",
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"  DELETED {vid} HTTP {resp.status}")
                ok += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            print(f"  FAILED {vid} HTTP {e.code}: {body}", file=sys.stderr)
            fail += 1
    print(f"DONE ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
