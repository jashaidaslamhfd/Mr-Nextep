"""Duplicate-guard regressions.

The guard previously required title similarity >= 0.75 AND body similarity >= 0.55
together. The pipeline's own failure mode was the exact opposite shape: an identical
script body under a different news headline each time. Body similarity was 1.0, title
similarity was below 0.75, and the AND let it through — which is how the channel
published the same script repeatedly.
"""
from __future__ import annotations

from src.content import fallback
from src.guards import (
    BODY_SIMILARITY_LIMIT,
    duplicate_reason,
    enforce,
    fingerprint,
    is_duplicate,
)

SHARED_BODY = (
    "Your sensory neurons fire before awareness. A hidden neural pathway takes over. "
    "Neuroscientists call this spontaneous cognitive drift. Your brain manufactures a "
    "false memory. The eerie feeling is completely biological."
)


def _script_with_body(title: str, body: str) -> dict:
    return {
        "title": title,
        "scenes": [{"caption": part.strip(), "narration": part.strip()} for part in body.split(". ") if part.strip()],
    }


def test_same_body_different_title_is_now_rejected():
    """The regression that mattered: identical script, unrelated headline as the title."""
    candidate = _script_with_body("Why does sleep clear brain waste?", SHARED_BODY)
    history = [{
        "title": "Apple acquires a brain imaging firm",
        "body": SHARED_BODY,
        "text": f"Apple acquires a brain imaging firm {SHARED_BODY}",
    }]
    reason = duplicate_reason(candidate, history)
    assert reason is not None
    assert "body" in reason
    assert is_duplicate(candidate, history) is True


def test_title_only_history_entry_still_blocks_a_repeat():
    """Backfilled uploads carry a title and no body; that has to be enough."""
    candidate = _script_with_body("Why does silence feel physically loud?", "Fresh unrelated script text here.")
    history = [{"title": "Why does silence feel physically loud?", "body": "", "text": "Why does silence feel physically loud?"}]
    reason = duplicate_reason(candidate, history)
    assert reason is not None
    assert "title" in reason


def test_genuinely_different_content_passes():
    candidate = _script_with_body(
        "Why does silence feel loud?",
        "Silence raises your auditory gain. Your ears hunt for missing signal. The hiss is your own nervous system.",
    )
    history = [{
        "title": "Why do dim mirrors melt your face?",
        "body": "Low light starves your face recognition. Your visual cortex fills the gap. The melt is invented detail.",
        "text": "unrelated",
    }]
    assert duplicate_reason(candidate, history) is None
    assert is_duplicate(candidate, history) is False


def test_identical_fingerprint_is_rejected():
    script = fallback("Why does deja vu feel real?")
    assert duplicate_reason(script, [{"fingerprint": fingerprint(script)}]) is not None


def test_enforce_surfaces_the_reason():
    candidate = _script_with_body("Why does sleep clear brain waste?", SHARED_BODY)
    history = [{"title": "An unrelated headline entirely", "body": SHARED_BODY, "text": "x"}]
    try:
        enforce(candidate, 20.0, history)
    except RuntimeError as exc:
        assert "Duplicate" in str(exc)
        assert "body" in str(exc)
    else:
        raise AssertionError("duplicate body passed the guard")


def test_body_limit_is_the_documented_threshold():
    assert BODY_SIMILARITY_LIMIT == 0.85


def test_template_scripts_vary_by_topic():
    """The template used to emit identical scenes 2-8 for every topic."""
    first = fallback("Why does silence feel physically loud?")
    second = fallback("Why do nightmares wake you up?")
    first_body = " ".join(s["caption"] for s in first["scenes"])
    second_body = " ".join(s["caption"] for s in second["scenes"])
    assert first_body != second_body
    assert not is_duplicate(second, [{"title": first["title"], "body": first_body, "text": "x"}])
