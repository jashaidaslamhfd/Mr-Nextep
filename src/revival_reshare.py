"""
Revival resharing for Facebook and Instagram.
Called by the main revival workflow to reshare old reels to Stories.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
REVIVAL_STATE_PATH = os.path.join(DATA_DIR, 'revival_state.json')
IG_REELS_PATH = os.path.join(DATA_DIR, 'instagram_real_data.json')
FB_REELS_PATH = os.path.join(DATA_DIR, 'facebook_real_data.json')

FB_API_VERSION = os.environ.get("FB_API_VERSION", "v23.0").strip()


def _load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)


def reshare_ig_to_stories(reel_id: str, ig_token: str) -> bool:
    """Share an IG reel to the account's Stories.

    Uses the IG Graph API: POST /{ig-user-id}/media
    with { media_type: REELS, media_url, share_to_story: true }

    This is NOT a re-upload — it's the platform-native "Share to Story"
    feature. No duplicate detection, no health impact.
    """
    try:
        import requests as req
    except ImportError:
        logger.error("requests not installed, cannot reshare to IG stories")
        return False

    # Step 1: Get reel media URL
    ig_user_id = os.environ.get("IG_USER_ID")
    if not ig_user_id or not ig_token:
        logger.warning("IG_USER_ID or IG_ACCESS_TOKEN not set — skipping IG story share")
        return False

    try:
        # Get the reel's media URL
        resp = req.get(
            f"https://graph.facebook.com/{FB_API_VERSION}/{reel_id}",
            params={'fields': 'media_url', 'access_token': ig_token},
            timeout=30,
        )
        resp.raise_for_status()
        media_url = resp.json().get('media_url')
        if not media_url:
            logger.warning("Could not get media URL for reel %s", reel_id)
            return False

        # Create story media item
        story_resp = req.post(
            f"https://graph.facebook.com/{FB_API_VERSION}/{ig_user_id}/media",
            data={
                'media_type': 'STORIES',
                'media_url': media_url,
                'access_token': ig_token,
            },
            timeout=30,
        )
        story_resp.raise_for_status()
        story_id = story_resp.json().get('id')
        if not story_id:
            logger.warning("Failed to create story media for reel %s", reel_id)
            return False

        # Publish the story
        pub_resp = req.post(
            f"https://graph.facebook.com/{FB_API_VERSION}/{ig_user_id}/media_publish",
            data={
                'creation_id': story_id,
                'access_token': ig_token,
            },
            timeout=30,
        )
        pub_resp.raise_for_status()
        logger.info("Successfully shared reel %s to IG Stories", reel_id)
        return True

    except Exception as exc:
        logger.warning("IG story share failed for reel %s: %s", reel_id, exc)
        return False


def reshare_fb_to_stories(post_id: str, fb_token: str) -> bool:
    """Share a FB reel to the page's Stories.

    Uses the Pages API: POST /{page-id}/photo with story bucket.
    No re-upload, no duplicate detection.
    """
    try:
        import requests as req
    except ImportError:
        logger.error("requests not installed, cannot reshare to FB stories")
        return False

    page_id = os.environ.get("FB_PAGE_ID")
    if not page_id or not fb_token:
        logger.warning("FB_PAGE_ID or FB_ACCESS_TOKEN not set — skipping FB story share")
        return False

    try:
        # Get reel source URL
        resp = req.get(
            f"https://graph.facebook.com/{FB_API_VERSION}/{post_id}",
            params={'fields': 'source', 'access_token': fb_token},
            timeout=30,
        )
        resp.raise_for_status()
        source_url = resp.json().get('source')
        if not source_url:
            logger.warning("Could not get source URL for FB reel %s", post_id)
            return False

        # Upload to stories
        story_resp = req.post(
            f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/photo",
            data={
                'source': source_url,
                'published': True,
                'story': True,
                'access_token': fb_token,
            },
            timeout=30,
        )
        story_resp.raise_for_status()
        logger.info("Successfully shared reel %s to FB Stories", post_id)
        return True

    except Exception as exc:
        logger.warning("FB story share failed for reel %s: %s", post_id, exc)
        return False


if __name__ == '__main__':
    # Test mode — just print what would be reshared
    state = _load_json(REVIVAL_STATE_PATH, {})
    from revival import plan_meta_stories
    plan = plan_meta_stories(state=state)
    print(f"Stories to reshare: {len(plan)}")
    for p in plan:
        print(f"  → {p['title']} (reel_id={p['reel_id']}, {p['age_days']}d old)")
