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
    current_title = str(script.get("title", ""))
    current_body = " ".join(str(s.get("caption", "")) for s in script.get("scenes", []))
    for item in history if isinstance(history, list) else []:
        if item.get("fingerprint") == current: return True
        previous_title = str(item.get("title", ""))
        previous_body = str(item.get("body", ""))
        if not previous_title and item.get("text"):
            previous_title, _, previous_body = str(item["text"]).partition(" ")
        if not item.get("title") and item.get("text") and token_similarity(f"{current_title} {current_body}", str(item["text"])) >= 0.95:
            return True
        if previous_title and previous_body:
            if token_similarity(current_title, previous_title) >= 0.75 and token_similarity(current_body, previous_body) >= 0.55:
                return True
    return False

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
    if is_duplicate(script, history): raise RuntimeError("Duplicate or near-duplicate content rejected")
    score = retention_proxy(script, duration)
    if score < RETENTION_TARGET: raise RuntimeError(f"Retention proxy {score:.0%} is below target {RETENTION_TARGET:.0%}")
    title = str(script.get("title", ""))
    body = " ".join(str(s.get("caption", "")) for s in script.get("scenes", []))
    return {"retention_proxy": score, "fingerprint": fingerprint(script), "title": title, "body": body, "text": f"{title} {body}"}
