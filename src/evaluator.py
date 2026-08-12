"""Independent Evaluation Gate — the system's objective scoreboard.

The generation pipeline scores its own work (hook/CTR/SEO/quality) with
heuristics, and those can drift far from reality (the channel's metrics showed
identical high scores on videos spanning 2-882 real views, and the heuristics
were NEGATIVELY correlated with real views). A system that scores itself will
always call itself "good".

This module is the SEPARATE GATE: it evaluates the channel purely on REAL
outcomes (views, CTR, retention, watch-time) and reports how well the
pipeline's decisions are actually doing. It never reads the pipeline's own
quality scores — it only reads committed real metrics. That removes the
self-evaluation bias.

It also drives REAL-data ML: it gathers the training rows (real CTR, real
retention, real views) that `intelligence` can learn on, and reports data
health so the pipeline knows when its signals are trustworthy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Weights for the composite "true performance" score, all based on REAL metrics.
# These are the actual gates the platforms use (completion, CTR, watch time).
SCORE_WEIGHTS = {
    "retention": 0.40,   # completion % vs gate — dominant ranking signal
    "ctr": 0.30,         # real click-through vs healthy ~4%+
    "views": 0.20,       # raw distribution (weakest signal, but shows reach)
    "engagement": 0.10,  # likes/comments per view
}


def _load(path: str, default):
    p = DATA / path
    if not p.exists():
        return default
    try:
        return __import__("json").load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _video_metrics() -> List[Dict[str, Any]]:
    """Rows of REAL outcome data from committed analytics. No pipeline scores."""
    vh = _load("video_history.json", []) or []
    rows = []
    for v in vh:
        # only videos that have a real analytics reading
        if not v.get("analytics_fetched_at"):
            continue
        views = v.get("views") or 0
        if not views:
            continue
        rows.append({
            "views": float(views),
            "retention": _pct(v.get("average_view_percentage")),
            "avg_watch_sec": float(v.get("average_view_duration_sec") or 0),
            "ctr": float(v.get("actual_ctr") or 0),
            "likes": float(v.get("likes") or 0),
            "comments": float(v.get("comments") or 0),
            "published": (v.get("published_at") or v.get("posted_at") or "")[:16],
        })
    return rows


def _pct(v) -> float:
    """average_view_percentage is 0-100 (occasionally >100 from loops) -> fraction."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return min(x / 100.0, 1.5)


def _engagement_rate(row) -> float:
    if not row["views"]:
        return 0.0
    return (row["likes"] + row["comments"]) / row["views"]


def _ctr_score(ctr: float) -> float:
    # healthy Shorts CTR ~4%+; scale so 4% = 1.0
    return min(ctr / 4.0, 1.0)


def _retention_score(ret: float, gate: float = 0.6) -> float:
    # gate ~60% completion (platforms vary 50-72%); score = fraction of gate cleared
    return min(ret / gate, 1.0) if gate else 0.0


def _views_score(views: float) -> float:
    # logarithmic: 100 views = 0.25, 1000 = 0.5, 10k = 0.75, 100k = 1.0
    import math
    if views <= 0:
        return 0.0
    return min(math.log10(max(views, 1)) / 5.0, 1.0)


def evaluate(video_rows: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Produce the independent, real-data-only performance evaluation.

    Returns a composite 0-100 'true performance' score per video plus an
    overall channel score, alongside data-health flags so the pipeline knows
    whether it has enough trustworthy signal to make decisions.
    """
    rows = video_rows if video_rows is not None else _video_metrics()
    n = len(rows)

    per_video = []
    for r in rows:
        c = SCORE_WEIGHTS
        s = (
            c["retention"] * _retention_score(r["retention"])
            + c["ctr"] * _ctr_score(r["ctr"])
            + c["views"] * _views_score(r["views"])
            + c["engagement"] * min(_engagement_rate(r) / 0.05, 1.0)
        )
        per_video.append({
            "views": r["views"],
            "retention": r["retention"],
            "ctr": r["ctr"],
            "true_score": round(s * 100, 1),
            "published": r["published"],
        })

    avg = {
        "views": round(sum(r["views"] for r in rows) / n, 1) if n else 0.0,
        "retention": round(sum(r["retention"] for r in rows) / n, 4) if n else 0.0,
        "ctr": round(sum(r["ctr"] for r in rows) / n, 3) if n else 0.0,
    }

    # Data-health guards — is there enough REAL signal to trust decisions?
    n_real_ctr = sum(1 for r in rows if r["ctr"] > 0)
    health = {
        "n_videos": n,
        "n_with_real_ctr": n_real_ctr,
        "ctr_scope_ok": n_real_ctr >= 6,   # enough real CTR to calibrate
        "enough_retention": n >= 6,        # enough retention signal
        "trust_worthy": n_real_ctr >= 6 and n >= 6,
        "verdict": (
            "TRUST" if (n_real_ctr >= 6 and n >= 6) else
            "LIMITED" if n >= 6 else
            "COLD_START"
        ),
    }

    overall = round(sum(v["true_score"] for v in per_video) / n, 1) if n else 0.0
    return {
        "independent": True,          # evaluated on real outcomes, not pipeline scores
        "n": n,
        "per_video": per_video,
        "channel_score": overall,
        "channel_avg": avg,
        "data_health": health,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def evaluate_channel() -> Dict[str, Any]:
    """Convenience wrapper: evaluate the whole committed history."""
    return evaluate()


def has_reliable_signal() -> bool:
    """Quick guard the pipeline can call before trusting ML decisions."""
    e = evaluate()
    return e["data_health"]["trust_worthy"]


def real_training_rows() -> List[Dict[str, Any]]:
    """The REAL outcome rows the ML should learn on (views/retention/ctr).
    This is what `intelligence` uses instead of heuristic predictions."""
    return _video_metrics()
