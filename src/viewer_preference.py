"""Viewer-Preference Guard — FREE, content-based "will people like this?" score.

The structural guards (gates.py) verify that a video is technically correct
(canvas, scenes, voice, no bait), and the heuristic quality scores (hook/CTR/
SEO) have been shown to DRIFT from real views. This module is the missing
piece: a FREE, local, content-based estimate of how much viewers will actually
like a script — i.e. the signals that research and the platform algorithms
reward (curiosity, specificity, emotional pull, payoff, pacing, loopability).

It deliberately does NOT rely on the drifted heuristic scores. It computes its
own 0-100 "viewer preference" score from the script's actual text/structure,
and the guard blocks a publish below a threshold.

Free: no API calls, pure Python + regex over the script. Offline, testable.

Self-improving: every scored script + its eventual real outcome is written to
data/viewer_preference_history.json so the model can be re-fit once enough real
labels accumulate (see recalibrate()).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY_PATH = os.environ.get(
    "VIEWER_PREF_HISTORY", str(DATA / "viewer_preference_history.json"))

# Curiosity / open-loop words that research shows stop the scroll and keep
# viewers watching to the payoff.
CURIOSITY_WORDS = (
    "why", "what happens", "how", "secret", "actually", "never", "every",
    "hidden", "truth", "really", "the reason", "did you know", "believe",
    "crazy", "weird", "strange", "no one tells you", "surprising",
)
# Concrete, picturable subjects — a hook that names a real body/phenomenon is
# a much stronger first-2s signal than an abstract one.
CONCRETE_SUBJECTS = (
    "eye", "hand", "foot", "brain", "heart", "muscle", "skin", "ear", "tongue",
    "knee", "finger", "nose", "voice", "sleep", "dream", "memory", "cramp",
    "twitch", "shake", "freeze", "yawn", "blush", "goosebump", "ring", "burn",
    "jerking", "heartbeat", "paralysis", "delusion", "reflex", "limb",
)
# Second-person framing — "your body" hooks make it personally relevant.
PERSONAL_FRAME = ("you", "your", "you're", "yourself")

_BAIT = ("like and subscribe", "smash that like", "hit the bell", "tag someone",
         "share this", "subscribe for more", "comment below")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _count_words(text: str, words) -> int:
    t = _norm(text)
    return sum(1 for w in words if re.search(r"\b" + re.escape(w) + r"\b", t))


# --------------------------------------------------------------------------- #
# FREE content-feature extraction (no API)
# --------------------------------------------------------------------------- #

def extract_features(script_data: Dict[str, Any]) -> Dict[str, float]:
    """Compute content-based features that predict viewer engagement. All free
    and offline. Returns normalized feature dict (0-1 scale)."""
    title = script_data.get("title") or script_data.get("topic") or ""
    hook = script_data.get("hook") or (script_data.get("scenes") or [{}])[0].get("caption") or ""
    voice = script_data.get("voiceover") or " ".join(
        (s.get("caption") or "") for s in (script_data.get("scenes") or []))
    scenes = script_data.get("scenes") or []
    desc = script_data.get("description") or ""

    # 1. Hook strength: curiosity + concrete + personal
    hook_n = _norm(hook)
    n_words = max(len(hook_n.split()), 1)
    hook_curiosity = min(_count_words(hook, CURIOSITY_WORDS) / 2.0, 1.0)
    hook_concrete = 1.0 if any(w in hook_n for w in CONCRETE_SUBJECTS) else 0.0
    hook_personal = 1.0 if any(w in hook_n.split() for w in PERSONAL_FRAME) else 0.0
    hook_not_too_long = 1.0 if n_words <= 10 else (0.5 if n_words <= 14 else 0.2)
    hook_score_f = 0.40 * hook_curiosity + 0.30 * hook_concrete + 0.20 * hook_personal + 0.10 * hook_not_too_long

    # 2. Story completeness: payoff + loop-back + structure
    n_scenes = len(scenes)
    has_payoff = 1.0 if any(_count_words(s.get("caption", ""),
                            ("because", "actually", "the reason", "so", "that's why"))
                            for s in scenes) else 0.0
    has_loop = 1.0 if n_scenes >= 7 else 0.0  # loop-back needs a full arc
    structure = min(n_scenes / 8.0, 1.0) * 0.5 + has_loop * 0.5

    # 3. Pacing: voiceover word count reasonable for a Short
    vo_n = _norm(voice)
    vo_words = len(vo_n.split())
    if 60 <= vo_words <= 105:
        pacing = 1.0
    elif 45 <= vo_words <= 120:
        pacing = 0.7
    else:
        pacing = 0.3

    # 4. Title curiosity + personal
    title_c = min(_count_words(title, CURIOSITY_WORDS) / 2.0, 1.0)
    title_p = 1.0 if any(w in _norm(title).split() for w in PERSONAL_FRAME) else 0.0

    # 5. Bait penalty (engagement bait is demoted by 2026 feeds)
    all_text = _norm(title + " " + hook + " " + desc)
    bait = 1.0 if any(b in all_text for b in _BAIT) else 0.0

    return {
        "hook_strength": round(hook_score_f, 3),
        "story_completeness": round(structure, 3),
        "pacing": round(pacing, 3),
        "title_curiosity": round((title_c + title_p) / 2.0, 3),
        "payoff_present": has_payoff,
        "bait_penalty": bait,
    }


# --------------------------------------------------------------------------- #
# Free viewer-preference score
# --------------------------------------------------------------------------- #

def score_viewer_preference(script_data: Dict[str, Any]) -> Dict[str, Any]:
    """FREE 0-100 estimate of how much viewers will like the script.

    Weights are set from research + the channel's own data (completion is the
    top ranking signal; hook is the top first-2s signal; payoff/loop drive
    completion; bait is demoted). This is a content-based prior — it improves
    as real outcome data accumulates via recalibrate().
    """
    f = extract_features(script_data)
    # use calibrated weights if a previous recalibrate() fitted them
    if _CALIBRATED_WEIGHTS:
        w = _CALIBRATED_WEIGHTS
        score = (
            f["hook_strength"] * w.get("hook_strength", 0.35)
            + f["story_completeness"] * w.get("story_completeness", 0.25)
            + f["pacing"] * w.get("pacing", 0.15)
            + f["title_curiosity"] * w.get("title_curiosity", 0.15)
            + f["payoff_present"] * w.get("payoff_present", 0.10)
        ) * 100
    else:
        score = (
            f["hook_strength"] * 0.35
            + f["story_completeness"] * 0.25
            + f["pacing"] * 0.15
            + f["title_curiosity"] * 0.15
            + f["payoff_present"] * 0.10
        ) * 100
    # bait penalty: up to -20
    score -= f["bait_penalty"] * 20
    score = max(0, min(100, score))

    verdict = "strong" if score >= 70 else ("ok" if score >= 55 else "weak")
    return {
        "score": round(score, 1),
        "verdict": verdict,
        "features": f,
        "free": True,           # no API calls
        "note": "Free content-based viewer-preference estimate (offline).",
    }


def viewer_preference_guard(script_data: Dict[str, Any],
                            threshold: float = 70) -> Dict[str, Any]:
    """The guard: does this script pass the viewer-preference bar?

    Blocks publish when the free content score is below `threshold` — the
    channel's own data shows the heuristic scores don't predict views, so we
    rely on this content-based signal (plus the structural guards) instead.
    """
    s = score_viewer_preference(script_data)
    ok = s["score"] >= threshold
    return {
        "guard": "viewer_preference",
        "pass": ok,
        "score": s["score"],
        "verdict": s["verdict"],
        "threshold": threshold,
        "issues": [] if ok else [f"viewer-preference score {s['score']} < {threshold}"],
        "features": s["features"],
    }


# --------------------------------------------------------------------------- #
# Self-improving: log scores + real outcomes so the model can be recalibrated
# --------------------------------------------------------------------------- #

def record_outcome(script_data: Dict[str, Any], real_retention: float,
                   real_views: float) -> None:
    """Store a (features, real outcome) pair for future recalibration. Called
    by the analytics loop once a video has real analytics."""
    try:
        f = extract_features(script_data)
        rec = {
            "features": f,
            "real_retention": round(float(real_retention), 4),
            "real_views": round(float(real_views), 1),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        hist = _load_history()
        hist.append(rec)
        hist = hist[-2000:]  # cap
        with open(HISTORY_PATH, "w", encoding="utf-8") as fh:
            json.dump(hist, fh, indent=2)
    except Exception as exc:  # noqa: BLE001 - logging must never break the loop
        logger.warning("Could not record viewer-preference outcome: %s", exc)


def _load_history() -> List[Dict[str, Any]]:
    p = Path(HISTORY_PATH)
    if not p.exists():
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return []


# module-level override used by score_viewer_preference if set
_CALIBRATED_WEIGHTS: Optional[Dict[str, float]] = None


def recalibrate() -> Dict[str, Any]:
    """Re-fit the feature weights once enough real-outcome labels accumulate.

    Uses real retention labels (0-100) to find which FREE content features
    actually predict viewer liking on THIS channel, and updates the weights in
    score_viewer_preference via a module-level override. Returns the fitted
    weights + how many labels were used.
    """
    global _CALIBRATED_WEIGHTS
    hist = _load_history()
    labeled = [r for r in hist if (r.get("real_retention") or 0) > 0]
    if len(labeled) < 8:
        return {"calibrated": False, "n_labels": len(labeled),
                "note": "Need >=8 real-outcome labels to recalibrate."}

    import numpy as np
    keys = ["hook_strength", "story_completeness", "pacing",
            "title_curiosity", "payoff_present"]
    X = np.array([[r["features"][k] for k in keys] for r in labeled], dtype=float)
    y = np.array([r["real_retention"] / 100.0 for r in labeled], dtype=float)
    # solve least squares for feature weights (non-negative, fit_intercept)
    A = np.column_stack([X, np.ones(len(X))])
    try:
        coef, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
    except Exception:
        return {"calibrated": False, "n_labels": len(labeled), "note": "fit failed"}
    weights = {k: float(c) for k, c in zip(keys, coef[:-1])}
    # normalize to sum 1 (positive)
    total = sum(max(w, 0.0) for w in weights.values()) or 1.0
    weights = {k: round(max(w, 0.0) / total, 4) for k, w in weights.items()}
    _CALIBRATED_WEIGHTS = weights
    return {"calibrated": True, "n_labels": len(labeled), "weights": weights,
            "note": "Recalibrated free content weights from real retention."}
