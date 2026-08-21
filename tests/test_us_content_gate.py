import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from us_content_gate import evaluate


def base_script(**overrides):
    script = {
        "title": "Why Your Eyes Blink",
        "hook": "Why do your eyes blink without thinking?",
        "voiceover": "Your eyelids blink to protect the eye and keep its surface moist.",
        "description": "A short explanation of the blink reflex.",
        "evidence_summary": "Blinking spreads a tear film across the eye.",
        "sources": [{
            "title": "National Eye Institute",
            "url": "https://www.nei.nih.gov/learn-about-eye-health/healthy-vision/keep-your-eyes-healthy",
            "accessed_at": "2026-08-21",
        }],
        "risk_level": "low",
        "disclaimer_required": False,
        "scenes": [{"caption": "Why do your eyes blink without thinking?", "visual": "Close-up blinking eye"}],
    }
    script.update(overrides)
    return script


def test_missing_sources_blocks_publish():
    result = evaluate(base_script(sources=[]), history=[])
    assert result["approved"] is False
    assert any("source" in issue.lower() for issue in result["issues"])


def test_bait_language_blocks_publish():
    result = evaluate(base_script(cta="Like this and share it"), history=[])
    assert result["approved"] is False
    assert any("bait" in issue.lower() for issue in result["issues"])


def test_recent_duplicate_topic_blocks_publish():
    result = evaluate(
        base_script(topic="eye blink"),
        history=[{"topic": "eye blink", "title": "Old Eye Blink"}],
    )
    assert result["approved"] is False
    assert result["duplicate_count"] == 1


def test_near_duplicate_title_blocks_publish():
    result = evaluate(
        base_script(title="Why Your Eyes Blink Often"),
        history=[{"title": "Why Your Eyes Blink"}],
    )
    assert result["approved"] is False
    assert any("near-duplicate" in issue.lower() for issue in result["issues"])


def test_medium_risk_requires_authoritative_source():
    result = evaluate(
        base_script(
            risk_level="medium",
            disclaimer_required=True,
            sources=[{
                "title": "A random blog",
                "url": "https://example.com/health",
                "accessed_at": "2026-08-21",
            }],
        ),
        history=[],
    )
    assert result["approved"] is False
    assert any("authoritative" in issue.lower() for issue in result["issues"])


def test_low_risk_content_auto_approves_without_human_record():
    old = os.environ.pop("HUMAN_REVIEW_APPROVED_AT", None)
    old_auto = os.environ.get("AUTO_PUBLISH_LOW_RISK")
    os.environ["AUTO_PUBLISH_LOW_RISK"] = "true"
    try:
        result = evaluate(base_script(), history=[])
        assert result["approved"] is True
        assert result["requires_human_review"] is False
        assert result["issues"] == []
    finally:
        if old is not None:
            os.environ["HUMAN_REVIEW_APPROVED_AT"] = old
        if old_auto is None:
            os.environ.pop("AUTO_PUBLISH_LOW_RISK", None)
        else:
            os.environ["AUTO_PUBLISH_LOW_RISK"] = old_auto


def test_medium_risk_requires_human_record():
    old = os.environ.pop("HUMAN_REVIEW_APPROVED_AT", None)
    try:
        result = evaluate(
            base_script(risk_level="medium", disclaimer_required=True), history=[]
        )
        assert result["approved"] is False
        assert result["requires_human_review"] is True
    finally:
        if old is not None:
            os.environ["HUMAN_REVIEW_APPROVED_AT"] = old
