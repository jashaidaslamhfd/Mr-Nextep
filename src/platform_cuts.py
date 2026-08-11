"""
src/platform_cuts.py — build a per-platform edit instead of one compromise cut.

THE PROBLEM
-----------
One 40-55s video was being published to all three platforms. In 2026 those
platforms grade completion on different curves:

  YouTube Shorts   ~50% average-view-percentage for a 30-60s Short
  Facebook Reels   ~72% watch-through is where distribution widens (15-45s)
  Instagram Reels  first 3s decides; short Reels rewatched beat long ones

A single 47s cut therefore failed two of the three gates by construction, and
the channel's own Meta numbers proved it: measured average watch time on
Instagram was 2.6-7.5 seconds against a 47s clip — 5-16% completion, when the
bar is ~70%. No hook rewrite fixes a length mismatch that large.

THE FIX
-------
Generate ONE script and ONE set of assets, then assemble two edits:

  master cut  -> YouTube, policy-ideal ~36s, the full 8-beat arc
  meta cut    -> Facebook + Instagram, ~27s, the same arc with the
                 lowest-information middle scenes dropped

Because both cuts come from the same per-scene audio and images, the second
edit costs a render, not a second generation — no extra LLM calls, no extra
image credits, and no risk of the two versions telling different stories.

WHY DROP SCENES INSTEAD OF SPEEDING UP
--------------------------------------
Speeding narration to fit is the obvious shortcut and it is the wrong one: it
degrades the voice, breaks caption pacing, and viewers hear "AI slop", which
is precisely the perception both platforms' 2026 policies punish. Dropping a
whole scene keeps every remaining second natural and keeps sentences intact,
because every scene boundary is already a sentence boundary.

SCENE PRIORITY (what survives the cut)
--------------------------------------
protected   scene 1  HOOK        the promise; nothing works without it
protected   scene 2  SUSPENSE    the open question that stops the swipe
protected   last-1   PAYOFF      the answer; dropping it makes the video a lie
protected   last     LOOP-BACK   echoes the hook, earns the replay
droppable   middle scenes, weakest information density first
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Sequence, Tuple

from algorithm_policy import FACEBOOK, INSTAGRAM, YOUTUBE, duration_policy

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Words that signal an explanatory payload rather than filler. A scene using
# them is carrying mechanism — the part that makes the video worth watching —
# so it is dropped last.
_INFORMATION_MARKERS = (
    "because", "which", "signal", "nerve", "muscle", "brain", "blood",
    "pressure", "oxygen", "cells", "receptor", "reflex", "chemical",
    "hormone", "fluid", "pathway", "response", "system", "trigger",
)

# Connective/filler openings that add rhythm but almost no information. A
# scene starting with these is the cheapest thing to lose.
_FILLER_OPENERS = (
    "and ", "so ", "but ", "then ", "also ", "that's why", "in other words",
    "basically", "of course", "it turns out",
)


def _scene_value(caption: str) -> float:
    """Rough information density of one scene, 0..1.

    Deliberately simple and deterministic: this decides which sentence a
    viewer loses, so it must be explainable and reproducible in tests, not a
    black box. Density = how much mechanism the sentence carries, minus a
    penalty for being pure connective tissue.
    """
    text = (caption or "").strip().lower()
    if not text:
        return 0.0
    words = text.split()
    markers = sum(1 for marker in _INFORMATION_MARKERS if marker in text)
    score = min(markers / 3.0, 1.0) * 0.7
    # A sentence with a number or a comparison is usually the concrete beat.
    if re.search(r"\d", text):
        score += 0.15
    # Reasonable length means a complete thought, not a fragment.
    if 8 <= len(words) <= 18:
        score += 0.15
    if any(text.startswith(opener) for opener in _FILLER_OPENERS):
        score -= 0.25
    return max(0.0, min(score, 1.0))


def select_meta_cut(
    scenes: Sequence[Dict],
    audio_segments: Sequence[Dict],
    target_seconds: float | None = None,
    hard_ceiling: float | None = None,
) -> List[int]:
    """Indices of the scenes that make up the Meta (FB/IG) cut.

    Returns them in playback order. The four structural beats are always kept;
    middle scenes are dropped cheapest-first until the cut fits under the
    ceiling, and then re-added while there is room, so the result is the
    longest edit that still clears the gate rather than the shortest possible.
    """
    count = len(scenes)
    if count != len(audio_segments):
        raise ValueError("scenes and audio_segments must be the same length")
    if count == 0:
        return []

    floor, ideal, ceiling = duration_policy(INSTAGRAM)
    fb_floor, _fb_ideal, fb_ceiling = duration_policy(FACEBOOK)
    # The Meta cut serves both networks, so it must satisfy the tighter of the
    # two ceilings and the higher of the two floors.
    # META_TARGET_SECONDS lets the operator force a shorter Meta cut than the
    # policy ideal. Measured Meta completion is 19-24% vs a 70%+ gate with a
    # ~23s cut and 2.6-7.5s avg watch — a shorter cut raises completion% for
    # free (completion = watch_time / total). Default to the policy ideal.
    import os as _os
    try:
        _override = float(_os.environ.get("META_TARGET_SECONDS", "") or 0)
    except ValueError:
        _override = 0.0
    target = float(
        target_seconds if target_seconds is not None
        else (_override if _override > 0 else ideal)
    )
    limit = float(hard_ceiling if hard_ceiling is not None else min(ceiling, fb_ceiling))
    minimum = max(floor, fb_floor)

    durations = [float(seg.get("duration", 0.0)) for seg in audio_segments]
    total = sum(durations)
    if total <= limit:
        return list(range(count))

    if count <= 4:
        # Too short to prune structurally; keep everything and let the caller
        # decide. Never mangle a video that is already minimal.
        return list(range(count))

    protected = {0, 1, count - 2, count - 1}
    keep = set(protected)
    kept_duration = sum(durations[i] for i in sorted(keep))

    # Middle scenes, best information first.
    middle = [i for i in range(count) if i not in protected]
    middle.sort(key=lambda i: (-_scene_value(scenes[i].get("caption", "")), durations[i]))

    # Fill toward the TARGET, not the ceiling.
    #
    # The first version of this filled greedily up to the hard ceiling, which
    # produced 29.4s cuts against a 26s target — technically legal, but it
    # gives away the entire point of cutting. Completion is a percentage, so
    # every second added raises the number of seconds a viewer must watch to
    # clear the same gate. A scene is only worth its runtime if it still fits
    # the target; the ceiling is a limit, not a goal.
    for index in middle:
        if kept_duration + durations[index] <= target:
            keep.add(index)
            kept_duration += durations[index]

    # Under the floor: a Reel too short to carry the arc is worse than one a
    # few seconds over the target, so scenes come back until it is viable.
    if kept_duration < minimum:
        for index in middle:
            if index in keep:
                continue
            if kept_duration + durations[index] > limit:
                continue
            keep.add(index)
            kept_duration += durations[index]
            if kept_duration >= minimum:
                break

    ordered = sorted(keep)
    logger.info(
        "Meta cut: %d/%d scenes, %.1fs (target %.0fs, ceiling %.0fs) — dropped scene(s) %s",
        len(ordered), count, kept_duration, target, limit,
        [i + 1 for i in range(count) if i not in keep] or "none",
    )
    return ordered


def apply_cut(
    indices: Sequence[int],
    image_paths: Sequence[str],
    audio_segments: Sequence[Dict],
    scenes: Sequence[Dict],
    media_types: Sequence[str] | None = None,
) -> Tuple[List[str], List[Dict], List[Dict], List[str]]:
    """Slice every parallel asset list with one index set.

    Keeping this in a single helper is the point: the four lists MUST stay
    aligned or build_video silently renders the wrong image over the wrong
    sentence, and that class of bug is invisible until someone watches the
    finished video.
    """
    media_types = list(media_types or ["image"] * len(image_paths))
    return (
        [image_paths[i] for i in indices],
        [audio_segments[i] for i in indices],
        [scenes[i] for i in indices],
        [media_types[i] for i in indices],
    )


def cut_summary(indices: Sequence[int], audio_segments: Sequence[Dict], total_scenes: int) -> Dict:
    """Machine-readable description of a cut, stored in video history so the
    growth engine knows which edit each platform actually received.

    Both index bases are reported, and the key names say which is which.
    The first version of this returned 0-based `scene_indices` next to
    1-based `dropped_scenes`, which produced output like
    `indices [0,1,3,4,6,7] / dropped [3,6]` — where "3" appears in both and
    means two different scenes. Anyone debugging a bad cut from that data
    would reach the wrong conclusion.
    """
    kept = set(indices)
    seconds = sum(float(audio_segments[i].get("duration", 0.0)) for i in indices)
    return {
        "kept_indices_0based": list(indices),
        "dropped_indices_0based": [i for i in range(total_scenes) if i not in kept],
        # Human-facing scene numbers, matching how the script prompt and the
        # logs talk about "scene 1 = the hook".
        "dropped_scene_numbers": [i + 1 for i in range(total_scenes) if i not in kept],
        "scene_count": len(indices),
        "total_scenes": total_scenes,
        "seconds": round(seconds, 2),
    }


def fits_platform(seconds: float, platform: str) -> Tuple[bool, str]:
    """Check a rendered duration against that platform's policy window."""
    floor, ideal, ceiling = duration_policy(platform)
    if seconds > ceiling:
        return False, (
            f"{seconds:.1f}s exceeds the {ceiling:.0f}s ceiling — completion rate "
            f"will fall under the gate (ideal {ideal:.0f}s)."
        )
    if seconds < floor:
        return False, (
            f"{seconds:.1f}s is under the {floor:.0f}s floor — too little runtime to "
            "land the arc or register a meaningful watch."
        )
    return True, f"{seconds:.1f}s is inside the {floor:.0f}-{ceiling:.0f}s window."


def master_target() -> Tuple[float, float, float]:
    """Duration window for the YouTube master cut."""
    return duration_policy(YOUTUBE)
