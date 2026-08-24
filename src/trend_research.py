# src/trend_research.py
"""
Lightweight, no-API-key trend research for the dark body/brain/mystery niche.

WHY THIS EXISTS:
niche_strategy.DARK_TOPICS was a small static list of ~10 topics picked with
random.choice() and no memory of what was already used - so the channel was
guaranteed to repeat topics every couple weeks. That hurts virality (YouTube/
Facebook suppress near-duplicate content) and it never reacts to what's
actually resonating with people right now.

This module pulls today's top posts from a few science/body-adjacent
subreddits via Reddit's public JSON endpoints (no auth, no API key needed),
filters them to ones relevant to this channel's niche, and cleans them into
short topic strings the same shape as DARK_TOPICS entries.

This is best-effort by design: if Reddit is unreachable, rate-limits, or
returns nothing usable, fetch_trending_topics() returns an empty list so the
caller (niche_strategy.get_random_topic) falls back to the static pool
instead of breaking the pipeline.
"""
import logging
import re
import requests

logger = logging.getLogger(__name__)

# Public, unauthenticated Reddit JSON endpoints - no API key required.
REDDIT_SOURCES = [
    "https://www.reddit.com/r/todayilearned/top.json?t=day&limit=25",
    "https://www.reddit.com/r/Damnthatsinteresting/top.json?t=day&limit=25",
    "https://www.reddit.com/r/science/top.json?t=day&limit=25",
    "https://www.reddit.com/r/AskDocs/top.json?t=day&limit=15",
]

# Only pull posts that are actually relevant to this channel's niche -
# random trending Reddit posts about politics/gaming/etc. would be off-brand.
RELEVANT_KEYWORDS = [
    "brain", "heart", "body", "blood", "lung", "bone", "nerve", "sleep",
    "organ", "skin", "muscle", "cell", "dna", "gene", "hormone", "immune",
    "stomach", "kidney", "liver", "eye", "ear", "spine", "human", "brains",
    "spinal", "gut", "digest", "breath", "pain", "reflex", "instinct",
]

# Reddit titles often start with meta-prefixes that don't belong in a
# video topic - strip them before use.
_PREFIX_PATTERN = re.compile(r"^(TIL\s+(that\s+)?|til\s+(that\s+)?)", re.IGNORECASE)

MAX_TOPIC_WORDS = 16  # keep topics short/punchy, same spirit as DARK_TOPICS


def _clean_title(raw_title: str) -> str:
    """Strips Reddit-isms and trims to a usable, short topic string."""
    title = _PREFIX_PATTERN.sub("", raw_title).strip()
    title = title.rstrip(".").strip()
    words = title.split()
    if not words:
        return ""
    if len(words) > MAX_TOPIC_WORDS:
        title = " ".join(words[:MAX_TOPIC_WORDS])
    # Capitalize first letter for consistency with the static topic list.
    return title[0].upper() + title[1:] if title else ""


def fetch_trending_topics(limit: int = 15, timeout: int = 10) -> list:
    """Best-effort fetch of today's relevant trending topics.

    Returns a deduplicated list of clean topic strings, capped at `limit`.
    Returns [] on any network/parse failure - callers must treat this as
    'no trends available right now' and fall back gracefully, not as an
    error worth crashing the pipeline over.
    """
    headers = {"User-Agent": "Nextep-trend-research/1.0 (content research bot)"}
    collected = []

    for url in REDDIT_SOURCES:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            posts = data.get("data", {}).get("children", [])
            for post in posts:
                raw_title = post.get("data", {}).get("title", "")
                if not raw_title:
                    continue
                lowered = raw_title.lower()
                if not any(kw in lowered for kw in RELEVANT_KEYWORDS):
                    continue
                cleaned = _clean_title(raw_title)
                if cleaned:
                    collected.append(cleaned)
        except Exception as e:
            # A single subreddit failing (rate-limit, timeout, etc.) should
            # not block the others - just log and move on.
            logger.warning(f"Trend fetch failed for {url}: {e}")
            continue

    # Dedup case-insensitively while preserving discovery order.
    seen, result = set(), []
    for topic in collected:
        key = topic.lower()
        if key not in seen:
            seen.add(key)
            result.append(topic)
        if len(result) >= limit:
            break

    if result:
        logger.info(f"Trend research: found {len(result)} relevant trending topics today.")
    else:
        logger.info("Trend research: no relevant trending topics found - will use static pool.")

    return result
