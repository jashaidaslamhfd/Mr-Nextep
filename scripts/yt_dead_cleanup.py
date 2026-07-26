#!/usr/bin/env python3
"""Operation Cleanup (2026-07-26) — delete algorithm-dead uploads.

Fresh 87-video time-vs-views analysis: these 8 uploads have <=10 views
after >=7 days live. YouTube's recommendation system has already fully
evaluated and rejected them; they earn nothing, and dead uploads are the
only "view blocker" left on a channel whose metadata is 100% clean
(0 dup topics, all Shorts, all en-US). Removing them is zero-risk.

The 23 videos in the <50-views watchlist are KEPT — underperforming is
not the same as rejected, and search/suggested can still revive them.

DRY by default; pass --apply to delete for real.
Needs GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / REFRESH_TOKEN env.
"""
import argparse
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("yt-dead-cleanup")

DELETE_IDS = {
    "V2gHiQavBhE": "1 view in 37 days (Why Your Body Does This: Dark Truth)",
    "BZnUB9qH9HY": "3 views in 9 days (Your Brain Lies to You Every Hour)",
    "kFcfVOFsVJQ": "6 views in 20 days (Your Blood's Dark Secret Weapon)",
    "iwxP015WTz8": "7 views in 13 days (Lungs Can Drown You From Inside)",
    "D6Io-EiUs-s": "7 views in 20 days (Blood's Silent Alarm: Midnight Weapon)",
    "vgfHHr2bszo": "8 views in 14 days (Brain Forgets Names)",
    "mIL8aW2QpCs": "9 views in 12 days (Body Clock Controls Your Sleep)",
    "3UJG2yavzKk": "9 views in 15 days (Why Your Body Does This: Pain Enigma)",
}


def _token() -> str:
    data = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(
            urllib.request.Request("https://oauth2.googleapis.com/token", data=data),
            timeout=30) as r:
        return json.load(r)["access_token"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    token = _token()
    deleted, failed = 0, 0
    for vid, why in DELETE_IDS.items():
        if not args.apply:
            log.info("[dry] would DELETE %s (%s)", vid, why)
            continue
        try:
            req = urllib.request.Request(
                f"https://www.googleapis.com/youtube/v3/videos?id={vid}", method="DELETE")
            req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=40) as r:
                r.read()
            deleted += 1
            log.info("DELETED %s (%s)", vid, why)
        except Exception as exc:
            failed += 1
            log.error("FAILED %s (%s): %s", vid, why, exc)
        time.sleep(1)
    log.info("done (apply=%s, deleted=%d, failed=%d)", args.apply, deleted, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
