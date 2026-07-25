#!/usr/bin/env python3
"""One-shot REPAIR for the faults found by scripts/fb_page_audit.py
(audit 2026-07-25, Mr. Nextep page 1122980080905302).

1. Welcome post posted EIGHT times (tune-up's 25-item feed scan kept
   losing it — guard now fixed with a durable repo marker). DELETE the 7
   older copies, KEEP the newest (2026-07-25).

2. "Forgetting names" content posted twice (text post x2 + reel x2):
   DELETE the older text post and the older reel.

3. Two baby-era reels (2026-07-04, pre-niche-shift) have only a bare
   title as their caption: REBUILD captions properly.

4. 23 reels have NO hashtags at all: append a standard body-science
   hashtag block (22 after removing the dup reel deleted in step 2).

Run DRY by default; pass --apply to write. Stdlib only.
Env: FB_ACCESS_TOKEN, FB_PAGE_ID.
"""
import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fb-repair")

API = os.environ.get("FB_API_VERSION", "v23.0").strip()
TOKEN = os.environ["FB_ACCESS_TOKEN"]
PAGE = os.environ["FB_PAGE_ID"]

DELETE_POST_IDS = {
    # welcome-post duplicates — KEEP the newest one (…49577351165, 07-25 14:48)
    "1122980080905302_122122947825351165": "welcome dup 2/8 (07-25 14:43)",
    "1122980080905302_122122781241351165": "welcome dup 3/8 (07-24 20:42)",
    "1122980080905302_122122773531351165": "welcome dup 4/8 (07-24 19:51)",
    "1122980080905302_122122772769351165": "welcome dup 5/8 (07-24 19:49)",
    "1122980080905302_122122772097351165": "welcome dup 6/8 (07-24 19:44)",
    "1122980080905302_122122713921351165": "welcome dup 7/8 (07-24 13:30)",
    "1122980080905302_122122705533351165": "welcome dup 8/8 (07-24 12:45)",
    "1122980080905302_122114681277351165": "older 'forgetting names' text post copy",
}
DELETE_VIDEO_IDS = {
    "1733591804494122": "caption-duplicate reel ('forgetting names', 06-25 17:03)",
}
RECAPTION = {
    "1345906440366316": (
        "Attachment Theory in 60 Seconds\n\n"
        "Your brain wires itself for connection from the very first day — here is "
        "the science of why, in under a minute.\n\n"
        "#AttachmentTheory #BrainFacts #BodyScience #MrNextep #Shorts"
    ),
    "1780810203076642": (
        "Why Babies Need to Crawl Before Walking\n\n"
        "Skipping the crawling stage changes how the brain maps movement and "
        "balance — the science in 60 seconds.\n\n"
        "#BrainFacts #BodyScience #ChildDevelopment #MrNextep #Shorts"
    ),
}
HASHTAG_BLOCK = "\n\n#BodyScience #WeirdFacts #BrainFacts #MrNextep #Shorts"
HASHTAG_APPEND_IDS = [
    "1345906440366316", "1780810203076642", "1663567374903296",
    "1045777861212266", "947830784988145", "1047646771023317",
    "1432392458952501", "2142936766267529", "2110486596201470",
    "1038855332426025", "844276145183200", "1006828912076419",
    "995139406605549", "1323304896113007", "4304682836438200",
    "993487203545365", "1002266265854965", "4040564796240873",
    "3314378625410338", "2171677247008570", "2524117774699365",
    "863548253034850",
]  # 22 ids; the 23rd (1733591804494122) is deleted above


def _call(method: str, url: str, params: dict | None = None):
    params = dict(params or {})
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params).encode() if method != "GET" else None
    if method == "GET":
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read().decode("utf-8", "replace")
            return json.loads(body) if body.strip() else {"success": True}
    except Exception as e:  # noqa: BLE001
        body = getattr(e, "read", lambda: b"")() or b""
        return {"error": getattr(e, "code", "network"),
                "body": body[:250].decode("utf-8", "replace") if isinstance(body, bytes) else str(body)[:250]}


def _get_desc(vid: str) -> str:
    res = _call("GET", f"https://graph.facebook.com/{API}/{vid}",
                {"fields": "description"})
    return res.get("description", "") if "error" not in res else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    stats = {"deleted": 0, "recaptioned": 0, "hashtagged": 0, "errors": 0}

    for pid, why in DELETE_POST_IDS.items():
        if not args.apply:
            log.info("[dry] would DELETE post %s (%s)", pid, why)
            continue
        res = _call("DELETE", f"https://graph.facebook.com/{API}/{pid}")
        if "error" in res:
            stats["errors"] += 1
            log.warning("delete post %s failed: %s", pid, res)
        else:
            stats["deleted"] += 1
            log.info("DELETED post %s (%s)", pid, why)
        time.sleep(0.6)

    for vid, why in DELETE_VIDEO_IDS.items():
        if not args.apply:
            log.info("[dry] would DELETE reel %s (%s)", vid, why)
            continue
        res = _call("DELETE", f"https://graph.facebook.com/{API}/{vid}")
        if "error" in res:
            stats["errors"] += 1
            log.warning("delete reel %s failed: %s", vid, res)
        else:
            stats["deleted"] += 1
            log.info("DELETED reel %s (%s)", vid, why)
        time.sleep(0.6)

    for vid, new_desc in RECAPTION.items():
        if not args.apply:
            log.info("[dry] would RECAPTION reel %s", vid)
            continue
        res = _call("POST", f"https://graph.facebook.com/{API}/{vid}",
                    {"description": new_desc})
        if "error" in res:
            stats["errors"] += 1
            log.warning("recaption %s failed: %s", vid, res)
        else:
            stats["recaptioned"] += 1
            log.info("RECAPTIONED reel %s", vid)
        time.sleep(0.6)

    for vid in HASHTAG_APPEND_IDS:
        if not args.apply:
            log.info("[dry] would APPEND hashtags to reel %s", vid)
            continue
        desc = _get_desc(vid)
        if not desc:
            stats["errors"] += 1
            log.warning("hashtag append %s: could not read description — skipped", vid)
            continue
        if "#" in desc:
            log.info("reel %s already has hashtags — skipped", vid)
            continue
        res = _call("POST", f"https://graph.facebook.com/{API}/{vid}",
                    {"description": desc + HASHTAG_BLOCK})
        if "error" in res:
            stats["errors"] += 1
            log.warning("hashtag append %s failed: %s", vid, res)
        else:
            stats["hashtagged"] += 1
            log.info("HASHTAGGED reel %s", vid)
        time.sleep(0.6)

    log.info("done (apply=%s) %s", args.apply, stats)
    print(json.dumps({"date": dt.date.today().isoformat(),
                      "apply": args.apply, **stats}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
