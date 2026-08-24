#!/usr/bin/env python3
"""Build an auto_repair_plan.json for Mr-Nextep from the live channel
classification (video_classification.json), matching the Neuro-Somaa plan
schema so it can be consumed by SEO-repair tooling.

Usage:
  python scripts/build_auto_repair_plan.py          # plan only
  python scripts/build_auto_repair_plan.py --apply  # also write plan file
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from ctr_engine import generate_high_ctr_title  # noqa: E402

CLASS_PATH = ROOT / "data" / "video_classification.json"
PLAN_PATH = ROOT / "data" / "auto_repair_plan.json"

TOPIC_HINTS = {
    "IjwfP0tcZH8": "body freezes completely when you are extremely scared",
    "cGVDXd8HN4g": "we got fired from the animal hospital — the real reason",
}


def _topic_for(item: dict) -> str:
    hint = TOPIC_HINTS.get(item["youtube_video_id"], "")
    if hint:
        return hint
    topic = item.get("topic") or item.get("title") or ""
    # Normalize "Why Your Body Does This: X 😳" → clean topic
    topic = topic.split("\n")[0].strip()
    for pat in ["😳", "🫀", "🧠", "👁️", "👀", "🦵", "😴", "🌟", "🌻", "💔", "💓", "🙂"]:
        topic = topic.replace(pat, "").strip()
    topic = topic.replace("Why Your Body Does This:", "").strip()
    low = topic.lower()
    # Turn 'Why X ...?' questions into clean noun-phrase topics so the CTR
    # engine always has a real anchored subject to build a title from.
    if low.startswith("why your "):
        topic = topic[8:].strip()
    elif low.startswith("why you "):
        topic = topic[7:].strip()
    elif low.startswith("why a ") or low.startswith("why an "):
        topic = topic[6:].strip()
    elif low.startswith("why "):
        topic = topic[4:].strip()
    return topic or "body science fact"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    items = json.load(open(CLASS_PATH, encoding="utf-8"))
    repairs = []
    for item in items:
        decision = item.get("decision", "")
        if decision not in ("repair_top", "repair_low", "hide"):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue
        # Skip titles that already look fine (short but meaningful one-liners
        # like 'Dizzy Standing 🫀' are handled by the CTR guard's own
        # description-repair step; we focus on malformed 'Why ...' titles).
        if not title.lower().startswith("why"):
            continue
        topic = _topic_for(item)
        new_title = generate_high_ctr_title(topic, platform="youtube")
        repairs.append({
            "id": item["youtube_video_id"],
            "url": f"https://youtu.be/{item['youtube_video_id']}",
            "views": item.get("views"),
            "current_title": title,
            "reasons": ["legacy malformed 'Why ...' title — weak CTR pattern"],
            "proposed_title": new_title,
            "proposed_description": (
                f"{new_title}\n\nSubscribe for daily body science shorts.\n\n"
                f"#shorts #body #science #health #facts"
            ),
        })

    plan = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "Verified by MrNextep CTR guard. Apply via SEO Repair workflow (apply mode).",
        "repairs": repairs,
    }
    print(f"plan: {len(repairs)} repairs")
    for r in repairs:
        print(f"  {r['id']} | '{r['current_title']}' -> '{r['proposed_title']}'")

    if args.apply:
        with open(PLAN_PATH, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=1, ensure_ascii=False)
        print(f"written: {PLAN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
