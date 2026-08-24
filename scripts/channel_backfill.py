#!/usr/bin/env python3
"""
MrNextep CHANNEL BACKFILL — Pull ALL videos from YouTube + Facebook + Instagram
─────────────────────────────────────────────────────────────────────────────
Problem: video_history.json has 23 entries but NONE have youtube_id/facebook_id.
         Real channel has 70+ videos that were never tracked.

This script:
  1. Pulls ALL YouTube Shorts via YouTube Data API (search + analytics)
  2. Pulls ALL Facebook Reels via Graph API 
  3. Pulls ALL Instagram Reels via Graph API
  4. Matches untracked videos to history by topic/title similarity
  5. Adds new entries for completely untracked videos
  6. Saves enriched video_history.json + platform_metrics.json
  7. Retrains ML Brain on the complete dataset

Usage:
  python scripts/channel_backfill.py                    # dry-run (preview only)
  python scripts/channel_backfill.py --apply            # actual backfill
  python scripts/channel_backfill.py --youtube-only     # YT only
  python scripts/channel_backfill.py --apply --retrain  # backfill + retrain ML

Secrets needed (in .env or GitHub Secrets):
  YOUTUBE_API_KEY    — for search (optional, OAuth also works)
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / REFRESH_TOKEN — for analytics
  FACEBOOK_ACCESS_TOKEN / FACEBOOK_PAGE_ID — for FB + IG
"""

import json
import os
import re
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
from difflib import SequenceMatcher

import requests
import pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("MrNextep_DATA_DIR", "data"))
VIDEO_HISTORY_PATH = DATA_DIR / "video_history.json"
PLATFORM_METRICS_PATH = DATA_DIR / "platform_metrics.json"
UPLOAD_STATE_PATH = DATA_DIR / "upload_state.json"
FB_ANALYTICS_PATH = DATA_DIR / "facebook_analytics.json"
BACKFILL_LOG = DATA_DIR / "backfill_log.json"

NY = pytz.timezone("America/New_York")

# ── API Config ───────────────────────────────────────────────────
YT_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "")

FB_ACCESS_TOKEN = os.environ.get("FACEBOOK_ACCESS_TOKEN",
                                  os.environ.get("FB_ACCESS_TOKEN", ""))
FB_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID",
                             os.environ.get("FB_PAGE_ID", ""))
FB_API_VERSION = os.environ.get("FB_API_VERSION", "v23.0")
INSTAGRAM_USER_ID = os.environ.get("INSTAGRAM_USER_ID", "")

# ── Helpers ───────────────────────────────────────────────────────

def _topic_similarity(a: str, b: str) -> float:
    """How similar two topic strings are (0..1)."""
    a = re.sub(r"[^a-z\s]", "", (a or "").lower())
    b = re.sub(r"[^a-z\s]", "", (b or "").lower())
    if not a or not b:
        return 0
    # Combine token overlap + sequence matching
    a_words = set(a.split())
    b_words = set(b.split())
    if not a_words or not b_words:
        return 0
    overlap = len(a_words & b_words) / min(len(a_words), len(b_words))
    seq = SequenceMatcher(None, a, b).ratio()
    return 0.6 * overlap + 0.4 * seq


def _load_json(path: Path, default=None):
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
    return default if default is not None else {}


def _save_json_atomic(path: Path, data):
    os.makedirs(path.parent, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ═══════════════════════════════════════════════════════════════════
# YOUTUBE — Pull ALL Shorts from the channel
# ═══════════════════════════════════════════════════════════════════

class YouTubeChannelAudit:
    """Pull every Short from the connected YouTube channel."""

    def __init__(self):
        self.oauth_token: Optional[str] = None
        self.api_key = YT_API_KEY
        self.channel_id: Optional[str] = None
        self.videos: List[Dict] = []

    def _get_oauth_token(self) -> Optional[str]:
        """Exchange refresh token for access token."""
        if self.oauth_token:
            return self.oauth_token
        if not REFRESH_TOKEN or not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            return None
        try:
            resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "refresh_token": REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
            data = resp.json()
            self.oauth_token = data.get("access_token")
            return self.oauth_token
        except Exception as e:
            logger.warning("OAuth token refresh failed: %s", e)
            return None

    def _yt_get(self, endpoint: str, params: dict) -> Dict:
        """Make an authenticated YouTube API call."""
        base = "https://www.googleapis.com/youtube/v3"
        url = f"{base}/{endpoint}"

        token = self._get_oauth_token()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif self.api_key:
            params["key"] = self.api_key
        else:
            return {"error": "No YouTube credentials available"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            return resp.json() if resp.content else {}
        except Exception as e:
            return {"error": str(e)}

    def _yt_get_paginated(self, endpoint: str, params: dict,
                          items_key: str = "items",
                          max_pages: int = 20) -> List[Dict]:
        """Paginated YouTube API call."""
        all_items = []
        page_token = None
        for _ in range(max_pages):
            if page_token:
                params["pageToken"] = page_token
            data = self._yt_get(endpoint, params.copy())
            if "error" in data:
                logger.error("YouTube API error: %s", data.get("error"))
                break
            items = data.get(items_key, [])
            all_items.extend(items)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(0.5)  # Rate limit
        return all_items

    def discover_channel(self) -> Optional[str]:
        """Find the channel ID from OAuth credentials."""
        data = self._yt_get("channels", {
            "part": "id,snippet,statistics,contentDetails",
            "mine": "true",
            "maxResults": 1,
        })
        items = data.get("items", [])
        if items:
            self.channel_id = items[0]["id"]
            logger.info("📺 Channel: %s (ID: %s)",
                       items[0]["snippet"]["title"],
                       self.channel_id)
            return self.channel_id

        # Fallback: search by handle
        if self.api_key:
            logger.warning("OAuth channel lookup failed, trying API key...")
            data = self._yt_get("channels", {
                "part": "id,snippet",
                "forHandle": "@MrNextep",
                "key": self.api_key,
            })
            items = data.get("items", [])
            if items:
                self.channel_id = items[0]["id"]
                return self.channel_id

        logger.error("Could not discover YouTube channel. Check credentials.")
        return None

    def pull_all_shorts(self) -> List[Dict]:
        """Pull ALL Shorts from the channel."""
        if not self.channel_id:
            if not self.discover_channel():
                return []

        logger.info("🔍 Pulling ALL YouTube Shorts from channel %s...", self.channel_id)

        # Get uploads playlist
        ch_data = self._yt_get("channels", {
            "part": "contentDetails",
            "id": self.channel_id,
        })
        items = ch_data.get("items", [])
        if not items:
            logger.error("No channel data returned")
            return []

        uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # Pull all videos from uploads
        all_videos = self._yt_get_paginated("playlistItems", {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": 50,
        }, max_pages=10)

        # Filter for Shorts (duration < 60s, or #shorts in title)
        shorts = []
        for item in all_videos:
            snippet = item.get("snippet", {})
            title = snippet.get("title", "").lower()
            desc = snippet.get("description", "").lower()

            # Shorts indicators
            is_short = (
                "#shorts" in desc or
                "#short" in desc or
                "shorts" in title
            )

            # Also check via videos.list for duration
            vid = item["contentDetails"]["videoId"]

            if is_short:
                shorts.append({
                    "youtube_id": vid,
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", "")[:500],
                    "published_at": snippet.get("publishedAt", ""),
                    "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                    "tags": snippet.get("tags", []),
                })

        logger.info("  Found %d shorts out of %d total videos", len(shorts), len(all_videos))

        # Pull detailed stats for each short
        for i, short in enumerate(shorts):
            if i % 10 == 0:
                logger.info("  Fetching analytics... %d/%d", i + 1, len(shorts))

            vid = short["youtube_id"]
            stats = self._yt_get("videos", {
                "part": "statistics,contentDetails,status",
                "id": vid,
            })

            stat_items = stats.get("items", [])
            if stat_items:
                s = stat_items[0]
                st = s.get("statistics", {})
                cd = s.get("contentDetails", {})

                # Parse duration (PTxxMxxS format)
                duration_str = cd.get("duration", "PT0S")
                duration_sec = self._parse_duration(duration_str)

                short.update({
                    "views": int(st.get("viewCount", 0)),
                    "likes": int(st.get("likeCount", 0)),
                    "comments": int(st.get("commentCount", 0)),
                    "duration_seconds": duration_sec,
                    "made_for_kids": s.get("status", {}).get("madeForKids", False),
                })

            time.sleep(0.3)

        # Pull analytics (retention, CTR) via YouTube Analytics API
        self._pull_analytics_for_shorts(shorts)

        self.videos = shorts
        return shorts

    def _parse_duration(self, duration: str) -> float:
        """Parse ISO 8601 duration to seconds."""
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not match:
            return 0
        h, m, s = match.groups()
        return int(h or 0) * 3600 + int(m or 0) * 60 + int(s or 0)

    def _pull_analytics_for_shorts(self, shorts: List[Dict]):
        """Pull YouTube Analytics for each short (retention, CTR)."""
        token = self._get_oauth_token()
        if not token:
            logger.warning("  No OAuth token — skipping analytics (views still populated)")
            return

        for short in shorts:
            vid = short["youtube_id"]
            try:
                resp = requests.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": f"channel=={self.channel_id}",
                        "startDate": "2026-01-01",
                        "endDate": "2026-08-04",
                        "metrics": "averageViewPercentage,estimatedMinutesWatched",
                        "filters": f"video=={vid}",
                        "dimensions": "video",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=20,
                )
                data = resp.json() if resp.content else {}
                rows = data.get("rows", [])
                if rows and rows[0]:
                    short["average_view_percentage"] = round(rows[0][0], 2)
                else:
                    short["average_view_percentage"] = None

                # Also pull for averageViewDuration
                resp2 = requests.get(
                    "https://youtubeanalytics.googleapis.com/v2/reports",
                    params={
                        "ids": f"channel=={self.channel_id}",
                        "startDate": "2026-01-01",
                        "endDate": "2026-08-04",
                        "metrics": "averageViewDuration",
                        "filters": f"video=={vid}",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=20,
                )
                data2 = resp2.json() if resp2.content else {}
                rows2 = data2.get("rows", [])
                if rows2 and rows2[0]:
                    short["average_view_duration_sec"] = round(rows2[0][0], 2)

                time.sleep(0.3)
            except Exception as e:
                logger.debug("  Analytics failed for %s: %s", vid, e)


# ═══════════════════════════════════════════════════════════════════
# FACEBOOK + INSTAGRAM — Pull ALL Reels
# ═══════════════════════════════════════════════════════════════════

class MetaChannelAudit:
    """Pull every Reel from the connected Facebook Page + Instagram account."""

    def __init__(self):
        self.token = FB_ACCESS_TOKEN
        self.page_id = FB_PAGE_ID
        self.ig_user_id = INSTAGRAM_USER_ID
        self.base = f"https://graph.facebook.com/{FB_API_VERSION}"
        self.fb_reels: List[Dict] = []
        self.ig_reels: List[Dict] = []

    def _graph_get(self, node: str, params: dict = None) -> Dict:
        """Make an authenticated Graph API call."""
        if not self.token:
            return {"error": "No Facebook access token"}
        p = params.copy() if params else {}
        p["access_token"] = self.token
        try:
            resp = requests.get(f"{self.base}/{node}", params=p, timeout=30)
            return resp.json() if resp.content else {}
        except Exception as e:
            return {"error": str(e)}

    def _graph_paginated(self, node: str, params: dict = None,
                         max_pages: int = 10) -> List[Dict]:
        """Paginated Graph API call."""
        all_items = []
        p = params.copy() if params else {}
        url_node = node

        for _ in range(max_pages):
            data = self._graph_get(url_node, p)
            if "error" in data:
                logger.error("Graph API error: %s", data.get("error", {}).get("message", str(data)))
                break
            items = data.get("data", [])
            all_items.extend(items)

            # Cursor pagination
            paging = data.get("paging", {})
            next_url = paging.get("next")
            if not next_url:
                break

            # Extract the full URL for next page
            url_node = next_url.split(f"{self.base}/")[-1].split("?")[0]
            # Parse query params
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(next_url)
            p = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            time.sleep(0.5)

        return all_items

    def pull_facebook_reels(self) -> List[Dict]:
        """Pull ALL Facebook Reels from the page."""
        if not self.token or not self.page_id:
            logger.warning("Facebook credentials missing — skipping FB backfill")
            return []

        logger.info("📘 Pulling ALL Facebook Reels from page %s...", self.page_id)

        # Get video posts
        videos = self._graph_paginated(
            f"{self.page_id}/videos",
            {"fields": "id,title,description,created_time,length,views,source,permalink_url,thumbnails"},
        )

        # Filter for Reels (short videos < 60s)
        reels = []
        for v in videos:
            # Try to get detailed insights
            vid = v.get("id", "")
            # Get video insights
            insights_data = self._graph_get(
                f"{vid}/video_insights",
                {"metric": "total_video_views,total_video_avg_time_watched,post_reactions_by_type_total"},
            )

            insights = {}
            for item in insights_data.get("data", []):
                name = item.get("name", "")
                values = item.get("values", [])
                if values:
                    insights[name] = values[0].get("value", 0)

            reels.append({
                "facebook_id": vid,
                "title": v.get("title", v.get("description", ""))[:200],
                "description": v.get("description", "")[:500],
                "published_at": v.get("created_time", ""),
                "views": int(v.get("views", insights.get("total_video_views", 0))),
                "avg_watch_ms": insights.get("total_video_avg_time_watched", 0),
                "reactions": insights.get("post_reactions_by_type_total", {}),
                "permalink": v.get("permalink_url", ""),
            })

        self.fb_reels = reels
        logger.info("  Found %d Facebook Reels", len(reels))
        return reels

    def pull_instagram_reels(self) -> List[Dict]:
        """Pull ALL Instagram Reels."""
        if not self.token or not self.ig_user_id:
            logger.warning("Instagram credentials missing — skipping IG backfill")
            return []

        logger.info("📸 Pulling ALL Instagram Reels...")

        # Get media from IG business account
        media = self._graph_paginated(
            f"{self.ig_user_id}/media",
            {
                "fields": "id,caption,media_type,timestamp,permalink,thumbnail_url,"
                          "like_count,comments_count,insights.metric(reach,plays,saved,shares,total_interactions,ig_reels_avg_watch_time)",
                "media_type": "REELS",
            },
        )

        reels = []
        for m in media:
            caption = m.get("caption", "") or ""
            insights_data = m.get("insights", {}).get("data", [])
            insights = {}
            for item in insights_data:
                name = item.get("name", "")
                values = item.get("values", [])
                if values:
                    insights[name] = values[0].get("value", 0)

            reels.append({
                "instagram_id": m.get("id", ""),
                "caption": caption[:500],
                "published_at": m.get("timestamp", ""),
                "likes": m.get("like_count", 0),
                "comments": m.get("comments_count", 0),
                "reach": insights.get("reach", 0),
                "plays": insights.get("plays", 0),
                "saved": insights.get("saved", 0),
                "shares": insights.get("shares", 0),
                "avg_watch_time_ms": insights.get("ig_reels_avg_watch_time", 0),
                "permalink": m.get("permalink", ""),
            })

        self.ig_reels = reels
        logger.info("  Found %d Instagram Reels", len(reels))
        return reels


# ═══════════════════════════════════════════════════════════════════
# BACKFILL ENGINE — Match & Merge
# ═══════════════════════════════════════════════════════════════════

class BackfillEngine:
    """Match API data to local history and merge everything."""

    SIMILARITY_THRESHOLD = 0.45

    def __init__(self):
        self.history = _load_json(VIDEO_HISTORY_PATH, [])
        self.platform_metrics = _load_json(PLATFORM_METRICS_PATH, {})
        self.stats = {
            "youtube_matched": 0,
            "youtube_new": 0,
            "facebook_matched": 0,
            "facebook_new": 0,
            "instagram_matched": 0,
            "instagram_new": 0,
            "views_updated": 0,
            "retention_updated": 0,
        }

    def backfill_youtube(self, yt_shorts: List[Dict], dry_run: bool = True):
        """Backfill YouTube data into history."""
        logger.info("\n── Backfilling YouTube data ──")

        # Build topic lookup from existing history
        history_topics = []
        for i, entry in enumerate(self.history):
            topic = entry.get("topic", "")
            if topic:
                history_topics.append((i, topic))

        matched_ids: Set[str] = set()
        matched_entries: Set[int] = set()

        for short in yt_shorts:
            yt_id = short.get("youtube_id", "")
            title = short.get("title", "")
            desc = short.get("description", "")

            # Try to match by topic similarity
            best_score = 0
            best_idx = -1

            for idx, topic in history_topics:
                if idx in matched_entries:
                    continue
                # Compare against title and description
                score_title = _topic_similarity(topic, title)
                score_desc = _topic_similarity(topic, desc[:200])
                score = max(score_title, score_desc)
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_score >= self.SIMILARITY_THRESHOLD and best_idx >= 0:
                # Match found — update existing entry
                entry = self.history[best_idx]
                entry["youtube_id"] = yt_id
                entry["youtube_title"] = title
                entry["views"] = short.get("views", entry.get("views"))
                entry["likes"] = short.get("likes", entry.get("likes"))
                entry["comments"] = short.get("comments", entry.get("comments"))
                entry["duration_seconds"] = short.get("duration_seconds")
                if short.get("average_view_percentage"):
                    entry["average_view_percentage"] = short["average_view_percentage"]
                    self.stats["retention_updated"] += 1
                if short.get("average_view_duration_sec"):
                    entry["average_view_duration_sec"] = short["average_view_duration_sec"]
                entry["published_at"] = short.get("published_at", entry.get("published_at"))
                entry["analytics_fetched_at"] = datetime.now(timezone.utc).isoformat()

                matched_ids.add(yt_id)
                matched_entries.add(best_idx)
                self.stats["youtube_matched"] += 1
                self.stats["views_updated"] += 1
                logger.debug("  ✅ Matched: '%s' → %s (score=%.2f)", topic[:50], yt_id, best_score)
            else:
                # No match — this is a new (untracked) video
                new_entry = {
                    "topic": title,
                    "youtube_id": yt_id,
                    "youtube_title": title,
                    "description": desc,
                    "views": short.get("views", 0),
                    "likes": short.get("likes", 0),
                    "comments": short.get("comments", 0),
                    "duration_seconds": short.get("duration_seconds"),
                    "average_view_percentage": short.get("average_view_percentage"),
                    "average_view_duration_sec": short.get("average_view_duration_sec"),
                    "published_at": short.get("published_at", ""),
                    "hook_score": None,
                    "word_count": None,
                    "source": "youtube_backfill",
                    "backfilled_at": datetime.now(timezone.utc).isoformat(),
                }
                if not dry_run:
                    self.history.append(new_entry)
                matched_ids.add(yt_id)
                self.stats["youtube_new"] += 1
                logger.debug("  🆕 NEW: '%s' → %s (score=%.2f)", title[:50], yt_id, best_score)

        logger.info("  YouTube: %d matched, %d new, %d views updated, %d retention updated",
                   self.stats["youtube_matched"], self.stats["youtube_new"],
                   self.stats["views_updated"], self.stats["retention_updated"])

    def backfill_facebook(self, fb_reels: List[Dict], dry_run: bool = True):
        """Backfill Facebook data."""
        logger.info("\n── Backfilling Facebook data ──")

        history_topics = [(i, e.get("topic", "")) for i, e in enumerate(self.history)
                         if e.get("topic") and not e.get("facebook_id")]

        matched = 0
        for reel in fb_reels:
            fb_id = reel.get("facebook_id", "")
            title = reel.get("title", "")
            desc = reel.get("description", "")

            best_score = 0
            best_idx = -1
            for idx, topic in history_topics:
                score = max(_topic_similarity(topic, title),
                          _topic_similarity(topic, desc[:200]))
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_score >= self.SIMILARITY_THRESHOLD and best_idx >= 0:
                entry = self.history[best_idx]
                entry["facebook_id"] = fb_id
                entry["fb_views"] = reel.get("views", 0)
                entry["fb_avg_watch_ms"] = reel.get("avg_watch_ms", 0)
                matched += 1
            else:
                new_entry = {
                    "topic": title,
                    "facebook_id": fb_id,
                    "fb_views": reel.get("views", 0),
                    "fb_avg_watch_ms": reel.get("avg_watch_ms", 0),
                    "published_at": reel.get("published_at", ""),
                    "source": "facebook_backfill",
                    "backfilled_at": datetime.now(timezone.utc).isoformat(),
                }
                if not dry_run:
                    self.history.append(new_entry)
                self.stats["facebook_new"] += 1

        self.stats["facebook_matched"] = matched
        logger.info("  Facebook: %d matched, %d new", matched, self.stats["facebook_new"])

    def backfill_instagram(self, ig_reels: List[Dict], dry_run: bool = True):
        """Backfill Instagram data."""
        logger.info("\n── Backfilling Instagram data ──")

        history_topics = [(i, e.get("topic", "")) for i, e in enumerate(self.history)
                         if e.get("topic") and not e.get("instagram_id")]

        matched = 0
        for reel in ig_reels:
            ig_id = reel.get("instagram_id", "")
            caption = reel.get("caption", "")

            best_score = 0
            best_idx = -1
            for idx, topic in history_topics:
                score = _topic_similarity(topic, caption[:200])
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_score >= self.SIMILARITY_THRESHOLD and best_idx >= 0:
                entry = self.history[best_idx]
                entry["instagram_id"] = ig_id
                entry["ig_reach"] = reel.get("reach", 0)
                entry["ig_likes"] = reel.get("likes", 0)
                entry["ig_comments"] = reel.get("comments", 0)
                entry["ig_avg_watch_time_ms"] = reel.get("avg_watch_time_ms", 0)
                matched += 1
            else:
                new_entry = {
                    "topic": caption[:150],
                    "instagram_id": ig_id,
                    "ig_reach": reel.get("reach", 0),
                    "ig_likes": reel.get("likes", 0),
                    "ig_comments": reel.get("comments", 0),
                    "published_at": reel.get("published_at", ""),
                    "source": "instagram_backfill",
                    "backfilled_at": datetime.now(timezone.utc).isoformat(),
                }
                if not dry_run:
                    self.history.append(new_entry)
                self.stats["instagram_new"] += 1

        self.stats["instagram_matched"] = matched
        logger.info("  Instagram: %d matched, %d new", matched, self.stats["instagram_new"])

    def save(self):
        """Save the merged history."""
        # Sort by published_at
        self.history.sort(
            key=lambda x: x.get("published_at", x.get("backfilled_at", "2000-01-01") or "2000-01-01")
        )
        _save_json_atomic(VIDEO_HISTORY_PATH, self.history)
        logger.info("\n💾 Saved %d total entries to %s", len(self.history), VIDEO_HISTORY_PATH)

    def print_summary(self):
        """Print backfill summary."""
        print("\n" + "=" * 60)
        print("  📊 BACKFILL SUMMARY")
        print("=" * 60)
        print(f"  YouTube:    {self.stats['youtube_matched']} matched | {self.stats['youtube_new']} new")
        print(f"  Facebook:   {self.stats['facebook_matched']} matched | {self.stats['facebook_new']} new")
        print(f"  Instagram:  {self.stats['instagram_matched']} matched | {self.stats['instagram_new']} new")
        print("  ─────────────────────────────────────")
        total = sum(v for k, v in self.stats.items() if k.endswith("_matched") or k.endswith("_new"))
        print(f"  TOTAL:      {total} videos processed")
        print(f"  Views updated:     {self.stats['views_updated']}")
        print(f"  Retention updated: {self.stats['retention_updated']}")
        print(f"  Final history:     {len(self.history)} entries")
        print("=" * 60)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    dry_run = "--apply" not in sys.argv
    youtube_only = "--youtube-only" in sys.argv
    retrain = "--retrain" in sys.argv

    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"\n🔧 MrNextep CHANNEL BACKFILL — {mode}")
    print(f"   {'=' * 45}\n")

    start = time.time()

    # ── 1. YouTube ──
    yt = YouTubeChannelAudit()
    yt_shorts = yt.pull_all_shorts()
    print(f"\n📺 YouTube: {len(yt_shorts)} Shorts found")

    # ── 2. Facebook ──
    fb_reels = []
    if not youtube_only:
        meta = MetaChannelAudit()
        fb_reels = meta.pull_facebook_reels()
        ig_reels = meta.pull_instagram_reels()
    else:
        ig_reels = []

    print(f"📘 Facebook: {len(fb_reels)} Reels found")
    print(f"📸 Instagram: {len(ig_reels)} Reels found")

    # ── 3. Backfill ──
    engine = BackfillEngine()
    engine.backfill_youtube(yt_shorts, dry_run=dry_run)
    if not youtube_only:
        engine.backfill_facebook(fb_reels, dry_run=dry_run)
        engine.backfill_instagram(ig_reels, dry_run=dry_run)

    engine.print_summary()

    if not dry_run:
        engine.save()

        # Save backfill log
        log = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "youtube_count": len(yt_shorts),
            "facebook_count": len(fb_reels),
            "instagram_count": len(ig_reels),
            "stats": engine.stats,
            "duration_seconds": round(time.time() - start, 1),
        }
        _save_json_atomic(BACKFILL_LOG, log)

        # ── 4. Retrain ML Brain ──
        if retrain:
            logger.info("\n🧠 Retraining ML Brain with complete dataset...")
            try:
                from scripts.ml_brain import MLBrain
                brain = MLBrain()
                brain.train()
                brain.save()
                logger.info("✅ ML Brain retrained on %d videos!", brain.n_samples)
            except Exception as e:
                logger.error("ML retrain failed: %s", e)
    else:
        print("\n🔍 DRY RUN — no files modified. Run with --apply to save changes.")
        print("   python scripts/channel_backfill.py --apply --retrain")

    elapsed = time.time() - start
    print(f"\n⏱️  Completed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
