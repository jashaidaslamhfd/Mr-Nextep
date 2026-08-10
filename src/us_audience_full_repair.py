import json
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPAIR_DIR = ROOT / "output" / "USA_Repair_2026_07_29"
METADATA_PATH = REPAIR_DIR / "repaired_metadata.json"

def main():
    """Generates the USA Repair Pack metadata and creates the directory."""
    os.makedirs(REPAIR_DIR, exist_ok=True)
    
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_repairs": 23,
        "videos": [
            {
                "youtube_video_id": f"vid_repair_{i}",
                "original_title": f"Original Title {i}",
                "new_title": f"Why Your Body Does This Repair {i}",
                "original_tags": ["body facts"],
                "new_tags": ["human body", "body facts", "science facts"],
                "description": "Learn the amazing science behind your body's functions in this video."
            }
            for i in range(1, 24)
        ]
    }
    
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        
    print(f"USA Repair Pack generated: {METADATA_PATH}")

if __name__ == "__main__":
    main()
