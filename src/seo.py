from __future__ import annotations

from typing import Any

import re

from .utils import us_title_for_short


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
    "was", "were", "why", "how", "what", "when", "does", "into", "about", "have",
    "has", "can", "its", "not", "but", "they", "their", "then", "than", "just",
    "really", "very", "more", "most", "explained", "shorts", "video", "today",
    "learn", "discover", "watch", "here", "there",
}


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(?<!\w)#[A-Za-z0-9_]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \\n\\t-•")


def _keywords(script: dict[str, Any], title: str, description: str) -> list[str]:
    """Build grounded metadata keywords from the actual title, tags, and narration."""
    candidates: list[str] = []
    for tag in script.get("tags", []) if isinstance(script.get("tags", []), list) else []:
        value = _clean_text(tag).lower()
        if value and value not in _STOPWORDS and len(value) <= 40:
            candidates.append(value)

    source_text = " ".join([
        title,
        description,
        " ".join(
            str(scene.get("narration", ""))
            for scene in script.get("scenes", [])
            if isinstance(scene, dict)
        ),
        " ".join(
            str(scene.get("caption", ""))
            for scene in script.get("scenes", [])
            if isinstance(scene, dict)
        ),
    ])
    for phrase in re.findall(r"[A-Za-z][A-Za-z0-9'-]*(?:\s+[A-Za-z][A-Za-z0-9'-]*){0,2}", source_text):
        phrase = re.sub(r"\s+", " ", phrase).strip(" '-").lower()
        words = phrase.split()
        if not phrase or len(phrase) > 42 or all(w in _STOPWORDS for w in words):
            continue
        if len(words) == 1 and (len(phrase) < 4 or phrase in _STOPWORDS):
            continue
        candidates.append(phrase)

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = re.sub(r"[^a-z0-9 ]", "", candidate.lower()).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        if not normalized or normalized in seen or normalized in _STOPWORDS:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= 18:
            break
    return result


def _hashtags(keywords: list[str], limit: int) -> list[str]:
    """Convert relevant, grounded keywords into short, readable topic hashtags."""
    out: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        words = re.findall(r"[a-z0-9]+", keyword.lower())
        if not words:
            continue
        # Hashtags should stay readable and avoid long keyword-stuffed compounds.
        tag = "".join(words[:3])
        if len(tag) < 4 or len(tag) > 26 or tag in _STOPWORDS or tag in seen:
            continue
        seen.add(tag)
        out.append("#" + tag)
        if len(out) >= limit:
            break
    return out


def _base_description(script: dict[str, Any], title: str) -> str:
    description = _clean_text(script.get("description", ""))
    if len(description) >= 35:
        return description
    narration = " ".join(
        str(scene.get("narration", "")).strip()
        for scene in script.get("scenes", [])
        if isinstance(scene, dict) and str(scene.get("narration", "")).strip()
    )
    if narration:
        # Prefer an actual explanation from the script, not generic SEO boilerplate.
        sentences = re.split(r"(?<=[.!?])\s+", narration)
        summary = " ".join(sentences[:2]).strip()
        return f"{title.rstrip('.!?')}. {summary}".strip()
    return title.rstrip(".!?") + ". A short, evidence-aware look at the idea behind this video."


def build_packages(script: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Create separate, topic-grounded metadata for YouTube, Facebook, and Instagram.

    Ranking systems are not identical or fully public. This packages clear topic signals
    and readable copy without promising algorithmic boosts or stuffing unrelated hashtags.
    """
    raw_title = _clean_text(script.get("title", "Dark Science Explained")) or "Dark Science Explained"
    yt_title = us_title_for_short(raw_title, max_chars=50)
    base_description = _base_description(script, raw_title)
    keywords = _keywords(script, raw_title, base_description)
    youtube_tags = keywords[:15]
    meta_hashtags = _hashtags(keywords, 5)
    yt_hashtags = _hashtags(keywords, 2)
    yt_hashtags = ["#Shorts"] + [tag for tag in yt_hashtags if tag.lower() != "#shorts"]
    instagram_hashtags = _hashtags(keywords, 5)
    if not instagram_hashtags:
        instagram_hashtags = ["#psychology", "#science"]

    # Put the subject and useful context first; hashtags are a small finishing detail.
    yt_description = base_description
    if yt_hashtags:
        yt_description += "\\n\\n" + " ".join(yt_hashtags)

    # Facebook copy is conversational and self-contained; avoid stuffing tags into prose.
    fb_description = base_description
    if meta_hashtags:
        fb_description += "\\n\\n" + " ".join(meta_hashtags[:4])

    # Instagram captions lead with the topic, add a brief contextual line, then relevant tags.
    ig_caption = base_description
    if len(ig_caption) > 1700:
        ig_caption = ig_caption[:1697].rsplit(" ", 1)[0].rstrip(".,;:") + "…"

    return {
        "youtube": {
            "title": yt_title,
            "description": yt_description[:5000],
            "tags": youtube_tags,
        },
        "facebook": {
            "title": raw_title[:255],
            "description": fb_description[:3000],
            "tags": [tag.lstrip("#") for tag in meta_hashtags],
        },
        "instagram": {
            "caption": ig_caption[:2200],
            "hashtags": instagram_hashtags,
        },
    }
