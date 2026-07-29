"""
src/platform_captions.py — one caption per platform, written for that
platform's ranking system.

WHY THIS IS NOT "COPY THE DESCRIPTION EVERYWHERE"
--------------------------------------------------
The three feeds read captions for completely different jobs:

  YouTube   Shorts now appear in YouTube search with their own carousel, and
            the title/description are how the topic gets matched. Keyword
            intent matters; 3-4 hashtags is the whole benefit, more is noise.

  Facebook  The UTIS model (Jan 2026) asks viewers whether a Reel matched
            their interests and trains on the answer. Plain, specific,
            interest-declaring language beats hype. Engagement bait is
            explicitly demoted, so nothing may ask for likes or shares.

  Instagram Captions are indexed for keyword search, the first line is what
            shows before "more", and sends-per-reach is the #2 ranking signal.
            The caption's job is to make the video feel worth forwarding —
            without ever saying "send this to a friend", which is bait.

Previously Instagram received Facebook's caption plus a YouTube pointer, so
Instagram's keyword surface and send framing were never addressed at all.

EVERY caption produced here is run through algorithm_policy.strip_bait, so a
banned ask cannot reach any platform even if a script slips one in.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Rotated closing lines. Byte-identical boilerplate across an entire channel
# is one of the clearest template-spam signals both platforms look for, so the
# closer is chosen deterministically from the topic — varied across the
# channel, stable for any single video (which keeps repair sweeps idempotent).
_YT_CLOSERS = (
    "Subscribe for a new body-science Short every day.",
    "Subscribe — one strange thing your body does, explained daily.",
    "Follow for short, accurate science with no hype.",
    "Follow along for the everyday biology nobody explains.",
    "Subscribe for more of what your body does and why.",
)
# Every Meta closer contains "Follow" on purpose. Since the spoken CTA was
# removed from the video (it cost ~8% of runtime on a signal that grades on
# completion), the caption is now the ONLY place the follow ask exists — so it
# cannot be optional. The rest of the sentence rotates so the channel is not
# shipping one byte-identical line on every post, which is a template-spam
# signal in its own right. "Follow" is not engagement bait on any of the three
# platforms; asking for likes, shares or comments is, and that stays banned.
_META_CLOSERS = (
    "Follow for daily body science.",
    "Follow for more everyday biology, explained simply.",
    "Follow along — one body mystery a day.",
    "Follow for daily science about the body you live in.",
)


def _clean(text: object, limit: int = 400) -> str:
    """Normalise whitespace and strip legacy formatting artefacts.

    Old descriptions in this repo carried divider characters and inline
    hashtags; feeding one back into a caption builder nested them and produced
    the duplicated blocks visible on the live channel.
    """
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = re.sub(r"#[A-Za-z0-9_]+", "", value)
    value = re.sub(r"[━═─]{3,}", " ", value)
    return re.sub(r"\s+", " ", value).strip(" .,;:")[:limit]


def _sentence(text: str) -> str:
    """Close a caption line properly.

    _clean deliberately strips trailing punctuation so fragments can be
    recombined, which left published captions ending mid-air ("...until the
    muscle resets"). A caption is read by humans first and parsed for topic
    relevance second; both want complete sentences.
    """
    value = (text or "").strip()
    if value and value[-1] not in ".!?…":
        value += "."
    return value


# Tags that exist purely for YouTube's Shorts shelf. On Facebook and Instagram
# they carry no discovery value and read as cross-posted filler — which is
# exactly the "unoriginal / aggregated" signal Meta's originality checks look
# for. Filtered out of Meta captions rather than being trimmed at random by
# the hashtag limit.
_YOUTUBE_ONLY_TAGS = {"shorts", "short", "youtubeshorts", "ytshorts", "youtube"}


def _pick(options: Sequence[str], seed_text: str) -> str:
    digest = hashlib.sha256((seed_text or "x").encode("utf-8")).hexdigest()[:8]
    return options[int(digest, 16) % len(options)]


def _keywords(script_data: Dict, tags: Sequence[str], limit: int = 4) -> List[str]:
    """Natural-language keywords for the caption body.

    Keyword-rich prose beats hashtag stuffing on all three platforms in 2026,
    so tags are rendered as readable words in a sentence rather than piled up
    at the bottom.
    """
    stop = {"shorts", "short", "viral", "fyp", "reels", "trending", "video", "youtube"}
    seen, out = set(), []
    for raw in tags:
        tag = re.sub(r"[^a-z0-9 ]", "", str(raw).lower().replace("_", " ")).strip()
        if not tag or tag in stop or tag in seen or len(tag) < 4:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= limit:
            break
    return out


def _meta_tags(tags: Sequence[str]) -> List[str]:
    """Hashtags for Facebook/Instagram, minus the YouTube-shelf tags.

    Leaving "#shorts" on a Reel is the small, visible tell of a cross-posted
    video, and Meta's 2026 originality checks specifically look for content
    that was clearly made for another platform. Removing them also frees the
    2-5 tag budget for niche keywords that actually aid discovery.
    """
    return [
        f"#{tag}" for tag in tags
        if re.sub(r"[^a-z0-9]", "", str(tag).lower()) not in _YOUTUBE_ONLY_TAGS
    ]


def _hook_and_summary(script_data: Dict) -> tuple[str, str]:
    hook = _clean(script_data.get("hook"), 180)
    summary = _clean(script_data.get("summary") or script_data.get("description"), 400)
    if summary and hook and (summary.lower() in hook.lower() or hook.lower() in summary.lower()):
        summary = ""
    return hook, summary


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

def build_youtube_description(script_data: Dict, tags: Sequence[str]) -> str:
    """Search-oriented description for the Shorts search carousel.

    Structure: promise -> answer -> keyword context -> hashtags. The first two
    lines are what YouTube shows in search results, so the actual topic has to
    be stated in plain words there, not teased.
    """
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
        closer = _pick(_YT_CLOSERS, script_data.get("topic") or readable)
        parts.append(f"Learn the science behind {readable}. {closer}")

    hashtags = enforce_hashtag_limit(
        ["#Shorts"] + [f"#{re.sub(r'[^A-Za-z0-9]', '', str(t).title().replace(' ', ''))}" for t in tags],
        YOUTUBE,
    )
    if hashtags:
        parts.append(" ".join(hashtags))

    description = strip_bait("\n\n".join(p for p in parts if p), YOUTUBE)
    return description[: limits["total_chars"]]


# ---------------------------------------------------------------------------
# Facebook
# ---------------------------------------------------------------------------

def build_facebook_caption(script_data: Dict, tags: Sequence[str]) -> str:
    """UTIS-friendly caption: state the interest plainly, then deliver.

    Meta's true-interest survey model rewards content whose subject is
    unmistakable to someone deciding "is this for me?". A vague teaser scores
    badly on relevance even when it scores well on watch time, so the topic is
    named in the first line rather than withheld.
    """
    limits = caption_limits(FACEBOOK)
    hook, summary = _hook_and_summary(script_data)
    parts: List[str] = []

    if hook:
        parts.append(_sentence(hook))
    if summary:
        parts.append(_sentence(summary))

    closer = _pick(_META_CLOSERS, script_data.get("topic") or hook)
    if closer.lower() not in " ".join(parts).lower():
        parts.append(closer)

    hashtags = enforce_hashtag_limit(_meta_tags(tags), FACEBOOK)
    if hashtags:
        parts.append(" ".join(hashtags))

    caption = strip_bait("\n\n".join(p for p in parts if p), FACEBOOK)
    return caption[: limits["total_chars"]]


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

def build_instagram_caption(script_data: Dict, tags: Sequence[str]) -> str:
    """Keyword-searchable caption whose payoff line is worth forwarding.

    Three deliberate choices:
    1. The first line is under the platform's truncation point, so the promise
       survives the "... more" fold.
    2. The body states the mechanism in plain words — Instagram indexes
       caption text for search, and niche keywords out-perform hashtags.
    3. It closes on the concrete fact, because a sendable Reel is one where
       the viewer can imagine a specific person who'd want to know this.
       We never write "send this to..." — that is bait and gets demoted.
    """
    limits = caption_limits(INSTAGRAM)
    hook, summary = _hook_and_summary(script_data)
    first_line = (hook or summary or "").strip()
    if len(first_line) > limits["first_line_chars"]:
        first_line = first_line[: limits["first_line_chars"]].rsplit(" ", 1)[0].rstrip(",;:") + "…"

    parts: List[str] = []
    if first_line:
        parts.append(_sentence(first_line))
    if summary and summary.lower() not in first_line.lower():
        parts.append(_sentence(summary))

    keywords = _keywords(script_data, tags, limit=3)
    if keywords:
        parts.append(f"Body science explained: {', '.join(keywords)}.")

    closer = _pick(_META_CLOSERS, (script_data.get("topic") or "") + "ig")
    parts.append(closer)

    hashtags = enforce_hashtag_limit(_meta_tags(tags), INSTAGRAM)
    if hashtags:
        parts.append(" ".join(hashtags))

    caption = strip_bait("\n\n".join(p for p in parts if p), INSTAGRAM)
    return caption[: limits["total_chars"]]


# ---------------------------------------------------------------------------
# Pinned comment (YouTube) — the one legitimate engagement lever
# ---------------------------------------------------------------------------

def build_pinned_comment(script_data: Dict) -> str:
    """A genuine question tied to THIS video's content.

    Comments are weighted above likes in YouTube's 2026 engagement re-ranking,
    and on a cold-start channel an empty comment section stays empty. Asking a
    specific, answerable question is the difference between a seed comment and
    engagement bait: bait demands an action ("comment YES"), a seed invites an
    experience ("has this happened to you at night?").
    """
    topic = _clean(script_data.get("topic") or script_data.get("title") or "this", 80).lower()
    templates = (
        f"Has this ever happened to you with {topic}? I read every reply.",
        f"Curious — did you already know why {topic} happens, or is this new?",
        f"What part of {topic} still doesn't make sense? I'll cover it next.",
        f"Which body question should I explain after {topic}?",
    )
    comment = _pick(templates, topic)
    return "" if contains_bait(comment) else comment[:200]
