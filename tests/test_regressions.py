from __future__ import annotations

import json
from pathlib import Path

from src import content, main
from src.config import Settings
from src.content import fallback, generate_script
from src.meta import publish


class _DummySettings:
    max_attempts = 2
    topic = ""
    data_dir = Path("/tmp/mr-nextep-regression-data")
    output_dir = Path("/tmp/mr-nextep-regression-output")
    dry_run = True
    duplicate_check_last = 10

    def check_config(self):
        return []

    def ensure_dirs(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


def test_clip_exhaustion_preserves_actionable_error(monkeypatch):
    monkeypatch.setattr(main, "SETTINGS", _DummySettings())
    monkeypatch.setattr(main, "load_history", lambda path: [])
    monkeypatch.setattr(main, "choose_topic", lambda settings: "test topic")
    monkeypatch.setattr(main, "generate_script", lambda topic, settings: {"title": "t", "scenes": []})
    monkeypatch.setattr(main, "render", lambda script, settings: (_ for _ in ()).throw(RuntimeError("No unique moving video clip found")))
    monkeypatch.setattr(main, "_git_persist", lambda paths, message: None)

    try:
        main.run()
    except RuntimeError as exc:
        assert "no unique moving video clip" in str(exc).lower()
        assert not isinstance(exc, UnboundLocalError)
    else:
        raise AssertionError("clip exhaustion unexpectedly passed")


def test_invalid_publish_timezone_is_rejected():
    settings = Settings(dry_run=True, timezone="Not/AZone")
    assert any("PUBLISH_TIMEZONE is invalid" in error for error in settings.check_config())


def test_real_iana_timezone_is_accepted():
    """The old validator used a hardcoded 5-item allowlist, so every other valid IANA
    zone was reported invalid. Validation now goes through zoneinfo."""
    settings = Settings(dry_run=True, timezone="Asia/Karachi")
    assert settings.check_config() == []


def test_llm_hook_above_seven_words_falls_back(monkeypatch):
    payload = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "title": "Test",
                    "description": "Test",
                    "tags": ["test"],
                    "scenes": [
                        {"caption": "This hook contains exactly eight separate words here", "narration": "Narration"}
                    ] * 8,
                })
            }
        }]
    }

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(content, "urlopen", lambda request, timeout: _Response())
    result = generate_script("Why does memory feel familiar?", Settings(dry_run=True))
    assert result == fallback("Why does memory feel familiar?")


def test_instagram_without_public_url_is_safely_skipped(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_USER_ID", "instagram-id")
    monkeypatch.setenv("FACEBOOK_ACCESS_TOKEN", "facebook-token")
    monkeypatch.delenv("PUBLIC_VIDEO_URL", raising=False)
    monkeypatch.delenv("FACEBOOK_PAGE_ID", raising=False)

    result = publish(Path("unused.mp4"), fallback("Why does memory feel familiar?"), {})
    assert result["instagram"]["status"] == "skipped"
    assert "PUBLIC_VIDEO_URL" in result["instagram"]["reason"]


def test_metadata_collision_is_detected_before_render():
    """Duplicate metadata is caught before the expensive encode, and resolved by
    regenerating rather than by appending a cosmetic suffix."""
    script = {"title": "Why do dreams feel real?", "description": "d"}
    history = [{"title": "Why do dreams feel real?", "description": "d"}]
    assert main.metadata_collides(script, history, 10) is True
    assert main.metadata_collides({"title": "Something else entirely"}, history, 10) is False
    assert main.metadata_collides(script, [], 10) is False


def test_unique_text_suffix_no_longer_garnishes_titles():
    """Titles must not gain emoji or random numbers; that was viewer-visible noise."""
    from src.utils import unique_text_suffix

    assert unique_text_suffix("Why do dreams feel real?") == ""
    assert unique_text_suffix(None) == ""


def test_403_is_not_retried_as_transient():
    """403 on the YouTube Data API is quota/permissions — permanent, not transient."""
    from googleapiclient.errors import HttpError

    from src.utils import is_transient_http_error

    class _Resp:
        def __init__(self, status):
            self.status = status
            self.reason = "Forbidden"

    forbidden = HttpError(_Resp(403), b'{"error":{"message":"quotaExceeded"}}')
    server_error = HttpError(_Resp(503), b"unavailable")
    rate_limited = HttpError(_Resp(429), b"slow down")

    assert is_transient_http_error(forbidden) is False
    assert is_transient_http_error(server_error) is True
    assert is_transient_http_error(rate_limited) is True
