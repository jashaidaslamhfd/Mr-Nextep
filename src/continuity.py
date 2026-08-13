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


# The operator's consistency goal: 3 uploads/day at US peak slots.
PRODUCTION_CADENCE = 3


def _load_growth_health() -> Dict[str, Any]:
    """Measured per-platform health written by growth_engine.analyse()."""
    path = os.environ.get("GROWTH_STATE_PATH") or str(DATA / "growth_state.json")
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
            health = state.get("platform_health")
            return health if isinstance(health, dict) else {}
    except Exception as exc:  # noqa: BLE001 - never block a run on state I/O
        logger.warning("Could not read growth health for cadence cap: %s", exc)
    return {}


def retention_cadence_ceiling(platform_health: Dict[str, Any] = None) -> tuple:
    """Highest uploads/day that MEASURED retention currently justifies.

    Why this exists
    ---------------
    This function used to be a hardcoded `return 3`. That silently overrode the
    strategy engine's retention-aware decision, so a channel whose Facebook and
    Instagram completion sat at 19-24% against a ~70% gate still published
    3x/day. That is the exact behaviour that (a) teaches every feed the format
    loses viewers, and (b) YouTube's inauthentic-content policy targets. More
    uploads of a video people swipe away from does not buy reach; it buys
    suppression.

    Consistency still matters, so the aspiration stays 3/day - but it must be
    EARNED by clearing the gates, never assumed.

    Returns (ceiling, reason).
    """
    health = _load_growth_health() if platform_health is None else (platform_health or {})

    statuses = {
        name: str(info.get("status") or "").strip().lower()
        for name, info in health.items()
        if isinstance(info, dict)
    }
    real = {n: s for n, s in statuses.items() if s and s != "no_data"}

    if not real:
        return 2, (
            "No readable platform health yet - holding 2/day while data "
            "accumulates instead of assuming 3/day is safe."
        )

    critical = [n for n, s in real.items() if s == "critical"]
    if critical:
        return 1, (
            f"{', '.join(sorted(critical))} is critical (far under its completion "
            "gate). Shipping one strong video a day until the hook and cut clear "
            "the gate - extra uploads of a losing format only widen the damage."
        )

    below = [n for n, s in real.items() if s == "below_gate"]
    if below:
        return 2, (
            f"{', '.join(sorted(below))} is below its completion gate. Two uploads "
            "a day at the best-measured slots concentrates the quality budget "
            "where it converts."
        )

    healthy = [n for n, s in real.items() if s == "healthy"]
    if len(healthy) >= 2:
        return PRODUCTION_CADENCE, (
            f"{len(healthy)} platforms are clearing their gates - the format has "
            f"earned the full {PRODUCTION_CADENCE}/day production cadence."
        )

    return 2, (
        f"Only {len(healthy)} platform is clearing its gate. Holding 2/day until a "
        "second platform stabilises."
    )


def clamp_cadence_3(cadence: int, platform_health: Dict[str, Any] = None) -> int:
    """Aim for the 3/day production cadence, but never above measured retention.

    `DISABLE_CADENCE_3=true` keeps the old escape hatch: the caller's own
    number is passed through untouched.
    """
    suggested = max(1, int(cadence or 1))
    if os.environ.get("DISABLE_CADENCE_3", "false").strip().lower() == "true":
        return suggested

    ceiling, reason = retention_cadence_ceiling(platform_health)
    target = min(max(suggested, PRODUCTION_CADENCE), ceiling)
    if target < PRODUCTION_CADENCE:
        logger.info("Cadence capped at %s/day: %s", target, reason)
    return max(1, min(PRODUCTION_CADENCE, target))
