#!/usr/bin/env python3
"""One-shot thumbnail upload for MrNextep (US).

Uploads every assets/thumbnails_us/<video_id>.jpg to YouTube via
thumbnails.set (media upload). Images were pre-rendered locally and
committed to the repo, so this script is upload-only and std-lib only.

Safety:
- uploads only for video IDs already listed in data/video_history.json
  (never touches an unknown video),
- every image is validated as JPEG < 2MB (YouTube hard limit),
- 1.5s pause between uploads, full report printed + artifacted.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THUMB_DIR = ROOT / "assets" / "thumbnails_us"
HISTORY = ROOT / "data" / "video_history.json"
REPORT = ROOT / "output" / "thumbnail_update_report.txt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("thumbnail_update")


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


def _uploads_playlist(token: str) -> str:
    import urllib.request

    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&mine=true")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _all_upload_ids(token: str, playlist_id: str) -> list:
    import urllib.request

    ids, page = [], None
    while True:
        url = ("https://www.googleapis.com/youtube/v3/playlistItems"
               f"?part=contentDetails&playlistId={playlist_id}&maxResults=50")
        if page:
            url += f"&pageToken={page}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
        ids += [i["contentDetails"]["videoId"] for i in res.get("items", [])]
        page = res.get("nextPageToken")
        if not page:
            return ids


def _set_thumbnail(token: str, video_id: str, jpeg: bytes) -> None:
    import urllib.error
    import urllib.request

    url = f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}"
    req = urllib.request.Request(url, data=jpeg, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "image/jpeg")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.status not in (200, 204):
                raise RuntimeError(f"unexpected status {r.status}")
    except urllib.error.HTTPError as e:
        payload = e.read().decode(errors="replace")[:400]
        raise RuntimeError(f"thumbnails.set {video_id} -> {e.code}: {payload}") from e


def main() -> int:
    images = sorted(THUMB_DIR.glob("*.jpg"))
    token = _access_token()
    # Membership guard = every video CURRENTLY on this channel (live list),
    # not just pipeline history — legacy uploads are covered too.
    try:
        known = set(_all_upload_ids(token, _uploads_playlist(token)))
    except Exception:  # noqa: BLE001 — fall back to history-only guard
        known = {e["youtube_video_id"] for e in json.loads(HISTORY.read_text())}
    logger.info("Thumbnails found: %d (channel covers %d videos)", len(images), len(known))

    jobs, skips = [], []
    for img in images:
        vid = img.stem
        if vid not in known:
            skips.append((vid, "not in video_history — refused"))
            continue
        data = img.read_bytes()
        if len(data) > 2 * 1024 * 1024:
            skips.append((vid, "image > 2MB — refused"))
            continue
        if not data[:3] == b"\xff\xd8\xff":
            skips.append((vid, "not a valid JPEG — refused"))
            continue
        jobs.append((vid, data))

    # Resume state: never re-upload a thumbnail that already succeeded —
    # each upload costs ~50 quota units; re-uploading 57 would waste ~3k.
    DONE_FILE = ROOT / "data" / "thumbnails_done.json"
    try:
        done_ids = set(json.loads(DONE_FILE.read_text()))
    except Exception:
        done_ids = set()
    jobs = [(v, d) for v, d in jobs if v not in done_ids]
    if done_ids:
        logger.info("Resume: %d already done, %d remaining", len(done_ids), len(jobs))

    if skips:
        for vid, why in skips:
            logger.warning("SKIP  %s (%s)", vid, why)

    ok, failed = 0, []
    if jobs:
        for vid, data in jobs:
            try:
                _set_thumbnail(token, vid, data)
                ok += 1
                done_ids.add(vid)
                DONE_FILE.parent.mkdir(parents=True, exist_ok=True)
                DONE_FILE.write_text(json.dumps(sorted(done_ids)))
                logger.info("UPLOADED  %s  (%d KB)", vid, len(data) // 1024)
            except Exception as exc:  # noqa: BLE001 — report and continue
                failed.append((vid, str(exc)))
                logger.error("FAILED    %s  %s", vid, exc)
            time.sleep(1.5)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["THUMBNAIL UPDATE REPORT", f"uploaded: {ok} / {len(jobs)}", f"skipped: {len(skips)}", f"failed: {len(failed)}", ""]
    lines += [f"FAIL {v}: {m}" for v, m in failed]
    REPORT.write_text("\n".join(lines))
    logger.info("DONE — uploaded: %d, skipped: %d, failed: %d", ok, len(skips), len(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
