"""Reality calibration — the antidote to "high score, bad content".

The channel's gates (hook scorer, quality, SEO, CTR prediction) are heuristic:
they approve anything that passes their internal rules. As the metrics show,
those scores can drift NEGATIVELY correlated with reality (hook_score vs views
= 0.06, predicted_ctr vs views = -0.38). That means the system was proudly
approving content the audience rejected.

This module closes the loop:
  1. measure how each heuristic score actually correlates with real performance,
  2. detect "drift" (a lever that scores high but underperforms),
  3. output a reality-adjusted approval signal so the pipeline stops trusting
     scores that reality contradicts.

Design: pure, offline, testable. Uses only fields already in video_history.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Minimum samples before a correlation is trustworthy.
MIN_CALIBRATION_SAMPLES = 6

# A lever is "drifted" if its correlation with real views is weakly positive
# or negative (i.e. higher scores do not mean better performance).
DRIFT_CORR_THRESHOLD = 0.10

# The heuristic levers we can reality-check against real views.
LEVERS = ["hook_score", "predicted_ctr", "seo_score", "predicted_retention"]


def _corr(xs: List[float], ys: List[float]):
    try:
        import numpy as np
        if len(xs) < 3:
            return 0.0
        x = np.array(xs, dtype=float)
        y = np.array(ys, dtype=float)
        if np.std(x) < 1e-9 or np.std(y) < 1e-9:
            return 0.0
        c = float(np.corrcoef(x, y)[0, 1])
        return c if np.isfinite(c) else 0.0
    except Exception:
        return 0.0


def calibrate(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Measure how each heuristic score actually predicts real views.

    Returns per-lever correlation, a drift verdict, and a recommendation on
    which levers the pipeline should stop trusting.
    """
    rows = [
        v for v in (history or [])
        if v.get("analytics_fetched_at") and v.get("views")
    ]
    n = len(rows)
    result: Dict[str, Any] = {
        "calibrated": False, "n": n, "levers": {}, "drifted": [],
        "trusted": [], "note": "",
    }
    if n < MIN_CALIBRATION_SAMPLES:
        result["note"] = f"Only {n} videos with real analytics — not enough to calibrate yet."
        return result

    for lever in LEVERS:
        pairs = [(v.get(lever), v.get("views")) for v in rows]
        pairs = [(s, view) for s, view in pairs if s and view]
        if len(pairs) < MIN_CALIBRATION_SAMPLES:
            result["levers"][lever] = {
                "corr": None, "samples": len(pairs), "verdict": "unknown",
            }
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        corr = _corr(xs, ys)
        drifted = corr < DRIFT_CORR_THRESHOLD
        verdict = "DRIFTED" if drifted else "ok"
        result["levers"][lever] = {
            "corr": round(corr, 3), "samples": len(pairs), "verdict": verdict,
        }
        if drifted:
            result["drifted"].append(lever)
        else:
            result["trusted"].append(lever)

    result["calibrated"] = True
    if result["drifted"]:
        result["note"] = (
            "Drift detected: these scores do NOT predict real views — "
            "higher scores are not earning more. Do not raise the approval "
            "bar on them; trust real metrics instead. "
            + ", ".join(result["drifted"])
        )
    else:
        result["note"] = "All checked levers positively correlate with real views."
    return result


def reality_adjusted_ok(history: List[Dict[str, Any]],
                        lever_scores: Dict[str, float],
                        ) -> Dict[str, Any]:
    """Decide whether to trust a candidate's heuristic scores.

    If a lever is DRIFTED, its score should NOT be used to approve or to inflate
    confidence — the pipeline should rely on real historical performance of
    similar content rather than the drifted heuristic.
    """
    cal = calibrate(history)
    drifted = set(cal["drifted"])

    # Which of the candidate's scores are drift-affected?
    affected = {k: v for k, v in (lever_scores or {}).items() if k in drifted}
    result: Dict[str, Any] = {
        "approve_on_heuristics": not drifted,   # if nothing drifted, heuristics OK
        "drifted_levers": cal["drifted"],
        "affected_scores": affected,
        "calibration": cal,
        "advice": (
            f"Reality shows {len(cal['drifted'])} lever(s) are unreliable "
            f"({', '.join(cal['drifted']) or 'none'}). Base approval on real "
            "performance, not on these scores."
        ),
    }
    return result
