#!/usr/bin/env python3
"""Meta (Facebook + Instagram) reach diagnostic — WHY are views so low?

The existing tools answer "did it upload?" (yes) and "what is the reach?"
(~100). Neither can distinguish the only two explanations that matter:

  A) DISTRIBUTION problem — Meta is barely showing the Reel to anyone.
     Signature: tiny reach, but the people who DO see it watch a healthy
     share of the video.
  B) RETENTION problem — Meta shows it, viewers swipe away instantly, so
     the algorithm stops showing it.
     Signature: reach is small AND average watch time is a few seconds.

The deciding number is `ig_reels_avg_watch_time` (milliseconds) compared
against the video's own length. Nothing in this repo has ever fetched it.

Everything here is READ-ONLY.

Also probes, and reports honestly, which Facebook fields/metrics this
page token can actually read — the token currently lacks read_insights,
so per-Reel FB views are NOT available and any tool claiming otherwise
would be fabricating. We record the exact error instead.

Env: INSTAGRAM_USER_ID, IG_ACCESS_TOKEN or FB_ACCESS_TOKEN, FB_PAGE_ID
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("FB_API_VERSION") or "v23.0"
BASE = f"https://graph.facebook.com/{API}"
TOKEN = (os.environ.get("IG_ACCESS_TOKEN") or os.environ.get("FB_ACCESS_TOKEN") or "").strip()
IG_USER = os.environ.get("INSTAGRAM_USER_ID", "").strip()
PAGE = os.environ.get("FB_PAGE_ID", "").strip()

# Pipeline renders 40-55s videos (TARGET_MIN_SECONDS / TARGET_MAX_SECONDS).
# Used only to turn avg-watch-time into an approximate completion rate when
# the platform does not expose the clip's own duration.
ASSUMED_LEN_S = float(os.environ.get("ASSUMED_VIDEO_SECONDS", "47"))


def _get(path: str, **params):
    params["access_token"] = TOKEN
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=45) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = body[:200]
        return {"error": exc.code, "message": msg}
    except Exception as exc:  # noqa: BLE001
        return {"error": "network", "message": str(exc)[:200]}


def probe_metrics(node: str, candidates: list) -> dict:
    """Ask for each metric SEPARATELY.

    Meta fails the entire insights call when any single requested metric is
    unsupported for that media product type, which is exactly how the old
    diagnostic lost every metric to one bad name. One call per metric costs
    more requests but can never lose a working metric to a broken one.
    """
    got, unsupported = {}, {}
    for metric in candidates:
        res = _get(f"{node}/insights", metric=metric)
        if "data" in res and res["data"]:
            values = res["data"][0].get("values") or [{}]
            got[metric] = values[0].get("value")
        else:
            unsupported[metric] = res.get("message", str(res))[:110]
    return {"ok": got, "unsupported": unsupported}


IG_MEDIA_METRICS = [
    "views", "reach", "saved", "shares", "comments", "likes",
    "total_interactions", "profile_visits", "follows",
    "ig_reels_avg_watch_time", "ig_reels_video_view_total_time",
]

FB_PAGE_METRICS = [
    "page_media_view", "page_follows", "page_post_engagements",
    "page_views_total", "page_impressions", "page_impressions_unique",
    "page_video_views", "page_daily_follows_unique",
]


def main() -> int:
    if not TOKEN:
        print("No access token — aborting.")
        return 1

    report = {"generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "api": API, "assumed_video_seconds": ASSUMED_LEN_S}

    # ------------------------------------------------------------------
    # INSTAGRAM
    # ------------------------------------------------------------------
    print("=" * 70)
    print("INSTAGRAM")
    print("=" * 70)
    rows = []
    if IG_USER:
        acct = _get(IG_USER, fields="username,followers_count,media_count")
        report["ig_account"] = acct
        print(f"  @{acct.get('username')}  followers={acct.get('followers_count')}  "
              f"media={acct.get('media_count')}")

        media = _get(f"{IG_USER}/media", limit=25,
                     fields="id,media_product_type,caption,permalink,timestamp,"
                            "like_count,comments_count")
        for item in media.get("data", []):
            mid = item["id"]
            caption = item.get("caption") or ""
            probe = probe_metrics(mid, IG_MEDIA_METRICS)
            ok = probe["ok"]

            watch_ms = ok.get("ig_reels_avg_watch_time")
            watch_s = round(watch_ms / 1000.0, 1) if isinstance(watch_ms, (int, float)) else None
            completion = (round(100.0 * watch_s / ASSUMED_LEN_S, 1)
                          if watch_s is not None else None)

            rows.append({
                "id": mid,
                "timestamp": item.get("timestamp"),
                "permalink": item.get("permalink"),
                "type": item.get("media_product_type"),
                "caption_len": len(caption),
                "hashtags": len(re.findall(r"#\w+", caption)),
                "first_line": caption.split("\n")[0][:60],
                "avg_watch_s": watch_s,
                "approx_completion_pct": completion,
                **ok,
                "_unsupported": probe["unsupported"],
            })
        report["ig_media"] = rows

        print()
        print(f"  {'date':11} {'views':>6} {'reach':>6} {'shares':>6} {'saves':>6} "
              f"{'watch_s':>8} {'compl%':>7}  hook")
        for r in rows:
            print(f"  {(r['timestamp'] or '')[:10]:11} "
                  f"{str(r.get('views', '-')):>6} {str(r.get('reach', '-')):>6} "
                  f"{str(r.get('shares', '-')):>6} {str(r.get('saved', '-')):>6} "
                  f"{str(r.get('avg_watch_s', '-')):>8} "
                  f"{str(r.get('approx_completion_pct', '-')):>7}  {r['first_line'][:34]}")

        watched = [r["avg_watch_s"] for r in rows if r.get("avg_watch_s") is not None]
        if watched:
            avg = sum(watched) / len(watched)
            pct = 100.0 * avg / ASSUMED_LEN_S
            report["ig_avg_watch_seconds"] = round(avg, 1)
            report["ig_approx_completion_pct"] = round(pct, 1)
            print()
            print(f"  AVG WATCH TIME  {avg:.1f}s of ~{ASSUMED_LEN_S:.0f}s  "
                  f"= {pct:.1f}% watched")
            # Interpretation is stated as a rule, not as a conclusion, so the
            # reader can check it against the number themselves.
            if pct < 20:
                print("  -> RETENTION-dominant: viewers are swiping away early.")
            elif pct < 40:
                print("  -> MIXED: watch time is weak but not collapsed.")
            else:
                print("  -> DISTRIBUTION-dominant: the few who see it do watch; "
                      "Meta simply is not showing it widely.")
        else:
            print("\n  avg watch time NOT served for this account "
                  "(see _unsupported in the JSON).")

        unsup = {}
        for r in rows:
            unsup.update(r.get("_unsupported", {}))
        if unsup:
            print("\n  metrics this account does NOT serve:")
            for k, v in unsup.items():
                print(f"    {k:32} {v[:80]}")

    # ------------------------------------------------------------------
    # FACEBOOK
    # ------------------------------------------------------------------
    print()
    print("=" * 70)
    print("FACEBOOK PAGE")
    print("=" * 70)
    if PAGE:
        page = _get(PAGE, fields="name,followers_count,fan_count")
        report["fb_page"] = page
        print(f"  {page.get('name')}  followers={page.get('followers_count')}")

        pm = probe_metrics(PAGE, FB_PAGE_METRICS)
        report["fb_page_insights"] = pm
        print("\n  page insights (latest day):")
        for k, v in pm["ok"].items():
            print(f"    {k:28} {v}")
        if pm["unsupported"]:
            print("  blocked / unsupported:")
            for k, v in pm["unsupported"].items():
                print(f"    {k:28} {v[:80]}")

        # 28-day trend on whatever page metric works: is reach falling,
        # flat, or was it never there? A flat floor across 28 days argues
        # against "the algorithm punished us recently".
        since = (dt.date.today() - dt.timedelta(days=28)).isoformat()
        trend = _get(f"{PAGE}/insights", metric="page_media_view",
                     period="day", since=since, until=dt.date.today().isoformat())
        series = []
        if "data" in trend and trend["data"]:
            for point in trend["data"][0].get("values", []):
                series.append({"date": (point.get("end_time") or "")[:10],
                               "value": point.get("value")})
        report["fb_media_view_28d"] = series
        if series:
            print(f"\n  page_media_view, last {len(series)} days:")
            print("    " + " ".join(str(p["value"]) for p in series))
            vals = [p["value"] for p in series if isinstance(p["value"], int)]
            if vals:
                print(f"    min={min(vals)} max={max(vals)} avg={sum(vals)/len(vals):.0f}")
        else:
            print(f"\n  page_media_view trend unavailable: "
                  f"{trend.get('message', trend)}")

        # Per-Reel view counts: prove availability rather than assume it.
        reels = _get(f"{PAGE}/video_reels", limit=5,
                     fields="id,created_time,length,description")
        probes = []
        for reel in reels.get("data", [])[:3]:
            rid = reel["id"]
            entry = {"id": rid, "created_time": reel.get("created_time"),
                     "length": reel.get("length")}
            for field in ("views", "post_views", "video_view_count"):
                res = _get(rid, fields=field)
                entry[field] = res.get(field, res.get("message", "?"))
            ins = _get(f"{rid}/video_insights", metric="total_video_views")
            entry["video_insights"] = ("OK" if "data" in ins
                                       else ins.get("message", "?")[:90])
            probes.append(entry)
        report["fb_reel_probes"] = probes
        print("\n  per-Reel view availability probe:")
        for p in probes:
            print(f"    {p['id']}  len={p.get('length')}  "
                  f"views={str(p.get('views'))[:40]}  "
                  f"insights={str(p.get('video_insights'))[:60]}")

    os.makedirs("data", exist_ok=True)
    with open("data/meta_reach_diag.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print("\nWROTE data/meta_reach_diag.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
