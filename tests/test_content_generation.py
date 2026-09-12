"""Generation-path regressions.

The old generate_script returned the built-in template whenever GROQ_API_KEY was missing
or the LLM call failed, and the pipeline published it. The template emitted near-identical
scenes for every topic, so a run without a key produced a duplicate upload rather than a
failure. A failed run is recoverable; a duplicate on the channel is not.
"""
from __future__ import annotations

import json

import pytest

from src import content
from src.content import ContentGenerationError, generate_script, salient_words
from src.utils import SHORTS_TITLE_MAX_CHARS


class _Settings:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run


def _groq_response(payload: dict):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode()

    return lambda request, timeout=None: _Response()


def _valid_payload(title: str = "Why does silence feel loud?") -> dict:
    return {
        "title": title,
        "description": "A short explainer.",
        "tags": ["dark science"],
        "scenes": [
            {"caption": "Your brain hides this signal", "narration": "Narration one."},
            *[{"caption": f"Scene {i} caption here", "narration": f"Narration {i}."} for i in range(2, 9)],
        ],
    }


def test_missing_api_key_fails_the_run_instead_of_publishing_the_template(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ContentGenerationError) as exc:
        generate_script("Why does silence feel loud?", _Settings(dry_run=False))
    assert "GROQ_API_KEY" in str(exc.value)


def test_missing_api_key_still_allows_a_dry_run(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    script = generate_script("Why does silence feel loud?", _Settings(dry_run=True))
    assert len(script["scenes"]) == 8


def test_repeated_llm_failure_fails_the_run(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(content, "urlopen", _groq_response({"title": "x", "scenes": []}))
    with pytest.raises(ContentGenerationError) as exc:
        generate_script("Why does silence feel loud?", _Settings(dry_run=False))
    assert "No publishable script" in str(exc.value)


def test_over_length_llm_title_is_rejected(monkeypatch):
    """The model's title goes through the same validator as everything else."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    long_title = "The dark neuroscience of why your brain invents shadows at night"
    assert len(long_title) > SHORTS_TITLE_MAX_CHARS
    monkeypatch.setattr(content, "urlopen", _groq_response(_valid_payload(long_title)))
    with pytest.raises(ContentGenerationError):
        generate_script("Why does silence feel loud?", _Settings(dry_run=False))


def test_valid_llm_output_is_returned(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(content, "urlopen", _groq_response(_valid_payload()))
    script = generate_script("Why does silence feel loud?", _Settings(dry_run=False))
    assert script["title"] == "Why does silence feel loud?"
    assert len(script["scenes"]) == 8


def test_retry_feeds_the_rejection_reason_back_to_the_model(monkeypatch):
    """A retry that repeats the same prompt just re-rolls the dice; the reason is carried."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    seen: list[str] = []
    attempts = iter([_valid_payload("Brain glitch"), _valid_payload()])

    def _fake_request(topic, key, feedback=None):
        seen.append(feedback or "")
        return next(attempts)

    monkeypatch.setattr(content, "_request_script", _fake_request)
    script = generate_script("Why does silence feel loud?", _Settings(dry_run=False))
    assert script["title"] == "Why does silence feel loud?"
    assert seen[0] == ""
    assert "words" in seen[1]


def test_salient_words_drops_stopwords():
    assert "silence" in salient_words("Why does silence feel physically loud?")
    assert "does" not in salient_words("Why does silence feel physically loud?")


def test_trend_queue_prefers_raw_headline_over_spliced_question(tmp_path):
    """Old queue files still carry the mechanical question_phrase; the headline wins."""
    class _S:
        topic = ""
        data_dir = tmp_path

    (tmp_path / "search_demand_queue_us.json").write_text(json.dumps({
        "topics": [{
            "topic": "Sleep clears brain waste overnight",
            "question_phrase": "Why does sleep clears brain waste overnight?",
        }]
    }), encoding="utf-8")

    assert content.choose_topic(_S()) == "Sleep clears brain waste overnight"
