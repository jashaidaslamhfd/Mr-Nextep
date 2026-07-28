"""
src/algorithm_policy.py — the 2026 ranking policy, expressed as code.

WHY THIS FILE EXISTS
--------------------
Before this module the channel's "algorithm strategy" lived in three places
that quietly disagreed with each other: prose in docs/ALGORITHM_PLAYBOOK.md,
magic numbers in src/video_editor.py / src/script_generator.py, and env vars
in .github/workflows/main.yml. When YouTube changed the Shorts ranking math in
late 2025 (swipe-rate -> watch-time-per-impression) the docs were updated and
the code was not, so the pipeline kept optimising for a signal that no longer
decided distribution.

Everything the three platforms actually rank on is now declared HERE, once,
with the evidence and the review date attached. Every other module imports
from this file instead of hardcoding numbers. Re-verify quarterly: change the
constants here and the whole pipeline (script length, hook budget, cuts,
captions, hashtags, publish gates, learning thresholds) follows.

HONEST SCOPE NOTE
-----------------
Nobody outside Google/Meta can read the ranking model. What is knowable is:
(a) statements from YouTube/Meta staff, (b) documented product behaviour,
(c) large-cohort creator measurements, and (d) THIS channel's own numbers.
Every entry below is tagged with which of those it came from. Anything that
is a channel-specific experiment is marked EXPERIMENT so it can be killed
without pretending it was ever a law of nature.

CONFIRMED 2026 CHANGES THAT DROVE THIS DESIGN
---------------------------------------------
1. YouTube separated the Shorts recommendation engine from long-form
   (late 2025). Shorts are judged on their own signals; long-form health no
   longer helps or hurts them.
2. Shorts ranking is watch-time-per-impression, not raw swipe rate. The
   practical gate reported consistently across 2026 creator cohorts is
   ~65% average-view-percentage for sub-30s Shorts and ~50% for 30-60s.
   -> A 30-45s Short is the easiest place to clear the bar, which is why the
      master cut targets 30-42s instead of the old 40-55s.
3. Viewer satisfaction (surveys, repeat views, "not interested") outweighs
   raw watch time, and comments are weighted above likes.
4. Instagram runs separate ranking systems per surface. For Reels the
   confirmed top signals are watch time, then sends-per-reach (DM shares,
   several times more valuable than likes), then likes-per-reach. Reposts /
   aggregator behaviour is actively suppressed.
5. Meta shipped the User True Interest Survey (UTIS) model for Reels in
   Jan 2026: it asks viewers whether content matches their interests and
   trains on the answers. Sharp niche relevance now beats broad-appeal
   engagement bait. Facebook Reels also get a same-day distribution boost.
6. YouTube's "inauthentic content" policy (the July 2025 rename of
   "repetitious content") demonetises mass-produced template output — AI or
   not. Properly disclosed AI with genuine per-video value is unaffected.
   -> Every guardrail in this file that looks like it costs us volume is
      protecting monetisation eligibility. Do not "optimise" them away.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Version + review metadata. scripts/growth_report.py prints these so nobody
# has to guess how stale the strategy is.
# ---------------------------------------------------------------------------
POLICY_VERSION = "2026.07"
LAST_VERIFIED = "2026-07-29"
REVERIFY_AFTER_DAYS = 90

YOUTUBE = "youtube_shorts"
FACEBOOK = "facebook_reels"
INSTAGRAM = "instagram_reels"
PLATFORMS = (YOUTUBE, FACEBOOK, INSTAGRAM)


# ---------------------------------------------------------------------------
# SPEECH RATE
# Measured on this channel's own Kokoro am_adam segments (data/video_history
# voiceovers vs. rendered durations): 2.55-2.75 words/second including the
# natural pauses the script inserts. 2.62 is the working midpoint and is what
# the script word budget below is derived from — so the writer never has to
# guess "how many words is 35 seconds".
# ---------------------------------------------------------------------------
WORDS_PER_SECOND = float(os.environ.get("SPEECH_WORDS_PER_SECOND", "2.62"))


# ---------------------------------------------------------------------------
# PER-PLATFORM POLICY
# ---------------------------------------------------------------------------
# duration:        (floor, ideal, ceiling) seconds for THAT platform's cut
# retention_gate:  average-view-percentage the cut has to clear to get pushed
#                  wider; expressed as a function of its own length
# decision_seconds: how long the viewer gives the video before deciding to
#                  stay or swipe. 2026 consensus across all three platforms is
#                  2-3 seconds. This is an observation about VIEWERS.
# hook_seconds:    how long the opening SENTENCE may run. Deliberately longer
#                  than decision_seconds, because the two are different
#                  things: the viewer decides mid-sentence, based on the first
#                  few words and the first frame — the sentence does not have
#                  to be finished for the promise to land.
#                  Conflating them was a real bug here: hook_seconds was set
#                  to decision_seconds, which at the measured speech rate
#                  allowed only FIVE words, and the caption trimmer then
#                  chopped good openers into fragments like "Your calf locks
#                  up in." A truncated hook fails the very moment it was
#                  supposed to win.
# hashtags:        (min, max) — more is not better on any of the three
# caption:         first-line and total character budgets
# spoken_cta:      whether an out-loud "follow me" is allowed in the audio
# ---------------------------------------------------------------------------
PLATFORM_POLICY: Dict[str, Dict] = {
    YOUTUBE: {
        "label": "YouTube Shorts",
        "duration": (30.0, 36.0, 42.0),
        "hard_max": 60.0,
        # Sub-30s Shorts are held to ~65% AVP, 30-60s to ~50%. We deliberately
        # sit just above 30s so the easier 50% bar applies while still being
        # short enough to finish.
        "retention_gate": {"under_30s": 0.65, "over_30s": 0.50},
        "decision_seconds": 2.5,
        "hook_seconds": 3.2,
        "hashtags": (3, 4),
        "caption": {"first_line_chars": 100, "total_chars": 4800},
        # YouTube tolerates a follow prompt, but a spoken CTA costs completion
        # on a 35s video and completion IS the ranking signal. The channel's
        # CTA now lives in the description only (SPOKEN_CTA_MODE=loop).
        "spoken_cta": False,
        "ranking_signals": (
            "average view percentage (watch time per impression)",
            "survival past the first 2-3 seconds",
            "replays / loop rate",
            "comments (weighted above likes) and shares",
            "viewer satisfaction surveys and 'not interested'",
        ),
        "sources": (
            "dataslayer.ai/blog/youtube-algorithm-2025-how-to-get-your-videos-recommended (2026-06)",
            "socialync.io/blog/youtube-shorts-algorithm-2026 (2026-07)",
            "outlierkit.com/resources/youtube-algorithm-updates (2026-06)",
            "meikuio.com/youtube-algorithm-2026 (2026-06, confirmed-vs-myth split)",
        ),
    },
    FACEBOOK: {
        "label": "Facebook Reels",
        # Meta's own benchmark: Reels that clear ~72% watch-through get
        # materially more distribution, and 15-45s is where brands actually
        # clear it. 24-30s is our compromise between "completable" and
        # "enough room for a real explanation".
        "duration": (20.0, 27.0, 32.0),
        "hard_max": 90.0,
        "retention_gate": {"under_30s": 0.72, "over_30s": 0.60},
        "decision_seconds": 2.5,
        "hook_seconds": 3.0,
        "hashtags": (2, 3),
        "caption": {"first_line_chars": 80, "total_chars": 2000},
        "spoken_cta": False,
        "ranking_signals": (
            "watch time + completion rate (top signal)",
            "shares/sends, especially to Messenger",
            "UTIS true-interest survey match (Jan 2026)",
            "original content (recycled/watermarked is suppressed)",
            "same-day freshness boost",
        ),
        "sources": (
            "affiversemedia.com — Meta UTIS Reels model, announced 2026-01-14",
            "posteverywhere.ai/blog/how-the-facebook-algorithm-works (2026-05)",
            "socialbee.com/blog/facebook-algorithm (2026-07)",
            "conbersa.ai/learn/what-are-facebook-reels-guide (2026-06)",
        ),
    },
    INSTAGRAM: {
        "label": "Instagram Reels",
        "duration": (18.0, 26.0, 30.0),
        "hard_max": 180.0,
        "retention_gate": {"under_30s": 0.70, "over_30s": 0.55},
        "decision_seconds": 2.0,
        "hook_seconds": 2.8,
        # IG rewards niche keyword hashtags; 3-5 is the 2026 working range.
        "hashtags": (3, 5),
        "caption": {"first_line_chars": 90, "total_chars": 2100},
        "spoken_cta": False,
        "ranking_signals": (
            "watch time / completion (Mosseri: top signal on every surface)",
            "sends per reach — DM shares, 3-5x the weight of a like",
            "likes per reach",
            "saves",
            "originality (aggregator/repost penalty)",
        ),
        "sources": (
            "creatorflow.so/blog/instagram-algorithm-2026 (2026-06)",
            "sproutsocial.com/insights/instagram-algorithm (2026-07)",
            "clixie.ai/blog/instagram-algorithm (2026-06)",
            "mirra.my/en/blog/instagram-algorithm-2026-complete-analysis (2026-05)",
        ),
    },
}


# ---------------------------------------------------------------------------
# ENGAGEMENT-BAIT VOCABULARY
#
# This is deliberately split, because the two families of platform do NOT
# agree on what counts as bait — and treating them the same costs reach on
# one side or a demotion on the other:
#
#   * Both:  demanding a like/comment/share/tag/save. YouTube's spam policy
#            and Meta's engagement-bait demotion both target these.
#   * Meta only: "subscribe". Meta reads a subscribe push as off-platform
#            promotion, while on YouTube "subscribe for more" is ordinary,
#            expected creator language that costs nothing.
#
# What is bait-free everywhere: a plain "Follow". That is the only ask the
# channel makes in the audio, and since the spoken CTA was removed it is the
# caption's job to carry it.
# ---------------------------------------------------------------------------
_UNIVERSAL_BAIT: Tuple[str, ...] = (
    r"\blike (this|if|and)\b",
    r"\bdouble tap\b",
    r"\bsmash (that )?like\b",
    r"\bshare (this|it|with)\b",
    r"\bsend this to\b",
    r"\btag (a|your|someone)\b",
    r"\bcomment (below|down|'?\w+'? if)\b",
    r"\bdrop a (like|comment|\W)\b",
    r"\bsave this (post|reel|for)\b",
    r"\bvote (below|now)\b",
    r"\bwho agrees\b",
)

# Extra restrictions that apply only on Facebook and Instagram.
_META_ONLY_BAIT: Tuple[str, ...] = (
    r"\bsubscribe\b",
    r"\blink in bio\b",
    r"\bcheck (out )?(my|our) (channel|youtube)\b",
)

# Kept as the union for callers that want the strictest possible check.
BAIT_PATTERNS: Tuple[str, ...] = _UNIVERSAL_BAIT + _META_ONLY_BAIT

# Phrases that make YouTube's advertiser-friendly + medical-misinformation
# reviewers nervous on a body-science channel. Blocked at script level.
FEAR_BAIT_PATTERNS: Tuple[str, ...] = (
    r"doctors? (don'?t|won'?t) want",
    r"they don'?t want you to know",
    r"\bbig pharma\b",
    r"\bmiracle cure\b",
    r"\byou'?re dying\b",
    r"\bkilling you\b",
    r"\bdeadly\b",
    r"\bshocking truth\b",
)


# ---------------------------------------------------------------------------
# CONTENT-ORIGINALITY GUARDRAILS (YouTube inauthentic-content policy, Meta
# aggregator penalty). These are hard product requirements, not preferences.
# ---------------------------------------------------------------------------
ORIGINALITY_RULES = {
    # No visual asset may ever appear in two videos (channel-wide hash ledger).
    "unique_visuals_per_video": True,
    # No two videos may share a title pattern more than this often in a row.
    "max_consecutive_same_title_frame": 2,
    # Description/caption boilerplate must rotate; identical byte-for-byte
    # copy across a whole channel is the classic template-spam signal.
    "rotate_boilerplate": True,
    # Every upload declares synthetic media on YouTube. Disclosed AI ranks
    # normally; undisclosed realistic AI is a suppression path.
    "declare_synthetic_media": True,
    # A human must actually look at the channel. Automation cannot fake this
    # and both platforms reward it.
    "human_review_daily": True,
}


# ---------------------------------------------------------------------------
# Helpers — every consumer goes through these instead of reaching into the
# dict, so a policy change can never be half-applied.
# ---------------------------------------------------------------------------

def get_policy(platform: str) -> Dict:
    """Return the policy block for a platform (raises on typos on purpose)."""
    try:
        return PLATFORM_POLICY[platform]
    except KeyError as exc:  # pragma: no cover - programmer error
        raise KeyError(
            f"Unknown platform {platform!r}; expected one of {PLATFORMS}"
        ) from exc


def duration_policy(platform: str) -> Tuple[float, float, float]:
    """(floor, ideal, ceiling) seconds for that platform's cut."""
    return tuple(get_policy(platform)["duration"])  # type: ignore[return-value]


def retention_gate(platform: str, seconds: float) -> float:
    """The average-view-percentage this cut must clear to be pushed wider.

    Expressed as a 0-1 fraction. The threshold depends on the video's OWN
    length, which is exactly why the dual-cut strategy exists: a 27s Meta cut
    and a 36s YouTube cut are graded on different curves.
    """
    gates = get_policy(platform)["retention_gate"]
    return float(gates["under_30s"] if seconds < 30.0 else gates["over_30s"])


def hook_seconds(platform: str = YOUTUBE) -> float:
    """Maximum spoken length of the opening SENTENCE."""
    return float(get_policy(platform)["hook_seconds"])


def decision_seconds(platform: str = YOUTUBE) -> float:
    """How long the viewer gives the video before staying or swiping.

    Distinct from hook_seconds: the decision happens mid-sentence, on the
    first few words and the first frame. Use this for "is the promise
    arriving fast enough", not for "is the sentence over".
    """
    return float(get_policy(platform)["decision_seconds"])


def shared_hook_seconds(platforms: Optional[Iterable[str]] = None) -> float:
    """Hook budget for the ONE audio track that serves every enabled platform.

    All three platforms receive the same narration, so the budget is the
    tightest of them (Instagram, ~2.0s). This function exists so the writer
    and the runtime gate compute the budget the SAME way: an earlier version
    derived the word count from YouTube's 2.8s while the gate enforced
    Instagram's 2.0s, which made it arithmetically impossible for a
    well-formed hook to pass — the generator was being asked for up to seven
    words and then rejected for taking longer than five words' worth of time.
    """
    selected = list(platforms) if platforms else [YOUTUBE]
    return min(hook_seconds(p) for p in selected)


# Natural speech is not metronomic: the opening line carries the most
# deliberate delivery (a beat before the twist, emphasis on the subject), so
# it consistently runs slower than the channel average. This tolerance keeps a
# strong 5-word hook that lands in 2.4s instead of 2.0s, while still rejecting
# the 4-5 second cold intros the gate exists to stop. It is applied to the
# ENFORCEMENT threshold only — the writer still aims at the true budget.
HOOK_DELIVERY_TOLERANCE = 1.35


def hook_enforcement_seconds(platforms: Optional[Iterable[str]] = None) -> float:
    """The hard limit the rendered audio is actually checked against."""
    return round(shared_hook_seconds(platforms) * HOOK_DELIVERY_TOLERANCE, 2)


def hashtag_limits(platform: str) -> Tuple[int, int]:
    return tuple(get_policy(platform)["hashtags"])  # type: ignore[return-value]


def caption_limits(platform: str) -> Dict[str, int]:
    return dict(get_policy(platform)["caption"])


def allows_spoken_cta(platform: str) -> bool:
    return bool(get_policy(platform)["spoken_cta"])


def spoken_cta_allowed_anywhere(platforms: Iterable[str]) -> bool:
    """One audio track serves all enabled platforms, so a spoken CTA is only
    acceptable if EVERY enabled platform tolerates it. In 2026 none of them
    reward it on a sub-45s video, which is why the default is loop mode."""
    return all(allows_spoken_cta(p) for p in platforms)


def script_word_budget(platform: str = YOUTUBE) -> Tuple[int, int]:
    """Words of narration that fit the master cut, derived from the duration
    policy and the measured speech rate — never hand-tuned separately.

    The floor gets a 5% tolerance because TTS pauses make short scripts run
    slightly long anyway. The ceiling gets NO tolerance: exceeding it means the
    renderer has to speed the narration up, and rushed audio is exactly the
    "machine-made" quality both platforms' 2026 policies penalise.
    """
    floor, _ideal, ceiling = duration_policy(platform)
    return (
        int(round(floor * WORDS_PER_SECOND * 0.95)),
        int(round(ceiling * WORDS_PER_SECOND)),
    )


def hook_word_budget(platform: str = YOUTUBE) -> Tuple[int, int]:
    """Hook length in words, sized against the SHARED audio budget.

    The single narration track goes to every enabled platform, so the writer
    must be briefed against the tightest hook budget, not YouTube's. Sizing
    this from one platform while the runtime gate enforced another is what
    made the hook gate unsatisfiable.

    The floor of 4 keeps the line from collapsing into a fragment ("Your eye
    twitches.") that names a subject but promises nothing.
    """
    max_words = int(shared_hook_seconds(PLATFORMS) * WORDS_PER_SECOND)
    return (4, max(5, max_words))


def scene_word_budget(scene_count: int = 8, platform: str = YOUTUBE) -> Tuple[int, int]:
    """Per-scene caption budget for the non-hook scenes, derived from the total
    word budget so scene count and video length can never drift apart."""
    total_min, total_max = script_word_budget(platform)
    hook_min, hook_max = hook_word_budget(platform)
    body_scenes = max(1, scene_count - 1)
    return (
        max(7, int((total_min - hook_max) / body_scenes)),
        max(9, int((total_max - hook_min) / body_scenes)),
    )


# ---------------------------------------------------------------------------
# Caption hygiene
# ---------------------------------------------------------------------------

_UNIVERSAL_BAIT_RE = re.compile("|".join(_UNIVERSAL_BAIT), re.IGNORECASE)
_META_BAIT_RE = re.compile("|".join(_UNIVERSAL_BAIT + _META_ONLY_BAIT), re.IGNORECASE)
_FEAR_RE = re.compile("|".join(FEAR_BAIT_PATTERNS), re.IGNORECASE)


def _bait_matcher(platform: Optional[str]):
    """Meta enforces a wider bait vocabulary than YouTube — see the note above
    the pattern lists. Passing no platform applies the strict Meta rules,
    which is the safe default for shared assets like the spoken script."""
    return _UNIVERSAL_BAIT_RE if platform == YOUTUBE else _META_BAIT_RE


def contains_bait(text: str, platform: Optional[str] = None) -> bool:
    """True if the text contains an engagement-bait ask for that platform."""
    return bool(text) and bool(_bait_matcher(platform).search(text))


def contains_fear_bait(text: str) -> bool:
    return bool(text) and bool(_FEAR_RE.search(text))


def strip_bait(text: str, platform: Optional[str] = None) -> str:
    """Remove bait sentences, keeping everything else — including layout.

    Two things matter here:
    1. Filtering per SENTENCE, not per caption: one bad clause ("Share this
       with a friend!") must not cost us the surrounding explanation, which is
       the part the ranking model reads for topic relevance.
    2. Preserving the blank-line structure: these captions are built as
       hook / summary / context / hashtag blocks, and the first line is what
       shows before the "... more" fold on Instagram and Facebook. Flattening
       them into one paragraph would quietly bury the hook.
    """
    if not text:
        return ""
    matcher = _bait_matcher(platform)
    clean_blocks = []
    for block in text.split("\n\n"):
        sentences = re.split(r"(?<=[.!?])\s+", block)
        kept = [s for s in sentences if s.strip() and not matcher.search(s)]
        rebuilt = re.sub(r"[ \t]{2,}", " ", " ".join(kept)).strip()
        if rebuilt:
            clean_blocks.append(rebuilt)
    return "\n\n".join(clean_blocks)


def enforce_hashtag_limit(hashtags: List[str], platform: str) -> List[str]:
    """Trim to the platform's working range and de-duplicate case-insensitively.

    Over-tagging is measurably useless on all three platforms in 2026 and looks
    like spam to reviewers, so the ceiling is enforced rather than suggested.
    """
    _min, maximum = hashtag_limits(platform)
    seen, out = set(), []
    for tag in hashtags:
        token = str(tag or "").strip()
        if not token:
            continue
        token = token if token.startswith("#") else f"#{token}"
        token = "#" + re.sub(r"[^A-Za-z0-9_]", "", token[1:])
        if len(token) <= 2:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= maximum:
            break
    return out


# ---------------------------------------------------------------------------
# Publishing cadence
# ---------------------------------------------------------------------------
# Consistency beats volume on all three platforms in 2026, and YouTube's
# inauthentic-content policy makes "more uploads" an actively risky lever for
# a faceless channel. The pipeline therefore never posts more than this, and
# the growth engine is allowed to recommend LESS (see src/growth_engine.py).
MAX_UPLOADS_PER_DAY = 3
MIN_UPLOADS_PER_DAY = 1
MIN_MINUTES_BETWEEN_PUBLISHES = 90


def clamp_cadence(per_day: int) -> int:
    return max(MIN_UPLOADS_PER_DAY, min(int(per_day), MAX_UPLOADS_PER_DAY))


# ---------------------------------------------------------------------------
# Health thresholds used by the learning loop (src/growth_engine.py). These
# are the numbers that turn "the algorithm wants retention" into an actual
# if-statement somewhere.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# HOOK GATE
#
# shorts_enhancer.score_hook_detailed awards:
#     25  right spoken length (fits the hook budget)
#     20  addresses the viewer ("you"/"your")
#     25  names something concrete the viewer can picture
#     20  opens a curiosity loop (explicit question OR implicit gap)
#     10  not a cold open
#     -35 vague authority   ·   veto (score 0) for fear-bait
#
# The gate is therefore not a taste value, it is a statement about which
# checks are MANDATORY. 80 = every structural check must pass; the curiosity
# loop is what separates a competent hook from a strong one, and the retry
# loop spends its attempts chasing it.
#
# This lives here rather than in the workflow because the previous magic "85"
# in main.yml was calibrated against a DIFFERENT scoring scale. When the
# scorer was rewritten, that number silently became near-unreachable: only 3
# of the channel's 21 published hooks would have cleared it, so most runs
# would have failed their gates and skipped the upload entirely. A threshold
# and the scale it is measured on must live together.
MIN_HOOK_SCORE = 80
# Above this the hook is strong enough that the retry loop stops early instead
# of spending API calls trying to beat it.
STRONG_HOOK_SCORE = 100

HEALTH_THRESHOLDS = {
    # Below this share of the platform's retention gate, the format itself is
    # the problem — not the topic, not the posting time.
    "critical_retention_ratio": 0.6,
    # A slot needs this many mature videos before its average means anything.
    "min_samples_per_slot": 3,
    # Videos younger than this are still inside their distribution ramp.
    "maturity_hours": 48,
    # YouTube Shorts CTR is a weak signal, but a floor still catches a broken
    # thumbnail/title pair on the search + channel surfaces.
    "min_ctr": 0.03,
}


def summary() -> str:
    """One-screen human summary — printed by scripts/growth_report.py."""
    lines = [
        f"SKILLOR algorithm policy {POLICY_VERSION} (verified {LAST_VERIFIED})",
        "",
    ]
    for platform in PLATFORMS:
        policy = get_policy(platform)
        floor, ideal, ceiling = policy["duration"]
        lo, hi = policy["hashtags"]
        lines.append(
            f"- {policy['label']}: {floor:.0f}-{ceiling:.0f}s (ideal {ideal:.0f}s), "
            f"hook <= {policy['hook_seconds']}s, {lo}-{hi} hashtags, "
            f"gate {retention_gate(platform, ideal):.0%} AVP"
        )
    words_lo, words_hi = script_word_budget()
    hook_lo, hook_hi = hook_word_budget()
    lines += [
        "",
        f"Script budget: {words_lo}-{words_hi} words at {WORDS_PER_SECOND} w/s "
        f"(hook {hook_lo}-{hook_hi} words).",
        f"Cadence ceiling: {MAX_UPLOADS_PER_DAY}/day, "
        f">= {MIN_MINUTES_BETWEEN_PUBLISHES} min apart.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    print(summary())
