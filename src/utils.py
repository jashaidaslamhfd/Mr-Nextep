"""
Small utilities used across upload modules.

Features:
- retry_on_exception: exponential backoff with jitter for transient errors.
- requests_session_with_retries: a requests.Session wrapper that uses the retry logic.
- sanitize_hashtags, unique_text_suffix: basic metadata utilities to avoid exact duplicates.
- randomized_window: helper to jitter a datetime by +/- minutes.

This module intentionally does NOT include any evasion/stealth techniques.
"""
from __future__ import annotations
import time
import random
import logging
from functools import wraps
from typing import Callable, Any, Iterable, List
import requests
from requests.exceptions import RequestException
from googleapiclient.errors import HttpError

logger = logging.getLogger("mrnextep.utils")


def backoff_with_jitter(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    exp = min(cap, base * (2 ** (attempt - 1)))
    jitter = random.uniform(0, max(0.1, exp * 0.25))
    wait = exp + jitter
    logger.debug("backoff_with_jitter: attempt=%d wait=%.2f", attempt, wait)
    return wait


def retry_on_exception(max_attempts: int = 5, allowed_exceptions: Iterable[type] = (Exception,)):
    """
    Decorator to retry a function on exception with exponential backoff + jitter.
    - For HttpError, this will reattempt on 5xx and certain 429/403 transient-like statuses.
    - For RequestException will retry.
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
                    # Special-case: googleapiclient HttpError -> inspect status
                    transient = False
                    if isinstance(exc, HttpError):
                        try:
                            status = int(getattr(exc, "status_code", exc.resp.status))
                        except Exception:
                            status = None
                        # Retry on 5xx or 429; 403 can be transient in some quota flows (be conservative)
                        if status and (500 <= status < 600 or status == 429 or status == 403):
                            transient = True
                    elif isinstance(exc, RequestException):
                        transient = True
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


def sanitize_hashtags(tags: List[str], max_hashtags: int = 10) -> List[str]:
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
    """
    Produce a short, mostly harmless suffix when needed to avoid exact duplication.
    Keeps texts human-readable while introducing minor variation.
    """
    # 30% chance to append nothing, otherwise append a small emoji or number
    if not previous_text:
        return ""
    if random.random() < 0.3:
        return ""
    suffixes = [" ✨", " 🔥", " •", " #shorts", f" #{random.randint(1,999)}"]
    return random.choice(suffixes)


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
