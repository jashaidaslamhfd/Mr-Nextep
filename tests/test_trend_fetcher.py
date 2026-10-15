from __future__ import annotations

import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from scripts import fetch_usa_trends as trends


class Response:
    def __init__(self, body=b"<rss/>", headers=None, status=200):
        self.body = body
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def test_fresh_cache_avoids_network_requests(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    path = cache_dir / "google_trends_us.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "body_b64": "PHJzcz48L3Jzcz4=",
        "fetched_at": trends._utc_now().isoformat(),
        "etag": "tag-1",
        "last_modified": "",
    }), encoding="utf-8")
    monkeypatch.setattr(trends, "urlopen", lambda *args, **kwargs: pytest.fail("network should not be called"))

    assert trends.fetch("https://example.test/feed", "google_trends_us", cache_dir) == b"<rss></rss>"


def test_rate_limit_retries_then_succeeds(tmp_path, monkeypatch):
    calls = {"count": 0}
    def fake_urlopen(request, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
        return Response(b"<rss>fresh</rss>", {"ETag": "v2"})

    monkeypatch.setattr(trends, "urlopen", fake_urlopen)
    monkeypatch.setattr(trends.time, "sleep", lambda _seconds: None)

    assert trends.fetch("https://example.test/feed", "test_feed", tmp_path) == b"<rss>fresh</rss>"
    assert calls["count"] == 2
    saved = json.loads((tmp_path / "test_feed.json").read_text(encoding="utf-8"))
    assert saved["etag"] == "v2"


def test_rate_limit_uses_stale_cache_without_failing(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache = cache_dir / "feed.json"
    cache.write_text(json.dumps({
        "body_b64": "PGZlZWQ+Y2FjaGVkPC9mZWVkPg==",
        "fetched_at": (trends._utc_now().replace(year=trends._utc_now().year - 1)).isoformat(),
        "etag": "",
        "last_modified": "",
    }), encoding="utf-8")

    def rate_limited(request, timeout=None):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)

    monkeypatch.setattr(trends, "urlopen", rate_limited)
    monkeypatch.setattr(trends.time, "sleep", lambda _seconds: None)

    # A cache older than the configured stale limit is not silently used.
    with pytest.raises(HTTPError):
        trends.fetch("https://example.test/feed", "feed", cache_dir)
