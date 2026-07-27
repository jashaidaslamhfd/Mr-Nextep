#!/usr/bin/env python3
"""Backfill Reel covers by matching the FULL caption to a YouTube title.

23 Reels still have no cover. They are all pre-pipeline uploads (Jun 24 -
Jul 25), so video_history.json has no entry to match against and the exact
hook-text map used for the first 9 cannot reach them.

What it does differently from the tune-up's date-order guesser:
  · reads the WHOLE caption, not just the first line. The opening line is a
    clickbait template ("Most parents don't know this about...", "Your brain
    is ALREADY..."), which is identical across dozens of Reels and matches
    nothing. The real topic sits in the body.
  · scores against the actual YouTube title of every cover on disk.
  · requires a strong overlap. A wrong cover misrepresents the video to
    every viewer, so anything uncertain is skipped rather than guessed.

Read-only unless --apply. Never touches titles or captions.

Env: FB_ACCESS_TOKEN + FB_PAGE_ID
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("FB_API_VERSION", "v23.0")
TOKEN = (os.environ.get("FB_ACCESS_TOKEN") or "").strip()
PAGE = (os.environ.get("FB_PAGE_ID") or "").strip()
THUMB_DIR = os.path.join(ROOT, "assets", "thumbnails_us")
DONE_PATH = os.path.join(ROOT, "data", "fb_thumbs_done.json")
MAP_PATH = os.path.join(ROOT, "data", "fb_cover_map.json")
PACE = 0.5

# Clickbait scaffolding shared by dozens of Reels — it carries no topic.
STOP = {
    "the", "a", "an", "your", "you", "this", "that", "is", "are", "to", "of",
    "in", "on", "and", "why", "what", "how", "it", "its", "for", "with",
    "about", "does", "do", "most", "dont", "don", "know", "already", "right",
    "now", "truth", "scientists", "doctors", "want", "parents", "explained",
    "seconds", "but", "why", "here", "was", "were", "been", "have", "has",
    "can", "will", "just", "like", "get", "got", "one", "two", "not", "all",
    "more", "than", "then", "when", "who", "our", "out", "off", "into",
    "they", "them", "their", "there", "these", "those", "some", "any",
    "comment", "share", "tag", "follow", "agree", "yes", "mind", "blew",
    "someone", "needs", "see", "daily", "body", "science", "shorts",
}


def words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower())
            if len(w) > 2 and w not in STOP}


def _get(path: str, **params) -> dict:
    params["access_token"] = TOKEN
    url = f"https://graph.facebook.com/{API}/{path}?{urllib.parse.urlencode(params)}"
    time.sleep(PACE)
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return {"error": exc.code, "body": exc.read().decode("utf-8", "replace")[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"error": "network", "body": str(exc)[:200]}


def get_all_reels() -> list:
    items, url = [], None
    while True:
        if url:
            time.sleep(PACE)
            try:
                with urllib.request.urlopen(url, timeout=45) as response:
                    data = json.load(response)
            except Exception:  # noqa: BLE001
                break
        else:
            data = _get(f"{PAGE}/video_reels", limit=50,
                        fields="id,created_time,description")
            if data.get("data") is None:
                return []
        items.extend(data.get("data") or [])
        url = (data.get("paging") or {}).get("next")
        if not url:
            return items


def youtube_title(video_id: str) -> str | None:
    url = ("https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v="
           f"{video_id}&format=json")
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            return json.load(response).get("title")
    except Exception:  # noqa: BLE001
        return None


def post_cover(reel_id: str, path: str) -> dict:
    """Upload a cover as multipart/form-data (thumbnails need a binary POST)."""
    boundary = "----fbcover" + os.urandom(8).hex()
    body = bytearray()
    for key, value in (("access_token", TOKEN), ("is_preferred", "true")):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.extend(f"{value}\r\n".encode())
    with open(path, "rb") as handle:
        blob = handle.read()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="source"; filename="cover.jpg"\r\n')
    body.extend(b"Content-Type: image/jpeg\r\n\r\n")
    body.extend(blob)
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        f"https://graph.facebook.com/{API}/{reel_id}/thumbnails",
        data=bytes(body), method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return {"error": exc.code, "body": exc.read().decode("utf-8", "replace")[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"error": "network", "body": str(exc)[:200]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--min-overlap", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=0.40)
    args = parser.parse_args()

    if not TOKEN or not PAGE:
        print("FB_ACCESS_TOKEN / FB_PAGE_ID missing — aborting.")
        return 1

    done = set()
    if os.path.isfile(DONE_PATH):
        try:
            done = set(json.load(open(DONE_PATH, encoding="utf-8")))
        except Exception:  # noqa: BLE001
            done = set()

    covers = {f[:-4] for f in os.listdir(THUMB_DIR) if f.endswith(".jpg")}
    print(f"cover files on disk : {len(covers)}")

    titles = {}
    for vid in sorted(covers):
        title = youtube_title(vid)
        if title:
            titles[vid] = title
    print(f"resolvable YouTube titles: {len(titles)}")

    reels = get_all_reels()
    todo = [r for r in reels if r["id"] not in done]
    print(f"reels fetched: {len(reels)}   without a cover: {len(todo)}\n")

    used = set(json.load(open(MAP_PATH, encoding="utf-8")).values()) if os.path.isfile(MAP_PATH) else set()
    applied, skipped, report = 0, 0, []

    for reel in todo:
        caption = reel.get("description") or ""
        reel_words = words(caption)
        best = (0, 0.0, None)
        for vid, title in titles.items():
            if vid in used:
                continue                      # one cover per Reel
            overlap = len(reel_words & words(title))
            score = overlap / max(4, len(words(title)))
            if overlap > best[0] or (overlap == best[0] and score > best[1]):
                best = (overlap, score, vid)

        overlap, score, vid = best
        first_line = caption.splitlines()[0][:44] if caption else ""
        if not vid or overlap < args.min_overlap or score < args.min_score:
            skipped += 1
            print(f"  ·  skip  ({overlap}w/{score:.2f})  {first_line}")
            continue

        cover = os.path.join(THUMB_DIR, f"{vid}.jpg")
        if not os.path.isfile(cover):
            skipped += 1
            continue

        print(f"  ✅ {overlap}w/{score:.2f}  {first_line}")
        print(f"         -> {titles[vid][:56]}")
        report.append({"reel": reel["id"], "youtube": vid,
                       "title": titles[vid], "overlap": overlap,
                       "score": round(score, 2)})
        used.add(vid)

        if args.apply:
            result = post_cover(reel["id"], cover)
            if "error" in result:
                print(f"         ❌ {str(result)[:110]}")
                continue
            done.add(reel["id"])
            applied += 1

    if args.apply and applied:
        with open(DONE_PATH, "w", encoding="utf-8") as handle:
            json.dump(sorted(done), handle, indent=2)

    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
    with open(os.path.join(ROOT, "output", "fb_cover_backfill.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"mode": "apply" if args.apply else "dry-run",
                   "matched": len(report), "applied": applied,
                   "skipped": skipped, "pairs": report},
                  handle, indent=2, ensure_ascii=False)

    print(f"\nmatched {len(report)}, applied {applied}, skipped {skipped}")
    if not args.apply and report:
        print("re-run with --apply to upload these covers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
