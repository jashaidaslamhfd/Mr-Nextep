"""
src/safe_zones.py — keep text out from behind the platform UI.

THE PROBLEM
-----------
A 9:16 video is not a blank canvas. Each app draws its own chrome on top:

  bottom   caption, username, audio ticker, "Subscribe"/CTA button
  right    the like / comment / share / more column
  top      occasional "Reels" or "Shorts" label and a back arrow

Anything the pipeline renders underneath that chrome is invisible to viewers,
and the two places it matters most are the two places this repo was putting
text:

  * generate_thumbnail() drew the title between 84% and 97% down the frame —
    entirely inside every platform's bottom overlay. The thumbnail's job is to
    be legible in a feed at ~120x90 pixels; hiding the words behind the caption
    bar defeats it completely.
  * burned-in captions sit at 52% (fine), but nothing enforced that they
    stayed above the fold as the font auto-shrinks and blocks grow.

WHY ONE SHARED MODULE
---------------------
The insets differ per platform, but the SAME rendered file goes to all three.
So the usable area is the intersection: the tightest top inset, the tightest
bottom inset, the tightest right inset. Computing that in one place means the
thumbnail generator and the caption renderer can never disagree about where
"safe" is, and adding a fourth platform later is a single dict entry.

The numbers below are conservative measurements of each app's chrome as a
fraction of frame height/width. They are intentionally slightly generous:
being 2% too cautious costs nothing, being 2% too tight hides the payoff word.
"""

from __future__ import annotations

from typing import Dict, Iterable, Tuple

from algorithm_policy import FACEBOOK, INSTAGRAM, PLATFORMS, YOUTUBE

_PLATFORM_INSETS: Dict[str, Dict[str, float]] = {
    YOUTUBE: {"top": 0.06, "bottom": 0.18, "right": 0.13, "left": 0.04},
    # Instagram's caption block plus the audio ticker is the deepest of the
    # three, and it expands when a caption wraps to a second line.
    INSTAGRAM: {"top": 0.08, "bottom": 0.22, "right": 0.15, "left": 0.04},
    # Facebook adds a CTA button under the caption on Page reels.
    FACEBOOK: {"top": 0.07, "bottom": 0.25, "right": 0.14, "left": 0.04},
}


def insets(platforms: Iterable[str] | None = None) -> Dict[str, float]:
    """Worst-case insets across every platform that will receive the file.

    One render serves all three, so the safe area is the INTERSECTION of the
    three safe areas — i.e. the largest inset on each side.
    """
    selected = list(platforms) if platforms else list(PLATFORMS)
    known = [p for p in selected if p in _PLATFORM_INSETS] or list(PLATFORMS)
    return {
        side: max(_PLATFORM_INSETS[p][side] for p in known)
        for side in ("top", "bottom", "right", "left")
    }


def safe_box(width: int, height: int, platforms: Iterable[str] | None = None
             ) -> Tuple[int, int, int, int]:
    """Pixel box (left, top, right, bottom) that no platform UI covers."""
    pad = insets(platforms)
    return (
        int(width * pad["left"]),
        int(height * pad["top"]),
        int(width * (1.0 - pad["right"])),
        int(height * (1.0 - pad["bottom"])),
    )


def caption_baseline(height: int, platforms: Iterable[str] | None = None) -> int:
    """Lowest y-coordinate a caption's last line may reach.

    Captions are read while the video plays, so they should sit comfortably
    above the chrome rather than hugging it.
    """
    left, top, right, bottom = safe_box(1080, height, platforms)
    return int(bottom - height * 0.02)


def thumbnail_text_band(width: int, height: int,
                        platforms: Iterable[str] | None = None) -> Tuple[int, int]:
    """(top_y, bottom_y) band where thumbnail text belongs.

    Deliberately NOT flush against the bottom of the safe box. A thumbnail is
    judged at roughly 120x90 in a feed, where the eye lands slightly below
    centre; text placed in the lower-middle third reads as designed, while
    text pinned to the very bottom reads as an afterthought — and is the first
    thing to disappear behind a caption that wraps to an extra line.
    """
    _left, top, _right, bottom = safe_box(width, height, platforms)
    usable = bottom - top
    band_top = int(top + usable * 0.52)
    return band_top, int(bottom)


def safe_text_width(width: int, platforms: Iterable[str] | None = None) -> int:
    """Maximum text width that clears the action-button column."""
    left, _top, right, _bottom = safe_box(width, 1920, platforms)
    return max(200, right - left)


def describe(width: int = 1080, height: int = 1920) -> str:
    """Human-readable summary, used in logs and tests."""
    left, top, right, bottom = safe_box(width, height)
    return (
        f"Safe area {right - left}x{bottom - top}px "
        f"(x {left}-{right}, y {top}-{bottom}) on a {width}x{height} frame; "
        f"clears every platform's caption block and action column."
    )
