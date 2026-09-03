from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from typing import Any

RETENTION_TARGET = 0.70

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()

def fingerprint(script: dict[str, Any]) -> str:
    text = " ".join([script.get("title", "")] + [str(s.get("caption", "")) for s in script.get("scenes", [])])
    return hashlib.sha256(normalize(text).encode()).hexdigest()

def token_similarity(left: str, right: str) -> float:
    a, b = set(normalize(left).split()), set(normalize(right).split())
    return len(a & b) / max(1, len(a | b))

def is_duplicate(script: dict[str, Any], history: list[dict[str, Any]]) -> bool:
    current = fingerprint(script)
    current_text = " ".join([script.get("title", "")] + [str(s.get("caption", "")) for s in script.get("scenes", [])])
    for item in history:
        if item.get("fingerprint") == current: return True
        previous = item.get("text", "")
        if previous and token_similarity(current_text, previous) >= 0.78: return True
    return False

def retention_proxy(script: dict[str, Any], duration: float) -> float:
    scenes = len(script.get("scenes", []))
    first = str((script.get("scenes") or [{}])[0].get("caption", ""))
    score = 0.70
    if scenes >= 8: score += 0.04
    if 15 <= duration <= 24: score += 0.03
    if 4 <= len(first.split()) <= 12: score += 0.03
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
    if is_duplicate(script, history): raise RuntimeError("Duplicate or near-duplicate content rejected")
    score = retention_proxy(script, duration)
    if score < RETENTION_TARGET: raise RuntimeError(f"Retention proxy {score:.0%} is below target {RETENTION_TARGET:.0%}")
    return {"retention_proxy": score, "fingerprint": fingerprint(script), "text": " ".join([script.get("title", "")] + [str(s.get("caption", "")) for s in script.get("scenes", [])])}
