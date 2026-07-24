#!/usr/bin/env python3
"""One-shot Facebook Page tune-up for the SKILLOR FB presence (Mr. Nextep).

The automated Reels pipeline already posts clean, Facebook-native captions
(since 2026-07-22).  This script fixes what came BEFORE that and finishes
the page set-up, all idempotently:

  1. legacy caption cleanup — Reels uploaded before the caption fix carry
     YouTube artifacts (duplicated lines, "#Shorts", space-broken hashtags,
     "Subscribe for more", keyword-stuffed "Learn the science behind a, b,
     c" sentences).  Each such Reel caption is rebuilt hook + answer +
     follow CTA + 2-3 clean hashtags and PATCHed back onto the video.
  2. page long description — set `description` if empty.
  3. CTA button — "Learn More" pointing at the YouTube channel (best
     effort; needs pages_manage_engagement which the token may lack).
  4. pinned welcome post — one permanent intro post with the YouTube link,
     created and pinned only if no welcome post exists yet.

Every action is isolated (try/except) so one missing permission never kills
the rest.  Writes data/fb_tuneup_<date>.json and prints a human summary.
Set FB_TUNEUP_DRY=1 to preview without any writes.  Stdlib only.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("FB_API_VERSION", "v23.0").strip()
TOKEN = os.environ.get("FB_ACCESS_TOKEN", "")
PAGE = os.environ.get("FB_PAGE_ID", "")
DRY = os.environ.get("FB_TUNEUP_DRY") == "1"
YT_LINK = "https://youtube.com/@mrnextep"
PACE = float(os.environ.get("FB_TUNEUP_PACE", "0.4"))  # s between API calls

if not TOKEN or not PAGE:
    print("FB_ACCESS_TOKEN / FB_PAGE_ID missing — aborting.")
    sys.exit(1)

LEGACY_CUTOFF = "2026-07-22"  # captions posted from this date on are clean
DEFAULT_TAGS = ["humanbody", "bodyscience", "brainfacts", "sciencefacts"]
FOLLOW_CTA = "Follow for daily body science."

report = {"generated_at_utc": dt.datetime.utcnow().isoformat(), "api": API,
          "dry_run": DRY, "actions": []}


def note(action, status, detail=""):
    entry = {"action": action, "status": status, "detail": str(detail)[:400]}
    report["actions"].append(entry)
    print(f"[{status}] {action}: {str(detail)[:220]}")


def _gget_raw(path, **params):
    params["access_token"] = TOKEN
    url = f"https://graph.facebook.com/{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read()[:400].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return {"error": "network", "body": str(e)[:200]}


def gpost(path, **params):
    params["access_token"] = TOKEN
    url = f"https://graph.facebook.com/{API}/{path}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    for attempt in range(3):  # retry transient app-rate-limit (#4)
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                time.sleep(PACE)
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read()[:400].decode("utf-8", "replace")
            if "#4" in body and attempt < 2:
                time.sleep(75)
                continue
            return {"error": e.code, "body": body}
        except Exception as e:  # noqa: BLE001
            return {"error": "network", "body": str(e)[:200]}
    return {"error": "ratelimit", "body": "app request limit after retries"}


def gget(path, **params):
    time.sleep(PACE)
    return _gget_raw(path, **params)


# ---------------------------------------------------------------- captions
def is_legacy(desc: str, created: str) -> bool:
    if not desc or (created or "") >= LEGACY_CUTOFF:
        return False
    d = desc.lower()
    if "#shorts" in d or "subscribe" in d:
        return True
    lines = [l.strip() for l in desc.splitlines() if l.strip()]
    if len({l.lower() for l in lines}) != len(lines):  # duplicated lines
        return True
    if re.search(r"#[A-Za-z]+ [a-z]", desc):  # space-broken hashtag rows
        return True
    if "science behind" in d and d.count(",") >= 2:
        return True
    return False


def rebuild_caption(desc: str) -> str:
    """Legacy caption -> clean hook + answer + CTA + hashtags."""
    lines = [re.sub(r"\s+", " ", l).strip() for l in desc.splitlines()]
    lines = [l for l in lines if l]
    kept, seen = [], set()
    for line in lines:
        low = line.lower().rstrip(".")
        if low in seen:
            continue
        seen.add(low)
        if low.startswith("subscribe for more"):
            continue  # replaced by the follow CTA below
        if line.count("#") >= 2:
            continue  # hashtag rows are rebuilt at the end
        # drop keyword-stuffed "Learn the science behind a, b, c" tails,
        # keeping an informative first sentence on the same line if present
        if "science behind" in low and line.count(",") >= 2:
            head = re.split(r"(?:Learn the science behind|Learn how)\b", line)[0].strip(" .")
            if len(head) >= 25 and head.lower().rstrip(".") not in seen:
                kept.append(head)
                seen.add(head.lower().rstrip("."))
            continue
        kept.append(line)
    body = "\n\n".join(kept[:3]).strip()

    # Legacy captions only ever carried space-broken junk (#human body ...) or
    # keyword fragments, so their hashtags are unusable.  Pick a topic-matched
    # clean set from the caption body instead.
    low_body = body.lower()
    if any(w in low_body for w in ("brain", "memor", "déjà", "deja",
                                   "thought", "neuro", "sleep", "dream")):
        chosen = ["brainfacts", "brainscience", "neuroscience"]
    else:
        chosen = DEFAULT_TAGS[:3]
    parts = [body, FOLLOW_CTA, " ".join(f"#{t}" for t in chosen)]
    return "\n\n".join(p for p in parts if p)[:2200]


def fix_legacy_captions():
    reels = gget(f"{PAGE}/video_reels", limit=50,
                 fields="id,created_time,description")
    data = reels.get("data")
    if data is None:
        note("legacy caption cleanup", "error", reels.get("body", reels))
        return
    for reel in data:
        desc = reel.get("description") or ""
        if not is_legacy(desc, reel.get("created_time", "")):
            continue
        new_desc = rebuild_caption(desc)
        if new_desc.strip() == desc.strip():
            continue
        if DRY:
            note("legacy caption cleanup", "dry",
                 f"reel {reel['id']}: would replace caption -> {new_desc[:80]!r}")
            continue
        res = gpost(reel["id"], description=new_desc)
        if "error" in res:
            note("legacy caption cleanup", "blocked",
                 f"reel {reel['id']}: {res.get('body', res)}")
        else:
            check = gget(reel["id"], fields="description")
            ok = (check.get("description") or "").strip() == new_desc.strip()
            note("legacy caption cleanup", "ok" if ok else "unverified",
                 f"reel {reel['id']} caption rewritten")


# ---------------------------------------------------------------- page
PAGE_DESCRIPTION = (
    "Mr. Nextep explains the weird things your body and brain do — in "
    "under a minute. Body glitches, brain quirks and everyday science "
    "mysteries, answered simply. New short videos daily.\n\n"
    f"Watch on YouTube: {YT_LINK}")


def tune_page_fields():
    info = gget(PAGE, fields="id,description,about")
    if "error" in info:
        note("page long description", "error", info.get("body", info))
    elif (info.get("description") or "").strip():
        note("page long description", "skip", "already set")
    elif DRY:
        note("page long description", "dry", "would set long description")
    else:
        res = gpost(PAGE, description=PAGE_DESCRIPTION)
        note("page long description",
             "ok" if "error" not in res and res.get("success") else "blocked",
             res.get("body", res.get("success")))

    if DRY:
        note("CTA button -> YouTube", "dry", "would add LEARN_MORE button")
    else:
        cta = json.dumps([{"type": "LEARN_MORE", "value": {"link": YT_LINK}}])
        res = gpost(PAGE, ctas=cta)
        note("CTA button -> YouTube",
             "ok" if "error" not in res else "blocked",
             res.get("body", res.get("success", "set")))


def welcome_post():
    feed = gget(f"{PAGE}/feed", limit=25, fields="id,message")
    post_id = next((p["id"] for p in feed.get("data", [])
                    if "welcome to mr. nextep" in (p.get("message") or "").lower()),
                   None)
    if DRY:
        note("pinned welcome post", "dry",
             f"would {'pin existing' if post_id else 'create + pin'} welcome post")
        return
    if not post_id:
        msg = ("Welcome to Mr. Nextep 🧠\n\n"
               "Your body does weird things — goosebumps from music, a falling "
               "feeling when you are half asleep, ringing ears at night — and we "
               "explain why, in under a minute.\n\n"
               "New body & brain science every day. Start anywhere, follow along.\n\n"
               f"More on YouTube: {YT_LINK}")
        res = gpost(f"{PAGE}/feed", message=msg)
        if "error" in res:
            note("pinned welcome post", "blocked", res.get("body", res))
            return
        post_id = res.get("id", "")
    pin = gpost(post_id, is_pinned="true")
    note("pinned welcome post",
         "ok" if "error" not in pin else "posted (pin blocked)",
         f"post {post_id} " + ("pinned" if "error" not in pin
                               else str(pin.get("body", ""))[:150]))


def main() -> int:
    fix_legacy_captions()
    tune_page_fields()
    welcome_post()

    date = dt.datetime.utcnow().strftime("%Y%m%d")
    path = os.path.join("data", f"fb_tuneup_{date}.json")
    os.makedirs("data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    ok = sum(1 for a in report["actions"] if a["status"] == "ok")
    blocked = sum(1 for a in report["actions"] if "blocked" in a["status"])
    print(f"\nFB tune-up summary: {ok} applied, {blocked} blocked "
          f"(see {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
