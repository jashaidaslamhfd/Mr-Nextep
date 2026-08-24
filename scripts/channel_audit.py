#!/usr/bin/env python3
"""One-shot CHANNEL-level audit + branding repair for MrNextep FR.

Checks the things the YouTube algorithm looks at ABOVE single videos:
- channel description (niche clarity + keywords)
- channel keywords field
- defaultLanguage (fr for a French channel)
- avatar / banner / video-watermark presence (read-only — API can't set images)

Mode A (default) = READ audit only.
Mode B (--apply) = writes optimized branding via channels.update.
"""
import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("channel_audit")

NEW_DESCRIPTION = (
    "MrNextep — la science de votre corps expliquée simplement.\n\n"
    "Chaque jour, 3 nouveaux Shorts sur les phénomènes étranges du corps humain :\n"
    "pourquoi vos genoux craquent, pourquoi le temps semble accélérer en vieillissant, "
    "ce que le stress fait à votre cerveau, pourquoi vous entendez votre cœur battre la nuit.\n\n"
    "Science amusante, réponses claires, zéro jargon médical — tout vérifié.\n"
    "Abonnez-vous pour ne jamais rater un fait étonnant. 🧠⚡"
)

NEW_KEYWORDS = (
    'science shorts "corps humain" pourquoi cerveau '
    '"expliqué simplement" "faits étonnants" phénomènes curiosité '
    '"science amusante" santé "culture générale" français'
)


def _access_token() -> str:
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def _api(path, token, *, method="GET", body=None):
    import urllib.error
    import urllib.request

    url = "https://www.googleapis.com/youtube/v3/" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            if r.status == 204:
                return None
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')[:300]}") from e


def audit(item):
    ch = item["snippet"]
    bs = item.get("brandingSettings", {})
    chs = bs.get("channel", {})
    img = bs.get("image", {})
    stats = item.get("statistics", {})
    print("================ CHANNEL AUDIT ================")
    print(f"Title:           {ch.get('title')}")
    print(f"Handle:          {ch.get('customUrl')}")
    print(f"Subscribers:     {stats.get('subscriberCount')} | Views: {stats.get('viewCount')} | Videos: {stats.get('videoCount')}")
    print(f"defaultLanguage: {chs.get('defaultLanguage')!r}")
    print(f"country:         {chs.get('country')!r}")
    print(f"keywords:        {chs.get('keywords')!r}")
    print(f"description len: {len(chs.get('description') or '')}")
    print(f"--- description ---\n{chs.get('description') or '(EMPTY)'}")
    print(f"avatar set:      {'YES' if (ch.get('thumbnails') or {}).get('medium') else 'NO'}")
    print(f"banner set:      {'YES' if img.get('bannerExternalUrl') else 'NO'}  ({(img.get('bannerExternalUrl') or '')[:60]})")
    print(f"watermark set:   {'YES' if img.get('watchIconImageUrl') else 'NO'}")
    print("===============================================")
    issues = []
    if not (chs.get("defaultLanguage") or "").lower().startswith("fr"):
        issues.append("defaultLanguage is not French")
    desc = chs.get("description") or ""
    if len(desc) < 200 or "corps" not in desc.lower():
        issues.append("channel description thin / missing niche keywords")
    if len(chs.get("keywords") or "") < 40:
        issues.append("channel keywords field empty/thin")
    if not img.get("bannerExternalUrl"):
        issues.append("NO channel banner (art) — must be set in YouTube Studio app")
    return issues


def geo_report(token, days=90):
    """Audience geography from YouTube Analytics API (needs yt-analytics.readonly)."""
    import datetime
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    path = ("https://youtubeanalytics.googleapis.com/v2/reports"
            f"?ids=channel==MINE&startDate={start}&endDate={end}"
            "&metrics=views,estimatedMinutesWatched,subscribersGained"
            "&dimensions=country&sort=-views&maxResults=10")
    import urllib.error
    import urllib.request
    req = urllib.request.Request(path)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"GEO: analytics query blocked ({e.code}) — {e.read().decode(errors='replace')[:200]}")
        return
    rows = res.get("rows") or []
    total = sum(r[1] for r in rows) or 1
    print(f"================ AUDIENCE GEOGRAPHY (last {days}d) ================")
    for r in rows:
        print(f"  {r[0]:4} | {r[1]:>7} views ({100*r[1]/total:4.1f}%) | {r[2]:>7} min | +{r[3]} subs")
    print("=================================================================")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    token = _access_token()
    res = _api("channels?part=snippet,brandingSettings,statistics&mine=true", token)
    item = res["items"][0]
    issues = audit(item)
    print("ISSUES FOUND:", len(issues))
    for i in issues:
        print(" -", i)
    geo_report(token)

    if args.apply:
        cid = item["id"]
        body = {"id": cid, "brandingSettings": {"channel": {
            "description": NEW_DESCRIPTION,
            "keywords": NEW_KEYWORDS,
            "defaultLanguage": "fr",
        }}}
        try:
            _api("channels?part=brandingSettings", token, method="PUT", body=body)
            print("APPLY: branding updated (description + keywords + defaultLanguage=fr)")
        except Exception as exc:
            print("APPLY FAILED:", exc)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
