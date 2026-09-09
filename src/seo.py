from __future__ import annotations
from typing import Any

from .utils import generate_us_hashtag_sets, us_title_for_short

def build_packages(script: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_title = str(script.get("title", "Dark Science Explained")).strip()
    description = str(script.get("description", "")).strip()
    tags = [str(tag).strip().lower() for tag in script.get("tags", []) if str(tag).strip()]

    # US-focused title for Shorts (mobile-friendly under ~50 chars)
    yt_title = us_title_for_short(raw_title, max_chars=50)

    # Build US-focused hashtag clusters
    tag_sets = generate_us_hashtag_sets(raw_title, tags, max_total=8)

    # YouTube description: strong hook + search-friendly keywords
    # Keep first line compelling for Suggested/Watch Next; include keywords and location where appropriate.
    yt_description_hook = f"{description}\n\nWatch till the end for the quick solution — made for viewers in the USA."
    yt_description_tags = " ".join(tag_sets["youtube_tags"]) if tag_sets.get("youtube_tags") else "#Shorts"

    # Meta caption: strong first line before the cut, CTA, and mixed hashtag strategy
    first_line = raw_title.rstrip("?.!") + " — you won't believe this"
    cta = "\n\nTell us: did you know this? Comment below 👇 and share with someone in the US who needs to see this."
    meta_caption = first_line + "\n\n" + description + cta

    meta_hashtags = tag_sets.get("meta_tags", [])

    return {
        "youtube": {
            "title": yt_title,
            "description": (yt_description_hook + "\n\n" + yt_description_tags)[:5000],
            "tags": [t.lstrip('#') for t in tag_sets.get("youtube_tags", [])],
        },
        "facebook": {
            "title": raw_title[:255],
            "description": (description + "\n\nFollow for more US-focused short explainers.")[:3000],
        },
        "instagram": {
            "caption": (meta_caption)[:2200],
            "hashtags": meta_hashtags,
        },
    }
