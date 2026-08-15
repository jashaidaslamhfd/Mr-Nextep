#!/usr/bin/env python3
"""Apply the curated legacy-title repair plan (data/auto_repair_plan.json)
against live YouTube videos via the YouTube Data API.

Each plan entry is verified against the live video (oEmbed) before the
metadata is rewritten. Idempotent via data/plan_ledger.json.

Usage:
  env GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... REFRESH_TOKEN=... \
      python scripts/apply_repair_plan.py
"""
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import repair_all_seo as base  # noqa: E402  (YouTubeRepair OAuth class)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("apply_repair_plan")

PLAN_PATH = ROOT / "data" / "auto_repair_plan.json"
LEDGER_PATH = ROOT / "data" / "plan_ledger.json"


def load_ledger() -> set:
    try:
        return set(json.load(open(LEDGER_PATH, encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def save_ledger(ledger: set) -> None:
    try:
        json.dump(sorted(ledger), open(LEDGER_PATH, "w", encoding="utf-8"),
                  indent=1)
    except Exception as exc:  # noqa: BLE001
        logger.error("ledger write failed: %s", exc)


def _oembed_title(vid: str) -> str | None:
    try:
        import requests
        r = requests.get("https://www.youtube.com/oembed",
                         params={"url": f"https://youtu.be/{vid}",
                                 "format": "json"}, timeout=15)
        if r.status_code == 200:
            return r.json().get("title")
    except Exception as exc:  # noqa: BLE001
        logger.debug("oembed failed for %s: %s", vid, exc)
    return None


def main() -> int:
    if not PLAN_PATH.exists():
        logger.info("no repair plan at %s — nothing to do", PLAN_PATH)
        return 0
    plan = json.load(open(PLAN_PATH, encoding="utf-8"))
    repairs = plan.get("repairs") or []
    ledger = load_ledger()
    yt = base.YouTubeRepair()

    done = 0
    for entry in repairs:
        vid = entry.get("id")
        if not vid or vid in ledger:
            continue
        live = _oembed_title(vid)
        if live is None:
            logger.warning("%s: video not found live (skipped)", vid)
            continue
        logger.info("%s: live title is '%s' — applying plan fix", vid, live)
        res = yt.update_video(
            vid, entry["proposed_title"], entry["proposed_description"],
        )
        if res.get("ok"):
            logger.info("%s: repaired -> '%s'", vid, entry["proposed_title"])
            ledger.add(vid)
            done += 1
        else:
            logger.error("%s: apply failed — %s (will retry next run)",
                         vid, res.get("error", res))
    save_ledger(ledger)
    logger.info("plan apply complete: %d videos repaired this run", done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
