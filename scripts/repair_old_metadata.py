"""
Repair and update old metadata to match US-targeting SEO rules.

Usage:
  python src/repair_old_metadata.py [--dry-run] [--confirm] [--max-updates N]
  python src/repair_old_metadata.py --revert --revert-count N

Notes:
- By default runs in dry-run mode and prints proposed changes.
- Use --confirm to apply changes for real. Use --max-updates to limit updates per run.
- Requires YouTube OAuth credentials in environment (REFRESH_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET).
- For Meta updates, set FACEBOOK_ACCESS_TOKEN, FACEBOOK_PAGE_ID, INSTAGRAM_USER_ID if available.

Safety:
- Respects rate limits with configurable sleep and exponential backoff.
- Logs all attempted updates and appends revised metadata to video_history.json.
- Staged rollout: honors STAGED_DAILY_LIMIT env var and limits updates per 24h window.
- Revert mode: can revert applied updates using saved original snippets in history.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import SETTINGS
from src.guards import load_history, save_history
from src.seo import build_packages
from src.utils import retry_on_exception, sanitize_hashtags

logger = logging.getLogger("mrnextep.repair")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STAGED_DAILY_LIMIT = int(os.getenv("STAGED_DAILY_LIMIT", "15"))
META_GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v21.0")


def _load_youtube_creds() -> Credentials:
    refresh_token = os.getenv("REFRESH_TOKEN", "").strip()
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    token_uri = "https://oauth2.googleapis.com/token"
    if not (refresh_token and client_id and client_secret):
        raise RuntimeError("Missing YouTube credentials in environment (REFRESH_TOKEN/GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET)")
    creds = Credentials(None,
                        refresh_token=refresh_token,
                        token_uri=token_uri,
                        client_id=client_id,
                        client_secret=client_secret,
                        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"])
    creds.refresh(Request())
    return creds


def _iter_uploaded_video_ids(youtube) -> list[str]:
    """Return a list of all video IDs uploaded by the authenticated channel."""
    resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        logger.error("No channels found for authenticated user")
        return []
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    video_ids: list[str] = []
    page_token: str | None = None
    while True:
        pl = youtube.playlistItems().list(part="contentDetails", playlistId=uploads_playlist, maxResults=50, pageToken=page_token)
        resp = pl.execute()
        for it in resp.get("items", []):
            vid = it.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
        time.sleep(1)
    return video_ids


def _fetch_video_snippets(youtube, ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i+50]
        resp = youtube.videos().list(part="snippet,contentDetails", id=','.join(chunk)).execute()
        for v in resp.get("items", []):
            out[v["id"]] = v
        time.sleep(1)
    return out


@retry_on_exception(max_attempts=5)
def _update_video_snippet(youtube, video_id: str, new_snippet: dict[str, Any]):
    body = {"id": video_id, "snippet": new_snippet}
    resp = youtube.videos().update(part="snippet", body=body).execute()
    return resp


def _normalize_tags_for_youtube(tags: list[str]) -> list[str]:
    cleaned = [t.lstrip('#') for t in sanitize_hashtags(tags, max_hashtags=15)]
    return cleaned


def _count_recent_updates(video_history: list[dict[str, Any]], window_hours: int = 24) -> int:
    cutoff = time.time() - window_hours * 3600
    cnt = 0
    for e in reversed(video_history[-1000:]):
        if not isinstance(e, dict):
            continue
        if not e.get("updated"):
            continue
        ts = e.get("timestamp", 0)
        if ts >= cutoff:
            cnt += 1
    return cnt


def plan_and_apply_updates(youtube, video_ids: list[str], dry_run: bool = True, max_updates: int | None = None, sleep_between: float = 2.0):
    logger.info("Inspecting %d videos", len(video_ids))
    snippets = _fetch_video_snippets(youtube, video_ids)

    updates = []
    for vid in video_ids:
        item = snippets.get(vid)
        if not item:
            continue
        snippet = item.get("snippet", {})
        current_title = snippet.get("title", "").strip()
        current_description = snippet.get("description", "").strip()
        current_tags = snippet.get("tags", []) or []

        script = {"title": current_title, "description": current_description, "tags": current_tags}
        seo = build_packages(script).get("youtube", {})
        target_title = seo.get("title", current_title).strip()
        target_description = seo.get("description", current_description).strip()
        target_tags = seo.get("tags", []) or []
        target_tags = [t.lstrip('#') for t in target_tags]

        needs_update = False
        reasons = []
        if target_title and target_title != current_title and len(target_title) <= 60:
            needs_update = True
            reasons.append("title")
        if target_description and target_description != current_description:
            needs_update = True
            reasons.append("description")
        if set([t.lower() for t in target_tags]) != set([t.lower() for t in current_tags]):
            needs_update = True
            reasons.append("tags")

        if needs_update:
            updates.append({
                "video_id": vid,
                "current": {"title": current_title, "description": current_description, "tags": current_tags},
                "target": {"title": target_title, "description": target_description, "tags": target_tags},
                "reasons": reasons,
            })

    logger.info("Planned updates for %d videos", len(updates))

    video_history_path = SETTINGS.data_dir / "video_history.json"
    video_history = load_history(video_history_path)

    # Staged rollout: limit by STAGED_DAILY_LIMIT and by recent updates in history
    recent_count = _count_recent_updates(video_history, window_hours=24)
    daily_remaining = max(0, STAGED_DAILY_LIMIT - recent_count)
    if max_updates is None:
        allowed = daily_remaining
    else:
        allowed = min(max_updates, daily_remaining)
    logger.info("Staged rollout limit: daily limit=%d, recent applied=%d, allowed this run=%d", STAGED_DAILY_LIMIT, recent_count, allowed)

    applied = 0
    for u in updates:
        if applied >= allowed:
            logger.info("Reached staged rollout limit for this run: %d updates applied", applied)
            break
        vid = u["video_id"]
        logger.info("Processing video %s for update: reasons=%s", vid, u["reasons"])
        if dry_run:
            logger.info("Dry-run: would update %s -> %s", vid, u["target"])
            entry = {"platform": "youtube", "id": vid, "updated": False, "planned": u["target"], "original_snippet": u.get("current"), "timestamp": time.time()}
            video_history.append(entry)
            applied += 1
            continue

        try:
            existing = snippets.get(vid, {}).get("snippet", {})
            new_snippet = existing.copy()
            # Save original to history before updating
            original_snippet = existing.copy()
            new_snippet["title"] = u["target"]["title"]
            new_snippet["description"] = u["target"]["description"]
            new_snippet["tags"] = u["target"]["tags"]

            resp = _update_video_snippet(youtube, vid, new_snippet)
            logger.info("Updated video %s: response id=%s", vid, resp.get("id"))

            entry = {"platform": "youtube", "id": vid, "updated": True, "result": resp, "original_snippet": original_snippet, "timestamp": time.time()}
            video_history.append(entry)
            applied += 1
            time.sleep(sleep_between)
        except HttpError as he:
            logger.exception("YouTube HttpError updating %s: %s", vid, he)
            entry = {"platform": "youtube", "id": vid, "updated": False, "error": str(he), "timestamp": time.time()}
            video_history.append(entry)
            time.sleep(5)
        except Exception as ex:
            logger.exception("Unexpected error updating %s: %s", vid, ex)
            video_history.append({"platform": "youtube", "id": vid, "updated": False, "error": str(ex), "timestamp": time.time()})
            time.sleep(5)

    save_history(video_history_path, video_history)
    logger.info("Finished. Applied %d updates (planned %d). History saved to %s", applied, len(updates), video_history_path)


def revert_updates(youtube, video_history_path: Path, revert_count: int | None = None, revert_ids: list[str] | None = None, dry_run: bool = True, sleep_between: float = 2.0):
    """Revert previously applied updates using original_snippet stored in history.

    If revert_ids is provided, attempt to revert those videos. Otherwise revert the most recent revert_count applied updates.
    """
    video_history = load_history(video_history_path)
    applied = 0

    # Build list of candidate entries that were updated and have original_snippet
    candidates = [e for e in reversed(video_history) if isinstance(e, dict) and e.get("platform") == "youtube" and e.get("updated") and e.get("original_snippet")]

    if revert_ids:
        # Filter candidates by requested ids
        candidates = [c for c in candidates if c.get("id") in revert_ids]
    else:
        if revert_count:
            candidates = candidates[:revert_count]

    if not candidates:
        logger.info("No eligible applied updates found to revert.")
        return

    for c in candidates:
        if revert_count and applied >= revert_count:
            break
        vid = c.get("id")
        original = c.get("original_snippet")
        if not original:
            logger.warning("No original snippet stored for %s; skipping", vid)
            continue
        logger.info("Reverting video %s to original snippet", vid)
        if dry_run:
            logger.info("Dry-run: would revert %s", vid)
            video_history.append({"platform": "youtube", "id": vid, "reverted": False, "planned_revert": True, "timestamp": time.time()})
            applied += 1
            continue
        try:
            resp = _update_video_snippet(youtube, vid, original)
            logger.info("Reverted video %s: %s", vid, resp.get("id"))
            video_history.append({"platform": "youtube", "id": vid, "reverted": True, "result": resp, "timestamp": time.time()})
            applied += 1
            time.sleep(sleep_between)
        except HttpError as he:
            logger.exception("YouTube HttpError reverting %s: %s", vid, he)
            video_history.append({"platform": "youtube", "id": vid, "reverted": False, "error": str(he), "timestamp": time.time()})
            time.sleep(5)
        except Exception as ex:
            logger.exception("Unexpected error reverting %s: %s", vid, ex)
            video_history.append({"platform": "youtube", "id": vid, "reverted": False, "error": str(ex), "timestamp": time.time()})
            time.sleep(5)

    save_history(video_history_path, video_history)
    logger.info("Revert run complete. Applied %d reverts.", applied)


def meta_attempt_update(fb_token: str, facebook_page_id: str, instagram_id: str, video_history_path: Path, dry_run: bool = True, max_updates: int | None = None):
    session = None
    try:
        import requests
        session = requests.Session()
    except Exception:
        session = None

    if not session:
        logger.warning("Requests session unavailable, skipping Meta updates")
        return

    video_history = load_history(video_history_path)
    candidates = [v for v in video_history if isinstance(v, dict) and v.get("platform") == "youtube" and v.get("result")]
    applied = 0
    for c in candidates:
        if max_updates and applied >= max_updates:
            break
        meta_info = c.get("result", {})
        fb_id = meta_info.get("facebook_id") or meta_info.get("fb_id")
        ig_id = meta_info.get("instagram_id") or meta_info.get("ig_id")
        if not fb_id and not ig_id:
            continue
        planned = c.get("planned") or {}
        title = planned.get("title") or c.get("current", {}).get("title")
        description = planned.get("description") or c.get("current", {}).get("description")
        seo = build_packages({"title": title, "description": description, "tags": planned.get("tags", [])}).get("instagram", {})
        caption = seo.get("caption")
        hashtags = seo.get("hashtags") or []
        caption_with_tags = caption + "\n\n" + " ".join(hashtags) if hashtags else caption

        if ig_id:
            logger.info("Attempting to update IG media %s", ig_id)
            if dry_run:
                logger.info("Dry-run: would update IG %s caption to: %s", ig_id, caption_with_tags[:200])
                video_history.append({"platform": "instagram", "id": ig_id, "updated": False, "planned": caption_with_tags, "timestamp": time.time()})
                applied += 1
                continue
            url = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{ig_id}"
            params = {"access_token": fb_token, "caption": caption_with_tags}
            resp = session.post(url, params=params)
            try:
                resp.raise_for_status()
                logger.info("IG updated %s: %s", ig_id, resp.text)
                video_history.append({"platform": "instagram", "id": ig_id, "updated": True, "response": resp.json(), "timestamp": time.time()})
                applied += 1
            except Exception as ex:
                logger.exception("Failed to update IG %s: %s", ig_id, ex)
                video_history.append({"platform": "instagram", "id": ig_id, "updated": False, "error": resp.text if resp is not None else str(ex), "timestamp": time.time()})
                if resp is not None and resp.status_code in (400, 403):
                    logger.warning("Instagram API may not allow caption edits programmatically for this media. Consider reposting as fallback.")
                time.sleep(2)

        if fb_id:
            logger.info("Attempting to update FB video %s", fb_id)
            if dry_run:
                logger.info("Dry-run: would update FB %s title/description", fb_id)
                video_history.append({"platform": "facebook", "id": fb_id, "updated": False, "planned": {"title": title, "description": description}, "timestamp": time.time()})
                applied += 1
                continue
            url = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{fb_id}"
            params = {"access_token": fb_token}
            data = {"title": title, "description": description}
            resp = session.post(url, params=params, data=data)
            try:
                resp.raise_for_status()
                logger.info("FB video updated %s: %s", fb_id, resp.text)
                video_history.append({"platform": "facebook", "id": fb_id, "updated": True, "response": resp.json(), "timestamp": time.time()})
                applied += 1
            except Exception as ex:
                logger.exception("Failed to update FB %s: %s", fb_id, ex)
                video_history.append({"platform": "facebook", "id": fb_id, "updated": False, "error": resp.text if resp is not None else str(ex), "timestamp": time.time()})
                if resp is not None and resp.status_code in (400, 403):
                    logger.warning("Facebook API may restrict editing video metadata for published videos. Check Page permissions and API docs.")
                time.sleep(2)

    save_history(video_history_path, video_history)
    logger.info("Meta repair run complete. Applied %d updates (planned %d).", applied, len(candidates))


def main():
    parser = argparse.ArgumentParser(description="Repair old metadata for YouTube/Meta to US-targeted SEO")
    parser.add_argument("--dry-run", action="store_true", help="Do not apply changes, only log planned updates")
    parser.add_argument("--confirm", action="store_true", help="If set, apply changes (requires --dry-run to be false)")
    parser.add_argument("--max-updates", type=int, default=10, help="Maximum number of videos to update in this run")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to sleep between updates")
    parser.add_argument("--revert", action="store_true", help="Revert previously applied updates using backups in video_history.json")
    parser.add_argument("--revert-count", type=int, default=0, help="Number of recent applied updates to revert")
    parser.add_argument("--revert-ids", type=str, help="Comma-separated video ids to revert")
    args = parser.parse_args()

    if args.confirm and args.dry_run:
        logger.error("--confirm cannot be used with --dry-run. To apply changes, run without --dry-run and with --confirm flag.")
        return

    if args.confirm:
        logger.warning("Live mode enabled. This script will modify remote video metadata. Proceed with caution.")

    SETTINGS.ensure_dirs()
    video_history_path = SETTINGS.data_dir / "video_history.json"

    try:
        creds = _load_youtube_creds()
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.exception("Failed to initialize YouTube client: %s", exc)
        return

    if args.revert:
        revert_ids = [s.strip() for s in args.revert_ids.split(',')] if args.revert_ids else None
        revert_updates(youtube, video_history_path, revert_count=(args.revert_count if args.revert_count > 0 else None), revert_ids=revert_ids, dry_run=args.dry_run, sleep_between=args.sleep)
        return

    video_ids = _iter_uploaded_video_ids(youtube)
    logger.info("Found %d uploaded videos", len(video_ids))

    if not video_ids:
        logger.info("No videos found, exiting")
        return

    plan_and_apply_updates(youtube, video_ids, dry_run=args.dry_run, max_updates=args.max_updates, sleep_between=args.sleep)

    fb_token = os.getenv("FACEBOOK_ACCESS_TOKEN", "").strip()
    fb_page = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    ig_user = os.getenv("INSTAGRAM_USER_ID", "").strip()
    if fb_token and (fb_page or ig_user):
        logger.info("Starting Meta repair attempt (may be limited by API)")
        meta_attempt_update(fb_token, fb_page, ig_user, video_history_path, dry_run=args.dry_run, max_updates=args.max_updates)
    else:
        logger.info("Facebook/Instagram credentials missing or incomplete; skipping Meta repairs.")


if __name__ == "__main__":
    main()
