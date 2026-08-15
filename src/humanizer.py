"""Humanizer — natural variation layer for a faceless channel.

Every feed (2026 and beyond) penalises *repetitive, template-y, obviously
machine-made* output, and viewers swipe away when the same words / same visual
style / same hashtag set show up again and again. This module adds *seeded,
deterministic natural variation* so the channel reads as one consistent human
creator rather than a pipeline:

  * a topic always maps to the same choice (so it's consistent, not random),
  * but different topics get different phrasing, style, order and pacing,
  * so no two videos look or read identical.

Everything is pure + offline + testable. The seed is derived from the topic
text, so results are reproducible run-to-run.
"""

from __future__ import annotations

import hashlib
import re


def seed_for(value: str) -> int:
    """Deterministic 32-bit seed from a string (topic/title)."""
    return int(hashlib.sha256((value or "x").encode("utf-8")).hexdigest()[:8], 16)


def pick(pool: list, value: str) -> str:
    """Stable pick from a pool using a string seed (no random module)."""
    if not pool:
        return ""
    return pool[seed_for(value) % len(pool)]


def pick_n(pool: list, value: str, n: int) -> list:
    """Stable, ordered subset of `n` items from `pool`, seeded by value.

    Order is shuffled by the seed too, so the chosen items also appear in a
    different order for different topics (identical ordering is a tell).
    """
    if not pool:
        return []
    idx = seed_for(value)
    items = list(pool)
    # deterministic shuffle
    for i in range(len(items) - 1, 0, -1):
        j = (idx >> (i % 24)) % (i + 1)
        items[i], items[j] = items[j], items[i]
    return items[: max(0, n)]


# --------------------------------------------------------------------------- #
# Visual style rotation — so scene images don't all share one identical look.
# --------------------------------------------------------------------------- #

# 2026-08-15 CHANNEL SIGNATURE — "Neon Cortex" (replaces the generic
# cinematic styles that any channel on YouTube can produce). Fixed identity
# anchors (midnight cobalt/violet palette, neural circuitry glow, noir
# contrast) with per-video variation seeded by the topic, so the channel is
# instantly recognizable and no two videos look identical.
VISUAL_STYLES = [
    # 1: midnight neural — the signature look
    "midnight cobalt and deep violet palette, glowing neural circuitry lines "
    "tracing anatomy, high-contrast noir mystery lighting, one strong key "
    "light, dark cinematic documentary, hyper-detailed realistic rendering",
    # 2: laboratory noir — the clinical discovery shot
    "sterile midnight laboratory, cold teal scan-lines over anatomy, sharp "
    "forensic clarity, dramatic single-beam lighting, film-noir documentary "
    "still, hyper-detailed realistic detail",
    # 3: living luminescence — the inside-the-body shot
    "soft bioluminescent inner glow under dark indigo skin, translucent "
    "tissue depth, ember-gold core highlights, cinematic macro realism, "
    "premium documentary photography",
    # 4: synapse storm — the brain/mind shot
    "dark indigo-violet neural storm, synapse spark trails, electric teal "
    "accents, high-contrast noir depth, hyper-detailed scientific rendering",
    # 5: dawn revelation — the calm payoff shot
    "soft dawn-grey window light meeting deep navy shadow, calm scientific "
    "revelation atmosphere, clean premium editorial composition, tack-sharp "
    "realistic detail",
    # 6: specimen focus — the single-subject shot
    "heavy noir shadow weight, one specimen in crisp forensic spotlight, "
    "charcoal and steel palette, museum-of-nature stillness, hyper-detailed "
    "cinematic realism",
]

_VISUAL_TAIL = "vertical composition, no text, no watermark, not blurry, not dull"


def style_suffix(topic: str, first_frame: bool = False) -> str:
    """Pick a varied (but deterministic) visual style for the scene.

    Uses the topic as the seed so the same video keeps one cohesive style but
    different videos look different — a single fixed suffix on every image is
    what makes a whole channel look generated.
    """
    style = pick(VISUAL_STYLES, topic or "x")
    if first_frame:
        return f"{style}, {_VISUAL_TAIL}"
    return f"{style}, {_VISUAL_TAIL}"


# --------------------------------------------------------------------------- #
# Hashtag variation — no two videos should carry the identical tag set/order.
# --------------------------------------------------------------------------- #

def rotate_hashtags(tags: list, value: str, keep_top: int = 3, total: int = 8) -> list:
    """Return a stable, varied subset of `tags`.

    `keep_top` are always retained (they're the on-niche anchors); the rest are
    picked deterministically and returned in a seeded order so the set isn't
    byte-for-byte identical across videos while staying on-niche.
    """
    if not tags:
        return []
    ordered = list(tags)
    anchors = ordered[:keep_top]
    rest = ordered[keep_top:]
    chosen = pick_n(rest, value, max(0, total - keep_top))
    return anchors + chosen


# --------------------------------------------------------------------------- #
# Micro-phrasing variation — so titles/captions don't all start the same way.
# --------------------------------------------------------------------------- #

_OPENERS = [
    "Here's something your body does every day: ",
    "Most people never notice this, but ",
    "You've probably felt this before — ",
    "There's a weird fact about this: ",
    "Nobody talks about this, but ",
    "It turns out ",
    "Funny enough, ",
    "You might not realize it, but ",
]

_OPENERS_LITE = [
    "Here's the science: ",
    "The short version: ",
    "It comes down to this: ",
    "Quick breakdown: ",
    "Here's what's happening: ",
]


def opener(value: str, lite: bool = False) -> str:
    """A varied sentence opener for the first caption/description line."""
    pool = _OPENERS_LITE if lite else _OPENERS
    return pick(pool, value)


# --------------------------------------------------------------------------- #
# Natural tempo jitter — human speech is never exactly on-beat.
# --------------------------------------------------------------------------- #

def breath_pause(index: int, caption: str) -> float:
    """A natural between-scene pause (seconds) for the timeline builder.

    Humans take uneven breaths between thoughts: some transitions are tight
    (0.25s), some get a real beat (0.55s). A single fixed gap after every
    scene is a machine tell; a seeded per-transition value sounds like one
    person reading with normal rhythm. Kept small (<=0.55s) so the 24s master
    cut's total budget stays inside the retention gate.
    """
    seed = seed_for(f"{caption}::{index}")
    base = 0.25 + ((seed % 300) / 300.0) * 0.30  # 0.25 .. 0.55
    # occasional longer beat (~1 in 5) — a narrator thinking for a second
    if seed % 5 == 0:
        base = min(0.85, base + 0.30)
    return round(base, 2)


def tempo_jitter(base_tempo: float, value: str, spread: float = 0.04) -> float:
    """Deterministic tiny variation around a base tempo (±spread).

    A fixed tempo across every video sounds robotic; a stable per-video offset
    sounds like one person who reads slightly differently each time.
    """
    idx = seed_for(value)
    delta = ((idx % 200) - 100) / 100.0  # -1.0 .. 1.0
    return round(max(0.85, min(1.15, base_tempo + delta * spread)), 3)


# --------------------------------------------------------------------------- #
# Natural punctation/spacing micro-variation.
# --------------------------------------------------------------------------- #

def natural_ellipsis(value: str, seed: str) -> str:
    """Add a natural '...' pause at most once (humanlike trailing thought).

    Only when the line is long enough and never twice, so it never looks
    manufactured. Deterministic.
    """
    s = (value or "").strip()
    if len(s) < 25 or s.count("…") > 0:
        return s
    if seed_for(seed) % 3 != 0:  # only ~1/3 of lines get it
        return s
    # insert before the last word
    words = s.split(" ")
    if len(words) < 3:
        return s
    return " ".join(words[:-1]) + " … " + words[-1]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
