#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import html
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger("trend_fetcher")
CACHE_TTL_HOURS = 6
CACHE_MAX_STALE_DAYS = 7
MAX_RETRIES = 3
MAX_RETRY_AFTER_SECONDS = 30

UA = "Mr-Nextep-TrendFetcher/2.0"
SOURCES = {
    "google_trends_us": "https://trends.google.com/trending/rss?geo=US",
    "google_news_us": "https://news.google.com/rss/search?q=AI+OR+artificial+intelligence+OR+chatbot+OR+deepfake+OR+brain+OR+psychology+OR+memory+OR+behavior+OR+consciousness&hl=en-US&gl=US&ceid=US:en",
    "nih_news": "https://news.google.com/rss/search?q=site%3Anih.gov+(brain+OR+sleep+OR+memory+OR+psychology+OR+behavior+OR+neuroscience)&hl=en-US&gl=US&ceid=US:en",
}
CORE_KEYWORDS = (
    "ai", "artificial intelligence", "chatbot", "chatbots", "deepfake",
    "synthetic media", "voice clone", "machine learning", "robot", "algorithm",
    "brain", "neuron", "neuroscience", "memory", "dream", "sleep", "attention",
    "perception", "psychology", "behavior", "behaviour", "emotion", "consciousness",
    "subconscious", "illusion", "bias", "dopamine", "trust", "hallucination",
    "false memory", "human mind",
)
NOISE = (
    "stock", "stocks", "shares", "investor", "investing", "market", "price target",
    "earnings", "crypto", "bitcoin", "sports", "score", "odds", "lottery",
    "vaccine", "vaccines", "supplement", "creatine", "diet", "weight loss",
    "drug", "drugs", "medication", "mold", "injury", "broken ribs", "celebrity gossip",
)

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def _utc_now() -> datetime:
    return datetime.now(UTC)


def _read_cache(cache_path: Path) -> dict | None:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        body = base64.b64decode(payload["body_b64"], validate=True)
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return {**payload, "body": body, "fetched_dt": fetched_at.astimezone(UTC)}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _save_cache(cache_path: Path, body: bytes, headers, fetched_at: datetime) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "body_b64": base64.b64encode(body).decode("ascii"),
        "fetched_at": fetched_at.isoformat(),
        "etag": headers.get("ETag", ""),
        "last_modified": headers.get("Last-Modified", ""),
    }
    temp_path = cache_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload), encoding="utf-8")
    temp_path.replace(cache_path)


def fetch(url: str, source: str = "feed", cache_dir: str | Path = "data/trend_source_cache") -> bytes:
    """Fetch politely: use a six-hour cache, conditional requests, bounded backoff, stale fallback."""
    cache_path = Path(cache_dir) / f"{source}.json"
    cached = _read_cache(cache_path)
    now = _utc_now()
    if cached and now - cached["fetched_dt"] < timedelta(hours=CACHE_TTL_HOURS):
        log.info("%s: using fresh cached feed", source)
        return cached["body"]

    headers = {"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml"}
    if cached and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    if cached and cached.get("last_modified"):
        headers["If-Modified-Since"] = cached["last_modified"]

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with urlopen(Request(url, headers=headers), timeout=12) as response:
                body = response.read()
                _save_cache(cache_path, body, response.headers, _utc_now())
                return body
        except HTTPError as exc:
            if exc.code == 304 and cached:
                _save_cache(cache_path, cached["body"], {
                    "ETag": cached.get("etag", ""),
                    "Last-Modified": cached.get("last_modified", ""),
                }, _utc_now())
                return cached["body"]
            last_error = exc
            if exc.code not in (408, 425, 429, 500, 502, 503, 504):
                break
            retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
            try:
                delay = min(MAX_RETRY_AFTER_SECONDS, max(1.0, float(retry_after)))
            except (TypeError, ValueError):
                delay = min(MAX_RETRY_AFTER_SECONDS, 2.0 ** attempt)
            log.warning("%s returned HTTP %s; retry %d/%d in %.1fs", source, exc.code, attempt + 1, MAX_RETRIES, delay)
        except (URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            delay = min(MAX_RETRY_AFTER_SECONDS, 2.0 ** attempt)
            log.warning("%s connection failed; retry %d/%d in %.1fs: %s", source, attempt + 1, MAX_RETRIES, delay, exc)
        if attempt < MAX_RETRIES - 1:
            time.sleep(delay)

    if cached and now - cached["fetched_dt"] <= timedelta(days=CACHE_MAX_STALE_DAYS):
        log.warning("%s fetch failed; reusing cached feed from %s: %s", source, cached["fetched_at"], last_error)
        return cached["body"]
    if last_error:
        raise last_error
    raise RuntimeError(f"{source} feed fetch failed")

def date(s: str) -> str:
    try:
        return parsedate_to_datetime(s).astimezone(UTC).isoformat()
    except Exception:
        return ""

def parse(raw: bytes, source: str) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    out: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        def v(name: str, element=item) -> str:
            n = element.find(name)
            return clean(n.text if n is not None else "")
        title = v("title")
        if title:
            out.append({"title": title, "url": v("link"), "published_at": date(v("pubDate")), "source": source})
    return out

def _has_phrase(title: str, phrase: str) -> bool:
    # Word boundaries prevent "ai" matching unrelated fragments such as "daily".
    pattern = r"(?<![a-z0-9])" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return re.search(pattern, title.lower()) is not None


def score(row: dict[str, str]) -> int:
    title = row["title"].lower()
    return sum(_has_phrase(title, k) for k in CORE_KEYWORDS) * 4 - sum(_has_phrase(title, k) for k in NOISE) * 10 + (2 if row["source"] == "google_trends_us" else 1)


def relevant(row: dict[str, str]) -> bool:
    title = row["title"].lower()
    return any(_has_phrase(title, k) for k in CORE_KEYWORDS) and not any(_has_phrase(title, k) for k in NOISE)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="data/search_demand_queue_us.json")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--cache-dir", default="data/trend_source_cache")
    a = ap.parse_args()
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for name, url in SOURCES.items():
        try:
            rows += parse(fetch(url, name, a.cache_dir), name)
        except Exception as e:
            errors.append(f"{name}: {e}")

    unique: dict[str, dict[str, str]] = {}
    for row in rows:
        row["title"] = re.sub(r"\s*[-|–—:].*$", "", row["title"]).strip()
        key = re.sub(r"[^a-z0-9]", "", row["title"].lower())
        if key and key not in unique and relevant(row) and score(row) >= 4:
            unique[key] = row

    # Prefer fresh headlines; undated feeds are retained but rank below dated recent items.
    cutoff = _utc_now() - timedelta(days=7)
    fresh = []
    for row in unique.values():
        published = row.get("published_at", "")
        if published:
            try:
                if datetime.fromisoformat(published) < cutoff:
                    continue
            except ValueError:
                pass
        fresh.append(row)
    ranked = sorted(fresh, key=lambda row: (score(row), row.get("published_at", "")), reverse=True)[:max(1, a.limit)]
    now = datetime.now(UTC).isoformat()
    topics = [
        {
            "series_number": f"TREND-{i}",
            "topic": row["title"],
            "source": row["source"],
            "source_url": row["url"],
            "published_at": row.get("published_at", ""),
            "trend_score": score(row),
            "fetched_at": now,
        }
        for i, row in enumerate(ranked, 1)
    ]
    payload = {
        "source": "Google Trends US + US AI/science/psychology RSS",
        "mined_at": now,
        "topics": topics,
        "source_errors": errors,
    }
    p = Path(a.output)
    if topics:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        print(json.dumps({"output": str(p), "topics": 0, "source_errors": errors, "note": "existing queue file left untouched"}))
        return 2
    print(json.dumps({"output": str(p), "topics": len(topics), "source_errors": errors}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
