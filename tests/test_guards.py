from __future__ import annotations

from datetime import datetime, timezone

from src.content import fallback
from src.guards import (
    check_publish_gap,
    enforce,
    fingerprint,
    is_duplicate,
    retention_proxy,
)


def test_duplicate_is_rejected():
    script = fallback("Why does déjà vu feel real?")
    assert is_duplicate(script, [{"fingerprint": fingerprint(script)}])


def test_near_duplicate_is_rejected():
    script = fallback("Why does déjà vu feel real?")
    previous = dict(script)
    previous["title"] = "Why does déjà vu feel real today?"
    previous["body"] = " ".join(s["caption"] for s in previous["scenes"])
    assert is_duplicate(script, [{"title": previous["title"], "body": previous["body"], "text": f"{previous['title']} {previous['body']}"}])


def test_weak_script_fails_retention_gate():
    weak = {"title": "Weak", "scenes": [{"caption": "x", "narration": "x"}]}
    assert retention_proxy(weak, 8.0) < 0.70
    try:
        enforce(weak, 8.0, [])
    except RuntimeError as exc:
        # The message deliberately says "Structural conformance", not "Retention": this
        # check reads scene count, duration and caption lengths, none of which is evidence
        # about retention. Real retention now comes from analytics.evaluate_retention.
        assert "Structural conformance" in str(exc)
    else:
        raise AssertionError("weak script passed retention gate")


def test_retention_proxy_meets_gate_for_short_format():
    script = fallback("Why does déjà vu feel real?")
    assert retention_proxy(script, 20.0) >= 0.70
    assert enforce(script, 20.0, [])['retention_proxy'] >= 0.70


def test_publish_gap_allows_when_empty_history():
    can_publish, elapsed = check_publish_gap([])
    assert can_publish is True
    assert elapsed is None


def test_publish_gap_blocks_when_recent_upload():
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    recent_history = [
        {"status": "uploaded", "created_at": "2026-09-15T10:30:00+00:00", "title": "Recent Video"}
    ]
    can_publish, elapsed = check_publish_gap(recent_history, min_gap_hours=4.0, now=now)
    assert can_publish is False
    assert elapsed is not None
    assert 1.4 <= elapsed <= 1.6


def test_publish_gap_allows_when_elapsed_exceeds_threshold():
    now = datetime(2026, 9, 15, 18, 0, 0, tzinfo=timezone.utc)
    past_history = [
        {"status": "uploaded", "created_at": "2026-09-15T12:00:00+00:00", "title": "Past Video"}
    ]
    can_publish, elapsed = check_publish_gap(past_history, min_gap_hours=4.0, now=now)
    assert can_publish is True
    assert elapsed is not None
    assert elapsed == 6.0
