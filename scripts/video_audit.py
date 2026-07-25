#!/usr/bin/env python3
"""Read-only METADATA audit of EVERY video on the SKILLOR US channel
(MrNextep — English-language channel, so the expected standard is ENGLISH:
any French residue is the fault here).

Scans the whole uploads list and flags per-video faults:

  TITLE
    title_empty / title_french / title_bilingual / title_truncated
    duplicate_title (exact match with another video on the channel)
  DESCRIPTION
    description_empty / description_thin (<80 chars) / description_no_hashtag
    / description_french
  TAGS
    tags_missing / tags_thin (<5) / tags_french
  LANGUAGE
    language_not_en (defaultLanguage missing or != en)
  THUMBNAIL (hint only)
    thumbnail_possibly_auto (no maxres variant -> likely an auto frame)
  FORMAT / STATE (informational)
    not_short (>65s), not_public, scheduled_pending

Writes data/video_audit_us_<date>.json and prints a human summary.
Stdlib only. READ-ONLY. Needs GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET /
REFRESH_TOKEN env.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DATA = "https://www.googleapis.com/youtube/v3/"

FR_MARKERS = {
    "le", "la", "les", "des", "une", "et", "est", "sont", "que", "qui",
    "dans", "pour", "avec", "sur", "pas", "plus", "vous", "votre", "vos",
    "cette", "ces", "aux", "du", "au", "il", "elle", "on", "ne", "se",
    "sa", "son", "ses", "par", "mais", "aussi", "comme", "peut", "encore",
    "quand", "pourquoi", "comment", "sans", "sous", "chez", "leur", "notre",
    "corps", "cerveau", "coeur", "temps", "vie", "toute", "fait",
    "entre", "tres", "apres", "avant", "chaque", "pendant", "toujours",
    "quoi", "voici", "cela", "cet", "effet", "raison", "vraiment",
}
EN_MARKERS = {
    "the", "and", "is", "are", "was", "were", "with", "your", "you", "why",
    "how", "what", "when", "this", "that", "these", "those", "from", "have",
    "has", "will", "would", "can", "could", "not", "but", "for", "into",
    "about", "after", "before", "between", "because", "every", "really",
    "science", "brain", "body", "time", "years", "sleep", "water", "heart",
    "blood", "morning", "night", "truth", "secret", "hidden", "reason",
    "happens", "strange", "weird", "actually", "ever", "during", "feel",
    "feeling", "feels", "reflex", "mouth", "dry", "yawn", "yawns", "yawning",
    "freeze", "itch", "pain", "muscle", "muscles", "skin", "stomach",
    "sneeze", "sneezing", "hiccup", "hiccups", "voice", "sound", "chills",
    "goosebumps", "shiver", "shivering", "twitch", "cramp", "dream",
    "dreams", "dreaming", "blink", "blinking", "tears", "sweat", "sweating",
}
# A title ending on one of these almost certainly got cut mid-sentence (EN).
EN_DANGLERS = ("the", "a", "an", "of", "to", "in", "on", "at", "by", "for",
               "and", "or", "but", "when", "why", "how", "your", "our",
               "my", "his", "her", "its", "their", "this", "that", "these",
               "those", "with", "from", "into", "is", "are", "was", "were",
               "you", "we", "they")
ACCENT_RE = re.compile(r"[àâäçéèêëîïôöùûüÿœæ]", re.IGNORECASE)
WORD_RE = re.compile(r"[a-zA-Zàâäçéèêëîïôöùûüÿœæ']+")


def _access_token() -> str:
    payload = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=payload)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["access_token"]


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"GET {url[:90]}... -> {exc.code}: {body}") from exc


def _query(path: str, params: dict, token: str) -> dict:
    return _get(DATA + path + "?" + urllib.parse.urlencode(params), token)


def _lang_score(text: str):
    table = str.maketrans("àâäçéèêëîïôöùûüÿœæ", "aaaceeeeiioouuuyee")
    words = [w.strip("'").translate(table).lower() for w in WORD_RE.findall(text or "")]
    fr = sum(1 for w in words if w in FR_MARKERS)
    en = sum(1 for w in words if w in EN_MARKERS)
    return fr, en, bool(ACCENT_RE.search(text or ""))


def _classify(text: str) -> str:
    """Same heuristics as the FR audit; FR/mixed is BAD on this EN channel."""
    fr, en, accented = _lang_score(text)
    if fr >= 1 and en >= 2:
        return "mixed" if not accented else "fr"
    if fr >= 2 and en == 0:
        return "fr"
    if fr >= 1 and en >= 1:
        return "mixed"
    if en >= 1 or (not fr and not accented):
        return "en"
    return "fr" if (fr or accented) else "unknown"


def _audit_video(video: dict) -> list:
    faults = []
    sn = video.get("snippet", {})
    st = video.get("status", {})
    cd = video.get("contentDetails", {})

    title = (sn.get("title") or "").strip()
    desc = (sn.get("description") or "").strip()
    tags = sn.get("tags") or []

    # ---- title ----
    if not title:
        faults.append("title_empty")
    else:
        verdict = _classify(title)
        if verdict == "fr":
            faults.append("title_french")
        elif verdict == "mixed":
            faults.append("title_bilingual")
        last_word = WORD_RE.findall(title)
        last_word = last_word[-1].lower() if last_word else ""
        if (last_word in EN_DANGLERS or title.endswith(("…", " -", " |", ":"))
                or (len(title) >= 95 and not title.endswith(("?", "!", ".")))):
            faults.append("title_truncated")

    # ---- description ----
    if not desc:
        faults.append("description_empty")
    else:
        if len(desc) < 80:
            faults.append("description_thin")
        if "#" not in desc:
            faults.append("description_no_hashtag")
        if _classify(desc[:400]) == "fr":
            faults.append("description_french")

    # ---- tags ----
    if not tags:
        faults.append("tags_missing")
    else:
        if len(tags) < 5:
            faults.append("tags_thin")
        if sum(1 for t in tags if _classify(t) in ("fr", "mixed")) > 0:
            faults.append("tags_french")

    # ---- language ----
    if sn.get("defaultLanguage") != "en":
        faults.append("language_not_en")

    # ---- thumbnail hint ----
    if "maxres" not in (sn.get("thumbnails") or {}):
        faults.append("thumbnail_possibly_auto")

    # ---- format / state (informational) ----
    duration = cd.get("duration", "")
    match = re.match(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", duration)
    seconds = 0.0
    if match:
        seconds = (int(match.group(1) or 0) * 60) + float(match.group(2) or 0)
    if seconds > 65:
        faults.append("not_short")
    if st.get("privacyStatus") != "public" and not st.get("publishAt"):
        faults.append("not_public")
    if st.get("publishAt"):
        faults.append("scheduled_pending")
    return faults


def main() -> int:
    token = _access_token()

    channels = _query("channels", {"part": "contentDetails,statistics", "mine": "true"}, token)
    items = channels.get("items") or []
    if not items:
        print("AUDIT FAILED: no channel visible with this token")
        return 1
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    total_uploads = int(items[0].get("statistics", {}).get("videoCount", 0))

    video_ids = []
    page_token = None
    while True:
        params = {"part": "contentDetails", "playlistId": uploads_playlist,
                  "maxResults": "50"}
        if page_token:
            params["pageToken"] = page_token
        page = _query("playlistItems", params, token)
        for item in page.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)
        page_token = page.get("nextPageToken")
        if not page_token:
            break

    videos = []
    for idx in range(0, len(video_ids), 50):
        batch = video_ids[idx:idx + 50]
        resp = _query("videos", {
            "part": "snippet,status,contentDetails,statistics",
            "id": ",".join(batch),
            "maxResults": "50",
        }, token)
        videos.extend(resp.get("items", []))

    report = []
    title_registry = {}
    for v in videos:
        sn = v.get("snippet", {})
        faults = _audit_video(v)
        norm = re.sub(r"\W+", "", (sn.get("title") or "").lower())
        entry = {
            "video_id": v["id"],
            "url": f"https://youtu.be/{v['id']}",
            "title": sn.get("title", ""),
            "published_at": sn.get("publishedAt"),
            "views": v.get("statistics", {}).get("viewCount"),
            "language": sn.get("defaultLanguage"),
            "tags_count": len(sn.get("tags") or []),
            "desc_len": len(sn.get("description") or ""),
            "faults": faults,
        }
        report.append(entry)
        title_registry.setdefault(norm, []).append(v["id"])
    dup_map = {k: v for k, v in title_registry.items() if len(v) > 1 and k}
    dup_owner = set()
    for ids in dup_map.values():
        dup_owner.update(ids)
    for entry in report:
        if entry["video_id"] in dup_owner:
            entry["faults"].append("duplicate_title")

    from collections import Counter
    counter = Counter(f for e in report for f in e["faults"])
    clean = [e for e in report if not e["faults"]]
    faulty = [e for e in report if e["faults"]]

    out = {
        "date": dt.date.today().isoformat(),
        "channel": "SKILLOR US (MrNextep)",
        "channel_video_count": total_uploads,
        "videos_scanned": len(report),
        "videos_clean": len(clean),
        "videos_faulty": len(faulty),
        "fault_counts": dict(counter.most_common()),
        "faulty_videos": sorted(faulty, key=lambda e: -len(e["faults"])),
    }
    os.makedirs("data", exist_ok=True)
    path = f"data/video_audit_us_{dt.date.today().isoformat()}.json"
    with open(path, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    print("=" * 64)
    print(f"VIDEO METADATA AUDIT — US — {out['date']}")
    print(f"channel videos: {total_uploads} | scanned: {len(report)}")
    print(f"clean: {len(clean)} | faulty: {len(faulty)}")
    print("-" * 64)
    for fault, count in counter.most_common():
        print(f"  {fault:26s} {count}")
    print("-" * 64)
    print("FAULTY VIDEOS (worst first):")
    for e in out["faulty_videos"]:
        print(f"  {e['video_id']}  views={e['views']}  {sorted(set(e['faults']))}")
        print(f"      title: {e['title'][:80]}")
    print(f"\nsaved -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
