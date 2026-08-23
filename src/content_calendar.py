import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "content_calendar.json"

logger = logging.getLogger(__name__)

def build_content_calendar(days=30):
    """Builds and returns the content calendar derived from actual growth analytics."""
    # Keep planning aligned with the owner's current YouTube Studio heatmap:
    # one strong daily release at 12:30 PM America/New_York. The live scheduler
    # remains the source of truth for the actual DST-aware timestamp.
    best_slots = ["12:30 NY"]
    try:
        from growth_engine import load_state
        state = load_state()
        if state.get("best_slot"):
            best_slots = [state.get("best_slot")]
    except Exception as exc:
        logger.warning(f"Failed to load best slot from growth engine: {exc}")

    default_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "total_candidates": days * len(best_slots),
        "calendar": [],
        "best_slots": best_slots,
        "recent_topics_excluded": 0
    }
    
    # Try to merge with existing data if present
    if DATA_PATH.exists():
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing["best_slots"] = best_slots
            existing["generated_at"] = default_data["generated_at"]
            default_data = existing
        except Exception as exc:
            logger.warning(f"Error reading existing content calendar: {exc}")

    os.makedirs(DATA_PATH.parent, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(default_data, f, indent=2)
        
    return default_data
