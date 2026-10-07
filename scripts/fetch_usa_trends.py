#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

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

def fetch(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=20) as r:
        return r.read()

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

def score(row: dict[str, str]) -> int:
    title = row["title"].lower()
    return sum(k in title for k in CORE_KEYWORDS) * 4 - sum(k in title for k in NOISE) * 10 + (2 if row["source"] == "google_trends_us" else 1)

def relevant(row: dict[str, str]) -> bool:
    title = row["title"].lower()
    return any(k in title for k in CORE_KEYWORDS) and not any(k in title for k in NOISE)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="data/search_demand_queue_us.json")
    ap.add_argument("--limit", type=int, default=30)
    a = ap.parse_args()
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for name, url in SOURCES.items():
        try:
            rows += parse(fetch(url), name)
        except Exception as e:
            errors.append(f"{name}: {e}")

    unique: dict[str, dict[str, str]] = {}
    for row in rows:
        row["title"] = re.sub(r"\s*[-|–—:].*$", "", row["title"]).strip()
        key = re.sub(r"[^a-z0-9]", "", row["title"].lower())
        if key and key not in unique and relevant(row) and score(row) >= 4:
            unique[key] = row

    ranked = sorted(unique.values(), key=lambda row: (score(row), row.get("published_at", "")), reverse=True)[:a.limit]
    now = datetime.now(UTC).isoformat()
    topics = [
        {
            "series_number": f"TREND-{i}",
            "topic": row["title"],
            "source": row["source"],
            "source_url": row["url"],
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
