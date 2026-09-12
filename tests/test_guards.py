from __future__ import annotations

from src.content import fallback
from src.guards import enforce, fingerprint, is_duplicate, retention_proxy


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
        assert "Retention proxy" in str(exc)
    else:
        raise AssertionError("weak script passed retention gate")


def test_retention_proxy_meets_gate_for_short_format():
    script = fallback("Why does déjà vu feel real?")
    assert retention_proxy(script, 20.0) >= 0.70
    assert enforce(script, 20.0, [])['retention_proxy'] >= 0.70
