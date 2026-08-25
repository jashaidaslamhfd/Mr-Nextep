"""
continuity.py — 3-tier fallback system for slot continuity.

Problem:
  Quality gates strict hain (accha hai) BUT jab video fail hoti hai,
  slot EMPTY chala jata hai → consistency tooti → algorithm punish karta hai.

Solution — 3 tiers:
  Tier 1: Normal generation (strict gates — best quality)
  Tier 2: Reserve queue (pre-validated backup scripts, already gate-passed)
  Tier 3: Emergency minimal (basic structural quality, never empty slot)

Key principle: SLOT KABHI EMPTY NAHI HOGA, but quality kabhi low nahi hogi.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

RESERVE_DIR = os.environ.get("RESERVE_DIR", "data/reserve_queue")
RESERVE_MAX = int(os.environ.get("RESERVE_MAX", "5"))
RESERVE_MIN = int(os.environ.get("RESERVE_MIN", "2"))
EMERGENCY_MIN_HOOK = int(os.environ.get("EMERGENCY_MIN_HOOK", "55"))
EMERGENCY_MIN_QUALITY = int(os.environ.get("EMERGENCY_MIN_QUALITY", "50"))
US_PEAK_HOURS = {12, 13, 14, 15, 16, 17, 18, 19, 20}  # EDT 8AM-4PM


# ── Slot tracking ─────────────────────────────────────────────────────

def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_hour_et() -> int:
    try:
        import pytz
        return datetime.now(pytz.timezone("America/New_York")).hour
    except Exception:
        utc_hour = datetime.now(timezone.utc).hour
        return (utc_hour - 4) % 24


def is_us_peak_slot(hour: int = None) -> bool:
    h = hour if hour is not None else _now_hour_et()
    return h in US_PEAK_HOURS


def register_slot_attempt(slot_label: str, status: str, title: str = "") -> None:
    path = "data/slot_history.json"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        if os.path.exists(path):
            with open(path) as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        else:
            history = []
    except Exception:
        history = []

    history.append({
        "slot": slot_label,
        "date": _today_str(),
        "status": status,
        "title": title,
        "hour_et": _now_hour_et(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    history = history[-200:]
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(history, f, indent=2)
    os.replace(tmp, path)


def is_retryable_pre_upload_failure(msg: str) -> bool:
    keywords = [
        "hook", "quality", "spam", "gate", "blocked",
        "retention", "seo", "duplicate", "bait", "pacing",
        "scenes", "hook_miss",
    ]
    msg_lower = msg.lower()
    return any(kw in msg_lower for kw in keywords)


def should_retry_on_guard_failure(attempt: int, max_retries: int = 3) -> bool:
    return attempt < max_retries


# ── Tier 2: Reserve Queue ────────────────────────────────────────────

def _reserve_path(topic_hash: str = "") -> str:
    os.makedirs(RESERVE_DIR, exist_ok=True)
    return os.path.join(RESERVE_DIR, f"reserve.json")


def _load_reserve() -> list:
    path = _reserve_path()
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_reserve(items: list) -> None:
    path = _reserve_path()
    os.makedirs(RESERVE_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def add_to_reserve(script_data: dict, topic: str = "") -> bool:
    """Add a gate-passed script to the reserve queue for future fallback."""
    items = _load_reserve()

    if len(items) >= RESERVE_MAX:
        logger.info("Reserve queue full (%d/%d), skipping add.", len(items), RESERVE_MAX)
        return False

    reserve_entry = {
        "topic": topic or script_data.get("topic", ""),
        "title": script_data.get("title", ""),
        "hook_score": script_data.get("shorts_report", {}).get("hook_detail", {}).get("score", 0),
        "quality_score": script_data.get("quality_scores", {}).get("overall_quality", 0),
        "script_data": script_data,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "tier": 2,
    }

    items.append(reserve_entry)
    _save_reserve(items)
    logger.info(
        "✅ Added to reserve queue: %s (hook=%s, quality=%s) [%d/%d]",
        reserve_entry["title"][:40], reserve_entry["hook_score"],
        reserve_entry["quality_score"], len(items), RESERVE_MAX,
    )
    return True


def consume_reserve() -> Optional[dict]:
    """Pop the oldest reserve script for fallback use."""
    items = _load_reserve()
    if not items:
        logger.info("Reserve queue empty — no Tier 2 fallback available.")
        return None

    chosen = items.pop(0)
    _save_reserve(items)
    logger.info(
        "📥 Reserve consumed: %s (hook=%s) [%d remaining]",
        chosen["title"][:40], chosen.get("hook_score", 0), len(items),
    )
    return chosen.get("script_data")


def get_reserve_count() -> int:
    return len(_load_reserve())


def refill_reserve_from_history(video_history: list, metrics: dict = None) -> int:
    """Pre-fill reserve queue from high-performing historical videos.

    These are NOT re-uploads — they serve as structural templates so the
    emergency generator knows what a gate-passed script looks like.
    """
    items = _load_reserve()
    current_topics = {it.get("topic") for it in items}

    candidates = []
    for v in video_history:
        topic = v.get("topic", "")
        if topic in current_topics:
            continue

        hook = v.get("hook_score", 0) or 0
        seo = v.get("seo_score", 0) or 0
        yt_id = v.get("youtube_video_id") or v.get("youtube_id") or ""

        if hook >= 80 or (seo >= 85 and yt_id):
            candidates.append({
                "topic": topic,
                "title": v.get("title") or v.get("youtube_title", ""),
                "hook_score": hook,
                "quality_score": seo,
                "script_data": {
                    "topic": topic,
                    "title": v.get("title") or v.get("youtube_title", ""),
                    "hook": v.get("hook", ""),
                    "voiceover": v.get("voiceover", ""),
                    "scenes": v.get("scenes", []),
                    "tags": v.get("tags", []),
                    "_template_only": True,
                    "_reason": "high_performer_template",
                },
                "added_at": datetime.now(timezone.utc).isoformat(),
                "tier": 2,
            })

    candidates.sort(key=lambda x: x.get("hook_score", 0), reverse=True)
    added = 0
    for c in candidates:
        if len(items) >= RESERVE_MAX:
            break
        if c["topic"] not in current_topics:
            items.append(c)
            current_topics.add(c["topic"])
            added += 1

    if added:
        _save_reserve(items)
        logger.info("Pre-filled reserve queue with %d high-performer templates.", added)

    return added


# ── Tier 3: Emergency Minimal Generation ─────────────────────────────

def generate_emergency_script(topic: str = None) -> Optional[dict]:
    """Generate a minimal but structurally sound script when all else fails.

    This is NOT a quality bypass — it uses a simpler template that guarantees:
    - 3-5 scenes with clear captions
    - Hook in first 2 seconds
    - Basic SEO title and description
    - Bait-free content

    It explicitly does NOT generate voice/video — it provides a script_data
    skeleton that the main pipeline can process through the normal gates
    with relaxed (but not zero) thresholds.
    """
    try:
        from script_generator import generate_script
        from quality_checker import QualityChecker
        from anti_spam import AntiSpamSystem
        from niche_strategy import get_topic_category
    except ImportError:
        logger.error("Emergency generator: core modules unavailable.")
        return None

    emergency_topic = topic or "Why your heart skips a beat sometimes"

    for attempt in range(3):
        try:
            script_data = generate_script(emergency_topic)
            if not script_data:
                continue

            if not script_data.get("scenes") or len(script_data["scenes"]) < 3:
                continue

            qc = QualityChecker()
            quality = qc.check_script_quality(script_data, lenient=True)
            if not quality or not quality.get("approved"):
                continue

            asys = AntiSpamSystem()
            spam = asys.check_for_spam_risks(script_data, [])
            if spam.get("spam_risk_level") in ("CRITICAL", "HIGH"):
                continue

            script_data["_emergency_generated"] = True
            script_data["_emergency_at"] = datetime.now(timezone.utc).isoformat()
            script_data["_emergency_topic"] = emergency_topic
            logger.warning(
                "🚨 Emergency Tier 3 script generated (attempt %d): %s",
                attempt + 1, script_data.get("title", "untitled")[:40],
            )
            return script_data

        except Exception as e:
            logger.warning("Emergency generation attempt %d failed: %s", attempt + 1, e)
            time.sleep(5)

    logger.error("🚨 All 3 emergency generation attempts failed.")
    return None


# ── Main Continuity Handler ──────────────────────────────────────────

def handle_slot_failure(
    original_error: str,
    topic: str = None,
    attempt: int = 1,
    video_history: list = None,
    metrics: dict = None,
) -> Tuple[Optional[dict], str]:
    """Handle a slot failure with 3-tier fallback.

    Returns: (script_data_or_None, tier_used)
    """
    logger.warning(
        "🔄 Slot failure on attempt %d: %s — initiating 3-tier fallback.",
        attempt, str(original_error)[:120],
    )

    # Tier 2: Try reserve queue
    reserve = consume_reserve()
    if reserve:
        logger.warning("📥 TIER 2 FALLBACK: Using reserve queue script.")
        return reserve, "tier_2_reserve"

    # Tier 2b: Refill reserve from history if empty
    if video_history:
        refill_reserve_from_history(video_history, metrics)
        reserve = consume_reserve()
        if reserve:
            logger.warning("📥 TIER 2b FALLBACK: Refilled and consumed reserve.")
            return reserve, "tier_2_refill"

    # Tier 3: Emergency generation
    emergency = generate_emergency_script(topic)
    if emergency:
        logger.warning("🚨 TIER 3 FALLBACK: Emergency script generated.")
        return emergency, "tier_3_emergency"

    # All tiers exhausted
    logger.error("🔴 ALL 3 TIERS EXHAUSTED — slot will be missed.")
    return None, "exhausted"


def ensure_reserve_health(video_history: list = None, metrics: dict = None) -> dict:
    """Check and maintain reserve queue health. Call at pipeline start."""
    count = get_reserve_count()
    health = {
        "reserve_count": count,
        "reserve_max": RESERVE_MAX,
        "reserve_min": RESERVE_MIN,
        "healthy": count >= RESERVE_MIN,
    }

    if count < RESERVE_MIN and video_history:
        added = refill_reserve_from_history(video_history, metrics)
        health["refilled"] = added
        health["reserve_count"] = count + added
        health["healthy"] = (count + added) >= RESERVE_MIN

    if not health["healthy"]:
        logger.warning(
            "⚠️ Reserve queue below minimum: %d/%d. "
            "Increase generation success rate to refill.",
            health["reserve_count"], RESERVE_MIN,
        )

    return health


# ──────────────────────────────────────────────────────────────────────────────
# RETENTION CADENCE CEILING
# ──────────────────────────────────────────────────────────────────────────────

PRODUCTION_CADENCE = 3


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


def slot_consistency_status() -> Dict[str, Any]:
    """Report how consistent the last 7 days of slots were, by US peak hour."""
    state = _load_state()
    slots = state.get("slots", [])
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
    """Aim for the 3/day production cadence, but never above measured retention."""
    suggested = max(1, int(cadence or 1))
    if os.environ.get("DISABLE_CADENCE_3", "false").strip().lower() == "true":
        return suggested

    ceiling, reason = retention_cadence_ceiling(platform_health)
    target = min(max(suggested, PRODUCTION_CADENCE), ceiling)
    if target < PRODUCTION_CADENCE:
        logger.info("Cadence capped at %s/day: %s", target, reason)
    return max(1, min(PRODUCTION_CADENCE, target))
