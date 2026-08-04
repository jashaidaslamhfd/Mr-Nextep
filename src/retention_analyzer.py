import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "retention_analysis.json"
METRICS_PATH = ROOT / "data" / "platform_metrics.json"

logger = logging.getLogger(__name__)

def analyze_all_videos():
    """Performs and returns video retention analysis based on real metrics."""
    default_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": 0,
        "critical": 0,
        "below_gate": 0,
        "healthy": 0,
        "top_issues": [],
        "videos": []
    }
    
    try:
        if METRICS_PATH.exists():
            with open(METRICS_PATH, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            
            if metrics:
                total = len(metrics)
                healthy = 0
                below = 0
                critical = 0
                
                for k, v in metrics.items():
                    yt = v.get("youtube_shorts", {})
                    completion = yt.get("completion")
                    if completion is not None:
                        if completion >= 0.65:
                            healthy += 1
                        elif completion >= 0.45:
                            below += 1
                        else:
                            critical += 1
                
                default_data["total_videos"] = total
                default_data["healthy"] = healthy
                default_data["below_gate"] = below
                default_data["critical"] = critical
                
                if critical > healthy:
                    default_data["top_issues"].append("High critical retention failure rate. Consider shortening intro hooks.")
    except Exception as exc:
        logger.warning(f"Error computing retention analysis: {exc}", exc_info=True)

    os.makedirs(DATA_PATH.parent, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(default_data, f, indent=2)
        
    return default_data
