import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "trend_forecast.json"

logger = logging.getLogger(__name__)

def build_trend_forecast(days_ahead=7):
    """Builds and returns the trend forecast using live Reddit trend data."""
    default_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days_ahead": days_ahead,
        "total_topics_scanned": 0,
        "forecast": [],
        "all_scored": []
    }
    
    try:
        from trend_research import fetch_trending_topics
        trends = fetch_trending_topics(limit=15)
        
        if trends:
            # Score them artificially for now, highest trending first
            scored = [{"topic": t, "score": 95 - i} for i, t in enumerate(trends)]
            default_data["forecast"] = scored[:5]
            default_data["all_scored"] = scored
            default_data["total_topics_scanned"] = len(trends)
        elif DATA_PATH.exists():
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing["days_ahead"] = days_ahead
            existing["generated_at"] = default_data["generated_at"]
            default_data = existing
    except Exception as exc:
        logger.warning(f"Error fetching trend forecast: {exc}", exc_info=True)

    os.makedirs(DATA_PATH.parent, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(default_data, f, indent=2)
        
    return default_data
