from __future__ import annotations

import json
from pathlib import Path

import content
import main
from config import Settings
from content import fallback, generate_script
from meta import publish


class _DummySettings:
    max_attempts = 2
    topic = ""
    data_dir = Path("/tmp/mr-nextep-regression-data")
    output_dir = Path("/tmp/mr-nextep-regression-output")
    dry_run = True

    def validate(self):
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
    assert any("PUBLISH_TIMEZONE is invalid" in error for error in settings.validate())


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
