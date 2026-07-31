"""
src/platform_captions.py — one caption per platform, written for that
platform's ranking system.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Dict, List, Sequence

from algorithm_policy import (
    FACEBOOK,
    INSTAGRAM,
    YOUTUBE,
    caption_limits,
    contains_bait,
    enforce_hashtag_limit,
    strip_bait,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


_YT_CLOSERS = (
    "Subscribe for a new body-science Short every day.",
    "Subscribe — one strange thing your body does, explained daily.",
    "Follow for short, accurate science with no hype.",
    "Follow along for the everyday biology nobody explains.",
    "Subscribe for more of what your body does and why.",
)

_META_CLOSERS = (
    "Follow for daily body science.",
    "Follow for more everyday biology, explained simply.",
    "Follow along — one body mystery a day.",
    "Follow for daily science about the body you live in.",
)


def _clean(text: object, limit: int = 400) -> str:
    """Normalise whitespace and remove legacy formatting."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = re.sub(r"#[A-Za-z0-9_]+", "", value)
    value = re.sub(r"[━═─]{3,}", " ", value)
    return re.sub(r"\s+", " ", value).strip(" .,;:")[:limit]


def _sentence(text: str) -> str:
    """Ensure a caption line ends as a complete sentence."""
    value = (text or "").strip()

    if value and value[-1] not in ".!?…":
        value += "."

    return value


_YOUTUBE_ONLY_TAGS = {
    "shorts",
    "short",
    "youtubeshorts",
    "ytshorts",
    "youtube",
}


def _pick(options: Sequence[str], seed_text: str) -> str:
    digest = hashlib.sha256(
        (seed_text or "x").encode("utf-8")
    ).hexdigest()[:8]

    return options[int(digest, 16) % len(options)]


def _keywords(
    script_data: Dict,
    tags: Sequence[str],
    limit: int = 4,
) -> List[str]:
    """Return readable keywords instead of hashtag stuffing."""
    stop = {
        "shorts",
        "short",
        "viral",
        "fyp",
        "reels",
        "trending",
        "video",
        "youtube",
    }

    seen = set()
    output = []

    for raw in tags:
        tag = re.sub(
            r"[^a-z0-9 ]",
            "",
            str(raw).lower().replace("_", " "),
        ).strip()

        if not tag:
            continue

        if tag in stop:
            continue

        if tag in seen:
            continue

        if len(tag) < 4:
            continue

        seen.add(tag)
        output.append(tag)

        if len(output) >= limit:
            break

    return output


def _meta_tags(tags: Sequence[str]) -> List[str]:
    """Return Meta hashtags without YouTube-only tags."""
    output = []

    for tag in tags:
        clean_tag = re.sub(
            r"[^a-z0-9]",
            "",
            str(tag).lower(),
        )

        if clean_tag in _YOUTUBE_ONLY_TAGS:
            continue

        output.append(f"#{tag}")

    return output


def _hook_and_summary(script_data: Dict) -> tuple[str, str]:
    hook = _clean(script_data.get("hook"), 180)

    summary = _clean(
        script_data.get("summary")
        or script_data.get("description"),
        400,
    )

    if (
        summary
        and hook
        and (
            summary.lower() in hook.lower()
            or hook.lower() in summary.lower()
        )
    ):
        summary = ""

    return hook, summary


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

def build_youtube_description(
    script_data: Dict,
    tags: Sequence[str],
) -> str:
    """Build a YouTube Shorts search-oriented description."""
    limits = caption_limits(YOUTUBE)
    hook, summary = _hook_and_summary(script_data)

    parts: List[str] = []

    if hook:
        parts.append(_sentence(hook))

    if summary:
        parts.append(_sentence(summary))

    keywords = _keywords(script_data, tags)

    if keywords:
        readable = ", ".join(keywords)
        closer = _pick(
            _YT_CLOSERS,
            script_data.get("topic") or readable,
        )

        parts.append(
            f"Learn the science behind {readable}. {closer}"
        )

    hashtags = enforce_hashtag_limit(
        [
            "#Shorts",
            *[
                "#"
                + re.sub(
                    r"[^A-Za-z0-9]",
                    "",
                    str(tag).title().replace(" ", ""),
                )
                for tag in tags
            ],
        ],
        YOUTUBE,
    )

    if hashtags:
        parts.append(" ".join(hashtags))

    description = strip_bait(
        "\n\n".join(
            part for part in parts if part
        ),
        YOUTUBE,
    )

    return description[: limits["total_chars"]]


# ---------------------------------------------------------------------------
# Facebook
# ---------------------------------------------------------------------------

def build_facebook_caption(
    script_data: Dict,
    tags: Sequence[str],
) -> str:
    """Build a Facebook-native Reel caption."""
    limits = caption_limits(FACEBOOK)
    hook, summary = _hook_and_summary(script_data)

    parts: List[str] = []

    if hook:
        parts.append(_sentence(hook))

    if summary:
        parts.append(_sentence(summary))

    closer = _pick(
        _META_CLOSERS,
        script_data.get("topic") or hook,
    )

    if closer.lower() not in " ".join(parts).lower():
        parts.append(closer)

    hashtags = enforce_hashtag_limit(
        _meta_tags(tags),
        FACEBOOK,
    )

    if hashtags:
        parts.append(" ".join(hashtags))

    caption = strip_bait(
        "\n\n".join(
            part for part in parts if part
        ),
        FACEBOOK,
    )

    return caption[: limits["total_chars"]]


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

def build_instagram_caption(
    script_data: Dict,
    tags: Sequence[str],
) -> str:
    """Build an Instagram-native, keyword-searchable caption."""
    limits = caption_limits(INSTAGRAM)
    hook, summary = _hook_and_summary(script_data)

    first_line = (
        hook
        or summary
        or ""
    ).strip()

    if len(first_line) > limits["first_line_chars"]:
        first_line = (
            first_line[
                : limits["first_line_chars"]
            ]
            .rsplit(" ", 1)[0]
            .rstrip(",;:")
            + "…"
        )

    parts: List[str] = []

    if first_line:
        parts.append(_sentence(first_line))

    if (
        summary
        and summary.lower() not in first_line.lower()
    ):
        parts.append(_sentence(summary))

    keywords = _keywords(
        script_data,
        tags,
        limit=3,
    )

    if keywords:
        parts.append(
            "Body science explained: "
            + ", ".join(keywords)
            + "."
        )

    closer = _pick(
        _META_CLOSERS,
        (script_data.get("topic") or "") + "ig",
    )

    parts.append(closer)

    hashtags = enforce_hashtag_limit(
        _meta_tags(tags),
        INSTAGRAM,
    )

    if hashtags:
        parts.append(" ".join(hashtags))

    caption = strip_bait(
        "\n\n".join(
            part for part in parts if part
        ),
        INSTAGRAM,
    )

    return caption[: limits["total_chars"]]


# ---------------------------------------------------------------------------
# Pinned YouTube comment
# ---------------------------------------------------------------------------

def build_pinned_comment(script_data: Dict) -> str:
    """Build a genuine topic-specific YouTube comment."""
    topic = _clean(
        script_data.get("topic")
        or script_data.get("title")
        or "this",
        80,
    ).lower()

    # Avoid awkward strings such as:
    # "why why your body..."
    topic = re.sub(
        r"^why\s+",
        "",
        topic,
    ).strip()

    templates = (
        f"Has this ever happened to you with {topic}? "
        "I read every reply.",

        f"Curious — did you already know what causes "
        f"{topic}, or is it new to you?",

        f"What part of {topic} still doesn't make sense? "
        "I'll cover it next.",

        f"Which body question should I explain after {topic}?",
    )

    comment = _pick(
        templates,
        topic,
    )

    if contains_bait(comment):
        return ""

    return comment[:200]
