"""Continuity & slot-consistency layer.

The guards are strict by design: they block a video that isn't good enough to
publish. But a blocked video must not become a MISSED slot — the channel needs
3 uploads a day at US peak times to stay consistent (consistency is one of the
strongest 2026 growth signals). This module reconciles those two goals:

  1. Guard failure is treated as RETRYABLE, not fatal: the pipeline regenerates
     with a NEW topic and re-runs the guards. A bad topic never kills the day.
  2. Every US peak slot is tracked so a slot is only "missed" after a bounded
     number of genuinely distinct generation attempts.
  3. Cadence is clamped to 3/day for the production schedule (the strategy
     engine may suggest lower while retention is low, but the operator's
     "3 US-peak videos a day" requirement wins unless overridden).

The pipeline calls `should_retry_on_guard_failure()` to decide, and
`register_slot_attempt()` / `slot_consistency_status()` to track slots.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Guard failures are retryable with a new topic up to this many attempts.
MAX_GUARD_RETRIES = int(os.environ.get("MAX_GUARD_RETRIES", "3"))

# US peak slot windows (America/New_York hour) — matches main.yml cron.
US_PEAK_HOURS = [12, 18, 20]


def _state_path() -> Path:
    return DATA / "slot_consistency.json"


def _load_state() -> Dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {"slots": []}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {"slots": []}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        json.dump(state, open(_state_path(), "w", encoding="utf-8"),
                  indent=2, default=str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist slot consistency state: %s", exc)


def _ny_now():
    try:
        import pytz
        return datetime.now(pytz.timezone("America/New_York"))
    except Exception:
        return datetime.now(timezone.utc)


def is_us_peak_slot(ny_hour: int) -> bool:
    """Is this New-York hour one of the 3 production peak slots?"""
    return ny_hour in US_PEAK_HOURS


def should_retry_on_guard_failure(attempt: int, max_attempts: int = None) -> bool:
    """Guard failure -> retry with a new topic, up to MAX_GUARD_RETRIES.

    This is the key continuity rule: a blocked video never has to become a
    missed slot — we simply try a different topic (bounded) before giving up.
    """
    cap = max_attempts if max_attempts is not None else MAX_GUARD_RETRIES
    return attempt < cap


def register_slot_attempt(slot_label: str, outcome: str, topic: str = "") -> None:
    """Record that a slot attempt happened (outcome: 'published', 'guard_fail',
    'empty', 'error'). Used to verify consistency and to surface gaps."""
    state = _load_state()
    now = datetime.now(timezone.utc).isoformat()
    state["slots"].append({
        "slot": slot_label,
        "outcome": outcome,
        "topic": topic[:80],
        "at": now,
    })
    # keep only recent history (last 30 entries)
    state["slots"] = state["slots"][-30:]
    _save_state(state)


def slot_consistency_status() -> Dict[str, Any]:
    """Report how consistent the last 7 days of slots were, by US peak hour."""
    state = _load_state()
    slots = state.get("slots", [])
    # count per slot label over the last entries
    per_slot: Dict[str, Dict[str, int]] = {}
    for s in slots:
        label = s.get("slot", "?")
        per_slot.setdefault(label, {"published": 0, "missed": 0, "total": 0})
        per_slot[label]["total"] += 1
        if s.get("outcome") == "published":
            per_slot[label]["published"] += 1
        elif s.get("outcome") in ("guard_fail", "empty", "error"):
            per_slot[label]["missed"] += 1

    total = len(slots)
    published = sum(1 for s in slots if s.get("outcome") == "published")
    consistency = round(100 * published / total, 1) if total else 100.0
    return {
        "total_attempts": total,
        "published": published,
        "missed": total - published,
        "consistency_pct": consistency,
        "per_slot": per_slot,
        "target": "3/day at US peak (12:30/18:30/20:00 NY)",
    }


def clamp_cadence_3(cadence: int) -> int:
    """Production requirement: 3 videos a day at US peak slots. Clamps any
    suggested cadence up to 3 unless explicitly disabled via env."""
    if os.environ.get("DISABLE_CADENCE_3", "false").strip().lower() == "true":
        return max(1, cadence)
    return 3
