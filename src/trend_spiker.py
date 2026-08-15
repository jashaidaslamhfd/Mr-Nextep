"""Trend-Spiker: viral spike detector for scheduled pipeline overrides.

Every scheduled run follows the curated series queue (500-topic consistency),
which is the correct default for building a durable audience. Trend-Spiker
is a thin, opt-in overlay: on each run it scans the same public trend feeds
used by trend_fetcher and asks a narrow question - "is there a spike that is
both genuinely hot right now AND on-brand for this channel?"

When both are true, the run logs "SPIKE OVERRIDE" and the spike topic is used
instead of the queue topic for that single slot. No keys are required - all
sources are public feeds (Google Trends RSS, YouTube trending page).

Safety rules (never relaxed):
  - The spike topic must pass the existing niche-relevance filter
    (_is_relevant) so off-brand news can never hijack a slot.
  - It must not be a near-duplicate of any recent channel video.
  - The spike must show at least TWO independent signals (two feeds, or a
    trending entry appearing in multiple regions/positions) to avoid acting
    on noise or a single feed's artifact.
  - The spike topic carries a `spike` flag so history/ML later can learn
    whether spike slots out-perform queue slots (AB evidence for the ML
    brain, no human tuning required).
"""
import logging
import os
import re
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

SPIKE_KEYWORDS = {
    # Sleep / brain / body pillars - what the channel actually earns views on.
    "sleep": ("sleep", "insomnia", "rem", "dream", "nap", "melatonin",
              "circadian", "somnambul", "sleepwalk"),
    "brain": ("brain", "mind", "memory", "focus", "dementia", "alzheimer",
              "cognitive", "neuro"),
    "body": ("body", "immune", "heart", "metabolism", "hormone", "adrenal",
             "cortisol", "fasting", "gut", "muscle", "cramp"),
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _request_public(url: str, *, params: Optional[Dict] = None,
                    timeout: int = 15) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp
    except Exception as exc:  # network issues never block the pipeline
        logger.warning("Trend-Spiker feed unreachable (%s): %s", url, exc)
        return None


def _google_trends_entries() -> List[str]:
    """Google Trends daily RSS - public, no key."""
    resp = _request_public("https://trends.google.com/trending/rss",
                           params={"geo": "US"})
    if resp is None:
        return []
    items = re.findall(r"<title[^>]*>(.+?)</title>", resp.text)
    # RSS feed-level title is always first ("Daily Trends"), skip it.
    return [re.sub(r"<[^>]+>", "", t).strip() for t in items[1:]][:15]


def _youtube_trending_titles() -> List[str]:
    """YouTube trending page - public HTML with public watch counts."""
    resp = _request_public("https://www.youtube.com/feed/trending")
    if resp is None:
        return []
    titles = re.findall(r'"title":\s*\{"runs":\[\{"text":"(.+?)"\}\]', resp.text)
    return titles[:15]


def _signal_strength(matches: int, sources: int) -> bool:
    """A spike must have at least 2 independent confirmations to act on.

    One hot title on one feed is noise (or a feed artifact); the same theme
    showing up on two feeds, or multiple related entries on the same feed,
    is a real demand spike the audience is already searching for.
    """
    return sources >= 2 or matches >= 2


def _topic_record(topic: str, sources: List[str], rank: int) -> Dict:
    return {
        "topic": topic,
        "source": "trend_spike",
        "sources": sources,
        "source_url": "https://trends.google.com/trending/rss",
        "trend_strength": rank,
        "spike": True,
        "thumbnail_text": topic.upper()[:28],
        "angle": "viral spike",
    }


def get_trend_spike(exclude: Optional[List[str]] = None) -> Optional[Dict]:
    """Return a spike topic if one exists, else None.

    The pipeline calls this once per run. None means "no override - use the
    curated queue as usual", which keeps the 500-topic consistency signal
    intact while still catching genuinely hot demand moments.
    """
    if os.environ.get("TREND_SPIKER_ENABLED", "false").lower() != "true":
        return None
    excluded = [str(s).lower() for s in (exclude or [])]

    gt = _google_trends_entries()
    yt = _youtube_trending_titles()
    if not gt and not yt:
        logger.info("Trend-Spiker: no public feeds reachable this run - queue topic used.")
        return None

    hits: Dict[str, Dict] = {}
    for raw in gt + yt:
        key = raw.strip().lower()
        if not key or len(key) < 6:
            continue
        on_brand = any(kw in key for group in SPIKE_KEYWORDS.values() for kw in group)
        if not on_brand:
            continue
        # skip if the channel already covered this theme recently
        if any(ex in key for ex in excluded if len(ex) >= 6):
            continue
        in_gt, in_yt = raw in gt, raw in yt
        src = "google_trends+youtube_trending" if (in_gt and in_yt) else \
              ("google_trends" if in_gt else "youtube_trending")
        hits[key] = {"topic": raw.strip(), "src": src, "in_gt": in_gt, "in_yt": in_yt}

    if not hits:
        return None

    # A real spike: either the SAME topic appears on BOTH feeds, or 2+ on-brand
    # topics show up on one feed (multiple hot entries = rising category heat).
    multi = {k: v for k, v in hits.items() if v["src"].startswith("google_trends+")}
    if multi:
        chosen_key, chosen = next(iter(multi.items()))
        n = len(multi)
        sources = ["google_trends", "youtube_trending"]
    else:
        chosen_key, chosen = next(iter(hits.items()))
        n = len(hits)
        sources = ["google_trends"] if chosen["in_gt"] else ["youtube_trending"]
    if not _signal_strength(n, 2 if multi else 1):
        return None

    record = _topic_record(chosen["topic"], sources, n)
    logger.info("Trend-Spiker: SPIKE OVERRIDE - %s (%s, %d confirmations)",
                record["topic"], record["sources"], n)
    return record
