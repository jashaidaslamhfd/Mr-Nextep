"""Fail-closed content gate for US science and body-fact publishing.

The LLM prompt is not a fact-checker. This module requires an auditable evidence
record, blocks high-risk medical language, and rejects exact/recent duplicates
before the uploader is allowed to publish. It deliberately has no network calls:
source retrieval and human review belong in the review workflow, not in a hidden
publish-time side effect.
"""

from __future__ import annotations

import os
import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from algorithm_policy import BAIT_PATTERNS, FEAR_BAIT_PATTERNS


_MEDICAL_TERMS = (
    "symptom", "disease", "disorder", "syndrome", "diagnos", "treatment",
    "medication", "medicine", "cure", "heal", "therapy", "infection",
    "cancer", "asthma", "seizure", "depression", "anxiety", "heart attack",
    "stroke", "blood pressure", "diabetes", "sleep apnea", "insomnia",
    "adhd", "autism", "pregnan", "suicide", "emergency", "doctor",
)
_HIGH_RISK_TERMS = (
    "cure", "diagnose", "you have", "stop taking", "replace your medication",
    "guaranteed", "emergency", "heart attack", "stroke", "suicide",
)


def _text(script: Dict[str, Any]) -> str:
    scenes = " ".join(
        str(s.get("caption", ""))
        for s in script.get("scenes", [])
        if isinstance(s, dict)
    )
    return " ".join(
        str(script.get(key, ""))
        for key in ("title", "hook", "voiceover", "description", "cta", "evidence_summary")
    ) + " " + scenes


def _has_pattern(text: str, patterns: Iterable[str]) -> List[str]:
    found: List[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(pattern)
    return found


def _is_valid_http_url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value))
        return parsed.scheme in {"https", "http"} and bool(parsed.netloc)
    except Exception:
        return False


def _risk_level(script: Dict[str, Any], text: str) -> str:
    declared = str(script.get("risk_level", "")).strip().lower()
    if declared in {"low", "medium", "high"}:
        level = declared
    else:
        level = "medium" if any(term in text.lower() for term in _MEDICAL_TERMS) else "low"
    if any(term in text.lower() for term in _HIGH_RISK_TERMS):
        level = "high"
    return level


_AUTHORITATIVE_DOMAINS = (
    ".gov", ".edu", "pubmed.ncbi.nlm.nih.gov", "who.int", "mayoclinic.org",
    "clevelandclinic.org", "hopkinsmedicine.org", "nih.gov",
)


def _source_issues(script: Dict[str, Any], risk: str = "low") -> List[str]:
    sources = script.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["No evidence source objects supplied"]
    issues: List[str] = []
    for idx, source in enumerate(sources[:3], 1):
        if not isinstance(source, dict):
            issues.append(f"Source {idx} is not an object")
            continue
        if len(str(source.get("title", "")).strip()) < 5:
            issues.append(f"Source {idx} has no usable title")
        source_url = str(source.get("url", "")).strip()
        if not _is_valid_http_url(source_url):
            issues.append(f"Source {idx} has no valid HTTP(S) URL")
        elif risk in {"medium", "high"}:
            host = (urlparse(source_url).hostname or "").lower()
            if not any(host == domain.lstrip(".") or host.endswith(domain) for domain in _AUTHORITATIVE_DOMAINS):
                issues.append(f"Source {idx} is not an approved authoritative domain for {risk}-risk content")
        accessed = str(source.get("accessed_at", "")).strip()
        if accessed:
            try:
                date.fromisoformat(accessed)
            except ValueError:
                issues.append(f"Source {idx} has invalid accessed_at date")
        else:
            issues.append(f"Source {idx} has no accessed_at date")
    return issues


def _recent_duplicate_issues(script: Dict[str, Any], history: List[Dict[str, Any]]) -> List[str]:
    title = " ".join(str(script.get("title", "")).lower().split())
    topic = " ".join(str(script.get("topic", "")).lower().split())
    hook = " ".join(str(script.get("hook", "")).lower().split())
    issues: List[str] = []
    for previous in history[-100:]:
        if not isinstance(previous, dict):
            continue
        old_title = " ".join(str(previous.get("title") or previous.get("youtube_title") or "").lower().split())
        old_topic = " ".join(str(previous.get("topic", "")).lower().split())
        old_hook = " ".join(str(previous.get("hook", "")).lower().split())
        if title and old_title and title == old_title:
            issues.append(f"Exact title duplicate: {old_title}")
        if topic and old_topic and topic == old_topic:
            issues.append(f"Recent topic duplicate: {old_topic}")
        if hook and old_hook and hook == old_hook:
            issues.append("Exact hook duplicate")
        for label, current, previous_value in (("title", title, old_title), ("hook", hook, old_hook)):
            if current and previous_value:
                current_tokens = set(current.split())
                previous_tokens = set(previous_value.split())
                overlap = len(current_tokens & previous_tokens) / max(1, min(len(current_tokens), len(previous_tokens)))
                if SequenceMatcher(None, current, previous_value).ratio() >= 0.88 or overlap >= 0.80:
                    issues.append(f"Near-duplicate {label} detected")
    return list(dict.fromkeys(issues))


def evaluate(script: Dict[str, Any], history: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """Return a publish decision; no external side effects are performed."""
    history = history or []
    text = _text(script)
    lowered = text.lower()
    issues: List[str] = []
    warnings: List[str] = []
    risk = _risk_level(script, text)

    if len(str(script.get("title", "")).strip()) < 5:
        issues.append("Title is missing or too short")
    if not str(script.get("evidence_summary", "")).strip():
        issues.append("Evidence summary is missing")
    issues.extend(_source_issues(script, risk=risk))
    verification = script.get("source_verification")
    if isinstance(verification, list):
        for item in verification:
            if isinstance(item, dict) and not item.get("ok"):
                issues.append(f"Evidence URL is unreachable: {item.get('url', 'unknown')}")

    bait = _has_pattern(lowered, BAIT_PATTERNS)
    fear = _has_pattern(lowered, FEAR_BAIT_PATTERNS)
    if bait:
        issues.append(
            f"Engagement-bait language detected ({len(bait)} pattern(s)): "
            + ", ".join(bait[:3])
        )
    if fear:
        issues.append(f"Fear/clickbait language detected ({len(fear)} pattern(s))")

    duplicates = _recent_duplicate_issues(script, history)
    issues.extend(duplicates)

    declared_disclaimer = bool(script.get("disclaimer_required"))
    if risk in {"medium", "high"} and not declared_disclaimer:
        issues.append(f"{risk} health-risk content must declare disclaimer_required=true")
    if risk == "high":
        warnings.append("High-risk health content requires human approval even after automated checks")

    human_approval = bool(os.environ.get("HUMAN_REVIEW_APPROVED_AT", "").strip())
    if not human_approval:
        warnings.append("No human review approval recorded")

    # Zero-touch mode is intentionally narrow: low-risk, non-fear content can
    # publish after automated evidence/originality checks; anything medical,
    # treatment-related, emergency-related, or fear-based still needs review.
    manual_review_configured = os.environ.get("REQUIRE_HUMAN_REVIEW", "1").lower() in {"1", "true", "yes"}
    auto_low_risk = os.environ.get("AUTO_PUBLISH_LOW_RISK", "false").lower() in {"1", "true", "yes"}
    require_human = (
        risk in {"medium", "high"}
        or bool(fear)
        or risk == "low" and not auto_low_risk
        or manual_review_configured and risk != "low" and not auto_low_risk
    )
    approved = not issues and (not require_human or human_approval)
    return {
        "approved": approved,
        "draft_only": not approved,
        "risk_level": risk,
        "issues": issues,
        "warnings": warnings,
        "duplicate_count": len(duplicates),
        "source_count": len(script.get("sources", [])) if isinstance(script.get("sources"), list) else 0,
        "requires_human_review": require_human,
    }
