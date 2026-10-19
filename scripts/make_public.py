from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("mrnextep.make_public")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


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


def validate_video_ids(video_ids: list[str]) -> list[str]:
    """Validate and de-duplicate explicit IDs before any API mutation."""
    validated: list[str] = []
    seen: set[str] = set()
    for raw in video_ids:
        video_id = str(raw or "").strip()
        if not _VIDEO_ID.fullmatch(video_id):
            raise ValueError("Every VIDEO_IDS item must be an 11-character YouTube video ID")
        if video_id not in seen:
            validated.append(video_id)
            seen.add(video_id)
    if not validated:
        raise ValueError("VIDEO_IDS must contain at least one explicit YouTube video ID")
    return validated


def make_videos_public(video_ids: list[str]) -> list[dict]:
    ids = validate_video_ids(video_ids)
    yt = get_youtube()
    results = []
    for vid in ids:
        try:
            res = yt.videos().list(part="snippet,status", id=vid).execute()
            items = res.get("items", [])
            if not items:
                logger.error("[%s] Video not found or inaccessible", vid)
                results.append({"video_id": vid, "status": "not_found"})
                continue
            item = items[0]
            curr_status = item.get("status", {})
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
        except Exception as exc:
            logger.error("[%s] Error transitioning to public: %s", vid, exc)
            results.append({"video_id": vid, "status": "error", "error": str(exc)})
    return results


def main() -> int:
    # Publishing is irreversible from the user's perspective (notifications and views may
    # already occur). Require both a deliberate confirmation and explicit IDs. Never scan
    # recent history implicitly: a missing input must not publish a batch by accident.
    if os.getenv("CONFIRM_PUBLICATION", "").strip().lower() not in {"true", "1", "yes"}:
        logger.error("Refusing to publish: set CONFIRM_PUBLICATION=true to confirm the action.")
        return 2

    ids_raw = os.getenv("VIDEO_IDS", "").strip()
    if not ids_raw:
        logger.error("Refusing to publish: VIDEO_IDS must explicitly list the intended videos.")
        return 2
    try:
        ids = validate_video_ids(ids_raw.split(","))
    except ValueError as exc:
        logger.error("Invalid VIDEO_IDS: %s", exc)
        return 2

    logger.info("Processing %d explicitly selected video(s) for immediate public status.", len(ids))
    results = make_videos_public(ids)
    print(__import__("json").dumps({"results": results}, ensure_ascii=False, sort_keys=True))
    failures = [item for item in results if item["status"] not in {"already_public", "transitioned_to_public"}]
    if failures:
        logger.error("%d of %d video(s) failed to become public.", len(failures), len(results))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
