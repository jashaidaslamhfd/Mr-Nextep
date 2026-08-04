"""
src/platform_metrics.py — one honest view of how every upload actually did.

THE PROBLEM THIS SOLVES
-----------------------
The channel publishes the same video to YouTube, Facebook and Instagram, but
performance data lived in three incompatible places: YouTube numbers were
folded into data/video_history.json, Facebook numbers into
data/facebook_analytics.json, and Instagram numbers only ever existed inside
a one-shot diagnostic (data/meta_reach_diag.json) that nothing read back.
Nothing could answer the only question that matters — "which of these three
platforms is actually working, and why?" — so every tuning decision was a
guess dressed up as a strategy.

This module fetches all three into ONE normalised record per video, keyed by
the content fingerprint the uploader already assigns, and writes
data/platform_metrics.json. src/growth_engine.py then learns from it.

NORMALISATION RULES (the whole point of the file)
-------------------------------------------------
Each platform reports a different metric with a different name and a
different unit. They are converted to two comparable numbers:

  views              - integer, best available "someone saw it" count
  completion         - 0..1 average share of the video actually watched

  YouTube  : averageViewPercentage (already a %) -> /100
  Instagram: ig_reels_avg_watch_time (ms) / clip duration (s*1000)
  Facebook : total_video_avg_time_watched (ms) / clip duration

Completion is the comparable currency because it is the signal all three
2026 ranking systems actually rank on, and because it is the only metric that
is fair across platforms with wildly different audience sizes. A 27s Reel at
70% and a 36s Short at 55% are both healthy; raw view counts would have told
us the opposite.

EVERYTHING HERE IS READ-ONLY and every failure is non-fatal: a missing
permission degrades one platform's data, never the run.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

VIDEO_HISTORY_PATH = os.environ.get("VIDEO_HISTORY_PATH", "data/video_history.json")
UPLOAD_STATE_PATH = os.environ.get("UPLOAD_STATE_PATH", "data/upload_state.json")
PLATFORM_METRICS_PATH = os.environ.get("PLATFORM_METRICS_PATH", "data/platform_metrics.json")

FB_API_VERSION = os.environ.get("FB_API_VERSION", "v23.0").strip()
_GRAPH = f"https://graph.facebook.com/{FB_API_VERSION}"

# Metrics are requested ONE AT A TIME on purpose. Meta fails the entire
# insights call if any single metric in the list is unsupported for that media
# product type, which is how the previous diagnostics lost every working
# metric to one bad name.
IG_METRICS = (
    "views", "reach", "saved", "shares", "comments", "likes",
    "total_interactions", "ig_reels_avg_watch_time",
    "replies", "follows", "profile_visits",
)
FB_METRICS = (
    "post_impressions", "post_impressions_unique",
    "total_video_views", "total_video_avg_time_watched",
    "post_video_avg_time_watched", "post_reactions_by_type_total",
)


# ---------------------------------------------------------------------------
# small IO helpers
# ---------------------------------------------------------------------------

def _load_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
    return default


def _save_json_atomic(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _graph_get(node: str, **params) -> Dict:
    """GET a Graph API node. Returns {'error': ...} instead of raising, because
    a missing Meta permission must never take the learning run down."""
    import requests  # imported lazily so offline tests can import this module

    token = params.pop("access_token", None)
    if not token:
        return {"error": "no_token"}
    try:
        response = requests.get(
            f"{_GRAPH}/{node}", params={**params, "access_token": token}, timeout=30
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400 or "error" in data:
            message = str(data.get("error", {}).get("message", response.status_code))
            return {"error": message[:200]}
        return data
    except Exception as exc:  # noqa: BLE001 - network/parse issues are expected
        return {"error": str(exc)[:200]}


def _probe_insights(node: str, metrics, token: str) -> Dict:
    """Fetch each metric separately; return {metric: value} for the ones that
    work plus an 'unsupported' map explaining the rest. Honest partial data
    beats a single opaque failure."""
    values, unsupported = {}, {}
    for metric in metrics:
        result = _graph_get(f"{node}/insights", metric=metric, access_token=token)
        if "error" in result:
            unsupported[metric] = result["error"]
            continue
        rows = result.get("data") or []
        if rows and rows[0].get("values"):
            values[metric] = rows[0]["values"][-1].get("value")
    return {"values": values, "unsupported": unsupported}


# ---------------------------------------------------------------------------
# per-platform fetchers
# ---------------------------------------------------------------------------

def fetch_youtube(video_id: str) -> Dict:
    """Real YouTube Analytics for one video, normalised.

    Delegates to seo_analytics.fetch_actual_performance, which already handles
    the two traps this API sets: never pin `scopes=` on the refresh grant
    (Google rejects it with invalid_scope), and drop unsupported metrics one at
    a time instead of losing the whole query.
    """
    try:
        from seo_analytics import fetch_actual_performance
    except ImportError as exc:  # pragma: no cover
        return {"error": f"seo_analytics unavailable: {exc}"}

    raw = fetch_actual_performance(video_id)
    if "error" in raw:
        return {"error": raw["error"]}
    if "note" in raw and raw.get("views") is None:
        return {"pending": raw["note"]}

    percentage = raw.get("average_view_percentage")
    return {
        "views": raw.get("views"),
        "completion": round(percentage / 100.0, 4) if percentage is not None else None,
        "avg_view_seconds": raw.get("average_view_duration_sec"),
        "impressions": raw.get("impressions"),
        "ctr": raw.get("actual_ctr"),
        "fetched_at": raw.get("fetched_at"),
    }


def fetch_instagram(media_id: str, clip_seconds: float, token: str) -> Dict:
    """Instagram Reel insights, normalised.

    `ig_reels_avg_watch_time` is milliseconds. Dividing by the clip's own
    length is what turns it into the completion rate Instagram actually ranks
    on — and it is the number that told us the old 47s cut was being watched
    for 7 seconds (15%), which no view count would ever have revealed.
    """
    if not media_id or not token:
        return {"error": "missing media_id or token"}
    probe = _probe_insights(media_id, IG_METRICS, token)
    values = probe["values"]
    if not values:
        return {"error": "no_insights", "detail": probe["unsupported"]}

    avg_ms = values.get("ig_reels_avg_watch_time")
    completion = None
    if avg_ms and clip_seconds > 0:
        completion = round(min(float(avg_ms) / (clip_seconds * 1000.0), 1.5), 4)

    reach = values.get("reach") or 0
    shares = values.get("shares") or 0
    saves = values.get("saved") or 0
    likes = values.get("likes") or 0
    return {
        "views": values.get("views"),
        "reach": reach,
        "completion": completion,
        "avg_watch_seconds": round(float(avg_ms) / 1000.0, 2) if avg_ms else None,
        "shares": shares,
        "saves": saves,
        "likes": likes,
        "comments": values.get("comments"),
        # Sends-per-reach is Instagram's confirmed #2 ranking signal and the
        # strongest lever for reaching non-followers, so it gets computed here
        # rather than being left for a human to work out.
        "sends_per_reach": round(shares / reach, 5) if reach else None,
        "saves_per_reach": round(saves / reach, 5) if reach else None,
        "likes_per_reach": round(likes / reach, 5) if reach else None,
        "unsupported": probe["unsupported"] or None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_facebook(video_id: str, clip_seconds: float, token: str) -> Dict:
    """Facebook Reel insights, normalised. Needs `read_insights` on the page
    token; without it this returns a clear error instead of zeros that would
    poison the learning loop with fake 'this platform is dead' signals."""
    if not video_id or not token:
        return {"error": "missing video_id or token"}
    probe = _probe_insights(video_id, FB_METRICS, token)
    values = probe["values"]
    if not values:
        detail = "; ".join(f"{k}: {v}" for k, v in list(probe["unsupported"].items())[:2])
        return {"error": "no_insights", "detail": detail}

    avg_ms = (
        values.get("total_video_avg_time_watched")
        or values.get("post_video_avg_time_watched")
    )
    completion = None
    if avg_ms and clip_seconds > 0:
        completion = round(min(float(avg_ms) / (clip_seconds * 1000.0), 1.5), 4)

    return {
        "views": values.get("total_video_views"),
        "impressions": values.get("post_impressions"),
        "reach": values.get("post_impressions_unique"),
        "completion": completion,
        "avg_watch_seconds": round(float(avg_ms) / 1000.0, 2) if avg_ms else None,
        "reactions": values.get("post_reactions_by_type_total"),
        "unsupported": probe["unsupported"] or None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# collection
# ---------------------------------------------------------------------------

def _clip_seconds(entry: Dict, platform: str) -> float:
    """Length of the cut THAT PLATFORM received.

    Since the dual-cut change, Facebook and Instagram get a shorter edit than
    YouTube, so completion must be divided by the right denominator. Falls
    back to the policy ideal when an older entry predates the field.
    """
    from algorithm_policy import FACEBOOK, INSTAGRAM, YOUTUBE, duration_policy

    key = {
        YOUTUBE: "duration_seconds",
        FACEBOOK: "meta_cut_seconds",
        INSTAGRAM: "meta_cut_seconds",
    }[platform]
    value = entry.get(key)
    if isinstance(value, (int, float)) and value > 1:
        return float(value)
    fallback = entry.get("duration_seconds")
    if platform == YOUTUBE and isinstance(fallback, (int, float)) and fallback > 1:
        return float(fallback)
    return float(duration_policy(platform)[1])


def _instagram_user_id() -> str:
    """The Instagram Business account id to read insights for.

    Normally supplied as INSTAGRAM_USER_ID. When it is absent — which happens
    because the analytics workflow's env block was written before Instagram
    existed in this pipeline, and workflow files cannot be edited by the
    automation maintaining this repo — fall back to the id recorded in the
    committed diagnostic.

    This is safe to read from the repo: an IG Business account id is a public
    identifier (it appears in the Graph API response for the linked Page), not
    a credential. Nothing can be done with it without the access token, which
    is never committed.

    Without this fallback the learning loop would report Instagram as
    "no_data" forever while the token and permissions were both perfectly
    fine — the most confusing possible failure.
    """
    explicit = (os.environ.get("INSTAGRAM_USER_ID") or "").strip()
    if explicit:
        return explicit
    try:
        diag = _load_json("data/ig_diag.json", {})
        recorded = str((diag.get("account") or {}).get("id") or "").strip()
        if recorded:
            logger.info(
                "INSTAGRAM_USER_ID not set; using the id recorded in "
                "data/ig_diag.json (@%s).",
                (diag.get("account") or {}).get("username", "unknown"),
            )
            return recorded
    except Exception:  # noqa: BLE001 - a missing diagnostic is not an error
        pass
    return ""


def _meta_token() -> str:
    """Any of the token names this repo has used over time.

    The workflows are inconsistent — analytics.yml sets FB_ACCESS_TOKEN from
    the FACEBOOK_ACCESS_TOKEN secret, main.yml sets both plus IG_ACCESS_TOKEN.
    Accepting all three means the loop works whichever step it runs in.
    """
    for name in ("IG_ACCESS_TOKEN", "FB_ACCESS_TOKEN", "FACEBOOK_ACCESS_TOKEN"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def collect(min_hours_old: int = 24, refresh_hours: int = 20) -> Dict:
    """Fetch metrics for every upload old enough to have data.

    min_hours_old : platforms need ~24h before numbers mean anything.
    refresh_hours : don't re-hit the APIs for a video fetched recently, but DO
                    keep refreshing older videos — Shorts keep accumulating
                    views for 3-6 weeks and a one-shot fetch would freeze each
                    video at its day-one numbers.
    """
    from algorithm_policy import FACEBOOK, INSTAGRAM, YOUTUBE

    history: List[Dict] = _load_json(VIDEO_HISTORY_PATH, [])
    upload_state: Dict = _load_json(UPLOAD_STATE_PATH, {})
    store: Dict = _load_json(PLATFORM_METRICS_PATH, {})
    if not isinstance(store, dict):
        store = {}

    meta_token = _meta_token()
    if not meta_token:
        logger.warning(
            "No Meta access token in the environment (looked for IG_ACCESS_TOKEN, "
            "FB_ACCESS_TOKEN, FACEBOOK_ACCESS_TOKEN) — Facebook and Instagram "
            "will report no_data even if their permissions are correct."
        )

    now = datetime.now(timezone.utc)
    stats = {"checked": 0, "updated": 0, "skipped_young": 0, "skipped_fresh": 0, "errors": {}}

    for entry in history:
        fingerprint = entry.get("content_fingerprint")
        posted_at = entry.get("posted_at")
        if not fingerprint or not posted_at:
            continue
        try:
            posted = datetime.fromisoformat(str(posted_at))
            posted = posted if posted.tzinfo else posted.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        age_hours = (now - posted).total_seconds() / 3600.0
        if age_hours < min_hours_old:
            stats["skipped_young"] += 1
            continue

        record = store.get(fingerprint) or {}
        last = record.get("fetched_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                last_dt = last_dt if last_dt.tzinfo else last_dt.replace(tzinfo=timezone.utc)
                if (now - last_dt).total_seconds() / 3600.0 < refresh_hours:
                    stats["skipped_fresh"] += 1
                    continue
            except ValueError:
                pass

        stats["checked"] += 1
        record.update({
            "title": entry.get("title"),
            "topic": entry.get("topic"),
            "posted_at": posted_at,
            "publish_at": entry.get("publish_at"),
            "age_hours": round(age_hours, 1),
            "hook_score": entry.get("hook_score"),
            "seo_score": entry.get("seo_score"),
            "duration_seconds": entry.get("duration_seconds"),
            "meta_cut_seconds": entry.get("meta_cut_seconds"),
            "fetched_at": now.isoformat(),
        })

        video_id = entry.get("youtube_video_id")
        if video_id:
            result = fetch_youtube(video_id)
            record[YOUTUBE] = result
            if "error" in result:
                stats["errors"].setdefault(YOUTUBE, result["error"])

        platform_state = upload_state.get(fingerprint, {})
        fb_id = (platform_state.get("facebook") or {}).get("video_id")
        if fb_id and meta_token:
            result = fetch_facebook(fb_id, _clip_seconds(record, FACEBOOK), meta_token)
            record[FACEBOOK] = result
            if "error" in result:
                stats["errors"].setdefault(FACEBOOK, result.get("detail") or result["error"])

        ig_id = (platform_state.get("instagram") or {}).get("media_id")
        if ig_id and meta_token:
            result = fetch_instagram(ig_id, _clip_seconds(record, INSTAGRAM), meta_token)
            record[INSTAGRAM] = result
            if "error" in result:
                stats["errors"].setdefault(INSTAGRAM, str(result.get("detail") or result["error"]))

        store[fingerprint] = record
        stats["updated"] += 1
        # Meta rate-limits aggressively on burst reads from one page token.
        time.sleep(0.3)

    _save_json_atomic(PLATFORM_METRICS_PATH, store)
    logger.info("Platform metrics: %s", stats)
    return {"stats": stats, "total_records": len(store)}


def load_metrics() -> Dict:
    """Read the merged store (used by growth_engine and the report)."""
    data = _load_json(PLATFORM_METRICS_PATH, {})
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    result = collect(
        min_hours_old=int(os.environ.get("METRICS_MIN_HOURS", "24")),
        refresh_hours=int(os.environ.get("METRICS_REFRESH_HOURS", "20")),
    )
    print(json.dumps(result, indent=2))
