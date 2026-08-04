import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "viral_intelligence.json"
METRICS_PATH = ROOT / "data" / "platform_metrics.json"

logger = logging.getLogger(__name__)

def build_viral_intelligence():
    """Builds and returns the viral intelligence analysis from actual metrics."""
    default_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_viral_videos": 0,
        "queries_used": [],
        "min_views_threshold": 10000,
        "title_starters": {},
        "power_words": {},
        "top_tags": {},
        "avg_title_length": 0,
        "viral_videos": [],
        "curated_patterns": [],
        "curated_tags": []
    }
    
    try:
        if METRICS_PATH.exists():
            with open(METRICS_PATH, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            
            if metrics:
                # Perform basic analytics
                viral_threshold = 5000  # Adjust as needed based on channel size
                viral_videos = []
                title_lengths = []
                title_starters = {}
                power_words_freq = {}
                
                for k, v in metrics.items():
                    yt = v.get("youtube_shorts", {})
                    views = yt.get("views", 0) or 0
                    if views >= viral_threshold:
                        viral_videos.append(v)
                        
                        title = v.get("title", "")
                        if title:
                            title_lengths.append(len(title))
                            words = title.split()
                            if words:
                                starter = " ".join(words[:2]).title()
                                title_starters[starter] = title_starters.get(starter, 0) + 1
                                for w in words:
                                    if len(w) > 4:
                                        pw = w.lower()
                                        power_words_freq[pw] = power_words_freq.get(pw, 0) + 1

                if viral_videos:
                    try:
                        from sklearn.ensemble import RandomForestRegressor
                        # Simple feature extraction for ML
                        X, y = [], []
                        for v in viral_videos:
                            title = v.get("title", "")
                            length = len(title)
                            hook_score = v.get("hook_score") or 50
                            seo_score = v.get("seo_score") or 50
                            yt = v.get("youtube_shorts", {})
                            views = yt.get("views", 0) or 0
                            X.append([length, hook_score, seo_score])
                            y.append(views)
                        
                        if len(X) >= 5: # Need enough samples for RF
                            rf = RandomForestRegressor(n_estimators=10, random_state=42)
                            rf.fit(X, y)
                            importance = rf.feature_importances_
                            default_data["ml_insights"] = {
                                "title_length_importance": round(importance[0], 2),
                                "hook_score_importance": round(importance[1], 2),
                                "seo_score_importance": round(importance[2], 2)
                            }
                    except Exception as ml_err:
                        logger.warning(f"ML analysis skipped: {ml_err}")

                    default_data["total_viral_videos"] = len(viral_videos)
                    default_data["avg_title_length"] = int(np.mean(title_lengths))
                    default_data["title_starters"] = dict(sorted(title_starters.items(), key=lambda item: item[1], reverse=True)[:5])
                    default_data["power_words"] = dict(sorted(power_words_freq.items(), key=lambda item: item[1], reverse=True)[:10])
    except Exception as exc:
        logger.warning(f"Failed to compute viral intelligence: {exc}", exc_info=True)

    # Save and return
    os.makedirs(DATA_PATH.parent, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(default_data, f, indent=2)
        
    return default_data
