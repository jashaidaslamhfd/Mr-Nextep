#!/usr/bin/env python3
"""US SEO sweep — repair descriptions on every published video.

Audit of the live MrNextep channel (2026-07-27) found two faults in every
single published description:

1. BROKEN HASHTAGS — multi-word tags were emitted with the space intact:

       #Shorts #brain facts #brain science #neuroscience
       #Shorts #human body #body science #sudden

   YouTube parses "#brain facts" as the hashtag "#brain" followed by the
   loose word "facts". So the intended hashtags never existed, the channel
   got a generic "#brain" instead, and the description ends in dangling
   words. Every video was affected.

2. FILLER KEYWORDS IN THE CONTEXT LINE — the description's keyword sentence
   was built from unfiltered tags:

       "Learn the science behind brain facts, brain science, neuroscience,
        having."
       "Learn the science behind human body, body science, sudden, charley."

   A trailing bare gerund reads as broken English to a viewer and carries no
   search intent.

Both are fixed in src/seo_generator.py for NEW videos; this script repairs
the ones already online.

Safety:
  - DRY-RUN by default, --apply to write
  - never touches titles (the short-title format is this channel's winner:
    830/795/652/988 views vs 77-179 for the older long titles)
  - never deletes anything
  - YouTube clears omitted snippet fields, so title/categoryId/language are
    resent unchanged

Env: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / REFRESH_TOKEN
"""
import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("us-seo-sweep")

API = "https://www.googleapis.com/youtube/v3"

# Bare verbs / loose adjectives with no search intent. Mirrors
# _TITLE_STOP_WORDS in src/seo_generator.py.
FILLER = {
    "a", "an", "and", "are", "at", "does", "do", "for", "from", "helps",
    "how", "in", "is", "it", "make", "of", "on", "the", "this", "to", "what",
    "when", "why", "with", "your", "you", "having", "being", "getting",
    "doing", "going", "making", "taking", "feeling", "happens", "happening",
    "sudden", "suddenly", "really", "very", "just", "some", "more", "most",
    "other", "such", "into", "about", "after", "before", "while", "during",
    "because", "that", "these", "those", "there", "here", "then", "than",
    "also", "even", "charley", "stuck", "own", "new", "old", "big", "small",
    "good", "bad",
}


def _token() -> str:
    """Bare refresh grant — never send `scope`; Google rejects any refresh
    that tries to narrow the scopes a token was minted with."""
    data = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    request = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["access_token"]


def _req(method: str, url: str, token: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if body:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        log.error("%s %s -> %s: %s", method, url.split("?")[0], exc.code,
                  exc.read().decode("utf-8", "replace")[:250])
        raise


def _all_video_ids(token: str) -> list:
    channel = _req("GET", f"{API}/channels?part=contentDetails&mine=true", token)
    uploads = channel["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], None
    while True:
        url = f"{API}/playlistItems?part=contentDetails&playlistId={uploads}&maxResults=50"
        if page:
            url += f"&pageToken={page}"
        data = _req("GET", url, token)
        ids += [i["contentDetails"]["videoId"] for i in data.get("items", [])]
        page = data.get("nextPageToken")
        if not page:
            return ids


def as_hashtag(word: str) -> str:
    """'brain facts' -> 'BrainFacts' (a hashtag cannot contain a space)."""
    return "".join(ch for ch in word.replace("_", " ").title().replace(" ", "")
                   if ch.isalnum())


def fix_description(description: str) -> tuple:
    """Return (new_description, report)."""
    original = description or ""
    lines = original.split("\n")
    report = {"hashtags_fixed": 0, "filler_removed": []}
    out = []

    for line in lines:
        stripped = line.strip()

        # --- hashtag line -------------------------------------------------
        if stripped.startswith("#"):
            # Re-parse: "#brain facts #body science" -> ["brain facts",
            # "body science"] by splitting on '#' rather than whitespace.
            chunks = [c.strip() for c in stripped.split("#") if c.strip()]
            rebuilt, seen = [], set()
            for chunk in chunks:
                # Apply the same filler rule as the context line, so a word
                # dropped there ("sudden") does not survive as "#Sudden".
                if chunk.lower() in FILLER:
                    report["filler_removed"].append(chunk)
                    continue
                token = as_hashtag(chunk)
                if len(token) > 2 and token.lower() not in seen:
                    seen.add(token.lower())
                    rebuilt.append("#" + token)
            if rebuilt:
                new_line = " ".join(rebuilt[:4])
                if new_line != stripped:
                    report["hashtags_fixed"] += 1
                out.append(new_line)
            continue

        # --- keyword context line ------------------------------------------
        if stripped.startswith("Learn the science behind"):
            match = re.match(r"(Learn the science behind )(.+?)\.(.*)$", stripped, re.S)
            if match:
                head, middle, tail = match.groups()
                terms = [t.strip() for t in middle.split(",") if t.strip()]
                kept = []
                for term in terms:
                    if term.lower() in FILLER or len(term) < 3:
                        report["filler_removed"].append(term)
                        continue
                    kept.append(term)
                if kept:
                    out.append(f"{head}{', '.join(kept)}.{tail}")
                continue

        out.append(line)

    cleaned = "\n".join(out).strip()[:4900]
    report["chars_saved"] = len(original) - len(cleaned)
    return cleaned, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write to YouTube")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    token = _token()
    ids = _all_video_ids(token)
    if args.limit:
        ids = ids[:args.limit]
    log.info("%d videos on the channel (mode %s)", len(ids),
             "APPLY" if args.apply else "DRY-RUN")

    changed, report_rows = 0, []
    for index in range(0, len(ids), 50):
        chunk = ",".join(ids[index:index + 50])
        data = _req("GET", f"{API}/videos?part=snippet,statistics&id={chunk}", token)
        for video in data.get("items", []):
            vid = video["id"]
            snippet = video["snippet"]
            views = int(video.get("statistics", {}).get("viewCount", 0) or 0)
            new_desc, rep = fix_description(snippet.get("description", ""))

            if new_desc == (snippet.get("description") or "").strip():
                continue

            changed += 1
            report_rows.append({"video_id": vid, "title": snippet.get("title"),
                                "views": views, **rep})
            log.info("[%s] %s (%d views)", vid, (snippet.get("title") or "")[:46], views)
            if rep["hashtags_fixed"]:
                log.info("    - hashtag line rebuilt (spaces removed)")
            if rep["filler_removed"]:
                log.info("    - filler keywords dropped: %s", rep["filler_removed"])

            if args.apply:
                payload = {
                    "id": vid,
                    "snippet": {
                        "title": snippet.get("title"),          # untouched
                        "description": new_desc,
                        "tags": snippet.get("tags", []),        # untouched
                        "categoryId": snippet.get("categoryId", "28"),
                        "defaultLanguage": snippet.get("defaultLanguage", "en"),
                        "defaultAudioLanguage": snippet.get("defaultAudioLanguage", "en"),
                    },
                }
                _req("PUT", f"{API}/videos?part=snippet", token, payload)
                log.info("    ✅ updated")
                time.sleep(1)

    os.makedirs("output", exist_ok=True)
    with open("output/us_seo_sweep.json", "w", encoding="utf-8") as handle:
        json.dump({"mode": "apply" if args.apply else "dry-run",
                   "scanned": len(ids), "changed": changed,
                   "videos": report_rows}, handle, ensure_ascii=False, indent=2)

    log.info("Done: %d/%d videos %s", changed, len(ids),
             "updated" if args.apply else "need fixing (dry-run)")
    if not args.apply and changed:
        log.info("Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
