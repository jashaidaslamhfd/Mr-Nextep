from __future__ import annotations
from typing import Any

def build_packages(script: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_title = str(script.get("title", "Dark Science Explained")).strip()
    description = str(script.get("description", "")).strip()
    tags = [str(tag).strip().lower() for tag in script.get("tags", []) if str(tag).strip()]

    # High-CTR Curiosity Title for Shorts
    clean_title = raw_title.rstrip("?.!")
    yt_title = raw_title if "#shorts" in raw_title.lower() else f"{clean_title} #shorts"

    # US YouTube Shorts Tag Cluster
    yt_tags = list(dict.fromkeys(
        tags + [
            "youtube shorts", "dark science", "psychology facts", "brain mystery",
            "curiosity", "strange facts", "shorts"
        ]
    ))[:15]

    question = clean_title + "?"

    return {
        "youtube": {
            "title": yt_title[:100],
            "description": f"{description}\n\nMind-bending dark psychology and science explained in 20 seconds.\n\n#shorts #science #psychology #curiosity",
            "tags": yt_tags,
        },
        "facebook": {
            "title": raw_title[:255],
            "description": f"{question}\n\n{description}\n\nFollow Mr-Nextep for daily psychological paradoxes and science mysteries. #Science #Psychology #HumanBehavior #Mystery",
        },
        "instagram": {
            # REMOVED #learnontiktok to avoid Meta algorithmic suppression
            # Replaced with high-engagement discovery tags
            "caption": f"{question}\n\n{description}\n\nSave this for later.\n\n#reels #darkpsychology #psychologyfacts #sciencereels #mindblowing #mysteryfacts",
        },
    }
