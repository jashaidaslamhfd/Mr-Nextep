#!/usr/bin/env python3
"""Read-only AUDIT of the SKILLOR Facebook Page ("Mr. Nextep").

Checks EVERYTHING the Meta algorithm + monetization review look at:

  PAGE
    page_about_missing / page_website_missing / page_cover_missing
    page_cta_missing (call-to-action button — API reports when readable)
  REELS (full list, not just recent)
    reel_caption_empty       description < 40 chars
    reel_title_unbranded     first line lacks the "Mr. Nextep |" brand mark
    reel_no_hashtag          no '#' anywhere in the caption
    reel_cover_missing       reel id not present in data/fb_thumbs_done.json
                             (the custom-cover ledger written by fb_tuneup)
    reel_caption_duplicate   same normalized caption as another reel
  POSTS (feed)
    post_duplicate           same normalized text as another post
                             (the "welcome post posted 3x" incident)
  TOKEN
    read_insights YES/NO (needed for reel-view analytics)

Writes data/fb_audit_<date>.json + human summary. Stdlib only, READ-ONLY.
Env: FB_ACCESS_TOKEN, FB_PAGE_ID (workflow maps FACEBOOK_ACCESS_TOKEN).
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("FB_API_VERSION", "v23.0")
TOKEN = os.environ["FB_ACCESS_TOKEN"]
PAGE = os.environ["FB_PAGE_ID"]
MARKER_PATH = os.environ.get("FB_THUMBS_MARKER", "data/fb_thumbs_done.json")


def gget(path: str, **params):
    params["access_token"] = TOKEN
    params.setdefault("limit", 100)
    url = f"https://graph.facebook.com/{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read()[:300].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return {"error": "network", "body": str(e)[:200]}


def gget_all(path: str, **params):
    items, guard = [], 0
    data = gget(path, **params)
    while guard < 20:
        for item in data.get("data", []):
            items.append(item)
        nxt = (data.get("paging") or {}).get("next")
        if not nxt:
            return items, None
        guard += 1
        try:
            with urllib.request.urlopen(urllib.request.Request(nxt), timeout=40) as r:
                data = json.load(r)
        except Exception as e:  # noqa: BLE001
            return items, f"pagination stopped: {e}"
    return items, "pagination guard hit"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def main() -> int:
    out = {"generated_at_utc": dt.datetime.utcnow().isoformat(), "api": API}
    faults = {}

    # ---------- page ----------
    page = gget(PAGE, fields="id,name,about,description,category,website,link,"
                             "followers_count,fan_count,cover")
    out["page"] = page
    page_faults = []
    if "error" in page:
        page_faults.append(f"page_read_failed ({page['error']})")
    else:
        if not (page.get("about") or page.get("description")):
            page_faults.append("page_about_missing")
        if not page.get("website"):
            page_faults.append("page_website_missing")
        if not (page.get("cover") or {}).get("source"):
            page_faults.append("page_cover_missing")
        followers = page.get("followers_count", page.get("fan_count"))
        out["followers"] = followers
    # CTA button (Meta may refuse without pages_manage_metadata)
    cta = gget(f"{PAGE}", fields="call_to_actions")
    out["cta_probe"] = cta
    if "error" in cta:
        page_faults.append("page_cta_unknown(insufficient perms to read)")
    elif not (cta.get("call_to_actions", {}) or {}).get("data"):
        page_faults.append("page_cta_missing")
    faults["page"] = page_faults

    # ---------- reels ----------
    thumbs_done = set()
    if os.path.exists(MARKER_PATH):
        try:
            thumbs_done = set(json.load(open(MARKER_PATH)))
        except Exception:  # noqa: BLE001
            pass
    reels, perr = gget_all(f"{PAGE}/video_reels",
                           fields="id,created_time,description,permalink_url")
    if perr:
        out["reels_pagination_note"] = perr
    reel_faults = {}
    caption_registry = {}
    for reel in reels:
        rid = reel["id"]
        desc = reel.get("description") or ""
        rf = []
        if len(desc.strip()) < 40:
            rf.append("reel_caption_empty")
        first_line = desc.strip().splitlines()[0] if desc.strip() else ""
        if "nextep" not in first_line.lower():
            rf.append("reel_title_unbranded")
        if "#" not in desc:
            rf.append("reel_no_hashtag")
        if rid not in thumbs_done:
            rf.append("reel_cover_missing")
        caption_registry.setdefault(_norm(desc), []).append(rid)
        if rf:
            reel_faults[rid] = {
                "created": reel.get("created_time"),
                "first_line": first_line[:70],
                "desc_len": len(desc),
                "faults": rf,
            }
    reel_dups = {k: v for k, v in caption_registry.items() if len(v) > 1 and k}
    for ids in reel_dups.values():
        for rid in ids:
            reel_faults.setdefault(rid, {"created": None, "first_line": "",
                                         "desc_len": 0, "faults": []})
            reel_faults[rid]["faults"].append("reel_caption_duplicate")
    out["reels_total"] = len(reels)
    out["reels_faulty"] = len(reel_faults)
    out["reel_faults"] = reel_faults

    # ---------- posts ----------
    posts, _ = gget_all(f"{PAGE}/posts", fields="id,created_time,message")
    post_registry = {}
    for post in posts:
        post_registry.setdefault(_norm(post.get("message", "")), []).append(
            (post["id"], post.get("created_time"), (post.get("message") or "")[:60]))
    post_dups = {k: v for k, v in post_registry.items() if len(v) > 1 and k}
    out["posts_total"] = len(posts)
    out["post_duplicates"] = list(post_dups.values())

    # ---------- token perms ----------
    ins = gget(f"{PAGE}/insights", metric="page_impressions", period="day")
    out["read_insights"] = ("error" not in ins)

    # ---------- summary ----------
    from collections import Counter
    counter = Counter()
    counter.update(f for f in faults["page"] if not f.startswith("page_cta_unknown"))
    for rf in reel_faults.values():
        counter.update(rf["faults"])
    if post_dups:
        counter["post_duplicate"] = sum(len(v) for v in post_dups.values())
    out["fault_counts"] = dict(counter.most_common())
    path = f"data/fb_audit_{dt.date.today().isoformat()}.json"
    os.makedirs("data", exist_ok=True)
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1)

    print("=" * 64)
    print(f"FB PAGE AUDIT — Mr. Nextep — {dt.date.today().isoformat()}")
    if "error" not in page:
        print(f"page: {page.get('name')} | followers: {out.get('followers')}")
    print(f"reels: {len(reels)} (faulty {len(reel_faults)}) | posts: {len(posts)} "
          f"(dup groups {len(post_dups)}) | read_insights: {out['read_insights']}")
    print("-" * 64)
    for fault, count in counter.most_common():
        print(f"  {fault:26s} {count}")
    print("-" * 64)
    for rid, rf in sorted(reel_faults.items(),
                          key=lambda kv: -len(kv[1]["faults"])):
        print(f"  reel {rid}  {sorted(set(rf['faults']))}")
        print(f"      {rf['created']} | {rf['first_line']}")
    for dup in out["post_duplicates"]:
        print(f"  DUP POST x{len(dup)}:")
        for pid, created, msg in dup:
            print(f"      {pid}  {created}  {msg}")
    print(f"\nsaved -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
