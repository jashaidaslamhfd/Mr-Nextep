#!/usr/bin/env python3
"""Train the NEW system's ML on real channel data and persist the result.

Runs the full modern stack — not the legacy ml_brain — on the channel's REAL
outcome data (views/retention from committed analytics) and writes a single
model state file (data/model_state.json) that the pipeline can read instead of
re-fitting on every run.

Trains:
  * views ensemble     (RandomForest + GBoost + ExtraTrees + Ridge, OOF-weighted)
  * completion ensemble(ensemble_predict on completion)
  * stacking meta-learner (learns the optimal blend of base models)
  * dedicated CTR model (on real CTR when available, else heuristic target)
  * dedicated retention model
  * independent evaluator (channel true-score + data health)
  * reality calibration (which levers are drifted from real views)

Usage:
  python scripts/train_ml.py                 # train + persist + print summary
  python scripts/train_ml.py --print-json    # also dump full JSON
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

MODEL_STATE_PATH = os.environ.get(
    "MODEL_STATE_PATH", str(ROOT / "data" / "model_state.json"))


def load_features() -> list:
    from strategy_engine import _load_video_features
    return _load_video_features()


def train() -> dict:
    from intelligence import synthesize_intelligence
    from evaluator import evaluate_channel
    from calibration import calibrate
    from strategy_engine import _load_json, HISTORY_PATH

    feats = load_features()

    # full intelligence report (ensemble + stacking + ctr + retention + segments)
    intelligence = synthesize_intelligence(feats)

    # independent evaluation (real outcomes only)
    evaluation = evaluate_channel()

    # reality calibration (drift detection)
    calibration = calibrate(_load_json(HISTORY_PATH, []))

    state = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_training_samples": len(feats),
        "data_health": evaluation.get("data_health", {}),
        "views_ensemble": intelligence.get("views_ensemble", {}),
        "completion_ensemble": intelligence.get("completion_ensemble", {}),
        "stacking_meta": intelligence.get("stacking_meta", {}),
        "ctr_model": intelligence.get("ctr_model", {}),
        "retention_model": intelligence.get("retention_model", {}),
        "topic_segments": intelligence.get("topic_segments", {}),
        "top_levers": intelligence.get("top_levers", []),
        "advice": intelligence.get("advice", []),
        "channel_score": evaluation.get("channel_score"),
        "calibration": calibration,
    }
    return state


def persist(state: dict) -> None:
    MODEL_STATE_PATH  # noqa
    p = Path(MODEL_STATE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, default=str)
    os.replace(tmp, p)
    print(f"Wrote model state -> {p}")


def main() -> int:
    print_json = "--print-json" in sys.argv
    state = train()
    persist(state)

    print("\n=== ML TRAINED (new system) ===")
    print(f"Training samples : {state['n_training_samples']}")
    print(f"Channel true-score: {state['channel_score']}/100 "
          f"({state['data_health'].get('verdict')})")
    ve = state.get("views_ensemble", {})
    print(f"Views ensemble   : trained={ve.get('trained')} r2={ve.get('r2_cv')} "
          f"confidence={ve.get('confidence')}")
    cm = state.get("ctr_model", {})
    print(f"CTR model        : trained={cm.get('trained')} "
          f"source={cm.get('target_source')} confidence={cm.get('confidence')}")
    rm = state.get("retention_model", {})
    print(f"Retention model  : trained={rm.get('trained')} "
          f"r2={rm.get('r2_cv')} confidence={rm.get('confidence')}")
    cal = state.get("calibration", {})
    print(f"Calibration drift: {cal.get('drifted') or 'none'}")
    for adv in state.get("advice", [])[:4]:
        print(f"  - {adv}")

    if print_json:
        print("\n" + json.dumps(state, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
