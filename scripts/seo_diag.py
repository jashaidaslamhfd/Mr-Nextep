#!/usr/bin/env python3
"""One-shot SEO / algorithm diagnostic for the SKILLOR US channel (READ-ONLY).

Answers ONE question: "why is the algorithm not picking the channel up?"

Pulls (YouTube Analytics API v2 — no Data-API quota cost):
  1. daily_28d         views / impressions / CTR / AVD / subs per day (28 days)
  2. shorts_daily_28d  same, filtered to the Shorts feed traffic source
  3. traffic_28d       which surfaces bring views/impressions
  4. pervideo_28d      per-video impressions + CTR + AVD (top 25)

Plus (YouTube Data API v3 — a few units):
  5. channel           branding / language / stats snapshot
  6. recent_uploads    last 15 uploads (cadence + title/hashtag check)
  7. videos_detail     snippet+stats for those 15 (tags present? category? duration?)

Writes everything to data/seo_diag_<date>.json and prints a human summary.
Stdlib only.
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ANA = "https://youtubeanalytics.googleapis.com/v2/reports?"
DATA = "https://www.googleapis.com/youtube/v3/"


def access_token() -> str:
    body = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def get_json(url: str, token: str):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read()[:400].decode("utf-8", "replace")}


def ana(token, start, end, metrics, dims=None, sort=None, maxr=None, filters=None):
    """Analytics query that self-heals: if the API rejects an unavailable
    metric (400 'Unknown identifier (X)'), drop X and retry, up to 5 times."""
    mets = metrics.split(",")
    for _ in range(5):
        q = {"ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": ",".join(mets)}
        if dims:
            q["dimensions"] = dims
        if sort:
            q["sort"] = sort
        if maxr:
            q["maxResults"] = str(maxr)
        if filters:
            q["filters"] = filters
        res = get_json(ANA + urllib.parse.urlencode(q), token)
        if "error" not in res:
            res["_dropped_metrics"] = [m for m in metrics.split(",") if m not in mets]
            return res
        import re as _re
        m = _re.search(r"Unknown identifier \(([\w]+)\)", res.get("body", ""))
        if res["error"] == 400 and m and m.group(1) in mets and len(mets) > 1:
            print(f"metric '{m.group(1)}' unavailable -> retrying without it")
            mets.remove(m.group(1))
            continue
        return res
    return res


def main() -> int:
    tok = access_token()
    today = dt.date.today()
    start = (today - dt.timedelta(days=28)).isoformat()
    end = today.isoformat()
    out = {"window": {"start": start, "end": end, "generated_at_utc": dt.datetime.utcnow().isoformat()}}

    out["daily_28d"] = ana(tok, start, end,
        "views,impressions,impressionsClickThroughRate,averageViewDuration,subscribersGained,likes,shares,comments",
        dims="day")
    out["shorts_daily_28d"] = ana(tok, start, end,
        "views,impressions,impressionsClickThroughRate,engagedViews,averageViewDuration",
        dims="day", filters="insightTrafficSourceType==SHORTS")
    out["traffic_28d"] = ana(tok, start, end,
        "views,impressions,impressionsClickThroughRate,averageViewDuration",
        dims="insightTrafficSourceType", sort="-views")
    out["pervideo_28d"] = ana(tok, start, end,
        "views,averageViewDuration,likes,comments,shares,subscribersGained",
        dims="video", sort="-views", maxr=25)

    ch = get_json(DATA + "channels?part=snippet,statistics,brandingSettings,contentDetails&mine=true", tok)
    out["channel"] = ch
    try:
        upl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = get_json(DATA + "playlistItems?part=snippet,contentDetails&maxResults=15&playlistId=" + upl, tok)
        out["recent_uploads"] = pl
        ids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])]
        if ids:
            out["videos_detail"] = get_json(
                DATA + "videos?part=snippet,statistics,contentDetails&id=" + ",".join(ids), tok)
    except Exception as e:  # noqa: BLE001
        out["recent_uploads_error"] = str(e)

    os.makedirs("data", exist_ok=True)
    path = f"data/seo_diag_{today.strftime('%Y%m%d')}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("WROTE", path)

    # --- compact human summary for the log ---
    def tbl(rep):
        hdr = [c["name"] for c in rep.get("columnHeaders", [])]
        return hdr, rep.get("rows", [])

    if "error" in out["daily_28d"]:
        print("daily_28d ERROR:", out["daily_28d"])
    else:
        hdr, rows = tbl(out["daily_28d"])
        print("DAILY", hdr)
        for r in rows:
            print("  ", r)
    if "error" in out["traffic_28d"]:
        print("traffic ERROR:", out["traffic_28d"])
    else:
        hdr, rows = tbl(out["traffic_28d"])
        print("TRAFFIC", hdr)
        for r in rows:
            print("  ", r)
    if "error" in out["shorts_daily_28d"]:
        print("shorts_daily ERROR:", out["shorts_daily_28d"])
    else:
        hdr, rows = tbl(out["shorts_daily_28d"])
        print("SHORTS DAILY", hdr)
        for r in rows:
            print("  ", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
