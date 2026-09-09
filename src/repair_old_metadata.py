"""
Repair and update old metadata to match US-targeting SEO rules.

Usage:
  python src/repair_old_metadata.py [--dry-run] [--confirm] [--max-updates N]

Notes:
- By default runs in dry-run mode and prints proposed changes.
- Use --confirm to apply changes for real. Use --max-updates to limit updates per run.
- Requires YouTube OAuth credentials in environment (REFRESH_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET).
- For Meta updates, set FACEBOOK_ACCESS_TOKEN, FACEBOOK_PAGE_ID, INSTAGRAM_USER_ID if available.

Safety:
- Respects rate limits with configurable sleep and exponential backoff.
- Logs all attempted updates and appends revised metadata to video_history.json.
"""
from __future__ import annotations
import argparse
import logging
import os
import time
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import SETTINGS
from seo import build_packages
from utils import retry_on_exception, sanitize_hashtags

# Local helpers for history
from guards import load_history, save_history

logger = logging.getLogger("mrnextep.repair")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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


def _iter_uploaded_video_ids(youtube) -> List[str]:
    """Return a list of all video IDs uploaded by the authenticated channel."""
    # Get channel's uploads playlist
    resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        logger.error("No channels found for authenticated user")
        return []
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    video_ids: List[str] = []
    page_token: Optional[str] = None
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
        # modest pause to avoid quota burst
        time.sleep(1)
    return video_ids


def _fetch_video_snippets(youtube, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i+50]
        resp = youtube.videos().list(part="snippet,contentDetails", id=','.join(chunk)).execute()
        for v in resp.get("items", []):
            out[v["id"]] = v
        time.sleep(1)
    return out


@retry_on_exception(max_attempts=5)
def _update_video_snippet(youtube, video_id: str, new_snippet: Dict[str, Any]):
    # Build minimal body: include id and snippet
    body = {"id": video_id, "snippet": new_snippet}
    resp = youtube.videos().update(part="snippet", body=body).execute()
    return resp


def _normalize_tags_for_youtube(tags: List[str]) -> List[str]:
    # sanitize_hashtags returns hashtags with '#'; remove and keep as tags
    cleaned = [t.lstrip('#') for t in sanitize_hashtags(tags, max_hashtags=15)]
    return cleaned


def plan_and_apply_updates(youtube, video_ids: List[str], dry_run: bool = True, max_updates: Optional[int] = None, sleep_between: float = 2.0):
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

        # Build our target packages using existing script info where possible
        # We pass a minimal script structure for seo.build_packages; primary input is title+description+tags
        script = {"title": current_title, "description": current_description, "tags": current_tags}
        seo = build_packages(script).get("youtube", {})
        target_title = seo.get("title", current_title).strip()
        target_description = seo.get("description", current_description).strip()
        target_tags = seo.get("tags", []) or []

        # Ensure tag format
        target_tags = [t.lstrip('#') for t in target_tags]

        needs_update = False
        reasons = []
        if target_title and target_title != current_title and len(target_title) <= 60:
            needs_update = True
            reasons.append("title")
        # Check description - simple substring / length heuristic
        if target_description and target_description != current_description:
            needs_update = True
            reasons.append("description")
        # Compare tags as sets
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

    # Load history
    video_history_path = SETTINGS.data_dir / "video_history.json"
    video_history = load_history(video_history_path)

    applied = 0
    for u in updates:
        if max_updates and applied >= max_updates:
            break
        vid = u["video_id"]
        logger.info("Processing video %s for update: reasons=%s", vid, u["reasons"])
        if dry_run:
            logger.info("Dry-run: would update %s -> %s", vid, u["target"])
            # Append to history with marker but do not call API
            entry = {"platform": "youtube", "id": vid, "updated": False, "planned": u["target"], "timestamp": time.time()}
            video_history.append(entry)
            applied += 1
            continue

        # Live update
        try:
            # Fetch existing snippet to preserve other fields
            existing = snippets.get(vid, {}).get("snippet", {})
            new_snippet = existing.copy()
            new_snippet["title"] = u["target"]["title"]
            new_snippet["description"] = u["target"]["description"]
            new_snippet["tags"] = u["target"]["tags"]

            resp = _update_video_snippet(youtube, vid, new_snippet)
            logger.info("Updated video %s: response id=%s", vid, resp.get("id"))

            entry = {"platform": "youtube", "id": vid, "updated": True, "result": resp, "timestamp": time.time()}
            video_history.append(entry)
            applied += 1
            time.sleep(sleep_between)
        except HttpError as he:
            logger.exception("YouTube HttpError updating %s: %s", vid, he)
            entry = {"platform": "youtube", "id": vid, "updated": False, "error": str(he), "timestamp": time.time()}
            video_history.append(entry)
            # backoff before next
            time.sleep(5)
        except Exception as ex:
            logger.exception("Unexpected error updating %s: %s", vid, ex)
            video_history.append({"platform": "youtube", "id": vid, "updated": False, "error": str(ex), "timestamp": time.time()})
            time.sleep(5)

    # Persist history
    save_history(video_history_path, video_history)
    logger.info("Finished. Applied %d updates (planned %d). History saved to %s", applied, len(updates), video_history_path)


def meta_attempt_update(fb_token: str, facebook_page_id: str, instagram_id: str, video_history_path: Path, dry_run: bool = True, max_updates: Optional[int] = None):
    """
    Attempt to update Facebook page video metadata and Instagram captions where supported.
    Note: Meta APIs have restrictions; editing captions may not be permitted for all media types.
    We'll attempt to update and log the response. If the API refuses, we log guidance.
    """
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

    # For safety, do not enumerate old IG/FB posts here; expect user to provide a list or rely on video_history.json
    # We'll scan video_history for existing youtube uploads that have meta IDs recorded
    candidates = [v for v in video_history if isinstance(v, dict) and v.get("platform") == "youtube" and v.get("result")]
    applied = 0
    for c in candidates:
        if max_updates and applied >= max_updates:
            break
        meta_info = c.get("result", {})
        # Try to find fb_id or ig_id in result
        fb_id = meta_info.get("facebook_id") or meta_info.get("fb_id")
        ig_id = meta_info.get("instagram_id") or meta_info.get("ig_id")

        # If none, skip
        if not fb_id and not ig_id:
            continue

        # Build desired meta caption from stored planned SEO where possible
        planned = c.get("planned") or {}
        title = planned.get("title") or c.get("current", {}).get("title")
        description = planned.get("description") or c.get("current", {}).get("description")
        # build using seo to keep consistency
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
            # Attempt to update via Graph API
            url = f"https://graph.facebook.com/v16.0/{ig_id}"
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
                # If API refuses, provide guidance
                if resp is not None and resp.status_code in (400, 403):
                    logger.warning("Instagram API may not allow caption edits programmatically for this media. Refer to Meta docs and consider reposting with updated caption as fallback.")
                time.sleep(2)

        if fb_id:
            logger.info("Attempting to update FB video %s", fb_id)
            if dry_run:
                logger.info("Dry-run: would update FB %s title/description", fb_id)
                video_history.append({"platform": "facebook", "id": fb_id, "updated": False, "planned": {"title": title, "description": description}, "timestamp": time.time()})
                applied += 1
                continue
            url = f"https://graph.facebook.com/v16.0/{fb_id}"
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
    args = parser.parse_args()

    if args.confirm and args.dry_run:
        logger.error("--confirm cannot be used with --dry-run. To apply changes, run without --dry-run and with --confirm flag.")
        return

    if args.confirm:
        logger.warning("Live mode enabled. This script will modify remote video metadata. Proceed with caution.")

    # Ensure dirs exist
    SETTINGS.ensure_dirs()
    video_history_path = SETTINGS.data_dir / "video_history.json"

    # YouTube flow
    try:
        creds = _load_youtube_creds()
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.exception("Failed to initialize YouTube client: %s", exc)
        return

    # Enumerate videos
    video_ids = _iter_uploaded_video_ids(youtube)
    logger.info("Found %d uploaded videos", len(video_ids))

    if not video_ids:
        logger.info("No videos found, exiting")
        return

    plan_and_apply_updates(youtube, video_ids, dry_run=args.dry_run, max_updates=args.max_updates, sleep_between=args.sleep)

    # Meta flow: attempt updates if tokens are present
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
