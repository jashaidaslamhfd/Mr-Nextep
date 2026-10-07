from __future__ import annotations

from typing import Any

from .utils import generate_us_hashtag_sets, us_title_for_short


def build_packages(script: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_title = str(script.get("title", "Dark Science Explained")).strip()
    description = str(script.get("description", "")).strip()
    tags = [str(tag).strip().lower() for tag in script.get("tags", []) if str(tag).strip()]

    # Keep the core metadata US-English and platform-specific without artificial
    # location stuffing. Geography should come from the actual audience/topic fit.
    yt_title = us_title_for_short(raw_title, max_chars=50)
    tag_sets = generate_us_hashtag_sets(raw_title, tags, max_total=8)

    youtube_tags = tag_sets.get("youtube_tags", []) or ["#Shorts"]
    yt_description = description
    if youtube_tags:
        yt_description += "\n\n" + " ".join(youtube_tags)

    # Meta gets a shorter, native caption: strong first line, useful context,
    # and only topic-relevant hashtags. No fake urgency or engagement bait.
    meta_hashtags = tag_sets.get("meta_tags", [])
    instagram_hashtags = ["#Reels"] + [
        t for t in meta_hashtags if t.lower() != "#reels"
    ]
    instagram_hashtags = instagram_hashtags[:8]
    facebook_hashtags = " ".join(meta_hashtags[:5])

    return {
        "youtube": {
            "title": yt_title,
            "description": yt_description[:5000],
            "tags": [t.lstrip("#") for t in youtube_tags],
        },
        "facebook": {
            "title": raw_title[:255],
            "description": (
                description
                + ("\n\n" + facebook_hashtags if facebook_hashtags else "")
            )[:3000],
            "tags": [t.lstrip("#") for t in meta_hashtags],
        },
        "instagram": {
            "caption": description[:2200],
            "hashtags": instagram_hashtags,
        },
    }
