from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("mrnextep.make_public")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def get_youtube():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    refresh_token = (os.getenv("REFRESH_TOKEN") or os.getenv("YT_REFRESH_TOKEN", "")).strip()
    client_id = (os.getenv("GOOGLE_CLIENT_ID") or os.getenv("YT_CLIENT_ID", "")).strip()
    client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("YT_CLIENT_SECRET", "")).strip()
    if not (refresh_token and client_id and client_secret):
        raise SystemExit("Missing YouTube credentials: REFRESH_TOKEN/GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET")

    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl"],
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def make_videos_public(video_ids: list[str]) -> list[dict]:
    yt = get_youtube()
    results = []
    for vid in video_ids:
        try:
            res = yt.videos().list(part="snippet,status", id=vid).execute()
            items = res.get("items", [])
            if not items:
                logger.warning("[%s] Video not found", vid)
                results.append({"video_id": vid, "status": "not_found"})
                continue
            item = items[0]
            curr_status = item["status"]
            current_privacy = curr_status.get("privacyStatus")
            has_publish_at = "publishAt" in curr_status

            if current_privacy == "public" and not has_publish_at:
                logger.info("[%s] Already public and unscheduled", vid)
                results.append({"video_id": vid, "status": "already_public"})
                continue

            status_body = {
                "id": vid,
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": bool(curr_status.get("selfDeclaredMadeForKids", False)),
                },
            }
            yt.videos().update(part="status", body=status_body).execute()
            logger.info("[%s] Successfully transitioned to PUBLIC!", vid)
            results.append({"video_id": vid, "status": "transitioned_to_public"})
        except Exception as e:
            logger.error("[%s] Error transitioning to public: %s", vid, e)
            results.append({"video_id": vid, "status": "error", "error": str(e)})
    return results


def main() -> int:
    ids_raw = os.getenv("VIDEO_IDS", "").strip()
    if ids_raw:
        ids = [v.strip() for v in ids_raw.split(",") if v.strip()]
    else:
        history_path = Path("data/video_history.json")
        ids = []
        if history_path.exists():
            try:
                hist = json.loads(history_path.read_text(encoding="utf-8"))
                for item in reversed(hist[-15:]):
                    yid = item.get("youtube_video_id")
                    if yid and yid not in ids:
                        ids.append(yid)
            except Exception as e:
                logger.warning("Could not parse video_history.json: %s", e)
    if not ids:
        logger.info("No video IDs provided or found in video_history.json")
        return 0

    logger.info("Processing %d videos for immediate public status: %s", len(ids), ids)
    make_videos_public(ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
