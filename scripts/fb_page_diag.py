#!/usr/bin/env python3
"""One-shot Facebook Page diagnostic for the MrNextep FB presence (read-only).

Answers: "is the FB side actually working, and how big is it?"

Pulls (Meta Graph API, page token from secrets):
  1. page info      — name / followers / about / category / cover-photo presence
  2. recent reels   — last 15 Reels with likes/comments (+ views when the
                      token has insights perms; records warnings otherwise)
  3. recent posts   — last 5 text posts (daily-question engagement check)

Writes data/fb_diag_<date>.json and prints a human summary.  Stdlib only.
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("FB_API_VERSION", "v21.0")
TOKEN = os.environ["FB_ACCESS_TOKEN"]
PAGE = os.environ["FB_PAGE_ID"]


def gget(path: str, **params):
    params["access_token"] = TOKEN
    url = f"https://graph.facebook.com/{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read()[:400].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return {"error": "network", "body": str(e)[:200]}


def main() -> int:
    out = {"generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"), "api": API}

    out["page"] = gget(PAGE, fields="id,name,about,category,category_list,"
                                    "followers_count,fan_count,link,website,cover")
    out["reels"] = gget(f"{PAGE}/video_reels", limit=15,
                        fields="id,created_time,description,permalink_url")
    reels = out["reels"].get("data", [])
    stats = []
    for reel in reels[:15]:
        rid = reel["id"]
        s = {"id": rid, "created_time": reel.get("created_time"),
             "caption": (reel.get("description") or "")[:90]}
        soc = gget(rid, fields="likes.summary(true),comments.summary(true)")
        if "error" not in soc:
            s["likes"] = soc.get("likes", {}).get("summary", {}).get("total_count")
            s["comments"] = soc.get("comments", {}).get("summary", {}).get("total_count")
        ins = gget(f"{rid}/video_insights", metric="total_video_views")
        if "error" not in ins:
            try:
                s["views"] = ins["data"][0]["values"][0]["value"]
            except Exception:  # noqa: BLE001
                pass
        else:
            s.setdefault("views_note", ins.get("body", "")[:120])
        stats.append(s)
    out["reel_stats"] = stats
    out["posts"] = gget(f"{PAGE}/posts", limit=5, fields="id,created_time,message")

    # Page-level growth metrics (verified working with the new full-perms
    # token; per-reel view counts are not API-exposed on New-Experience pages).
    page_metrics = {}
    for metric in ("page_media_view", "page_follows", "page_views_total",
                   "page_post_engagements"):
        res = gget(f"{PAGE}/insights", metric=metric, period="day")
        if "error" not in res:
            try:
                vals = res["data"][0].get("values", [])
                page_metrics[metric] = vals[-1]["value"] if vals else None
            except Exception:  # noqa: BLE001
                pass
    out["page_insights"] = page_metrics

    os.makedirs("data", exist_ok=True)
    path = f"data/fb_diag_{dt.date.today().strftime('%Y%m%d')}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("WROTE", path)

    print(json.dumps(out.get("page", {}), ensure_ascii=False, indent=1)[:700])
    print("page insights (yesterday):", page_metrics)
    for s in stats:
        print(f"{(s.get('created_time') or '')[:16]} | views={s.get('views','?')} "
              f"L={s.get('likes','?')} C={s.get('comments','?')} | {s.get('caption','')[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
