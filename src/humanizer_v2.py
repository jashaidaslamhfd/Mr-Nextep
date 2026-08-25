"""
src/humanizer_v2.py — Full Humanization Layer

Makes the ENTIRE pipeline appear human-created:
  - Upload timing: randomized within peak slots (not robotic)
  - Script language: casual, imperfect, human-like
  - Comments: sound like a real person, not a bot
  - Thumbnails: look hand-crafted, not AI-generated
  - Hashtags: organic, not stuffed
  - Captions: conversational, not formulaic

Viewer perception: "This is a real person who's passionate about body science."
"""

from __future__ import annotations

import hashlib
import random
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------

def _seed(text: str) -> int:
    return int(hashlib.sha256((text or "x").encode()).hexdigest()[:8], 16)


def _pick(pool: list, text: str) -> str:
    if not pool:
        return ""
    return pool[_seed(text) % len(pool)]


# ---------------------------------------------------------------------------
# 1. UPLOAD TIMING — Human-like randomization
# ---------------------------------------------------------------------------

def humanize_publish_time(slot_hour: int, slot_minute: int, topic: str) -> Tuple[int, int]:
    """Add ±5-15 minute jitter to publish time.
    
    Humans don't publish at EXACTLY the same minute every day.
    A channel posting at 13:30, 13:32, 13:28, 13:35 looks human.
    A channel posting at 13:30:00, 13:30:00, 13:30:00 looks bot.
    """
    jitter_range = 15  # ±15 minutes
    seed_val = _seed(topic + str(slot_hour))
    jitter = (seed_val % (jitter_range * 2 + 1)) - jitter_range
    
    total_minutes = slot_hour * 60 + slot_minute + jitter
    new_hour = (total_minutes // 60) % 24
    new_minute = total_minutes % 60
    
    return new_hour, new_minute


# ---------------------------------------------------------------------------
# 2. SCRIPT LANGUAGE — Remove AI patterns, add human imperfection
# ---------------------------------------------------------------------------

# AI-typical phrases to ELIMINATE
_AI_PATTERNS = [
    (r"\bdelve\b", "dig into"),
    (r"\buncover\b", "find"),
    (r"\bmeticulously\b", "carefully"),
    (r"\bpivotal\b", "key"),
    (r"\bparamount\b", "really important"),
    (r"\bsignificantly\b", "a lot"),
    (r"\bfurthermore\b", "plus"),
    (r"\bnevertheless\b", "but"),
    (r"\bconsequently\b", "so"),
    (r"\bserves to\b", "helps"),
    (r"\bresulting in\b", "which means"),
    (r"\bincreasingly\b", "more and more"),
    (r"\bremarkable\b", "crazy"),
    (r"\bfascinating\b", "wild"),
    (r"\bseamlessly\b", ""),
    (r"\brobust\b", "strong"),
    (r"\bcomprehensive\b", "full"),
    (r"\bleverage\b", "use"),
    (r"\boptimize\b", "improve"),
    (r"\benhance\b", "boost"),
    (r"\bfacilitate\b", "help"),
    (r"\bnever before seen\b", "crazy"),
    (r"\bin the realm of\b", "in"),
    (r"\bit is worth noting\b", ""),
    (r"\bwhat is particularly interesting\b", "what's wild"),
    (r"\bthis is particularly relevant\b", "this matters"),
    (r"\bthe reason for this\b", "why"),
    (r"\bin order to\b", "to"),
    (r"\bdue to the fact\b", "because"),
    (r"\bat this point in time\b", "now"),
    (r"\bprior to\b", "before"),
    (r"\bsubsequent to\b", "after"),
    (r"\bin the event\b", "if"),
    (r"\bwith regard to\b", "about"),
    (r"\bin addition to\b", "plus"),
    (r"\bat the end of the day\b", "really"),
]

# Human-like fillers/imperfections to ADD occasionally
_HUMAN_FILLERS = [
    "", "", "",  # most lines: no filler
    "Honestly, ",
    "Literally, ",
    "Okay so ",
    "So basically ",
    "Get this — ",
    "Wild fact — ",
    "Fun fact: ",
    "No joke, ",
    "I swear, ",
]

# Casual sentence starters (replaces AI-sounding ones)
_HUMAN_STARTERS = [
    "So ",
    "Okay so ",
    "Here's the thing — ",
    "Get this: ",
    "Turns out ",
    "Fun fact: ",
    "You know how ",
    "Ever wonder why ",
    "So apparently ",
    "Listen — ",
]


def humanize_script_language(text: str, topic: str = "") -> str:
    """Strip AI language patterns and add human imperfection.
    
    Viewers should read this and think "this person is passionate about
    body science" — not "this was written by ChatGPT."
    """
    if not text:
        return text
    
    result = text
    
    # Remove AI patterns
    for pattern, replacement in _AI_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # Clean up double spaces
    result = re.sub(r"  +", " ", result).strip()
    
    # Occasional human filler (1 in 5 sentences)
    seed_val = _seed(topic + result[:50])
    if seed_val % 5 == 0 and len(result.split(".")) > 1:
        sentences = result.split(". ")
        if sentences:
            filler = _pick(_HUMAN_FILLERS, topic + result[:20])
            sentences[0] = filler + sentences[0]
            result = ". ".join(sentences)
    
    return result


# ---------------------------------------------------------------------------
# 3. CAPTION STYLE — Conversational, not formulaic
# ---------------------------------------------------------------------------

# Instagram captions should feel like a friend texting you, not a press release
_IG_CASUAL_OPENERS = [
    "okay wait — ",
    "so apparently ",
    "y'all need to know this — ",
    "this is wild — ",
    "no one talks about this but ",
    "your body does something crazy and ",
    "listen — ",
    "real talk: ",
]

_IG_CASUAL_CLOSERS = [
    "follow for more body facts 🧬",
    "your body is insane. follow for more.",
    "this blew my mind. follow for daily facts.",
    "more body science daily — follow ✨",
    "body facts that'll make you say 'wait what' — follow",
    "your body is wilder than you think. follow 🧬",
    "daily body facts — follow if this surprised you",
    "more weird body facts incoming — follow 🧠",
]


def humanize_instagram_caption(caption: str, topic: str = "") -> str:
    """Make Instagram captions sound like a friend texting, not a bot posting.
    
    IG's algorithm rewards sends (DMs). Friends text in casual language.
    Formal captions don't get forwarded.
    """
    if not caption:
        return caption
    
    lines = caption.split("\n\n")
    if not lines:
        return caption
    
    # First line: casual opener
    seed_val = _seed(topic)
    if seed_val % 3 == 0:  # 1/3 get opener
        opener = _pick(_IG_CASUAL_OPENERS, topic)
        lines[0] = opener + lines[0].lstrip()
    
    # Last line: casual closer (if not already a hashtag block)
    if lines and not lines[-1].startswith("#"):
        closer = _pick(_IG_CASUAL_CLOSERS, topic)
        lines[-1] = lines[-1] + "\n\n" + closer
    
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# 4. PINNED COMMENT — Sound like a real person, not a template
# ---------------------------------------------------------------------------

# Comments that sound like a real creator engaging with their audience
_HUMAN_COMMENTS = [
    "who else gets this?? drop a 🧬 if your body does this too",
    "be honest — did you know this before watching? i had no idea until i researched it",
    "i literally Googled this for 3 hours after discovering it. your body is UNREAL",
    "my DMs are full of people asking about this one. here's the full answer 🧬",
    "the fact that most doctors don't explain this to patients is criminal",
    "if this video made you say 'wait WHAT' — wait until tomorrow's Short 😂",
    "i've gotten 47 messages about this topic. here's what the science actually says",
    "my girlfriend didn't believe me until she saw the study. now she tells everyone 😂",
    "this is the video i wish someone had made when i was in school",
    "reply with your weirdest body fact — i'll make a video about the best ones",
    "some of you DM'd me asking for part 2... so here it is 🧬",
    "i'm reading every single comment on this one. what surprised you the most?",
    "not me going down a rabbit hole at 3am making this video for you guys 😂",
    "tag someone who needs to hear this. their body is doing this RIGHT NOW",
]


def humanize_pinned_comment(topic: str = "") -> str:
    """Generate a comment that sounds like a real creator engaging.
    
    NOT a bot. NOT a template. A real person who's passionate about body
    science and loves interacting with their audience.
    """
    comment = _pick(_HUMAN_COMMENTS, topic)
    
    # Vary the emoji (sometimes no emoji)
    if _seed(topic) % 3 == 0:
        comment = comment.replace("🧬", "").replace("😂", "").strip()
    
    return comment


# ---------------------------------------------------------------------------
# 5. HASHTAG ORGANICITY — Not stuffed, not identical
# ---------------------------------------------------------------------------

def humanize_hashtag_count(tags: List[str], platform: str = "instagram") -> List[str]:
    """Vary hashtag count organically.
    
    Real creators don't use exactly 30 hashtags every post.
    Sometimes 5, sometimes 12, sometimes 3.
    Varies by topic and platform.
    """
    seed_val = _seed(platform)
    
    if platform == "instagram":
        # Real IG creators: 5-15 hashtags, usually 8-12
        target_count = 5 + (seed_val % 11)
    elif platform == "youtube":
        # YT Shorts: 3-8 hashtags
        target_count = 3 + (seed_val % 6)
    elif platform == "facebook":
        # FB Reels: 2-5 hashtags (FB penalizes >5)
        target_count = 2 + (seed_val % 4)
    else:
        target_count = len(tags)
    
    return tags[:target_count]


# ---------------------------------------------------------------------------
# 6. THUMBNAIL STYLE — Look hand-crafted, not AI-generated
# ---------------------------------------------------------------------------

def humanize_thumbnail_prompt(prompt: str, topic: str = "") -> str:
    """Add imperfection to thumbnail prompts.
    
    Real thumbnails have:
    - Slight imperfection (not perfectly symmetrical)
    - Human-like color choices (not "AI blue")
    - Emotional weight (not clinical precision)
    """
    # Add subtle imperfection keywords
    imperfections = [
        "slightly off-center composition",
        "natural lighting, not studio-perfect",
        "hand-drawn feel, not photorealistic",
        "organic texture, not synthetic smooth",
        "real-world imperfection, not AI-clean",
    ]
    
    suffix = _pick(imperfections, topic)
    
    # Remove any "AI-generated" or "synthetic" keywords from prompt
    cleaned = re.sub(r"\b(AI[- ]generated|synthetic|digital art|concept art)\b", "", prompt, flags=re.IGNORECASE)
    cleaned = re.sub(r"  +", " ", cleaned).strip()
    
    return f"{cleaned}, {suffix}"


# ---------------------------------------------------------------------------
# 7. DESCRIPTION STYLE — Not formulaic
# ---------------------------------------------------------------------------

def humanize_description(desc: str, topic: str = "") -> str:
    """Make descriptions feel like a person wrote them, not a template.
    
    Remove formulaic patterns:
    - Don't start every description the same way
    - Don't use the same CTA structure
    - Add occasional personality
    """
    if not desc:
        return desc
    
    # Remove "Learn the science behind X" pattern (too templated)
    desc = re.sub(
        r"Learn the science behind [^.]+\.",
        lambda m: _pick([
            f"Here's what's happening with {m.group().split('behind ')[-1].split('.')[0]}.",
            f"This one's wild — {m.group().split('behind ')[-1].split('.')[0]}.",
            f"Ever wonder about {m.group().split('behind ')[-1].split('.')[0]}?",
        ], topic),
        desc
    )
    
    return desc


# ---------------------------------------------------------------------------
# PUBLIC API — Apply all humanization at once
# ---------------------------------------------------------------------------

def humanize_all(script_data: Dict, platform: str = "youtube") -> Dict:
    """Apply full humanization to script data.
    
    Call this BEFORE upload to make everything appear human-created.
    """
    topic = script_data.get("topic", "")
    
    # Humanize captions
    if "hook" in script_data:
        script_data["hook"] = humanize_script_language(
            script_data["hook"], topic
        )
    
    if "summary" in script_data:
        script_data["summary"] = humanize_script_language(
            script_data["summary"], topic
        )
    
    if "voiceover" in script_data:
        script_data["voiceover"] = humanize_script_language(
            script_data["voiceover"], topic
        )
    
    # Humanize pinned comment
    script_data["pinned_comment"] = humanize_pinned_comment(topic)
    
    # Humanize hashtags
    if "tags" in script_data:
        script_data["tags"] = humanize_hashtag_count(
            script_data["tags"], platform
        )
    
    # Platform-specific caption humanization
    if platform == "instagram":
        # Caption will be humanized by build_instagram_caption
        pass
    
    return script_data
