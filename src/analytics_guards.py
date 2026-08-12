"""Analytics Guards — stop the pipeline running blind.

The channel's metrics showed the system was publishing on heuristic scores
that had NO relationship to real performance (actually NEGATIVELY correlated).
A key reason: no real CTR/impressions data ever reached the system
(`actual_ctr` was always 0), so the ML/calibration had nothing real to learn
on and the "quality" gates stayed uncalibrated.

These guards are the safety rails:
  1. data_health()      — report how much real signal exists right now.
  2. require_real_signal— a guard that warns/blocks when the pipeline is about
                          to trust decisions without real analytics.
  3. verify_analytics_scope — check whether the OAuth token actually has the
                          yt-analytics.readonly scope (the #1 reason CTR is 0).
  4. collect_metrics_guard — run from the analytics workflow to verify the
                          metrics loop is actually writing real data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _load(path: str, default):
    p = DATA / path
    if not p.exists():
        return default
    try:
        return __import__("json").load(open(p, encoding="utf-8"))
    except Exception:
        return default


def data_health() -> Dict[str, Any]:
    """How much REAL, usable signal does the system have right now?"""
    from evaluator import evaluate
    e = evaluate()
    h = e["data_health"]
    return {
        "n_videos_with_real_metrics": h["n_videos"],
        "n_with_real_ctr": h["n_with_real_ctr"],
        "ctr_scope_ok": h["ctr_scope_ok"],
        "enough_retention": h["enough_retention"],
        "trust_worthy": h["trust_worthy"],
        "verdict": h["verdict"],
        "channel_score": e["channel_score"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def require_real_signal(block: bool = False) -> Dict[str, Any]:
    """A guard the generation pipeline calls before trusting ML/calibration.

    If there isn't enough real signal, either block (publish nothing / require
    human review) or warn. Returns a decision dict the pipeline can act on.
    """
    h = data_health()
    ok = h["trust_worthy"]
    decision = {
        "can_trust_scores": ok,
        "verdict": h["verdict"],
        "action": (
            "PROCEED" if ok else
            ("BLOCKED" if block and h["verdict"] == "COLD_START" else "REVIEW")
        ),
        "reason": (
            f"{h['n_with_real_ctr']} real CTR readings "
            f"({h['n_videos_with_real_metrics']} videos) — "
            + ("enough to calibrate." if ok else "not enough to trust heuristics.")
        ),
    }
    if decision["action"] == "BLOCKED":
        logger.warning("🔴 GUARD: no real analytics signal — blocking publish "
                       "until real CTR/retention data is collected.")
    elif decision["action"] == "REVIEW":
        logger.warning("🟡 GUARD: limited real signal — heuristics may be "
                       "unreliable; consider human review before publish.")
    else:
        logger.info("🟢 GUARD: enough real signal to trust decisions.")
    return decision


def verify_analytics_scope() -> Dict[str, Any]:
    """Check whether the OAuth REFRESH_TOKEN has yt-analytics.readonly scope.

    This is the most common reason real CTR/impressions are never collected:
    the token was issued for upload only. We can't read scopes from the token
    string, so we attempt a real analytics query and report whether it works.
    """
    try:
        from seo_analytics import fetch_actual_performance
        # use a video id we know exists if possible
        vh = _load("video_history.json", []) or []
        vid = next((v.get("youtube_video_id") for v in vh if v.get("youtube_video_id")), None)
        if not vid:
            return {"scope_ok": False, "reason": "no video id to test analytics on"}
        r = fetch_actual_performance(vid)
        if "error" in r:
            return {"scope_ok": False, "reason": str(r.get("error") or r.get("note"))[:200]}
        return {"scope_ok": True, "reason": "analytics query succeeded", "sample": r}
    except Exception as exc:  # noqa: BLE001
        return {"scope_ok": False, "reason": str(exc)[:200]}


def collect_metrics_guard() -> Dict[str, Any]:
    """Run from the analytics workflow after metrics collection to confirm the
    loop actually wrote REAL data (not zeros)."""
    vh = _load("video_history.json", []) or []
    n_views = sum(1 for v in vh if (v.get("views") or 0) > 0)
    n_ctr = sum(1 for v in vh if (v.get("actual_ctr") or 0) > 0)
    n_ret = sum(1 for v in vh if (v.get("average_view_percentage") or 0) > 0)
    return {
        "views_collected": n_views,
        "ctr_collected": n_ctr,
        "retention_collected": n_ret,
        "ctr_working": n_ctr >= 6,
        "healthy": n_views >= 6 and n_ret >= 6,
        "note": ("Real analytics loop is writing data." if (n_views >= 6 and n_ret >= 6)
                 else "Analytics loop may be failing — CTR is " +
                 ("working" if n_ctr >= 6 else "NOT being collected (scope?).")),
    }


def status_summary() -> str:
    h = data_health()
    return (f"Analytics: {h['verdict']} — {h['n_with_real_ctr']} real CTR / "
            f"{h['n_videos_with_real_metrics']} videos, "
            f"CTR scope {'OK' if h['ctr_scope_ok'] else 'MISSING (yt-analytics.readonly?)'}.")
