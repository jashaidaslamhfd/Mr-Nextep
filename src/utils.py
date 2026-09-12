"""
Small utilities used across upload modules.

Features:
- retry_on_exception: exponential backoff with jitter for transient errors.
- requests_session_with_retries: a requests.Session wrapper that uses the retry logic.
- sanitize_hashtags, unique_text_suffix: basic metadata utilities to avoid exact duplicates.
- randomized_window: helper to jitter a datetime by +/- minutes.
- US-focused hashtag & title helpers for metadata generation targeted to US audiences.

This module intentionally does NOT include any evasion/stealth techniques.
"""
from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable, Iterable
from functools import wraps

import requests
from googleapiclient.errors import HttpError
from requests.exceptions import RequestException

logger = logging.getLogger("mrnextep.utils")


def backoff_with_jitter(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    exp = min(cap, base * (2 ** (attempt - 1)))
    jitter = random.uniform(0, max(0.1, exp * 0.25))
    wait = exp + jitter
    logger.debug("backoff_with_jitter: attempt=%d wait=%.2f", attempt, wait)
    return wait


def http_status_of(exc: Exception) -> int | None:
    """Best-effort HTTP status extraction from a googleapiclient HttpError."""
    if not isinstance(exc, HttpError):
        return None
    try:
        return int(getattr(exc, "status_code", None) or exc.resp.status)
    except Exception:
        return None


def is_transient_http_error(exc: Exception) -> bool:
    """Decide whether an exception is worth retrying.

    5xx and 429 are transient. 403 is NOT: on the YouTube Data API it is almost always
    quotaExceeded / uploadLimitExceeded, which is permanent for the rest of the day.
    Retrying it five times with backoff only burns quota and CI minutes while hiding
    the real cause, so it fails fast and loudly instead.
    """
    status = http_status_of(exc)
    if status is not None:
        if 500 <= status < 600 or status == 429:
            return True
        if status == 403:
            detail = ""
            try:
                detail = (exc.content or b"").decode("utf-8", "replace")[:300]
            except Exception:
                detail = str(exc)[:300]
            logger.error(
                "HTTP 403 from the API is treated as permanent (usually quota or permissions), "
                "not retried. Detail: %s",
                detail,
            )
            return False
        return False
    return isinstance(exc, RequestException)


def retry_on_exception(max_attempts: int = 5, allowed_exceptions: Iterable[type] = (Exception,)):
    """
    Decorator to retry a function on exception with exponential backoff + jitter.
    - For HttpError, retries 5xx and 429 only (403 is permanent — see is_transient_http_error).
    - For RequestException will retry.

    NOTE: do not wrap a resumable upload loop with this decorator. Re-entering the call
    restarts an already partially-consumed media upload; retry the chunk loop instead.
    """
    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    transient = False
                    if isinstance(exc, (HttpError, RequestException)):
                        transient = is_transient_http_error(exc)
                    else:
                        # for other exception types, only retry if explicitly allowed
                        for et in allowed_exceptions:
                            if isinstance(exc, et):
                                transient = True
                                break

                    logger.warning("Exception on attempt %d/%d: %s (transient=%s)", attempt, max_attempts, exc, transient)
                    if attempt >= max_attempts or not transient:
                        logger.exception("Giving up after attempt %d", attempt)
                        raise
                    wait = backoff_with_jitter(attempt)
                    logger.info("Sleeping %.1f seconds before retrying...", wait)
                    time.sleep(wait)
            # If we reach here, re-raise last exception
            raise last_exc
        return wrapper
    return decorator


def requests_session_with_retries(max_attempts: int = 4, backoff_base: float = 1.0) -> requests.Session:
    """
    Build a requests.Session that will use our retry_on_exception wrapper for POST/GET helpers
    (we return the session; callers should still wrap the actual calls with retry_on_exception).
    """
    session = requests.Session()
    # Optionally set headers like a descriptive User-Agent (don't fake user interaction).
    session.headers.update({"User-Agent": "Mr-Nextep/1.0 (+https://github.com/jashaidaslamhfd/Mr-Nextep)"})
    return session


def sanitize_hashtags(tags: list[str], max_hashtags: int = 10) -> list[str]:
    """
    Normalize and deduplicate hashtags, return up to max_hashtags.
    - Removes spaces, leading '#', lowercases duplication checks but preserves original case for output.
    """
    seen = set()
    out = []
    for t in tags:
        if not t:
            continue
        tag = t.strip()
        if tag.startswith("#"):
            tag = tag[1:]
        tag = tag.replace(" ", "")
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append("#" + tag)
        if len(out) >= max_hashtags:
            break
    return out


def unique_text_suffix(previous_text: str | None = None) -> str:
    """Deprecated. Always returns "".

    This used to append " ✨" / " 🔥" / " #<random>" to titles and descriptions so that
    duplicate metadata would slip past dedupe checks. That put visible noise in front of
    viewers (hurting CTR) without making the content any less duplicated. Duplicates are
    now resolved upstream in main.metadata_collides by regenerating the script.

    Kept as a no-op so any external caller keeps working; remove once nothing calls it.
    """
    return ""


def randomized_window(base_timestamp, window_minutes: int = 30):
    """
    Shift base_timestamp by +/- window_minutes seconds (float seconds allowed).
    Accepts and returns a datetime-like object supporting timestamp() and replacement via timestamp().
    """
    import datetime as _dt
    if not isinstance(base_timestamp, _dt.datetime):
        raise TypeError("base_timestamp must be datetime")
    offset_seconds = random.uniform(-window_minutes * 60, window_minutes * 60)
    return base_timestamp + _dt.timedelta(seconds=offset_seconds)


# --- USA-specific metadata helpers ---

def _tokenize_topic(topic: str) -> list[str]:
    return [p.strip().lower() for p in topic.replace('-', ' ').split() if p.strip()]


def generate_us_hashtag_sets(topic: str, raw_tags: list[str], max_total: int = 8) -> dict[str, list[str]]:
    """
    Generate hashtag clusters optimized for US discovery on YouTube/Meta.
    Returns a dict with keys: youtube_tags (3), meta_tags (8), meta_broad (3), meta_niche (3), meta_community (2)
    """
    topic_tokens = _tokenize_topic(topic)
    # Broad US trending tags (sensible, non-spammy defaults)
    broad_us = ["#USA", "#USATrends", "#TrendingNow"]
    # Niche tags from raw_tags and topic tokens
    niche_candidates = []
    for t in raw_tags:
        if t:
            niche_candidates.append('#' + t.strip().replace(' ', '').lower())
    for tok in topic_tokens[:4]:
        niche_candidates.append('#' + tok)
    niche = []
    for n in niche_candidates:
        if n not in niche:
            niche.append(n)
        if len(niche) >= 3:
            break
    # Community tags (broader communities related to content)
    community = ["#learn", "#howto", "#facts"]
    # Final sanitized sets
    youtube_tags = ['#Shorts'] + (niche[:2] if niche else ['#shorts'])
    meta_broad = broad_us[:3]
    meta_niche = niche[:3]
    meta_community = community[:2]

    meta_tags = meta_broad + meta_niche + meta_community
    meta_tags = sanitize_hashtags(meta_tags, max_hashtags=max_total)
    youtube_tags = sanitize_hashtags(youtube_tags, max_hashtags=3)

    return {
        'youtube_tags': youtube_tags,
        'meta_tags': meta_tags,
        'meta_broad': meta_broad,
        'meta_niche': meta_niche,
        'meta_community': meta_community,
    }


# --- Shorts title validation ---------------------------------------------------
#
# A Shorts title is the single highest-leverage CTR surface on the channel, and the
# previous implementation actively damaged it: it hard-truncated at max_chars, which
# cut words in half ("...Emotional Brain Proce", "...health and accessibilit"), then
# appended " #Shorts" to the stump. Combined with the trend scraper mechanically
# prepending "Why does " to a news headline, the channel published titles no human
# would click ("Why does apple acquires brain imaging firm for health and accessibilit").
#
# The fix is to never repair a bad title in place. A title either passes validation or
# it is rejected, and the caller generates a new one — truncation is not a repair.

SHORTS_TITLE_MAX_CHARS = 50

_INTERROGATIVE_OPENERS = frozenset({
    "why", "how", "what", "when", "where", "who", "whose", "which",
    "can", "could", "should", "would", "will", "does", "do", "did",
    "is", "are", "was", "were", "am",
})

# Words that must not be the last word of a title — they promise a continuation that a
# truncated title never delivers.
_DANGLING_TAIL_WORDS = frozenset({
    "the", "a", "an", "of", "and", "or", "but", "in", "on", "at", "for", "to", "with",
    "from", "by", "as", "that", "this", "these", "those", "into", "than", "then",
    "is", "are", "was", "were", "be", "been", "your", "our", "their", "its", "his",
    "her", "my", "it", "you", "we", "they",
})

# Third-person-singular verb forms that appear in news headlines. English requires the
# base form after "Why does <subject>" ("Why does Apple acquire ..."), so one of these
# inside a "Why does ..." title means a headline was spliced onto the interrogative
# mechanically. Deliberately limited to forms that are rarely plural nouns — this is a
# targeted guardrail for that specific bug, not a general grammar checker.
_HEADLINE_CONJUGATED_VERBS = frozenset({
    "acquires", "adds", "alters", "announces", "becomes", "begins", "brings", "builds",
    "buys", "claims", "confirms", "considers", "continues", "creates", "decides",
    "delivers", "denies", "describes", "develops", "discovers", "expands", "explains",
    "fails", "gains", "gives", "grows", "helps", "includes", "increases", "joins",
    "launches", "leaves", "protects", "proves", "provides", "receives", "reduces",
    "rejects", "releases", "remains", "removes", "reveals", "seeks", "seems", "sells",
    "sends", "shares", "stresses", "suggests", "supports", "teaches", "threatens",
    "unveils", "warns",
})

_TRUNCATION_MARKERS = ("...", "\u2026")
# Separators a scraped headline drags in ("Apple buys firm - Reuters").
_SOURCE_SEPARATORS = (" - ", " | ", " \u2013 ", " \u2014 ", " :: ")


class TitleRejected(ValueError):
    """A candidate title is not publishable.

    Raised instead of silently repairing the title. Callers respond by generating a new
    title, never by trimming this one — a cut-off title is worse than a short one.
    """


_WORD_EDGE_PUNCTUATION = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)


def _title_words(title: str) -> list[str]:
    """Lowercased words with surrounding punctuation removed, for the grammar checks."""
    words = (_WORD_EDGE_PUNCTUATION.sub("", w).lower() for w in title.split())
    return [w for w in words if w]


def validate_short_title(raw_title: str, max_chars: int = SHORTS_TITLE_MAX_CHARS) -> str:
    """Return the normalized title, or raise TitleRejected explaining why it is unusable.

    Never truncates and never rewrites. Every check here corresponds to a title the
    channel actually published, so loosening one should be a deliberate decision.
    """
    title = " ".join(str(raw_title or "").split())
    if not title:
        raise TitleRejected("title is empty")

    if len(title) > max_chars:
        raise TitleRejected(
            f"title is {len(title)} chars, over the {max_chars}-char Shorts limit; "
            "generate a shorter title (truncating cuts words in half)"
        )

    if any(marker in title for marker in _TRUNCATION_MARKERS):
        raise TitleRejected("title contains an ellipsis, which reads as cut off")

    if any(sep in title for sep in _SOURCE_SEPARATORS):
        raise TitleRejected("title still carries a source separator from a scraped headline")

    if "#" in title:
        raise TitleRejected(
            "title must not contain hashtags; the platform tag is appended at packaging time "
            "only when it fits"
        )

    # A second sentence-ending mark with text after it means two fragments were spliced,
    # e.g. "Why does overnight Therapy? The Role of Sleep in Emotional Brain Proce".
    if re.search(r"[.?!]\s+\S", title):
        raise TitleRejected("title contains more than one sentence; use a single line")

    words = _title_words(title)
    if len(words) < 4:
        raise TitleRejected(f"title has only {len(words)} words; too thin to build a curiosity gap")
    if len(words) > 12:
        raise TitleRejected(f"title has {len(words)} words; too long to read on a phone")

    if words[-1] in _DANGLING_TAIL_WORDS:
        raise TitleRejected(f"title ends on {words[-1]!r}, which reads as cut off mid-thought")

    if words[0] in _INTERROGATIVE_OPENERS and not title.endswith("?"):
        raise TitleRejected(
            f"title opens with {words[0]!r} but does not end with a question mark"
        )

    if words[0] == "why" and len(words) > 1 and words[1] in {"do", "does"}:
        if len(words) > 2 and words[2] in {"why", "how", "what", "when", "does", "do"}:
            raise TitleRejected("title stacks two interrogatives, e.g. 'Why does why ...'")
        spliced = [w for w in words[2:] if w in _HEADLINE_CONJUGATED_VERBS]
        if spliced:
            raise TitleRejected(
                f"'Why does ...' requires the base verb form, found {spliced[0]!r}; "
                "this is a headline spliced onto an interrogative, not a written title"
            )

    return title


def us_title_for_short(
    raw_title: str,
    max_chars: int = SHORTS_TITLE_MAX_CHARS,
    hashtag: str = "#Shorts",
) -> str:
    """Package a validated title for Shorts.

    Raises TitleRejected for anything unpublishable rather than trimming it. The platform
    hashtag is appended only when it fits inside max_chars; when it does not, it is left
    off and the description/tags carry it. Spending the viewer-visible characters of the
    title on a truncated word to make room for "#Shorts" is a bad trade.
    """
    title = validate_short_title(raw_title, max_chars=max_chars)
    if hashtag and hashtag.lower().lstrip("#") not in title.lower():
        candidate = f"{title} {hashtag}"
        if len(candidate) <= max_chars:
            return candidate
        logger.info(
            "Title uses %d of %d chars, no room for %s; leaving it to tags and description.",
            len(title), max_chars, hashtag,
        )
    return title
