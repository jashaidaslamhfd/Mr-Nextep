#!/usr/bin/env python3
"""Delete a specific YouTube video by ID (destructive — use carefully).

Uses the repo's OAuth env vars (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET /
REFRESH_TOKEN). Set VIDEO_ID env to the video to delete.

Usage:
  VIDEO_ID=<id> python scripts/delete_duplicate_video.py
"""
from __future__ import annotations

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
        return __import__("json").load(resp)["access_token"]


def main() -> int:
    vid = os.environ.get("VIDEO_ID", "").strip()
    if not vid:
        print("VIDEO_ID env is required", file=sys.stderr)
        return 2

    token = _token()
    url = f"https://www.googleapis.com/youtube/v3/videos?id={vid}"
    req = urllib.request.Request(
        url, method="DELETE",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"DELETED {vid} HTTP {resp.status}")
            return 0
    except urllib.error.HTTPError as e:
        print(f"DELETE {vid} FAILED HTTP {e.code}: {e.read().decode()[:300]}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
