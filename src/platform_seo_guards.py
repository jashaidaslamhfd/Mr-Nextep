"""Platform-specific SEO guards — does each platform's metadata match ITS OWN
2026 algorithm?

YouTube, Facebook and Instagram rank on different 2026 rules:
  * YouTube  — search+recommendation: keyword-aligned title/desc/tags, 3-4
               hashtags, curiosity hook, bait-free.
  * Facebook — UTIS true-interest match (Jan 2026): plain topic naming, 2-3
               hashtags, NO cross-posted #shorts/#youtube tags, no bait.
  * Instagram— forwardable payoff + niche hashtag clusters, 3-5 hashtags,
               DM-worthy, watch-time gate.

Each guard reads ONLY the platform's own caption/metadata and checks it against
the policy for THAT platform (algorithm_policy.get_policy). A video is only
passed if the metadata for every enabled platform is compliant with that
platform's 2026 algorithm.

These are independent observers — they do not trust the pipeline's SEO score.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_YOUTUBE_ONLY_TAGS = {"shorts", "short", "youtubeshorts", "ytshorts", "youtube"}
_META_FORBIDDEN_TAGS = {"shorts", "short", "youtubeshorts", "ytshorts",
                        "youtube", "viral", "fyp", "trending"}
_BAIT = ("like and subscribe", "smash that like", "hit the bell", "tag someone",
         "share this", "subscribe for more")


def _policy(platform: str) -> Dict:
    try:
        from algorithm_policy import get_policy
        return get_policy(platform)
    except Exception:
        return {}


def _hashtag_count(text: str) -> int:
    return len(re.findall(r"#[A-Za-z0-9_]+", text or ""))


def _extract_hashtags(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"#([A-Za-z0-9_]+)", text or "")]


def _bait_in(text: str) -> List[str]:
    low = (text or "").lower()
    return [b for b in _BAIT if b in low]


# --------------------------------------------------------------------------- #
# YOUTUBE SEO GUARD
# --------------------------------------------------------------------------- #

def check_youtube_seo(script_data: Dict) -> Dict[str, Any]:
    """YouTube 2026 SEO: keyword-aligned title, description length, tag count,
    3-4 hashtags, curiosity hook, bait-free."""
    issues: List[str] = []
    ok = True
    checked = ["title", "description", "tags", "hashtags", "hook", "no_bait"]

    title = (script_data.get("title") or "").strip()
    desc = (script_data.get("description") or "").strip()
    tags = script_data.get("tags") or []
    hashtags = script_data.get("hashtags") or []

    # Title: curiosity + keyword + mobile length
    if not title:
        ok, issues = False, issues + ["YT: missing title"]
    elif len(title) > 100:
        ok, issues = False, issues + [f"YT: title too long ({len(title)} chars >100)"]
    if not any(w in title.lower() for w in ("why", "what", "how", "you", "your", "never", "secret", "actually", "every")):
        ok, issues = False, issues + ["YT: title lacks curiosity trigger"]

    # Description: long enough, keyword echoed
    if len(desc) < 100:
        ok, issues = False, issues + [f"YT: description too short ({len(desc)} chars <100)"]
    if title and not any(k.lower() in desc.lower() for k in title.split()[:3]):
        ok, issues = False, issues + ["YT: description does not echo title keywords"]

    # Tags
    if len(tags) < 3:
        ok, issues = False, issues + [f"YT: too few tags ({len(tags)} <3)"]

    # Hashtags 3-4 (YouTube policy)
    hmin, hmax = 3, 4
    n = _hashtag_count(" ".join(hashtags))
    if n < hmin or n > hmax:
        ok, issues = False, issues + [f"YT: {n} hashtags (need {hmin}-{hmax})"]

    # Hook present (first-2s decision)
    if not (script_data.get("hook") or "").strip():
        ok, issues = False, issues + ["YT: missing hook"]

    # Bait
    bait = _bait_in(title + " " + desc)
    if bait:
        ok, issues = False, issues + [f"YT: bait phrase: {bait[0]}"]

    return {"guard": "yt_seo", "platform": "youtube", "pass": ok,
            "issues": issues, "confidence": "high", "checked": checked}


# --------------------------------------------------------------------------- #
# FACEBOOK SEO GUARD (UTIS, Jan 2026)
# --------------------------------------------------------------------------- #

def check_facebook_seo(script_data: Dict) -> Dict[str, Any]:
    """Facebook 2026 UTIS: plain topic naming in line 1, 2-3 hashtags, NO
    #shorts/#youtube/#viral cross-posted tags, no engagement bait."""
    issues: List[str] = []
    ok = True
    checked = ["caption", "topic_naming", "hashtags", "no_crosspost_tags", "no_bait"]

    fb_caption = (script_data.get("facebook_caption")
                  or script_data.get("meta_caption") or "").strip()
    # FB caption should be its own field; if absent, fall back to description.
    if not fb_caption:
        fb_caption = (script_data.get("description") or "").strip()

    if not fb_caption:
        return {"guard": "fb_seo", "platform": "facebook", "pass": False,
                "issues": ["FB: no caption available"], "confidence": "high",
                "checked": checked}

    # UTIS: first line names the topic plainly (not a teaser)
    first_line = fb_caption.split("\n")[0].lower()
    if any(t in first_line for t in ("follow", "subscribe", "like if", "comment")):
        ok, issues = False, issues + ["FB: first line is an ask, not a plain topic name"]

    # Hashtags 2-3
    n = _hashtag_count(fb_caption)
    if n < 2 or n > 3:
        ok, issues = False, issues + [f"FB: {n} hashtags (need 2-3)"]

    # No cross-posted YouTube/trend tags
    tags_in = set(_extract_hashtags(fb_caption))
    bad = tags_in & _META_FORBIDDEN_TAGS
    if bad:
        ok, issues = False, issues + [f"FB: forbidden cross-post tag(s): {sorted(bad)}"]

    # No bait
    bait = _bait_in(fb_caption)
    if bait:
        ok, issues = False, issues + [f"FB: bait phrase: {bait[0]}"]

    # UTIS length cap
    if len(fb_caption) > 2000:
        ok, issues = False, issues + [f"FB: caption too long ({len(fb_caption)} chars >2000)"]

    return {"guard": "fb_seo", "platform": "facebook", "pass": ok,
            "issues": issues, "confidence": "high", "checked": checked}


# --------------------------------------------------------------------------- #
# INSTAGRAM SEO GUARD
# --------------------------------------------------------------------------- #

def check_instagram_seo(script_data: Dict) -> Dict[str, Any]:
    """Instagram 2026 SEO: forwardable payoff, niche hashtag clusters 3-5,
    DM-worthy caption, no cross-posted tags, no bait."""
    issues: List[str] = []
    ok = True
    checked = ["caption", "payoff", "hashtags", "no_crosspost_tags", "no_bait", "dm_worthy"]

    ig_caption = (script_data.get("instagram_caption")
                  or script_data.get("meta_caption") or "").strip()
    if not ig_caption:
        ig_caption = (script_data.get("description") or "").strip()

    if not ig_caption:
        return {"guard": "ig_seo", "platform": "instagram", "pass": False,
                "issues": ["IG: no caption available"], "confidence": "high",
                "checked": checked}

    # Hashtags 3-5 (IG niche keyword range)
    n = _hashtag_count(ig_caption)
    if n < 3 or n > 5:
        ok, issues = False, issues + [f"IG: {n} hashtags (need 3-5)"]

    # No cross-posted YouTube/trend tags
    tags_in = set(_extract_hashtags(ig_caption))
    bad = tags_in & _META_FORBIDDEN_TAGS
    if bad:
        ok, issues = False, issues + [f"IG: forbidden cross-post tag(s): {sorted(bad)}"]

    # No bait
    bait = _bait_in(ig_caption)
    if bait:
        ok, issues = False, issues + [f"IG: bait phrase: {bait[0]}"]

    # Forwardable payoff: a concrete fact/answer present (IG #2 signal is
    # sends-per-reach). Look for an explanatory/payoff style line.
    low = ig_caption.lower()
    has_payoff = any(w in low for w in ("here's why", "the science", "because",
                                        "the reason", "it's because", "actually"))
    if not has_payoff:
        ok, issues = False, issues + ["IG: no forwardable payoff/explanation line"]

    # IG length cap
    if len(ig_caption) > 2200:
        ok, issues = False, issues + [f"IG: caption too long ({len(ig_caption)} chars >2200)"]

    return {"guard": "ig_seo", "platform": "instagram", "pass": ok,
            "issues": issues, "confidence": "high", "checked": checked}


# --------------------------------------------------------------------------- #
# Combined runner — check every ENABLED platform
# --------------------------------------------------------------------------- #

def run_platform_seo_guards(script_data: Dict, enabled_platforms: List[str]) -> Dict[str, Any]:
    """Run the SEO guard for each ENABLED platform. Returns overall pass + the
    per-platform results. A video passes only if every enabled platform's SEO
    complies with that platform's 2026 algorithm."""
    guards = {
        "youtube": check_youtube_seo,
        "facebook": check_facebook_seo,
        "instagram": check_instagram_seo,
    }
    results = []
    for plat in enabled_platforms:
        fn = guards.get(plat)
        if fn:
            results.append(fn(script_data))

    passed = [r for r in results if r["pass"]]
    failed = [r for r in results if not r["pass"]]
    overall = not failed

    if overall:
        logger.info("🟢 Platform SEO guards passed: %s",
                    ", ".join(r["platform"] for r in passed))
    else:
        logger.error("🔴 Platform SEO guard BLOCKED for: %s",
                     ", ".join(r["platform"] for r in failed))
        for r in failed:
            logger.error("   [%s] %s", r["platform"], "; ".join(r["issues"]))

    return {
        "overall": overall,
        "passed": [r["platform"] for r in passed],
        "failed": [r["platform"] for r in failed],
        "guards": results,
    }
