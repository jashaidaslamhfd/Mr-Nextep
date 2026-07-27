#!/usr/bin/env python3
"""One-shot YouTube metadata repair for SKILLOR (US).

Heals the metadata of videos published BEFORE the 2026-07-23 content fixes:
- 2-3 word label titles ("Throat Lump 🫀") → universal curiosity titles
  ("Why Your Body Does This: Throat Lump") — the pattern behind the channel's
  best performer ("Why You Hear Your Heartbeat at Night").
- Titles cut mid-sentence / dangling → rebuilt from the same subject.
- Thin/junk tags → topic SEO tags via the repo's own generate_upload_tags.
- Descriptions → rebuilt with the current generator (hook + keyword context
  + CTA + #Shorts + topic hashtags).

COVERAGE: every upload on the channel, not just pipeline history:
1) data/video_history.json entries (topic ground truth),
2) any other channel upload whose CURRENT title is broken — healed from the
   title's own subject. Nothing is ever invented: no topic, no heal, SKIP.

SAFETY:
- Default is DRY RUN: prints the full before/after plan, changes nothing.
- Pass --apply to write changes to YouTube (videos.update).
- --limit N processes at most N videos (oldest-first).
- 1.5s sleep between writes (each update ~50 quota units of 10k/day).
- A title that already reads as a full sentence/question is NEVER touched.
"""

import argparse
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("metadata_repair")

from seo_generator import _EN_DANGLING_ENDINGS, TITLE_MAX_LEN, generate_description  # noqa: E402
from seo_generator import generate_upload_tags  # noqa: E402
from niche_strategy import get_topic_category  # noqa: E402

_SUBJECT_STRIP = re.compile(r"^(?:shorts|watch|new)$|^(?:#\d+[:#]?|\d+[:#])$", re.I)
_JUNK_TAIL = {"hacked", "uncovered", "exposed", "revealed", "now", "today", "explained"}
_CURIOSITY_STARTERS = ("why", "what", "how", "the science", "the real", "this is",
                       "your body", "did you", "ever wonder", "science")


# --------------------------------------------------------------------------- #
# YouTube helpers (std-lib only)
# --------------------------------------------------------------------------- #
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


def _api(path: str, token: str, *, method: str = "GET", body: dict = None):
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
        payload = e.read().decode(errors="replace")[:400]
        raise RuntimeError(f"YouTube API {method} {path} -> {e.code}: {payload}") from e


def _uploads_playlist(token: str) -> str:
    res = _api("channels?part=contentDetails&mine=true", token)
    return res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _all_upload_ids(token: str, playlist_id: str) -> list:
    ids, page = [], None
    while True:
        path = f"playlistItems?part=contentDetails&playlistId={playlist_id}&maxResults=50"
        if page:
            path += f"&pageToken={page}"
        res = _api(path, token)
        ids += [i["contentDetails"]["videoId"] for i in res.get("items", [])]
        page = res.get("nextPageToken")
        if not page:
            return ids


def _get_videos(token: str, ids: list) -> dict:
    out = {}
    for k in range(0, len(ids), 50):
        res = _api("videos?part=snippet&id=" + ",".join(ids[k:k + 50]), token)
        for item in res.get("items", []):
            out[item["id"]] = item
    return out


# --------------------------------------------------------------------------- #
# Repair logic
# --------------------------------------------------------------------------- #
def _alnum_words(text: str) -> list:
    return [w for w in re.split(r"\s+", (text or "").strip())
            if any(ch.isalpha() for ch in w)]


def _looks_truncated(title: str) -> bool:
    words = _alnum_words(title)
    if not words:
        return True
    return words[-1].lower().rstrip("?!.…") in _EN_DANGLING_ENDINGS


def _is_label_title(title: str) -> bool:
    words = _subject_from(title).split()
    if not words:
        return True
    if len(words) > 3:
        return False
    return not (title or "").lower().lstrip("#: ").startswith(_CURIOSITY_STARTERS)


def _subject_from(title: str) -> str:
    """2-4 word Title-Case subject from a label title (emoji/junk stripped)."""
    words = []
    for w in _alnum_words(title):
        if _SUBJECT_STRIP.match(w) or set(w) <= {"#", ":", "-", "|"}:
            continue
        w = w.strip("#:|\"'")
        if w and not _SUBJECT_STRIP.match(w):
            words.append(w)
    # series prefix: "Body Glitch ..." / "Glitch ..." — strip only as a pair/lead
    if words and words[0].lower() == "glitch":
        words = words[1:]
    elif len(words) > 1 and words[0].lower() == "body" and words[1].lower() == "glitch":
        words = words[2:]
    # clickbait-junk tail adjectives from the old style
    while len(words) > 1 and words[-1].lower() in _JUNK_TAIL:
        words.pop()
    subject = " ".join(w[:24] for w in words[:4])
    return subject.title() if subject else ""


def _title_case_fit(template_subject: str, suffix: str = " 😳") -> str:
    t = template_subject
    if len(t) + len(suffix) <= TITLE_MAX_LEN:
        t += suffix
    return t


def _heal_title(subject: str) -> str:
    """Universal curiosity title. Empty if we cannot build one safely."""
    if not subject or len(subject.split()) < 1:
        return ""
    for tmpl in ("Why Your Body Does This: {s}", "{s}? Your Body Explains",
                 "The Truth About Your {s}"):
        cand = _title_case_fit(tmpl.format(s=subject))
        if len(cand.replace(" 😳", "")) <= TITLE_MAX_LEN:
            return cand
    # Last resort: shorten subject to fit the compact template
    words = subject.split()
    while len(words) > 1:
        words.pop()
        cand = _title_case_fit("{s}? Your Body Explains".format(s=" ".join(words)))
        if len(cand.replace(" 😳", "")) <= TITLE_MAX_LEN:
            return cand
    return ""


def build_new_metadata(entry: dict, current: dict) -> dict | None:
    """Return dict of changed fields, or None if nothing worth changing."""
    snip = current["snippet"]
    old_title = (snip.get("title") or "").strip()
    topic = (entry.get("topic") or "").strip()
    changes: dict = {}

    # --- TITLE ---
    broken = _looks_truncated(old_title) or _is_label_title(old_title)
    if broken:
        subject = _subject_from(old_title) or _subject_from(entry.get("series_title") or "")
        if _looks_truncated(old_title) and not _is_label_title(old_title):
            # cut mid-sentence: keep the readable head as the subject
            words = _alnum_words(old_title)
            while words and words[-1].lower().rstrip("?!.…") in _EN_DANGLING_ENDINGS:
                words.pop()
            if len(words) >= 2:
                subject = " ".join(words[-4:]).title()
        new_title = _heal_title(subject)
        if new_title and new_title != old_title and len(_alnum_words(new_title)) >= 3 \
                and not _looks_truncated(new_title):
            changes["title"] = new_title

    # --- TAGS ---
    seo_source = topic or _subject_from(entry.get("title") or "") or _subject_from(old_title)
    try:
        category = get_topic_category(topic or seo_source) or "Body"
    except Exception:
        category = "Body"
    raw_tags = generate_upload_tags(seo_source or "human body", category, limit=14)
    junk = {"the", "a", "an", "of", "in", "on", "at", "your", "you", "when", "and",
            "or", "to", "is", "are", "it", "this", "that", "with"}
    seen, new_tags = set(), []
    for t in raw_tags + ["science", "human body"]:
        t = re.sub(r"\s+", " ", (t or "").strip().lstrip("#"))
        if not t or t.lower() in junk or len(t) < 4:
            continue
        if t.lower() not in seen:
            seen.add(t.lower())
            new_tags.append(t)
        if len(new_tags) >= 14:
            break
    old_tags = snip.get("tags") or []
    if new_tags and {x.lower() for x in new_tags} != {x.lower() for x in old_tags}:
        changes["tags"] = new_tags

    # --- DESCRIPTION ---
    # Idempotency: a description already built by the CURRENT generator keeps
    # its signatures ("#Shorts" + "science behind" context). Without this rule
    # tag-shuffle noise would flag every video on every run forever.
    old_desc_raw = snip.get("description") or ""
    # A description built by the current generator carries "#Shorts" + a
    # "science behind" context line. Older runs ALSO wrote broken hashtags
    # with a space inside them (e.g. "#human body"), which YouTube truncates
    # at the space — killing that hashtag's SEO value. Detect that pattern and
    # force a rebuild even when the signatures are present, so this repair
    # actually heals those hashtags instead of skipping the video forever.
    broken_hashtag = re.search(r"#[A-Za-z][A-Za-z0-9]*\s+[a-z]", old_desc_raw)
    if "#Shorts" in old_desc_raw and "science behind" in old_desc_raw.lower() and not broken_hashtag:
        return changes or None
    voiceover = (entry.get("voiceover") or "").strip().replace("\n", " ")
    theme = (topic or _subject_from(entry.get("title") or "") or _subject_from(old_title)).lower()
    if voiceover:
        summary = voiceover[:280].rstrip()
    elif theme:
        summary = (f"In this Short we explain {theme} clearly: what triggers it "
                   f"in your body, the simple science behind it, and what to pay attention to.")
    else:
        summary = ""
    script_like = {"hook": changes.get("title", old_title), "summary": summary, "description": ""}
    new_desc = generate_description(script_like, changes.get("tags", old_tags) or new_tags).strip()
    if new_desc and new_desc != (snip.get("description") or "").strip():
        changes["description"] = new_desc

    # Nothing to offer? skip rather than write noise.
    if not changes:
        return None
    if set(changes) == {"description"} and not theme and not topic:
        return None
    return changes


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default = dry run)")
    ap.add_argument("--limit", type=int, default=0, help="max videos to process (oldest first)")
    ap.add_argument("--history", default="data/video_history.json")
    args = ap.parse_args()

    history = json.loads(Path(args.history).read_text(encoding="utf-8"))
    entries = history if isinstance(history, list) else history.get("videos", [])
    hist_map = {e["youtube_video_id"]: e for e in entries if e.get("youtube_video_id")}

    token = _access_token()

    # Coverage = pipeline history + every other upload on the channel.
    try:
        upload_ids = _all_upload_ids(token, _uploads_playlist(token))
    except Exception as exc:
        logger.warning("Channel discovery failed (%s) — falling back to history only", exc)
        upload_ids = list(hist_map)
    for vid in upload_ids:
        hist_map.setdefault(vid, {"youtube_video_id": vid, "posted_at": "9999"})
    ordered = sorted(hist_map.values(), key=lambda e: e.get("posted_at", "9999"))
    if args.limit:
        ordered = ordered[: args.limit]

    logger.info("Repair candidates: %d (history=%d, channel=%d, mode=%s)",
                len(ordered), len([v for v in upload_ids if v in hist_map and hist_map[v].get('topic')]),
                len(upload_ids), "APPLY" if args.apply else "DRY RUN")
    if not ordered:
        return 0

    plan_rows = []
    updated = skipped = failed = 0
    want_ids = [e["youtube_video_id"] for e in ordered]
    videos = _get_videos(token, want_ids)

    for e in ordered:
        vid = e["youtube_video_id"]
        # Deterministic tag generation per video — without this the generator's
        # random pools flag the same videos on every run (metadata churn).
        random.seed(int(hashlib.md5(vid.encode()).hexdigest()[:8], 16))
        try:
            current = videos.get(vid)
            if not current:
                skipped += 1
                plan_rows.append(f"SKIP  {vid} | not on channel anymore (deleted/private)")
                continue
            live_title = current["snippet"].get("title", "")
            changes = build_new_metadata(e, current)
            if not changes:
                skipped += 1
                plan_rows.append(f"SKIP  {vid} | already good | {live_title[:60]}")
                continue
            plan_rows.append(f"FIX   {vid}  [{', '.join(sorted(changes))}]\n"
                             f"  old: {live_title[:90]}\n"
                             f"  new: {changes.get('title', live_title)[:90]}")
            if args.apply:
                snip = dict(current["snippet"])
                snip.update(changes)
                allowed = {"title", "description", "tags", "categoryId",
                           "defaultLanguage", "defaultAudioLanguage"}
                body = {"id": vid, "snippet": {k: v for k, v in snip.items() if k in allowed and v is not None}}
                _api("videos?part=snippet", token, method="PUT", body=body)
                updated += 1
                time.sleep(1.5)
            else:
                updated += 1
        except Exception as exc:
            failed += 1
            plan_rows.append(f"FAIL  {vid} | {exc}")
            logger.warning("Failed %s: %s", vid, exc)

    report = "\n".join(plan_rows)
    print(report)
    Path("output").mkdir(exist_ok=True)
    Path("output/metadata_repair_report.txt").write_text(report, encoding="utf-8")
    logger.info("DONE — fixed: %d, skipped: %d, failed: %d (mode=%s)",
                updated, skipped, failed, "APPLY" if args.apply else "DRY RUN")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
