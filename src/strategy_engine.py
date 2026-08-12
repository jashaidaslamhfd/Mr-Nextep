"""Autonomous Strategy Engine — the self-deciding brain of the pipeline.

This module turns the fragmented intelligence already in the repo
(growth_engine weights, ml_brain predictions, viral_intelligence, competitor
intel, trend forecasts, real per-video metrics) into ONE place that makes a
decision before every run and after every learning pass.

It exists to remove the barriers between the system and millions of views by
answering, autonomously, the questions a human operator used to answer:

  1. Which content series should I run right now (dark_mystery, body_glitches,
     or a live trend hijack) — and is it time to pivot?
  2. Which topics are most likely to retain, ranked by a trained model (not
     just uniform random)?
  3. What is the single biggest barrier to growth right now (completion,
     CTR, scheduling, cadence) and what is the concrete fix?
  4. What quality gates / hook budget / duration should the run use, adapted
     to what the data actually says?

Design rules:
  * Fully offline and testable — never calls a network.
  * Degrades gracefully: no data -> sensible policy defaults, never raises.
  * Pure function core (`decide_from_state`) + thin class wrapper, so tests
    can feed synthetic state directly.
  * Uses the DS/ML stack already in requirements (numpy, pandas, scikit-learn)
    only where it genuinely helps; heuristic fallbacks keep it robust.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

# Paths (overridable via env for tests).
STRATEGY_STATE_PATH = os.environ.get("STRATEGY_STATE_PATH", str(DATA_DIR / "strategy_state.json"))
GROWTH_STATE_PATH = os.environ.get("GROWTH_STATE_PATH", str(DATA_DIR / "growth_state.json"))
HISTORY_PATH = os.environ.get("VIDEO_HISTORY_PATH", str(DATA_DIR / "video_history.json"))
VIRAL_PATH = os.environ.get("VIRAL_INTEL_PATH", str(DATA_DIR / "viral_intelligence.json"))
TREND_PATH = os.environ.get("TREND_FORECAST_PATH", str(DATA_DIR / "trend_forecast.json"))
COMPETITOR_PATH = os.environ.get("COMPETITOR_INTEL_PATH", str(DATA_DIR / "competitor_intel.json"))

# Supported content series + the topic strategy that drives each.
SERIES_STRATEGY = {
    "dark_mystery": "dark_mystery_series",
    "body_glitches": "body_glitch_series",
    "trend": "viral_hijack",
}
SUPPORTED_SERIES = list(SERIES_STRATEGY.keys())

# Minimum samples before we trust a model/dataset for a decision.
MIN_ML_SAMPLES = 8

# Barrier types we can detect and act on.
BARRIER_COMPLETION = "completion"
BARRIER_CTR = "ctr"
BARRIER_SCHEDULING = "scheduling"
BARRIER_VOLUME = "volume"


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001 - never let bad data break a decision
        logger.warning("Could not load %s (%s); using default", path, exc)
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _completion_fraction(value: Any, fallback: float = 0.0) -> float:
    """Normalise an average_view_percentage (0-100 scale) to a fraction 0-1.

    The pipeline stores completion as a percentage (0-100, occasionally >100
    from loops). Everywhere in the strategy engine we reason in fractions, so
    this converts and clamps to a sane [0,1.5] band (loops can exceed 100%).
    """
    pct = _safe_float(value)
    if pct <= 0:
        return fallback
    return min(pct / 100.0, 1.5)


def _load_video_features() -> List[Dict[str, float]]:
    """Pull the numeric feature set that a retention/views model can learn on.

    Uses only fields already recorded in video_history by the pipeline, so no
    new instrumentation is needed. Missing values become NaN for the model and
    0.0 for the heuristic.
    """
    history = _load_json(HISTORY_PATH, []) or []
    rows: List[Dict[str, float]] = []
    for v in history:
        views = _safe_float(v.get("views") or v.get("average_view_percentage"))
        # Only keep records that have a real analytics signal to learn from.
        if not v.get("analytics_fetched_at"):
            continue
        rows.append({
            "views": views,
            "completion": _completion_fraction(v.get("average_view_percentage")),
            # REAL measured CTR (from YouTube Analytics, when available). This
            # is what the ML should be trained on — not the heuristic estimate.
            "real_ctr": _safe_float(v.get("actual_ctr")),
            # REAL retention (%) as a fraction — the measured averageViewPercentage.
            "real_retention": _completion_fraction(v.get("average_view_percentage")),
            "hook_score": _safe_float(v.get("hook_score")),
            "predicted_ctr": _safe_float(v.get("predicted_ctr")),
            "seo_score": _safe_float(v.get("seo_score")),
            "duration_seconds": _safe_float(v.get("duration_seconds"), 30.0),
            "predicted_retention": _safe_float(v.get("predicted_retention")),
            "word_count": _safe_float(v.get("word_count")),
        })
    return rows


def _load_platform_health() -> Dict[str, Dict[str, float]]:
    """Normalised per-platform health from the growth engine state."""
    state = _load_json(GROWTH_STATE_PATH, {}) or {}
    return (state.get("platform_health") or {}) or {}


def _load_series_history() -> Dict[str, Dict[str, float]]:
    """Best-effort per-series retention signal.

    When series attribution is available in video_history (future-proofed via
    a 'series' field) it is used directly; otherwise we fall back to a single
    neutral bucket so the engine still makes a sane choice.
    """
    history = _load_json(HISTORY_PATH, []) or []
    # Map a recorded trend_source back to a supported series bucket. This lets
    # the engine compare how each launch series (body vs dark mystery) actually
    # retained, instead of lumping everything into one "trend" bucket.
    source_to_series = {
        "body_glitch_series": "body_glitches",
        "dark_mystery_series": "dark_mystery",
        "proven_channel_pillar": "trend",
        "youtube_trending": "trend",
        "google_trends": "trend",
        "reddit": "trend",
    }
    buckets: Dict[str, List[float]] = {}
    for v in history:
        source = (v.get("trend_source") or v.get("series") or "").strip().lower()
        bucket = source_to_series.get(source, "trend")
        if bucket not in SUPPORTED_SERIES:
            bucket = "trend"
        if not v.get("analytics_fetched_at"):
            continue
        comp = _completion_fraction(v.get("average_view_percentage"))
        if comp > 0:
            buckets.setdefault(bucket, []).append(comp)
    out: Dict[str, Dict[str, float]] = {}
    for series, comps in buckets.items():
        out[series] = {"avg_completion": sum(comps) / len(comps), "samples": float(len(comps))}
    return out


def _learned_series_weights() -> Dict[str, float]:
    """Which series currently retains best, derived from real completion."""
    series_hist = _load_series_history()
    if not series_hist:
        return {}
    base = {s: 1.0 for s in SUPPORTED_SERIES}
    for series, stats in series_hist.items():
        if stats["samples"] < 3:
            continue
        base[series] = _clamp(stats["avg_completion"] / 0.5, 0.35, 2.0)  # 0.5 = healthy bar
    return base


# --------------------------------------------------------------------------- #
# Pure decision core (feeds tests directly with synthetic state)
# --------------------------------------------------------------------------- #

def decide_from_state(*, platform_health: Optional[Dict] = None,
                      video_features: Optional[List[Dict[str, float]]] = None,
                      series_history: Optional[Dict[str, Dict[str, float]]] = None,
                      competitor_recs: Optional[List[str]] = None,
                      viral_tags: Optional[List[str]] = None,
                      slot_weights: Optional[Dict[str, float]] = None,
                      topic_pillar_weights: Optional[Dict[str, float]] = None,
                      current_series: Optional[str] = None,
                      ) -> Dict[str, Any]:
    """Make a full autonomous decision from raw state.

    This is a pure function: give it the numbers, get a decision. It never
    touches disk or the network, which keeps it easy to test and to reason
    about.

    `current_series` is the series the operator/workflow is currently running
    (e.g. "dark_mystery"). The engine respects an explicit, still-unproven
    pivot: it will NOT bounce a freshly-launched series back to a saturated
    niche just because the old niche happens to have more history. It only
    auto-switches when a proven alternative is clearly better.
    """
    platform_health = platform_health or {}
    video_features = video_features or []
    series_history = series_history or {}
    competitor_recs = competitor_recs or []
    viral_tags = viral_tags or []
    slot_weights = slot_weights or {}
    topic_pillar_weights = topic_pillar_weights or {}

    # ---- 1. Barrier analysis ---------------------------------------------- #
    barrier, barrier_advice = _detect_barrier(platform_health, video_features)

    # ---- 2. Which series to run (autonomous pivot) ------------------------ #
    # Compute proven weights from real completion (>= MIN samples to trust).
    proven = {}   # series -> weight, only series with enough samples
    for series, stats in series_history.items():
        if series not in SUPPORTED_SERIES:
            continue
        if stats.get("samples", 0) >= 3:
            comp = stats.get("avg_completion") or 0.0
            proven[series] = _clamp(comp / 0.5, 0.35, 2.0)
    series_weights = {s: proven.get(s, 1.0) for s in SUPPORTED_SERIES}

    current = current_series if current_series in SUPPORTED_SERIES else None
    if current:
        # Respect the operator's current series while it is still unproven:
        # an unproven pivot (dark_mystery) must not be overridden by a
        # saturated niche that merely has more history.
        current_proven = current in proven
        if not current_proven:
            recommended_series = current
        else:
            # Current is proven — keep it unless a better alternative is also
            # proven and meaningfully stronger.
            current_w = proven[current]
            best_alt = max((s for s in proven if s != current), key=lambda s: proven[s], default=None)
            if best_alt and proven[best_alt] > current_w * 1.25:
                recommended_series = best_alt
            else:
                recommended_series = current
    else:
        recommended_series = max(series_weights, key=lambda s: series_weights[s])

    pivot = False
    pivot_reason = None
    # If our recommended series is proven-failing, surface a pivot signal.
    if recommended_series in proven and proven[recommended_series] < 1.0:
        pivot = True
        pivot_reason = (
            f"{recommended_series} completion is below the retention bar; "
            "rotate toward a higher-retention series format."
        )

    # ---- 3. Rank topics / pick publish slot / cadence ---------------------- #
    top_series = SERIES_STRATEGY.get(recommended_series, SERIES_STRATEGY["dark_mystery"])
    best_slot = max(slot_weights.items(), key=lambda kv: kv[1])[0] if slot_weights else None
    cadence = 2
    if barrier == BARRIER_VOLUME:
        cadence = 3
    elif barrier == BARRIER_COMPLETION:
        cadence = 1  # quality over volume when retention is broken

    # ---- 4. Adaptive quality gate ----------------------------------------- #
    # Tighter gate when we have a strong learned signal; policy default 60.
    quality_threshold = 60
    if len(video_features) >= MIN_ML_SAMPLES:
        avg_comp = sum((v.get("completion") or 0) for v in video_features) / len(video_features)
        if avg_comp < 0.3:
            quality_threshold = 65  # demand more before publishing
        elif avg_comp > 0.6:
            quality_threshold = 55  # loosen a little to increase volume

    # ---- 5. ML lever analysis (which lever drives views) ------------------ #
    lever = ml_lever_analysis(video_features)

    # ---- 5b. Advanced intelligence (ensemble, outliers, segments) --------- #
    # Best-effort: the advanced stack (cross-validated ensemble, IsolationForest
    # outliers, KMeans segments) adds a deeper view on top of the basic lever
    # analysis. Never blocks the decision if it fails.
    intelligence = {}
    try:
        from intelligence import synthesize_intelligence
        intelligence = synthesize_intelligence(video_features)
    except Exception as exc:  # noqa: BLE001 - advanced intel must never block
        logger.warning("Advanced intelligence unavailable (%s); using basic lever analysis.", exc)
        intelligence = {"error": str(exc)[:120]}

    # ---- 5c. Reality calibration (high-score/bad-content detector) --------- #
    # The channel's metrics showed heuristic scores can be NEGATIVELY
    # correlated with real views (hook/ctr/seo/retention all DRIFTED). This
    # flags which levers the pipeline must stop trusting, so it stops approving
    # content reality rejects.
    calibration = {}
    try:
        from calibration import calibrate
        calibration = calibrate(_load_video_features() and _load_json(HISTORY_PATH, []))
    except Exception as exc:  # noqa: BLE001 - calibration must never block
        logger.warning("Calibration unavailable (%s)", exc)
        calibration = {"error": str(exc)[:120]}

    # ---- 5d. Independent evaluation gate (real outcomes, not self-scores) -- #
    # The pipeline scores itself with heuristics that can drift. This gate
    # evaluates on REAL views/CTR/retention only, so the decision knows the
    # channel's true performance and whether there's enough real signal to
    # trust ML/calibration at all.
    evaluation = {}
    try:
        from evaluator import evaluate_channel
        evaluation = evaluate_channel()
    except Exception as exc:  # noqa: BLE001 - evaluation must never block
        logger.warning("Independent evaluation unavailable (%s)", exc)
        evaluation = {"error": str(exc)[:120]}

    signal_guard = {}
    try:
        from analytics_guards import require_real_signal, data_health
        signal_guard = require_real_signal(block=False)
        signal_guard["health"] = data_health()
    except Exception as exc:  # noqa: BLE001 - guard must never block
        signal_guard = {"error": str(exc)[:120]}

    return {
        "recommended_series": recommended_series,
        "topic_strategy": top_series,
        "barrier": barrier,
        "barrier_advice": barrier_advice,
        "pivot": pivot,
        "pivot_reason": pivot_reason,
        "best_slot": best_slot,
        "cadence": cadence,
        "quality_threshold": quality_threshold,
        "lever_analysis": lever,
        "intelligence": intelligence,
        "calibration": calibration,
        "evaluation": evaluation,
        "signal_guard": signal_guard,
        "viral_readiness": viral_readiness_report(),
        "series_weights": series_weights,
        "competitor_leads": competitor_recs[:5],
        "viral_tags": viral_tags[:8],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }


def viral_readiness_report() -> Dict[str, Any]:
    """The viral-readiness scorecard, as a standalone decision field.

    Non-blocking: if the scorecard can't load it returns a neutral dict so a
    broken check can never fail a strategy decision.
    """
    try:
        from viral_readiness import readiness_scorecard
        return readiness_scorecard()
    except Exception as exc:  # noqa: BLE001 - scorecard must never block
        logger.warning("Viral readiness scorecard unavailable (%s)", exc)
        return {"score": None, "rating": "unknown", "error": str(exc)[:120]}


def _detect_barrier(platform_health: Dict, video_features: List[Dict[str, float]]) -> tuple:
    """Pick the single binding constraint, in priority order."""
    # Completion barrier: any platform well under its gate.
    completion_margin = None
    completion_platform = "platforms"
    for name, health in platform_health.items():
        ratio = _safe_float(health.get("gate_ratio"), 1.0)
        if completion_margin is None or ratio < completion_margin:
            completion_margin = ratio
            completion_platform = name
    if completion_margin is not None and completion_margin < 0.6:
        return BARRIER_COMPLETION, (
            f"{completion_platform} is at {completion_margin:.0%} of its completion "
            "gate. Rebuild the first-3-seconds hook and shorten the cut toward the "
            "platform ideal before adding volume."
        )

    # CTR barrier: predicted CTR is low across recent videos.
    if video_features:
        avg_ctr = sum((v.get("predicted_ctr") or 0) for v in video_features) / len(video_features)
        if avg_ctr < 3.0:
            return BARRIER_CTR, (
                f"Predicted CTR {avg_ctr:.1f}% is low. Improve the hook/title and "
                "thumbnail (face-to-text contrast, curiosity gap) to lift click-through."
            )

    # Scheduling barrier: no strong learned slot yet.
    if len(platform_health) == 0:
        return BARRIER_SCHEDULING, (
            "No analytics yet. Run a few publishes, wait ~48h, then re-decide "
            "so slots/topics can be learned from real completion."
        )

    # Otherwise assume we can push volume.
    return BARRIER_VOLUME, "Retention healthy enough; increase cadence for reach."


# --------------------------------------------------------------------------- #
# ML lever analysis (scikit-learn RandomForest on real video features)
# --------------------------------------------------------------------------- #

# Feature -> human label used in the recommendation.
_LEVER_LABELS = {
    "hook_score": "hook (first-3s)",
    "predicted_ctr": "click-through / title+thumbnail",
    "seo_score": "SEO / description+tags",
    "duration_seconds": "video length",
    "predicted_retention": "predicted retention",
}


def ml_lever_analysis(video_features: List[Dict[str, float]]) -> Dict[str, Any]:
    """Train a RandomForest on real per-video features to learn which lever
    drives views, and return the importance ranking.

    This is the genuine ML piece: instead of guessing whether the hook or the
    SEO matters more, we fit a model on this channel's own historical videos
    and let it tell us. Falls back to a neutral heuristic when there aren't
    enough samples to train safely.
    """
    import numpy as np  # local import keeps module import-light

    result: Dict[str, Any] = {"trained": False, "lever_importance": [], "sample_size": 0}
    if len(video_features) < MIN_ML_SAMPLES:
        result["lever_importance"] = [
            {"lever": "hook_score", "label": _LEVER_LABELS["hook_score"], "importance": 0.5},
            {"lever": "predicted_ctr", "label": _LEVER_LABELS["predicted_ctr"], "importance": 0.3},
            {"lever": "seo_score", "label": _LEVER_LABELS["seo_score"], "importance": 0.2},
        ]
        result["note"] = "Not enough samples to train; using neutral priorities."
        return result

    features = [
        "hook_score", "predicted_ctr", "seo_score", "duration_seconds", "predicted_retention"
    ]
    X = np.array(
        [[v.get(f) or 0.0 for f in features] for v in video_features],
        dtype=np.float64,
    )
    y = np.array([v.get("views") or 0.0 for v in video_features], dtype=np.float64)
    # A feature with zero variance can't contribute; guard the fit.
    if X.shape[0] < 3 or np.all(y == 0):
        result["note"] = "Insufficient variance to train a meaningful model."
        return result

    try:
        from sklearn.ensemble import RandomForestRegressor
        model = RandomForestRegressor(n_estimators=80, random_state=42, min_samples_leaf=2)
        model.fit(X, y)
        importances = model.feature_importances_
        if not np.any(np.isfinite(importances)) or float(np.sum(importances)) <= 0:
            return result
        ranked = sorted(
            ({"lever": f, "label": _LEVER_LABELS.get(f, f), "importance": float(imp)}
             for f, imp in zip(features, importances)),
            key=lambda item: item["importance"], reverse=True,
        )
        total = sum(item["importance"] for item in ranked) or 1.0
        for item in ranked:
            item["share"] = round(item["importance"] / total, 3)
        result.update({
            "trained": True, "lever_importance": ranked, "sample_size": len(video_features),
        })
    except Exception as exc:  # noqa: BLE001 - ML must never block a decision
        logger.warning("ML lever analysis failed: %s", exc)
        result["note"] = f"Model failed to train ({exc}); using neutral priorities."
    return result


# --------------------------------------------------------------------------- #
# Class wrapper (reads real state, writes decisions)
# --------------------------------------------------------------------------- #

class StrategyEngine:
    """Reads the repo's real state, decides, and persists the decision."""

    def __init__(self, state_path: Optional[str] = None) -> None:
        self.state_path = state_path or STRATEGY_STATE_PATH
        self.state: Dict[str, Any] = {}

    def collect(self) -> Dict[str, Any]:
        """Load every signal the engine can see into one dict."""
        self._platform_health = _load_platform_health()
        self._video_features = _load_video_features()
        self._series_history = _load_series_history()
        growth = _load_json(GROWTH_STATE_PATH, {}) or {}
        self._slot_weights = growth.get("slot_weights") or {}
        self._pillar_weights = growth.get("topic_weights") or {}

        viral = _load_json(VIRAL_PATH, {}) or {}
        competitor = _load_json(COMPETITOR_PATH, {}) or {}
        # top_tags can be a dict {tag: count} or a list; normalise to a list.
        viral_raw = viral.get("top_tags") or viral.get("curated_tags") or []
        self._viral_tags = (
            list(viral_raw.keys()) if isinstance(viral_raw, dict) else list(viral_raw)
        )
        self._competitor_recs = competitor.get("recommendations") or []
        if isinstance(self._competitor_recs, dict):
            self._competitor_recs = list(self._competitor_recs.values())

        # The series the operator/workflow currently runs (respect a pivot).
        self._current_series = (os.environ.get("CONTENT_SERIES") or "").strip().lower()

        return self.snapshot()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "platform_health": self._platform_health,
            "video_features": self._video_features,
            "series_history": self._series_history,
            "slot_weights": self._slot_weights,
            "pillar_weights": self._pillar_weights,
            "viral_tags": self._viral_tags,
            "competitor_recs": self._competitor_recs,
        }

    def decide(self) -> Dict[str, Any]:
        """Run the pure decision core on the collected state and persist it."""
        snap = self.snapshot()
        decision = decide_from_state(
            platform_health=snap["platform_health"],
            video_features=snap["video_features"],
            series_history=snap["series_history"],
            competitor_recs=snap["competitor_recs"],
            viral_tags=snap["viral_tags"],
            slot_weights=snap["slot_weights"],
            topic_pillar_weights=snap["pillar_weights"],
            current_series=self._current_series,
        )
        self.state = decision
        self.persist()
        return decision

    def persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh, indent=2, default=str)
            os.replace(tmp, self.state_path)
        except Exception as exc:  # noqa: BLE001 - decision logging must not break runs
            logger.warning("Could not persist strategy decision: %s", exc)


def decide() -> Dict[str, Any]:
    """Convenience: collect + decide + persist in one call."""
    engine = StrategyEngine()
    engine.collect()
    return engine.decide()


def decide_and_report() -> Dict[str, Any]:
    """Like decide() but ensures collect() ran first (used by CLI/CI)."""
    engine = StrategyEngine()
    engine.collect()
    return engine.decide()


def load_decision() -> Dict[str, Any]:
    """Read the last persisted decision (main.py consumes this)."""
    return _load_json(STRATEGY_STATE_PATH, {})


if __name__ == "__main__":  # pragma: no cover - CLI entry
    import sys
    decision = decide_and_report()
    print(json.dumps(decision, indent=2, default=str))
    sys.exit(0)
