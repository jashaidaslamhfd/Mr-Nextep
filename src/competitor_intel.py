import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "competitor_intel.json"

logger = logging.getLogger(__name__)

def build_competitor_intel():
    """Builds and returns the competitor intelligence analysis."""
    default_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_viral_videos": 0,
        "competitors_analyzed": 0,
        "per_channel": {},
        "overall_title_analysis": {},
        "overall_tag_analysis": {},
        "recommendations": [],
        "min_views_threshold": 500000
    }
    
    # Try to load existing intel if available to retain competitor list
    try:
        if DATA_PATH.exists():
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
            
            # Carry over dynamic analysis
            existing["generated_at"] = default_data["generated_at"]
            default_data = existing
    except Exception as exc:
        logger.warning(f"Error loading competitor intel: {exc}")

    # Generate some automated insights if competitors exist
    if default_data.get("per_channel"):
        try:
            from competitor_hijacker import get_competitor_channels
            channels = get_competitor_channels()
            default_data["competitors_analyzed"] = len(channels)
            default_data["recommendations"] = [
                "Replicate top competitor pacing (25-35s).",
                "Hook viewers within 3 seconds using proven power words."
            ]
        except Exception as exc:
            logger.warning(f"Could not refresh competitor dynamic intel: {exc}")

    os.makedirs(DATA_PATH.parent, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(default_data, f, indent=2)
        
    return default_data
