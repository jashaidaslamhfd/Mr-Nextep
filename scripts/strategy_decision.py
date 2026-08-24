#!/usr/bin/env python3
"""Autonomous Strategy Engine — CLI.

Runs the full decision: aggregates real analytics (growth state, per-video
metrics, viral/competitor intel) plus the ML lever analysis, decides the next
run's series / cadence / quality gate / barrier, and persists it to
data/strategy_state.json for the pipeline to consume.

Usage:
    python scripts/strategy_decision.py            # decide + persist + print
    python scripts/strategy_decision.py --report   # same, human-friendly output
    python scripts/strategy_decision.py --reset    # clear the decision file
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def main() -> int:
    parser = argparse.ArgumentParser(description="MrNextep autonomous strategy decision")
    parser.add_argument("--report", action="store_true", help="human-friendly output")
    parser.add_argument("--reset", action="store_true", help="clear the decision file")
    args = parser.parse_args()

    from strategy_engine import decide_and_report, STRATEGY_STATE_PATH

    if args.reset:
        try:
            os.remove(STRATEGY_STATE_PATH)
            print("Strategy decision cleared.")
        except FileNotFoundError:
            print("No decision file existed.")
        return 0

    decision = decide_and_report()

    if args.report:
        print("=" * 60)
        print("🤖 AUTONOMOUS STRATEGY DECISION")
        print("=" * 60)
        print(f"Series to run      : {decision.get('recommended_series')}")
        print(f"Topic strategy     : {decision.get('topic_strategy')}")
        print(f"Growth barrier     : {decision.get('barrier')}")
        print(f"  {decision.get('barrier_advice')}")
        print(f"Cadence            : {decision.get('cadence')} video(s)/day")
        print(f"Quality gate       : {decision.get('quality_threshold')}")
        print(f"Best slot          : {decision.get('best_slot')}")
        if decision.get("pivot"):
            print(f"⚠️  PIVOT: {decision.get('pivot_reason')}")
        lever = decision.get("lever_analysis") or {}
        imp = lever.get("lever_importance") or []
        if imp:
            print("ML lever priority  :")
            for item in imp[:3]:
                print(f"  - {item.get('label')}  ({round(item.get('share',0)*100)}%)")
    else:
        print(json.dumps(decision, indent=2, default=str))

    print(f"\nPersisted to {STRATEGY_STATE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
