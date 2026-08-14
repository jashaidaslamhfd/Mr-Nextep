#!/usr/bin/env python3
"""One-shot backfill: write Instagram (and Facebook) platform ids into
data/video_history.json from data/upload_state.json.

Historically upload_state.json recorded every platform's media id, but
video_history.json (the single source repair and metrics scripts read)
never received them — so Instagram was permanently "blind". From now on
main.py records these ids directly, but 118 older rows stay blind unless
this script backfills them.

Usage:
    python3 scripts/backfill_platform_ids.py        # dry-run preview
    python3 scripts/backfill_platform_ids.py apply  # actually patch the file
"""
import os
import sys
import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HISTORY = DATA / "video_history.json"
STATE = DATA / "upload_state.json"


def _fingerprint(topic, title, voiceover, hook):
    material = "|".join(
        str(v or "").strip().lower()
        for v in (topic, title, voiceover, hook)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _norm(text):
    return " ".join(str(text or "").lower().split())


def main():
    apply = len(sys.argv) > 1 and sys.argv[1] == "apply"

    if not STATE.exists():
        print(f"upload_state.json not found at {STATE} — nothing to backfill.")
        sys.exit(0)
    with open(STATE, encoding="utf-8") as fh:
        state = json.load(fh)

    history = []
    if HISTORY.exists():
        with open(HISTORY, encoding="utf-8") as fh:
            history = json.load(fh)

    # upload_state.json is keyed by the 64-char content fingerprint. Build
    # lookup maps by fingerprint first, then by youtube_video_id so the old
    # history rows (which often carry a title but no fingerprint field) can
    # still be matched against the state's youtube id.
    by_fp = {}
    by_yt = {}
    for fp, fp_state in state.items():
        if not isinstance(fp_state, dict):
            continue
        by_fp[fp] = fp_state
        yt_id = fp_state.get("youtube_video_id")
        if yt_id:
            by_yt["".join(str(yt_id).split())] = fp_state

    patched = []
    for row in history:
        changed = False
        if not row.get("instagram_media_id"):
            match = by_fp.get(row.get("content_fingerprint")) or \
                by_yt.get("".join(str(row.get("youtube_video_id") or "").split()))
            if match and match.get("instagram", {}).get("media_id"):
                row["instagram_media_id"] = match["instagram"]["media_id"]
                changed = True
        if not row.get("facebook_video_id"):
            match = by_fp.get(row.get("content_fingerprint")) or \
                by_yt.get("".join(str(row.get("youtube_video_id") or "").split()))
            if match and match.get("facebook", {}).get("video_id"):
                row["facebook_video_id"] = match["facebook"]["video_id"]
                changed = True
        if changed:
            patched.append(_norm(row.get("title")))

    print(f"History rows: {len(history)} | rows that will gain platform ids: {len(patched)}")
    for t in patched:
        print(f"  + {t[:80]}")

    if apply:
        tmp = str(HISTORY) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2)
        os.replace(tmp, HISTORY)
        print("Backfilled and saved to data/video_history.json")
    else:
        print("Dry run — pass 'apply' to patch the file.")


if __name__ == "__main__":
    main()
