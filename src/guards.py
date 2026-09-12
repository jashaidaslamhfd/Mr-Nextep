from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

RETENTION_TARGET = 0.70

# Duplicate thresholds. These are OR'd, not AND'd — see duplicate_reason for why.
BODY_SIMILARITY_LIMIT = 0.85
TITLE_SIMILARITY_LIMIT = 0.90
COMBINED_TITLE_LIMIT = 0.75
COMBINED_BODY_LIMIT = 0.55
TEXT_SIMILARITY_LIMIT = 0.95

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()

def fingerprint(script: dict[str, Any]) -> str:
    text = " ".join([script.get("title", "")] + [str(s.get("caption", "")) for s in script.get("scenes", [])])
    return hashlib.sha256(normalize(text).encode()).hexdigest()

def token_similarity(left: str, right: str) -> float:
    a, b = set(normalize(left).split()), set(normalize(right).split())
    return len(a & b) / max(1, len(a | b))

def duplicate_reason(script: dict[str, Any], history: list[dict[str, Any]]) -> str | None:
    """Explain why this script duplicates something already published, or return None.

    The checks are OR'd. The previous version required title similarity >= 0.75 AND body
    similarity >= 0.55 together, which could not catch what this pipeline actually
    produces: the templated fallback emits an identical body for every topic while the
    title comes from a different news headline each time. Body similarity was 1.0 and
    title similarity was below 0.75, so the AND kept letting it through and the channel
    published the same script repeatedly under different titles.

    Body similarity alone is therefore sufficient, and title similarity alone is too —
    the latter also lets title-only history entries (backfilled from the channel's
    published uploads, where no script body exists) block a repeat topic.
    """
    current = fingerprint(script)
    current_title = str(script.get("title", ""))
    current_body = " ".join(str(s.get("caption", "")) for s in script.get("scenes", []))
    for index, item in enumerate(history if isinstance(history, list) else []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("title") or item.get("text") or f"history entry {index}")[:60]

        if item.get("fingerprint") == current:
            return f"identical fingerprint to {label!r}"

        previous_title = str(item.get("title", ""))
        previous_body = str(item.get("body", ""))
        previous_text = str(item.get("text", ""))
        if not previous_title and previous_text:
            previous_title, _, previous_body = previous_text.partition(" ")

        if not item.get("title") and previous_text:
            whole = token_similarity(f"{current_title} {current_body}", previous_text)
            if whole >= TEXT_SIMILARITY_LIMIT:
                return f"{whole:.0%} of the combined text matches {label!r}"

        if previous_body:
            body_similarity = token_similarity(current_body, previous_body)
            if body_similarity >= BODY_SIMILARITY_LIMIT:
                return (
                    f"script body is {body_similarity:.0%} identical to {label!r} "
                    "(a different title does not make it different content)"
                )

        if previous_title:
            title_similarity = token_similarity(current_title, previous_title)
            if title_similarity >= TITLE_SIMILARITY_LIMIT:
                return f"title is {title_similarity:.0%} identical to {label!r}"

            if previous_body and title_similarity >= COMBINED_TITLE_LIMIT:
                body_similarity = token_similarity(current_body, previous_body)
                if body_similarity >= COMBINED_BODY_LIMIT:
                    return (
                        f"title {title_similarity:.0%} and body {body_similarity:.0%} "
                        f"both overlap {label!r}"
                    )
    return None


def is_duplicate(script: dict[str, Any], history: list[dict[str, Any]]) -> bool:
    return duplicate_reason(script, history) is not None

def retention_proxy(script: dict[str, Any], duration: float) -> float:
    scenes = len(script.get("scenes", []))
    first = str((script.get("scenes") or [{}])[0].get("caption", ""))
    score = 0.35
    if scenes >= 8: score += 0.20
    elif scenes >= 6: score += 0.10
    if 15 <= duration <= 24: score += 0.20
    elif 12 <= duration <= 28: score += 0.10
    if 4 <= len(first.split()) <= 12: score += 0.15
    elif first: score += 0.05
    if all(1 <= len(str(s.get("caption", "")).split()) <= 8 for s in script.get("scenes", [])): score += 0.10
    return min(0.90, score)

def load_history(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError, TypeError, json.JSONDecodeError): return []

def save_history(path: Path, history: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history[-500:], indent=2, ensure_ascii=False), encoding="utf-8")

def enforce(script: dict[str, Any], duration: float, history: list[dict[str, Any]]) -> dict[str, Any]:
    reason = duplicate_reason(script, history)
    if reason: raise RuntimeError(f"Duplicate or near-duplicate content rejected: {reason}")
    score = retention_proxy(script, duration)
    if score < RETENTION_TARGET: raise RuntimeError(f"Retention proxy {score:.0%} is below target {RETENTION_TARGET:.0%}")
    title = str(script.get("title", ""))
    body = " ".join(str(s.get("caption", "")) for s in script.get("scenes", []))
    return {"retention_proxy": score, "fingerprint": fingerprint(script), "title": title, "body": body, "text": f"{title} {body}"}
