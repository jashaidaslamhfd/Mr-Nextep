from __future__ import annotations
from typing import Any


def build_packages(script: dict[str, Any]) -> dict[str, dict[str, Any]]:
    title = str(script.get("title", "Dark Science Explained")).strip()
    description = str(script.get("description", "")).strip()
    tags = [str(tag).strip().lower() for tag in script.get("tags", []) if str(tag).strip()]
    question = title.rstrip("?.!") + "?"
    return {
        "youtube": {
            "title": title[:100],
            "description": f"{description}\n\nWhat do you think? Subscribe for more dark science and psychology Shorts.\n\n#shorts #science #psychology",
            "tags": list(dict.fromkeys(tags + ["youtube shorts", "science explained", "psychology facts"]))[:15],
        },
        "facebook": {
            "title": title[:255],
            "description": f"{question}\n\n{description}\n\nFollow Mr-Nextep for more science mysteries. #Science #Psychology #HumanBehavior",
        },
        "instagram": {
            "caption": f"{question}\n\n{description}\n\n#reels #science #psychology #mindblown #learnontiktok",
        },
    }
