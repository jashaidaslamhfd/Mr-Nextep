import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import source_research


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_pubmed_discovery_returns_real_source_shape(monkeypatch):
    responses = iter([
        FakeResponse({"esearchresult": {"idlist": ["12345"]}}),
        FakeResponse({"result": {"12345": {"title": "Blinking and ocular surface health"}}}),
    ])
    monkeypatch.setattr(source_research.requests, "get", lambda *args, **kwargs: next(responses))
    sources = source_research.discover_pubmed_sources("eye blinking")
    assert len(sources) == 1
    assert sources[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345/"
    assert sources[0]["provider"] == "pubmed"
    assert sources[0]["accessed_at"]


def test_pubmed_discovery_fails_closed_on_network_error(monkeypatch):
    def fail(*args, **kwargs):
        raise source_research.requests.RequestException("offline")

    monkeypatch.setattr(source_research.requests, "get", fail)
    assert source_research.discover_pubmed_sources("eye blinking") == []


def test_source_verification_records_reachable_url(monkeypatch):
    class HeadResponse:
        status_code = 200
        url = "https://pubmed.ncbi.nlm.nih.gov/12345/"

    monkeypatch.setattr(source_research.requests, "head", lambda *args, **kwargs: HeadResponse())
    result = source_research.verify_source_urls([{"url": "https://pubmed.ncbi.nlm.nih.gov/12345/"}])
    assert result[0]["ok"] is True
    assert result[0]["status"] == 200


def test_source_verification_marks_unreachable_url(monkeypatch):
    def fail(*args, **kwargs):
        raise source_research.requests.RequestException("offline")

    monkeypatch.setattr(source_research.requests, "head", fail)
    result = source_research.verify_source_urls([{"url": "https://example.com/nope"}])
    assert result[0]["ok"] is False
