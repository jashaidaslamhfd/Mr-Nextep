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

import logging
import os
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Version + review metadata. scripts/growth_report.py prints these so nobody
# has to guess how stale the strategy is.
# ---------------------------------------------------------------------------
POLICY_VERSION = "2026.08-fix4-views"
LAST_VERIFIED = "2026-08-14"
REVERIFY_AFTER_DAYS = 90

YOUTUBE = "youtube_shorts"
FACEBOOK = "facebook_reels"
INSTAGRAM = "instagram_reels"
PLATFORMS = (YOUTUBE, FACEBOOK, INSTAGRAM)


WORDS_PER_SECOND = float(os.environ.get("SPEECH_WORDS_PER_SECOND", "2.62"))


_RETIRED_ENV_VALUES: Dict[str, Tuple[str, ...]] = {
    "TARGET_MIN_SECONDS": ("40", "40.0"),
    "TARGET_MAX_SECONDS": ("55", "55.0"),
    "MAX_HOOK_SECONDS": ("5", "5.0"),
    "MIN_HOOK_SCORE": ("85", "70"),
}

_warned_retired: set = set()


def env_override(name: str) -> Optional[str]:
    """Read an env override, ignoring values left over from a retired strategy.

    Returns None when the variable is unset, empty, or holds a value this
    module has explicitly retired — in which case the caller falls back to the
    policy and a warning is logged once per process.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    if raw in _RETIRED_ENV_VALUES.get(name, ()):
        if name not in _warned_retired:
            _warned_retired.add(name)
            logging.getLogger(__name__).warning(
                "%s=%s is a retired setting from the pre-%s strategy and is being "
                "IGNORED; using the policy value instead. Remove it from the "
                "workflow/env to silence this.",
                name, raw, POLICY_VERSION,
            )
        return None
    return raw


def env_float(name: str, fallback: float) -> float:
    value = env_override(name)
    try:
        return float(value) if value is not None else float(fallback)
    except ValueError:
        return float(fallback)


def env_int(name: str, fallback: int) -> int:
    value = env_override(name)
    try:
        return int(float(value)) if value is not None else int(fallback)
    except ValueError:
        return int(fallback)


PLATFORM_POLICY: Dict[str, Dict] = {
    YOUTUBE: {
        "label": "YouTube Shorts",
        "duration": (14.0, 20.0, 25.0),  # FIXED 2026-08-24: 10-14s measured watch time needs 14-20s target to pass 65% gate
        "hard_max": 60.0,
        # FIXED 2026-08-14: see duration note above — 33s ideal made the gate
        # arithmetically unreachable on this channel's measured watch time.
        "retention_gate": {"under_30s": 0.65, "over_30s": 0.50},
        "decision_seconds": 2.2,
        "hook_seconds": 2.8,
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
        "duration": (10.0, 14.0, 22.0),
        "hard_max": 90.0,
        "retention_gate": {"under_30s": 0.72, "over_30s": 0.60},
        "decision_seconds": 2.0,
        "hook_seconds": 2.5,
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
        # FIXED 2026-08-13 (retention-first pass): same arithmetic as Facebook.
        # Measured Instagram Reels: 24% completion against a 70% gate. A 23s
        # ideal cannot clear that on 2.6-7.5s of watch time, so the floor/ideal
        # move down to lengths where the gate is reachable. IG allows 3s+.
        "duration": (12.0, 15.0, 22.0),
        "hard_max": 180.0,
        # FIXED: IG ideal 26s -> 23s, gate 70%. Sends_per_reach 0% vs healthy 0.5%+ -> need
        # shorter cut + quotable payoff for DM shares.
        "retention_gate": {"under_30s": 0.70, "over_30s": 0.55},
        "decision_seconds": 1.8,
        "hook_seconds": 2.3,
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


_UNIVERSAL_BAIT: Tuple[str, ...] = (
    r"\blike (this|if|and)\b",
    r"\bdouble tap\b",
    r"\bsmash (that )?like\b",
    r"\bshare\s+this\s+with\s+(?:a\s+)?friend\b",
    r"\bshare\s+(this|it|with)\b",
    r"\bsend this to\b",
    r"\btag (a|your|someone)\b",
    r"\bcomment (below|down|'?\w+'? if)\b",
    r"\bdrop a (like|comment|\W)\b",
    r"\bsave this (post|reel|for)\b",
    r"\bvote (below|now)\b",
    r"\bwho agrees\b",
    r"\bturn\s+on\s+(the\s+)?(notifications|bell)\b",
)

# Extra restrictions that apply only on Facebook and Instagram.
_META_ONLY_BAIT: Tuple[str, ...] = (
    r"\bsubscribe\s+(?:for\s+more|now|to\s+see)\b",
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
    # Stock footage + voiceover does NOT require disclosure per YouTube's
    # 2026 policy (disclosure is for deepfakes / AI-generated faces only).
    "declare_synthetic_media": False,
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


def _normalize_policy_text(text: str) -> str:
    """Normalize formatting so bait cannot bypass detection."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    normalized = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", normalized)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[^\S\n]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _bait_matcher(platform: Optional[str]):
    """Return the platform matcher; None uses strict shared-content rules."""
    return _UNIVERSAL_BAIT_RE if platform == YOUTUBE else _META_BAIT_RE


def contains_bait(text: str, platform: Optional[str] = None) -> bool:
    """True if normalized text contains an engagement-bait ask."""
    normalized = _normalize_policy_text(text)
    return bool(normalized) and bool(_bait_matcher(platform).search(normalized))


def contains_fear_bait(text: str) -> bool:
    return bool(text) and bool(_FEAR_RE.search(_normalize_policy_text(text)))


def strip_bait(text: str, platform: Optional[str] = None) -> str:
    """Remove complete and inline bait while preserving metadata blocks."""
    if not text:
        return ""

    normalized = _normalize_policy_text(text)
    matcher = _bait_matcher(platform)
    clean_blocks = []

    for block in normalized.split("\n\n"):
        cleaned_sentences = []
        sentences = re.split(r"(?<=[.!?])\s+|\s*;\s*", block)
        for sentence in sentences:
            sentence = sentence.strip(" \t-–—")
            if not sentence:
                continue

            # Remove bait clauses first. This retains useful information from
            # sentences such as: "This is harmless — subscribe for more."
            cleaned_sentence = sentence
            patterns = BAIT_PATTERNS if platform != YOUTUBE else _UNIVERSAL_BAIT
            for pattern in patterns:
                cleaned_sentence = re.sub(
                    rf"(?:\s*[-–—,:|]?\s*){pattern}(?:\s*[-–—,:|.!?]*)",
                    " ",
                    cleaned_sentence,
                    flags=re.IGNORECASE,
                )
            cleaned_sentence = re.sub(r"\s{2,}", " ", cleaned_sentence)
            cleaned_sentence = cleaned_sentence.strip(" -–—,;:|\t")

            # If the original sentence was only bait, no useful text remains.
            if cleaned_sentence and not matcher.search(cleaned_sentence):
                cleaned_sentences.append(cleaned_sentence)

        if cleaned_sentences:
            clean_blocks.append(" ".join(cleaned_sentences))

    return "\n\n".join(clean_blocks)


def clean_metadata_fields(
    payload: dict,
    fields: Tuple[str, ...] = ("title", "description", "summary", "cta"),
    platform: Optional[str] = None,
) -> dict:
    """Clean final metadata in place and return the same payload."""
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str):
            payload[field] = strip_bait(value, platform=platform)
    return payload


def assert_bait_free(payload: dict, fields: Tuple[str, ...] = ("title", "description", "summary", "cta"), platform: Optional[str] = None) -> None:
    """Fail closed with the exact field if cleanup did not remove bait."""
    for field in fields:
        value = payload.get(field, "")
        if isinstance(value, str) and contains_bait(value, platform=platform):
            raise ValueError(f"Engagement bait remains in metadata field: {field}")


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


MAX_UPLOADS_PER_DAY = 2
MIN_UPLOADS_PER_DAY = 1
MIN_MINUTES_BETWEEN_PUBLISHES = 90


def clamp_cadence(per_day: int) -> int:
    return max(MIN_UPLOADS_PER_DAY, min(int(per_day), MAX_UPLOADS_PER_DAY))


def retention_cadence_cap(channel_gate_ratio: float | None) -> int:
    """Hard cap: when channel retention is below the platform gate, force
    cadence to 1/day regardless of what the growth engine suggests.
    Published data (2026-08-24): channel median retention 36% vs 50-65% gate
    means every additional upload teaches the feed to stop showing the channel.
    Only raising cadence is gated; lowering is always allowed by clamp_cadence.
    Returns the MAX allowed cadence (no cap) when data is healthy.
    """
    if channel_gate_ratio is None or channel_gate_ratio < 0.80:
        return 1
    return MAX_UPLOADS_PER_DAY



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
        f"Nextep algorithm policy {POLICY_VERSION} (verified {LAST_VERIFIED})",
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



# Engagement score weights — how much each signal contributes to a video's
# total reach score. Higher = the algorithm pushes harder.
ENGAGEMENT_SCORE_WEIGHTS = {
    "retention": 0.30,       # watch time / completion (top YouTube signal)
    "ctr": 0.20,             # click-through rate (impressions → views)
    "shares": 0.20,          # shares/DMs (IG #2 signal, YT growing signal)
    "loop_rate": 0.15,       # replay rate = free watch time
    "comments": 0.10,        # comments weighted above likes (YouTube confirmed)
    "saves": 0.05,           # saves (IG signal)
}

# Minimum engagement score to be considered "reach-ready" (0-100)
REACH_READY_THRESHOLD = 72

# Topics ranked by measured engagement (from growth_state analytics)
# muscle and ear topics get highest completion; brain lowest
TOPIC_ENGAGEMENT_RANKINGS = {
    "muscle": 1.08,
    "ear": 1.05,
    "heart": 1.03,
    "sleep": 1.02,
    "skin": 1.01,
    "eye": 1.00,
    "nerve": 0.99,
    "brain": 0.88,
    "other": 0.95,
}

# Hook openers ranked by measured retention impact (from viral_optimizer calibration)
HOOK_RETENTION_RANKINGS = {
    "statement": 1.04,      # "Your muscle does X" — direct, no question mark
    "contradiction": 1.12,  # "Your brain does X, but the opposite is true"
    "mechanism": 1.10,      # "Here's how your nerve signal works"
    "countdown": 1.08,      # "In exactly 3 seconds, your body will..."
    "question": 0.92,       # "Why does your muscle do X?" (questions lower retention)
    "cold_open": 0.60,      # "Hi, today we're talking about..." (penalty)
}


def engagement_score(metrics: Dict[str, float]) -> float:
    """Compute a 0-100 reach score from predicted or actual metrics.

    metrics keys: retention, ctr, shares, loop_rate, comments, saves
    All values should be 0-1 fractions (except shares/comments which are rates).
    """
    score = 0.0

    # Normalize each metric to 0-100 scale
    retention = max(0, min(metrics.get("retention", 0), 1))
    ctr = max(0, min(metrics.get("ctr", 0), 1))
    shares = max(0, min(metrics.get("shares", 0) * 100, 1))  # 1% shares = 100
    loop_rate = max(0, min(metrics.get("loop_rate", 0), 1))
    comments = max(0, min(metrics.get("comments", 0) * 50, 1))  # 2% comments = 100
    saves = max(0, min(metrics.get("saves", 0) * 100, 1))

    for metric, value in [
        ("retention", retention),
        ("ctr", ctr),
        ("shares", shares),
        ("loop_rate", loop_rate),
        ("comments", comments),
        ("saves", saves),
    ]:
        weight = ENGAGEMENT_SCORE_WEIGHTS.get(metric, 0)
        score += value * weight * 100

    return round(min(score, 100), 1)


def topic_reach_multiplier(topic: str) -> float:
    """Multiplier on predicted reach based on topic performance history."""
    return TOPIC_ENGAGEMENT_RANKINGS.get(topic, 0.95)


def hook_reach_multiplier(hook_type: str) -> float:
    """Multiplier on predicted reach based on hook style performance."""
    return HOOK_RETENTION_RANKINGS.get(hook_type, 0.95)


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    print(summary())
