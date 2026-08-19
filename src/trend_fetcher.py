"""Reliable, best-effort topic research for the SKILLOR Shorts pipeline.

This module deliberately uses documented APIs where credentials are available:
* Google Trends daily RSS feed (public, no key)
* YouTube Data API v3 (optional YOUTUBE_API_KEY)
* Reddit OAuth API (optional REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET)

Every source is optional. A source failure is logged with its HTTP status and
never prevents a video from being made; a curated, non-duplicated topic pool
is the final fallback. Do not treat a trending headline as evidence for a
medical/scientific claim: the script/fact-review layer must still verify it.
"""
from __future__ import annotations

import base64
import logging
import json
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
MAX_SOURCE_RETRIES = 2
TARGET_REGION = os.environ.get("TREND_REGION", "US").upper()
YOUTUBE_REGION = os.environ.get("YOUTUBE_REGION_CODE", TARGET_REGION).upper()

# The channel is science/body/brain-oriented. Restricting external headlines
# prevents unrelated politics, celebrity stories and sports results from being
# turned into off-brand Shorts merely because they are trending.
# Deliberately narrow science anchors. Broad words such as "animal", "human",
# "history" and "nature" admitted entertainment headlines like "Why Got Fired
# Matters" that did not give this channel a real explainable science topic.
RELEVANCE_TERMS = (
    "brain", "body", "health", "medical", "medicine", "doctor", "science",
    "space", "nasa", "technology", "tech", "artificial intelligence", "robot",
    "climate", "ocean", "planet", "earth", "physics", "archaeology",
    "psychology", "sleep", "heart", "memory", "nerve", "hormone", "cell",
    "genetics", "genome", "research", "study", "discovery", "scientist",
    "disease", "virus", "nutrition", "immune", "anatomy", "biology",
)

# These are UI/navigation strings sometimes accidentally extracted by fragile
# HTML scrapers. The project no longer scrapes YouTube HTML, but retaining the
# filter protects all sources and future integrations.
INVALID_TOPIC_PATTERNS = (
    r"^try searching to get started$",
    r"^keyboard shortcuts$",
    r"^sign in$",
    r"^home$",
    r"^shorts$",
    r"^subscriptions$",
    r"^youtube$",
    r"^reddit$",
)

# MrNextep's channel data shows the strongest relative performance on familiar,
# low-risk brain/body experiences (yawning, memory, eye twitching, dreams,
# goosebumps)—not broad news headlines or generic "dark" claims. These are
# proven-pillar prompts, never labelled as daily trends.
PROVEN_TOPIC_POOL = [
    "Why songs get stuck in your head",
    "Why you forget names right after meeting someone",
    "Why yawning spreads from person to person",
    "Why your eye twitches randomly",
    "Why goosebumps appear when you are cold",
    "Why dreams disappear after you wake up",
    "Why deja vu feels strangely familiar",
    "Why your heart races when you feel nervous",
    "Why your body freezes when you feel scared",
    "Why your stomach growls when you are hungry",
    "Why you wake up before your alarm",
    "Why your hands wrinkle in water",
    "Why embarrassing memories return at night",
    "Why you forget why you entered a room",
    "Why silence can feel uncomfortable",
    "Why your brain notices your own name",
    "Why time feels faster as you get older",
    "Why stress makes it hard to remember things",
    "Why you feel dizzy after standing up",
    "Why your brain replays conversations later",
    "Why you hear your heartbeat at night",
    "Why bright light makes you sneeze",
    "Why your brain needs deep sleep",
    "Why your eyes see more green shades",
    "Why music changes your mood so quickly",
    "Why you blush when you feel embarrassed",
    "Why you shiver when you feel cold",
    "Why your brain remembers songs so easily",
    "Why your body feels heavy when tired",
    "Why you feel hungry at the same time daily",
]

REDDIT_SUBREDDITS = ("science", "technology", "space", "todayilearned")
USER_AGENT = "SKILLOR/1.1 (automated topic research; contact: channel-owner)"
BODY_GLITCH_CATALOGUE_PATH = Path("data/body_glitch_topics.json")
DARK_MYSTERY_CATALOGUE_PATH = Path("data/dark_mystery_topics.json")


def _normalise_topic(value: str) -> str:
    """Create a comparison key; preserve the original title for display."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.lower())).strip()


# Data-proven flop pattern (FR channel, Jul 2026): a reworded clone of a
# recent topic died at 4 views while the original earned 800+. Exact-string
# dedupe cannot see reworded repeats, so block near-duplicates semantically.
_EN_STOPWORDS = {
    "the", "a", "an", "your", "you", "yours", "why", "when", "what", "how",
    "is", "are", "to", "of", "in", "on", "and", "or", "if", "it", "its",
    "this", "that", "these", "those", "do", "does", "did", "can", "could",
    "will", "would", "with", "without", "for", "from", "at", "by", "as",
    "so", "be", "been", "being", "not", "no", "ever", "every", "daily",
    "really", "just", "don", "didn", "doesn", "isn", "aren", "won", "cant",
    "cannot", "our", "we", "their", "they", "them", "his", "her", "he",
    "she", "me", "my", "mine", "after", "before", "while", "during",
    "reason", "reasons", "get", "gets", "getting", "give", "gives",
    "science", "scientist", "scientists", "fact", "facts", "behind",
    "truth", "hidden", "secret", "secrets", "makes", "make", "making",
}

_WORD_FAMILIES = (
    ("slep", "sleep"), ("drows", "sleep"), ("insomn", "sleep"),
    ("brain", "brain"), ("cerebr", "brain"), ("neur", "brain"),
    ("heart", "heart"), ("cardia", "heart"), ("pulse", "heart"),
    ("stress", "stress"), ("anxie", "stress"), ("worr", "stress"),
    ("freez", "freeze"), ("paraly", "freeze"),
    ("yawn", "yawn"), ("goose", "goosebump"), ("chill", "goosebump"),
    ("wrinkl", "wrinkle"), ("crack", "crack"), ("pop", "crack"),
    ("voice", "voice"), ("vocal", "voice"), ("sound", "voice"),
    ("wake", "morning"),
    ("grow", "grow"), ("shrink", "shrink"),
    ("hunger", "hunger"), ("hungry", "hunger"), ("appet", "hunger"),
    ("morn", "morning"), ("night", "night"),
)


def _topic_words(value: str) -> set:
    norm = _normalise_topic(value)
    words = set()
    for w in norm.split():
        if len(w) <= 2 or w in _EN_STOPWORDS:
            continue
        stem = w
        for prefix, canon in _WORD_FAMILIES:
            if w.startswith(prefix):
                stem = canon
                break
        words.add(stem)
    return words


def _near_duplicate_of_recent(topic: str, excluded: Iterable[str]) -> bool:
    words = _topic_words(topic)
    if len(words) < 2:
        return False
    for recent in (excluded or []):
        rwords = _topic_words(recent)
        if not rwords:
            continue
        overlap = len(words & rwords)
        score = overlap / min(len(words), len(rwords))
        if score >= 0.6 or (rwords and rwords.issubset(words)) or (words and words.issubset(rwords)):
            return True
    return False


def _clean_topic(value: object) -> str:
    """Return a short, printable title or an empty string."""
    if not isinstance(value, str):
        return ""
    title = re.sub(r"\s+", " ", value).strip().strip("-–—: ")
    if len(title) < 12 or len(title) > 160:
        return ""
    lowered = title.lower()
    if any(re.fullmatch(pattern, lowered) for pattern in INVALID_TOPIC_PATTERNS):
        return ""
    return title


def _is_relevant(title: str) -> bool:
    """Match whole terms so e.g. football club “Hearts” is not body content."""
    lowered = title.lower()
    return any(re.search(r"\b" + re.escape(term) + r"\b", lowered) for term in RELEVANCE_TERMS)


def _request(method: str, url: str, *, source: str, **kwargs) -> Optional[requests.Response]:
    """Perform a bounded request and log useful diagnostics on failure."""
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("User-Agent", USER_AGENT)

    for attempt in range(1, MAX_SOURCE_RETRIES + 1):
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            if 200 <= response.status_code < 300:
                return response
            logger.warning(
                "%s unavailable (HTTP %s, attempt %s/%s): %s",
                source, response.status_code, attempt, MAX_SOURCE_RETRIES,
                response.text[:180].replace("\n", " "),
            )
            # Retrying a permanent auth/not-found failure only wastes a run.
            if response.status_code in (400, 401, 403, 404):
                return None
        except requests.RequestException as exc:
            logger.warning("%s request failed (attempt %s/%s): %s", source, attempt, MAX_SOURCE_RETRIES, exc)
        if attempt < MAX_SOURCE_RETRIES:
            time.sleep(1.5 * attempt)
    return None


def _topic_record(topic: str, source: str, **extra: object) -> Dict:
    record: Dict[str, object] = {"topic": topic, "title": topic, "source": source}
    record.update(extra)
    return record


def _deduplicate(records: Iterable[Dict], excluded: Optional[Iterable[str]] = None) -> List[Dict]:
    excluded_keys: Set[str] = {_normalise_topic(x) for x in (excluded or []) if x}
    seen: Set[str] = set()
    result: List[Dict] = []
    for record in records:
        title = _clean_topic(record.get("topic", ""))
        key = _normalise_topic(title)
        if not title or not key or key in seen or key in excluded_keys:
            continue
        seen.add(key)
        clean_record = dict(record)
        clean_record["topic"] = title
        clean_record["title"] = title
        result.append(clean_record)
    return result


def get_google_trends_topics(region: Optional[str] = None) -> List[Dict]:
    """Fetch daily Google trends through its XML RSS feed.

    The former ``/trends/api/dailytrends`` JSON endpoint used by this project
    now returns HTTP 404 in normal requests. RSS is simpler to parse and has a
    stable public response. Google Trends is a discovery signal only.
    """
    region = (region or TARGET_REGION).upper()
    response = _request(
        "GET", "https://trends.google.com/trending/rss", source="Google Trends RSS",
        params={"geo": region}, headers={"Accept": "application/rss+xml, application/xml;q=0.9"},
    )
    if response is None:
        return []
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        logger.warning("Google Trends RSS returned invalid XML: %s", exc)
        return []

    topics: List[Dict] = []
    for item in root.findall("./channel/item"):
        title = _clean_topic(item.findtext("title", default=""))
        if title and _is_relevant(title):
            topics.append(_topic_record(
                title, "google_trends", region=region,
                source_url=item.findtext("link", default=""),
            ))
    logger.info("Google Trends RSS: %s relevant topics for %s.", len(topics), region)
    return _deduplicate(topics)


def get_youtube_trending_topics(region: Optional[str] = None) -> List[Dict]:
    """Use the official YouTube Data API; never scrape the changing HTML UI."""
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        logger.info("YouTube trends skipped: YOUTUBE_API_KEY is not configured.")
        return []
    region = (region or YOUTUBE_REGION).upper()
    response = _request(
        "GET", "https://www.googleapis.com/youtube/v3/videos", source="YouTube Data API",
        params={
            "part": "snippet,statistics", "chart": "mostPopular", "regionCode": region,
            "maxResults": 25, "key": api_key,
        },
    )
    if response is None:
        return []
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("YouTube Data API returned non-JSON data: %s", exc)
        return []

    topics: List[Dict] = []
    for item in payload.get("items", []):
        snippet = item.get("snippet", {})
        title = _clean_topic(snippet.get("title", ""))
        if title and _is_relevant(title):
            topics.append(_topic_record(
                title, "youtube_trending", region=region,
                video_id=item.get("id", ""),
                source_url=f"https://www.youtube.com/watch?v={item.get('id', '')}",
                category_id=snippet.get("categoryId", ""),
            ))
    logger.info("YouTube Data API: %s relevant topics for %s.", len(topics), region)
    return _deduplicate(topics)


def _reddit_access_token() -> Optional[str]:
    """Return an app-only Reddit OAuth token, or None when not configured."""
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.info("Reddit trends skipped: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not configured.")
        return None
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    response = _request(
        "POST", "https://www.reddit.com/api/v1/access_token", source="Reddit OAuth",
        headers={"Authorization": f"Basic {basic}"}, data={"grant_type": "client_credentials"},
    )
    if response is None:
        return None
    try:
        token = response.json().get("access_token")
    except ValueError:
        token = None
    if not token:
        logger.warning("Reddit OAuth returned no access token.")
    return token


def get_reddit_trending_topics() -> List[Dict]:
    """Fetch niche-relevant posts trending today through Reddit OAuth."""
    token = _reddit_access_token()
    if not token:
        return []
    topics: List[Dict] = []
    headers = {"Authorization": f"Bearer {token}"}
    for subreddit in REDDIT_SUBREDDITS:
        response = _request(
            "GET", f"https://oauth.reddit.com/r/{subreddit}/top", source=f"Reddit r/{subreddit}",
            headers=headers, params={"limit": 25, "t": "day", "raw_json": 1},
        )
        if response is None:
            continue
        try:
            children = response.json().get("data", {}).get("children", [])
        except ValueError as exc:
            logger.warning("Reddit r/%s returned non-JSON data: %s", subreddit, exc)
            continue
        for child in children:
            post = child.get("data", {})
            title = _clean_topic(post.get("title", ""))
            if title and _is_relevant(title) and not post.get("over_18", False):
                topics.append(_topic_record(
                    title, f"reddit_r/{subreddit}", subreddit=subreddit,
                    permalink=post.get("permalink", ""),
                    source_url=f"https://www.reddit.com{post.get('permalink', '')}",
                    score=post.get("score", 0),
                ))
    topics = _deduplicate(topics)
    logger.info("Reddit OAuth: %s relevant topics.", len(topics))
    return topics


def get_body_glitch_topics() -> List[Dict]:
    """Load the fixed 500-topic Body Glitch catalogue with series metadata."""
    try:
        with BODY_GLITCH_CATALOGUE_PATH.open(encoding="utf-8") as file_handle:
            records = json.load(file_handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Body Glitch catalogue unavailable: {exc}") from exc

    result = []
    for item in records:
        topic = _clean_topic(item.get("topic", ""))
        if not topic:
            continue
        record = _topic_record(topic, "body_glitch_series", pillar="weird_body_glitches")
        record.update({
            "series_number": item.get("series_number"),
            "series_title": item.get("series_title"),
            "thumbnail_text": item.get("thumbnail_text"),
        })
        result.append(record)
    if len(result) < 500:
        raise RuntimeError(f"Body Glitch catalogue must contain at least 500 valid topics; found {len(result)}")
    return result


def get_dark_mystery_topics() -> List[Dict]:
    """Load the Dark Mystery & Mind-Bending Facts catalogue with series metadata.

    Mirrors the Body Glitch catalogue loader so the two 500-topic launch
    series can share one strategy switch. Topics lean on tension + curiosity
    (sleep paralysis, delusions, sensory glitches) because mystery/critical
    "why?" prompts drive the watch-to-end completion that the saturated
    body-facts niche was failing on, especially on Facebook/Instagram Reels.
    """
    try:
        with DARK_MYSTERY_CATALOGUE_PATH.open(encoding="utf-8") as file_handle:
            records = json.load(file_handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Dark Mystery catalogue unavailable: {exc}") from exc

    result = []
    for item in records:
        topic = _clean_topic(item.get("topic", ""))
        if not topic:
            continue
        record = _topic_record(topic, "dark_mystery_series", pillar="dark_mystery")
        record.update({
            "series_number": item.get("series_number"),
            "series_title": item.get("series_title"),
            "thumbnail_text": item.get("thumbnail_text"),
            "angle": item.get("angle"),
        })
        result.append(record)
    if len(result) < 500:
        raise RuntimeError(
            f"Dark Mystery catalogue must contain at least 500 valid topics; found {len(result)}"
        )
    return result


def get_proven_topics() -> List[Dict]:
    """Return channel-fit evergreen topics based on proven content pillars."""
    return [_topic_record(topic, "proven_channel_pillar") for topic in PROVEN_TOPIC_POOL]


def _weighted_topic_choice(candidates: List[Dict]) -> Dict:
    """Pick a topic, biased toward the body-system pillars that are actually
    holding viewers on this channel.

    Selection used to be uniform random across 500 topics, which meant the
    channel could not benefit from its own results: a pillar that consistently
    retained viewers had exactly the same chance as one that consistently lost
    them. Weights come from data/growth_state.json (see src/growth_engine.py)
    and are clamped to [0.35, 2.0], so:

      * a strong pillar is picked ~2x as often, not exclusively — variety is a
        hard requirement under YouTube's inauthentic-content policy, and a
        channel that only ever covers one body system also stops being a
        body-science channel;
      * a weak pillar keeps a real chance to recover, so a bad fortnight can
        never permanently delete a topic area;
      * with no analytics connected the weights are empty and this degrades
        to exactly the previous uniform behaviour.
    """
    if not candidates:
        raise ValueError("no topic candidates")
    try:
        from growth_engine import get_topic_weights, topic_pillar
        weights_map = get_topic_weights()
    except Exception:  # noqa: BLE001 - topic choice must never break
        return random.choice(candidates)

    if not weights_map:
        return random.choice(candidates)

    weights = [
        float(weights_map.get(topic_pillar(item.get("topic", "")), 1.0))
        for item in candidates
    ]
    chosen = random.choices(candidates, weights=weights, k=1)[0]
    pillar = topic_pillar(chosen.get("topic", ""))
    logger.info(
        "Topic pillar '%s' selected (measured weight %.2f).",
        pillar, weights_map.get(pillar, 1.0),
    )
    return chosen



SEARCH_DEMAND_QUEUE_PATH = Path("data/search_demand_queue_us.json")
def load_search_demand_queue() -> list[dict]:
    """Topics backed by REAL US YouTube search autocomplete demand.
    2026-08-19 (ported from Neuro-Somaa): demand-backed picks are the
    strongest organic growth signal — users actively type these queries, so
    Shorts surface in search + suggested. Missing/corrupt file simply yields
    an empty queue; topic selection degrades gracefully.
    """
    try:
        with SEARCH_DEMAND_QUEUE_PATH.open(encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("topics") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        topic = (item.get("angle") or item.get("topic") or "").strip()
        if not topic:
            continue
        result.append({
            "topic": topic,
            "source": "us_search_demand",
            "base_phenomenon": item.get("topic"),
            "question_phrase": item.get("question_phrase"),
            "angle": item.get("angle"),
            "demand_note": item.get("demand_note"),
        })
    return result

def get_trending_topic(
    exclude: Optional[List[str]] = None,
    *,
    return_metadata: bool = False,
) -> str | Dict:
    """Select a fresh topic using channel fit first and trends second.

    ``TOPIC_STRATEGY=proven_evergreen`` is the production default because the
    channel's own performance favors familiar human experiences. Live trends
    are used only as an occasional, niche-filtered inspiration signal; they
    never force unrelated news or workplace drama into a science channel.
    Set ``REQUIRE_DAILY_TREND=true`` only for a deliberate live-trend campaign.
    """
    # 2026-08-19 (ported from Neuro-Somaa): proven-demand queue picks first —
    # a query with REAL US search intent beats a blind catalogue guess.
    # Used-up entries are filtered by the same history/exclude mechanism.
    # Demand queries get their own stricter-duplicate policy: block only
    # near-identical phenomena, never a loose word overlap (a dark-mystery
    # niche will always reuse words like "mystery/unsolved/creepy" — the
    # phenomenon, not the vocabulary, must be what repeats).
    try:
        _demand = load_search_demand_queue()
        if _demand:
            _exclude_lower = {str(t).strip().lower() for t in (exclude or []) if t}
            def _demand_is_used(topic: str) -> bool:
                if topic.strip().lower() in _exclude_lower:
                    return True
                if _near_duplicate_of_recent(topic, exclude or []):
                    return True
                for published in (exclude or []):
                    p_words = _topic_words(published)
                    d_words = _topic_words(topic)
                    content = {w for w in d_words if len(w) > 3}
                    if not content:
                        continue
                    shared = content & p_words
                    if shared and len(shared) / len(content) >= 0.75:
                        return True
                return False
            _fresh_demand = [e for e in _demand if not _demand_is_used(e["topic"])]
            if _fresh_demand:
                chosen = _fresh_demand[0]
                chosen_rec = {
                    "topic": chosen["topic"],
                    "source": "us_search_demand",
                    "angle": chosen.get("angle"),
                    "question_phrase": chosen.get("question_phrase"),
                    "demand_note": chosen.get("demand_note"),
                }
                logger.info(
                    "🔎 Demand queue: picking REAL-search-demand topic "
                    "(%d left after this pick)", len(_fresh_demand) - 1)
                return chosen_rec if return_metadata else chosen_rec["topic"]
    except Exception as _demand_err:  # noqa: BLE001 - demand must never block the pipeline
        logger.warning("Demand queue skipped (%s) — falling back to strategy picks", _demand_err)
    strategy = os.environ.get("TOPIC_STRATEGY", "body_glitch_series").strip().lower()
    require_daily_trend = os.environ.get("REQUIRE_DAILY_TREND", "false").lower() == "true"

    # Dynamic competitor viral hijacker & real-time search trends strategy.
    # 2026-08-15: YouTube's inauthentic-engagement policy makes hijacking a
    # strike/demotion risk, so this is disabled by default and needs an
    # explicit operator opt-in (COMPETITOR_HIJACK_ENABLED=true) to ever run.
    _hijack_on = os.environ.get("COMPETITOR_HIJACK_ENABLED", "false").lower() == "true"
    if strategy in ("competitor_hijack", "viral_hijack") and _hijack_on:
        from competitor_hijacker import get_hijacked_viral_topic
        chosen = get_hijacked_viral_topic(exclude)
        return chosen if return_metadata else str(chosen["topic"])

    # The Body Glitch launch is deliberately isolated from noisy general
    # trend feeds. This gives YouTube 500 tightly consistent audience signals.
    if strategy == "body_glitch_series":
        series_topics = _deduplicate(get_body_glitch_topics(), exclude)
        series_topics = [t for t in series_topics
                         if not _near_duplicate_of_recent(t.get("topic", ""), exclude or [])]
        if series_topics:
            chosen = _weighted_topic_choice(series_topics)
        else:
            chosen = random.choice(get_body_glitch_topics())
            logger.warning("All Body Glitch topics were excluded; restarting the 500-topic series.")
        logger.info("Selected Body Glitch #%s: %s", chosen.get("series_number"), chosen["topic"])
        return chosen if return_metadata else str(chosen["topic"])

    # Dark Mystery & Mind-Bending Facts launch — tension + curiosity drives the
    # completion the saturated body-facts niche was losing on (Meta gate was
    # 19-24% vs a 70-72% bar). Same 500-topic micro-niche pattern.
    if strategy == "dark_mystery_series":
        series_topics = _deduplicate(get_dark_mystery_topics(), exclude)
        series_topics = [t for t in series_topics
                         if not _near_duplicate_of_recent(t.get("topic", ""), exclude or [])]
        if series_topics:
            chosen = _weighted_topic_choice(series_topics)
        else:
            chosen = random.choice(get_dark_mystery_topics())
            logger.warning("All Dark Mystery topics were excluded; restarting the 500-topic series.")
        logger.info("Selected Dark Mystery #%s: %s", chosen.get("series_number"), chosen["topic"])
        return chosen if return_metadata else str(chosen["topic"])

    records: List[Dict] = []
    records.extend(get_google_trends_topics())
    records.extend(get_youtube_trending_topics())
    records.extend(get_reddit_trending_topics())
    real_topics = _deduplicate(records, exclude)
    proven_topics = _deduplicate(get_proven_topics(), exclude)
    real_topics = [t for t in real_topics
                   if not _near_duplicate_of_recent(t.get("topic", ""), exclude or [])]
    proven_topics = [t for t in proven_topics
                     if not _near_duplicate_of_recent(t.get("topic", ""), exclude or [])]

    if require_daily_trend:
        if not real_topics:
            raise RuntimeError(
                "No relevant daily trend was available. Strict live-trend mode will not publish an off-niche fallback."
            )
        source_weight = {"youtube_trending": 3, "google_trends": 2}
        weights = [source_weight.get(str(item.get("source", "")), 1) for item in real_topics]
        chosen = random.choices(real_topics, weights=weights, k=1)[0]
    elif strategy == "live_trend" and real_topics:
        chosen = random.choice(real_topics)
    elif proven_topics:
        # During the rebuilding period, repeatedly deliver the relatable
        # experiences that already earned this channel's strongest signals —
        # weighted by which body-system pillars are measurably retaining.
        chosen = _weighted_topic_choice(proven_topics)
    elif real_topics:
        chosen = random.choice(real_topics)
    else:
        chosen = random.choice(get_proven_topics())
        logger.warning("All fresh topics were excluded; reusing a proven channel pillar.")

    logger.info(
        "Selected topic from %s: %s | source=%s",
        chosen["source"], chosen["topic"], chosen.get("source_url", "n/a"),
    )
    return chosen if return_metadata else str(chosen["topic"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print(get_trending_topic())
