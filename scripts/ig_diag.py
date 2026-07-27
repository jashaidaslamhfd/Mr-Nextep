#!/usr/bin/env python3
"""Instagram diagnostic — why are the Reels getting so few views?

The pipeline records instagram_success=True and stores real media ids, so
the uploads are landing. But nothing in this repo has ever read back what
Instagram itself reports, so there is no way to tell whether the problem is
reach, the account setup, or the content.

Read-only. Pulls, for the linked IG account:
  · account type, follower count, media count
  · per-Reel: plays, reach, likes, comments, saves, shares
  · caption length and hashtag count (IG penalises hashtag stuffing)
  · whether the Reel was shared to the main feed

Env: INSTAGRAM_USER_ID + IG_ACCESS_TOKEN (or FB_ACCESS_TOKEN)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = os.environ.get("FB_API_VERSION", "v23.0")
BASE = f"https://graph.facebook.com/{API_VERSION}"


def _get(path: str, **params) -> dict:
    params["access_token"] = TOKEN
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return {"error": exc.code, "body": body[:400]}
    except Exception as exc:  # noqa: BLE001
        return {"error": "network", "body": str(exc)[:200]}


TOKEN = (os.environ.get("IG_ACCESS_TOKEN") or os.environ.get("FB_ACCESS_TOKEN") or "").strip()
IG_USER = os.environ.get("INSTAGRAM_USER_ID", "").strip()

if not TOKEN or not IG_USER:
    print("INSTAGRAM_USER_ID / access token missing — aborting.")
    sys.exit(1)


def main() -> int:
    report = {}

    print("=" * 62)
    print("ACCOUNT")
    print("=" * 62)
    acct = _get(IG_USER, fields="username,name,followers_count,follows_count,"
                                "media_count,biography,website")
    if "error" in acct:
        print(f"  ERROR: {acct}")
        return 1
    report["account"] = acct
    for key in ("username", "name", "followers_count", "follows_count", "media_count"):
        print(f"  {key:18} {acct.get(key)}")
    bio = acct.get("biography") or ""
    print(f"  {'biography':18} {len(bio)} chars {'(EMPTY)' if not bio else ''}")
    print(f"  {'website':18} {acct.get('website') or '(none)'}")

    print()
    print("=" * 62)
    print("RECENT MEDIA + INSIGHTS")
    print("=" * 62)
    media = _get(f"{IG_USER}/media", limit=25,
                 fields="id,media_type,media_product_type,caption,permalink,"
                        "timestamp,like_count,comments_count")
    items = media.get("data") or []
    if not items:
        print(f"  no media returned: {media}")
        return 1

    rows = []
    for item in items:
        mid = item["id"]
        caption = item.get("caption") or ""
        hashtags = re.findall(r"#\w+", caption)

        # Reels report 'plays'/'reach'; older API versions use 'video_views'.
        ins = _get(f"{mid}/insights", metric="plays,reach,saved,shares")
        metrics = {}
        if "data" in ins:
            for m in ins["data"]:
                vals = m.get("values") or [{}]
                metrics[m["name"]] = vals[0].get("value")
        else:
            metrics["_error"] = str(ins)[:120]

        row = {
            "id": mid,
            "type": item.get("media_product_type") or item.get("media_type"),
            "timestamp": item.get("timestamp"),
            "permalink": item.get("permalink"),
            "likes": item.get("like_count"),
            "comments": item.get("comments_count"),
            "caption_len": len(caption),
            "hashtags": len(hashtags),
            "first_line": caption.split("\n")[0][:60],
            **metrics,
        }
        rows.append(row)

    report["media"] = rows
    print(f"  {'date':11} {'type':7} {'plays':>7} {'reach':>7} {'likes':>6} "
          f"{'tags':>5}  first line")
    for r in rows:
        print(f"  {(r['timestamp'] or '')[:10]:11} {str(r['type'])[:7]:7} "
              f"{str(r.get('plays', '-')):>7} {str(r.get('reach', '-')):>7} "
              f"{str(r.get('likes', '-')):>6} {r['hashtags']:>5}  {r['first_line'][:38]}")

    # ---- summary signals -------------------------------------------------
    plays = [r["plays"] for r in rows if isinstance(r.get("plays"), int)]
    reach = [r["reach"] for r in rows if isinstance(r.get("reach"), int)]
    tags = [r["hashtags"] for r in rows]

    print()
    print("=" * 62)
    print("SIGNALS")
    print("=" * 62)
    if plays:
        print(f"  plays   n={len(plays):2}  avg {sum(plays)//len(plays):>6}  "
              f"min {min(plays)}  max {max(plays)}")
    if reach:
        print(f"  reach   n={len(reach):2}  avg {sum(reach)//len(reach):>6}")
    if plays and reach and sum(reach):
        followers = acct.get("followers_count") or 0
        print(f"  followers {followers} — reach/follower ratio "
              f"{sum(reach)/len(reach)/max(followers,1):.1f}x")
    if tags:
        print(f"  hashtags per post: avg {sum(tags)/len(tags):.1f}  max {max(tags)}")
        if max(tags) > 10:
            print("    ⚠️  >10 hashtags: Instagram treats heavy tagging as spam")
    non_reels = [r for r in rows if str(r.get("type")).upper() != "REELS"]
    if non_reels:
        print(f"  ⚠️  {len(non_reels)} of {len(rows)} posts are NOT Reels "
              f"— those do not enter the Reels feed")

    os.makedirs("data", exist_ok=True)
    with open("data/ig_diag.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print("\nWROTE data/ig_diag.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
