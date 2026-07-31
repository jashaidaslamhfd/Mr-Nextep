import json
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "content_calendar.json"

def build_content_calendar(days=30):
    """Builds and returns the content calendar for the specified number of days."""
    if DATA_PATH.exists():
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["days"] = days
            return data
        except Exception:
            pass

    # Fallback default
    default_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "total_candidates": 15,
        "calendar": [],
        "best_slots": [],
        "recent_topics_excluded": 0
    }
    
    os.makedirs(DATA_PATH.parent, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(default_data, f, indent=2)
        
    return default_data
