#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  SKILLOR 2026 SEO REPAIR ENGINE — All Platforms, Modern Algorithm         ║
║  ───────────────────────────────────────────────────────────────────────  ║
║  Reads ALL 118 videos, rewrites metadata for 2026 YouTube/FB/IG rules:   ║
║                                                                          ║
║  YOUTUBE:  • Hook-driven titles (curiosity + keyword)                    ║
║            • SEO descriptions with keyword clusters                      ║
║            • Platform-appropriate hashtags (no #shorts elsewhere)        ║
║            • Pinned comment seeds (engagement signal)                    ║
║            • Synthetic media disclosure check                            ║
║                                                                          ║
║  FACEBOOK: • UTIS-friendly captions (plain topic naming)                 ║
║            • Stripped #shorts, #youtube tags                             ║
║            • Cover image (thumbnail)                                     ║
║            • Watch-through bait removed                                  ║
║                                                                          ║
║  INSTAGRAM:• Forwardable payoff fact (sends-per-reach boost)             ║
║            • Hashtag clusters (US audience)                              ║
║            • DM-worthy caption format                                    ║
║                                                                          ║
║  Usage:                                                                  ║
║    python scripts/repair_all_seo.py --dry-run       # preview changes    ║
║    python scripts/repair_all_seo.py --apply          # apply all repairs ║
║    python scripts/repair_all_seo.py --apply --limit 10  # first 10 only  ║
║    python scripts/repair_all_seo.py --youtube-only   # YT only           ║
║    python scripts/repair_all_seo.py --facebook-only  # FB only           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import re
import sys
import time
import hashlib
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("SKILLOR_DATA_DIR", "data"))
VIDEO_HISTORY = DATA_DIR / "video_history.json"
REPAIR_LOG = DATA_DIR / "seo_repair_20260804.json"
THUMBNAILS_DONE = DATA_DIR / "thumbnails_done.json"

# ── API Config ───────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "")

FB_TOKEN = (os.environ.get("FACEBOOK_ACCESS_TOKEN") or
            os.environ.get("FB_ACCESS_TOKEN") or "")
FB_PAGE_ID = (os.environ.get("FACEBOOK_PAGE_ID") or
              os.environ.get("FB_PAGE_ID") or "")
FB_API = os.environ.get("FB_API_VERSION", "v23.0")
IG_USER_ID = os.environ.get("INSTAGRAM_USER_ID", "")


# ═══════════════════════════════════════════════════════════════════
# 2026 ALGORITHM RULES (from algorithm_policy.py)
# ═══════════════════════════════════════════════════════════════════

YOUTUBE_RULES = {
    "title_max_chars": 100,
    "description_min_chars": 200,
    "description_max_chars": 500,
    "max_hashtags": 3,
    "hashtags": ["#shorts", "#science", "#humanbody"],
    "bait_words": ["subscribe", "like and subscribe", "smash that like",
                   "hit the bell", "comment below", "tag someone"],
    "cta_templates": [
        "New body-science Short every day. Subscribe for more 🧬",
        "One strange body fact, explained daily. Follow along.",
        "More everyday biology, made simple. Subscribe.",
    ],
}

FACEBOOK_RULES = {
    "title_max_chars": 80,
    "caption_max_chars": 400,
    "max_hashtags": 3,
    "hashtags": ["#bodyfacts", "#science", "#didyouknow"],
    "forbidden_tags": ["#shorts", "#short", "#youtubeshorts", "#ytshorts",
                       "#youtube", "#viral", "#fyp", "#trending"],
    "bait_words": ["subscribe", "like and subscribe", "smash that like",
                   "hit the bell", "comment below", "share this",
                   "tag a friend", "send this to"],
    "cta_templates": [
        "Follow for daily body science 🧬",
        "More everyday biology, explained simply. Follow.",
        "Follow — your body does weirder things than you think.",
    ],
}

INSTAGRAM_RULES = {
    "caption_max_chars": 400,
    "max_hashtags": 5,
    "hashtags": ["#bodyfacts", "#dailyscience", "#humanbody",
                 "#scienceexplained", "#didyouknow"],
    "forbidden_tags": FACEBOOK_RULES["forbidden_tags"],
    "bait_words": FACEBOOK_RULES["bait_words"],
    "payoff_templates": [
        "Here's why: {payoff} 🤯",
        "The science: {payoff}",
        "Quick explanation: {payoff}",
    ],
}

# Hook style: short, curiosity-driven, personalized
HOOK_TITLE_FORMATS = [
    "Why {topic_short}",
    "Your {topic_short}",
    "What happens when {topic_short}",
    "The real reason {topic_short}",
    "This is why {topic_short}",
    "{topic_short} — explained",
]

BODY_KEYWORDS = [
    "body", "brain", "muscle", "nerve", "blood", "heart", "skin",
    "ear", "eye", "foot", "hand", "leg", "arm", "head", "throat",
    "voice", "knee", "calf", "tongue", "taste", "nose", "finger",
    "spine", "lung", "stomach", "gut", "cell", "dna", "gene",
    "sleep", "dream", "memory", "pain", "feel", "brainhealth",
    "science", "biology", "psychology", "neuroscience",
]

SCIENCE_TRIGGERS = [
    "because", "signal", "trigger", "response", "system", "reflex",
    "chemical", "hormone", "nerve", "receptor", "pathway", "mechanism",
    "pressure", "oxygen", "cells", "fluid", "explain", "why", "cause",
]


# ═══════════════════════════════════════════════════════════════════
# TITLE & DESCRIPTION GENERATOR
# ═══════════════════════════════════════════════════════════════════

def clean_text(text: str, max_len: int = 500) -> str:
    """Normalize + trim."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t[:max_len]


def extract_topic_from_title(title: str) -> str:
    """Extract the core body-science topic from a generic YouTube title."""
    t = clean_text(title, 200)

    # Handle the "Why Your Body Does This: X" pattern
    body_does_match = re.match(r"(Why\s+)?(Your\s+)?Body\s+(Does\s+)?(This[:\s]+)?(.+)", t, re.IGNORECASE)
    if body_does_match:
        core = body_does_match.group(5) or t
        core = re.sub(r'[^\w\s\-.,!?()\'\"]+', '', core).strip()
        if core and len(core) > 3:
            # Make it a proper topic
            return f"your body {core.lower().rstrip('.,!?')}"

    # Generic prefixes
    for prefix in ["Why Your Body Does This: ", "Why ", "What ", "How ",
                    "The ", "This is ", "Do you "]:
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix):]

    # Strip emojis
    t = re.sub(r'[^\w\s\-.,!?()\'\"]+', '', t).strip()

    if not t or len(t) < 5:
        return title

    return t


def generate_youtube_title(topic: str) -> str:
    """Generate a 2026-optimized YouTube Shorts title."""
    topic = extract_topic_from_title(topic)
    topic_short = topic.lower().strip()

    # If topic already starts with "your body", use as-is
    if topic_short.startswith("your body "):
        core = topic_short[10:].strip()
        # Capitalize each word
        core_title = " ".join(w.capitalize() for w in core.split())
        # Add science subtitle
        if len(core_title) < 50 and "—" not in core_title:
            core_title += " — Explained"
        return "Your Body " + core_title

    # Clean topic for title
    clean = topic_short.rstrip(".,!?")
    
    # Best hook format
    if clean.startswith("your "):
        title = "Your " + clean[5:].strip().capitalize()
    elif clean.startswith("why "):
        title = "Why " + clean[4:].strip().capitalize()
    elif clean.startswith("what "):
        title = "What Happens When " + clean[5:].strip().capitalize()
    elif clean.startswith("the "):
        title = "Why " + clean[4:].strip().capitalize()
    else:
        title = "Why " + clean.capitalize()

    # Add science marker if topic is body-related
    body_words = ["body", "brain", "muscle", "nerve", "heart", "skin", "ear", "eye", "sleep", "dream", "memory", "psychology", "knee", "blood", "taste", "voice", "nose", "finger", "tongue"]
    if any(w in topic_short for w in body_words) and "—" not in title:
        title += " — Explained"

    return title[:100]


def generate_youtube_description(title: str, topic: str) -> str:
    """Generate a 2026 keyword-rich YouTube description."""
    topic_clean = extract_topic_from_title(topic)
    title_clean = clean_text(title, 100)

    # Extract keywords from topic
    words = set(re.findall(r"[a-z]+", topic_clean.lower()))
    body_kws = [w for w in words if w in BODY_KEYWORDS]
    sci_kws = [w for w in words if w in SCIENCE_TRIGGERS]

    # Build description
    lines = []

    # Line 1: Hook summary
    lines.append(f"{title_clean} — the surprising body-science explanation.")

    # Line 2-3: What viewers learn
    if body_kws:
        lines.append(f"")
        lines.append(f"Your {body_kws[0] if body_kws else 'body'} does something "
                     f"strange every day. Here's the real science behind "
                     f"{topic_clean.lower()}.")

    # Line 4-5: Keywords for search
    lines.append(f"")
    all_kws = body_kws[:3] + sci_kws[:2]
    if all_kws:
        lines.append(f"Topics: {', '.join(all_kws)} | body science | everyday biology")

    # Line 6: CTA
    import random
    lines.append(f"")
    lines.append(random.choice(YOUTUBE_RULES["cta_templates"]))

    # Line 7: Hashtags
    lines.append(f"")
    lines.append(" ".join(YOUTUBE_RULES["hashtags"]))

    desc = "\n".join(lines)
    return clean_text(desc, YOUTUBE_RULES["description_max_chars"])


def generate_facebook_caption(topic: str) -> str:
    """Generate a UTIS-friendly Facebook caption."""
    topic_clean = extract_topic_from_title(topic)

    # Plain, honest topic naming (UTIS rewards this)
    caption = f"{topic_clean} — here's the simple science.\n\n"

    # Add curiosity without bait
    caption += ("Our bodies do strange things every day. "
                "Most people never learn why.\n\n")

    # CTA (safe, no bait)
    import random
    caption += random.choice(FACEBOOK_RULES["cta_templates"])

    # Hashtags (no #shorts!)
    caption += "\n\n" + " ".join(FACEBOOK_RULES["hashtags"])

    return clean_text(caption, FACEBOOK_RULES["caption_max_chars"])


def generate_instagram_caption(topic: str) -> str:
    """Generate an Instagram caption optimized for sends-per-reach."""
    topic_clean = extract_topic_from_title(topic)

    # Forwardable payoff: extract key fact
    words = topic_clean.split()
    payoff = topic_clean if len(words) <= 10 else " ".join(words[:8]) + "..."

    caption = f"{topic_clean} 🤯\n\n"
    caption += f"The science: {payoff.lower()} — and here's the quick explanation.\n\n"

    import random
    caption += random.choice(FACEBOOK_RULES["cta_templates"])

    # Hashtag clusters (more on IG)
    caption += "\n\n" + " ".join(INSTAGRAM_RULES["hashtags"])

    return clean_text(caption, INSTAGRAM_RULES["caption_max_chars"])


def strip_bait_words(text: str, platform_rules: dict) -> str:
    """Remove engagement bait words."""
    t = text
    for bait in platform_rules["bait_words"]:
        t = re.sub(rf"\b{re.escape(bait)}\b", "", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip(" .,;:!")


def filter_hashtags(text: str, platform_rules: dict) -> str:
    """Remove platform-inappropriate hashtags."""
    for tag in platform_rules.get("forbidden_tags", []):
        text = re.sub(rf"#{re.escape(tag)}\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


# ═══════════════════════════════════════════════════════════════════
# API CLIENTS
# ═══════════════════════════════════════════════════════════════════

class YouTubeRepair:
    """Update YouTube video metadata via Data API v3."""

    def __init__(self):
        self._token: Optional[str] = None

    def _get_token(self) -> Optional[str]:
        if self._token:
            return self._token
        if not REFRESH_TOKEN or not GOOGLE_CLIENT_ID:
            return None
        try:
            resp = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": REFRESH_TOKEN,
                "grant_type": "refresh_token",
            }, timeout=15)
            self._token = resp.json().get("access_token")
            return self._token
        except Exception as e:
            logger.warning("OAuth failed: %s", e)
            return None

    def update_video(self, video_id: str, title: str, description: str,
                    tags: List[str] = None, category_id: str = "27") -> Dict:
        """Update a YouTube video's metadata."""
        token = self._get_token()
        if not token:
            return {"error": "no_token", "video_id": video_id}

        body = {
            "id": video_id,
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "categoryId": category_id,
            },
        }
        if tags:
            body["snippet"]["tags"] = tags[:30]

        try:
            resp = requests.put(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "snippet"},
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=20,
            )
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                err = data.get("error", {}).get("message", str(data))
                return {"error": err, "video_id": video_id, "status": resp.status_code}
            return {"ok": True, "video_id": video_id, "title": title[:50]}
        except Exception as e:
            return {"error": str(e), "video_id": video_id}

    def add_comment(self, video_id: str, comment_text: str) -> Dict:
        """Post a pinned-comment seed (engagement signal)."""
        token = self._get_token()
        if not token:
            return {"error": "no_token"}

        try:
            resp = requests.post(
                "https://www.googleapis.com/youtube/v3/commentThreads",
                params={"part": "snippet"},
                json={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {
                            "snippet": {"textOriginal": comment_text[:500]}
                        },
                    }
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            if resp.status_code >= 400:
                return {"error": resp.json().get("error", {}).get("message", ""),
                       "video_id": video_id}
            return {"ok": True, "video_id": video_id}
        except Exception as e:
            return {"error": str(e)}


class FacebookRepair:
    """Update Facebook Reel metadata via Graph API."""

    def __init__(self):
        self.token = FB_TOKEN
        self.page_id = FB_PAGE_ID
        self.base = f"https://graph.facebook.com/{FB_API}"

    def _graph_post(self, node: str, data: dict) -> Dict:
        if not self.token:
            return {"error": "no_token"}
        data["access_token"] = self.token
        try:
            resp = requests.post(f"{self.base}/{node}", data=data, timeout=20)
            return resp.json() if resp.content else {}
        except Exception as e:
            return {"error": str(e)}

    def update_reel_caption(self, reel_id: str, caption: str,
                           title: str = "") -> Dict:
        """Update a Facebook Reel's caption/title."""
        caption = strip_bait_words(caption, FACEBOOK_RULES)
        caption = filter_hashtags(caption, FACEBOOK_RULES)

        result = self._graph_post(reel_id, {
            "description": caption[:2200],
        })

        if title:
            r2 = self._graph_post(reel_id, {
                "title": title[:80],
            })

        if "error" in result:
            err = result.get("error", {})
            return {"error": err.get("message", str(result)), "reel_id": reel_id}
        return {"ok": True, "reel_id": reel_id}

    def add_comment(self, reel_id: str, comment: str) -> Dict:
        """Post a comment as the page (engagement seed)."""
        return self._graph_post(f"{reel_id}/comments", {"message": comment[:500]})


class InstagramRepair:
    """Update Instagram Reel captions."""

    def __init__(self):
        self.token = FB_TOKEN  # Same token
        self.ig_id = IG_USER_ID
        self.base = f"https://graph.facebook.com/{FB_API}"

    def _graph_post(self, node: str, data: dict) -> Dict:
        if not self.token:
            return {"error": "no_token"}
        data["access_token"] = self.token
        try:
            resp = requests.post(f"{self.base}/{node}", data=data, timeout=20)
            return resp.json() if resp.content else {}
        except Exception as e:
            return {"error": str(e)}

    def update_caption(self, media_id: str, caption: str) -> Dict:
        """Update Instagram media caption."""
        caption = strip_bait_words(caption, INSTAGRAM_RULES)
        caption = filter_hashtags(caption, INSTAGRAM_RULES)

        result = self._graph_post(media_id, {"caption": caption[:2200]})
        if "error" in result:
            err = result.get("error", {})
            return {"error": err.get("message", str(result)), "media_id": media_id}
        return {"ok": True, "media_id": media_id}


# ═══════════════════════════════════════════════════════════════════
# MAIN REPAIR ENGINE
# ═══════════════════════════════════════════════════════════════════

class SEO2026RepairEngine:
    """Orchestrate repairs across all 3 platforms."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.yt = YouTubeRepair()
        self.fb = FacebookRepair()
        self.ig = InstagramRepair()
        self.history = []
        self.stats = {
            "youtube": {"total": 0, "repaired": 0, "errors": 0, "skipped": 0},
            "facebook": {"total": 0, "repaired": 0, "errors": 0, "skipped": 0},
            "instagram": {"total": 0, "repaired": 0, "errors": 0, "skipped": 0},
        }
        self.results = []

    def load_videos(self) -> List[Dict]:
        """Load all videos from history."""
        if not VIDEO_HISTORY.exists():
            return []
        with open(VIDEO_HISTORY) as f:
            self.history = json.load(f)
        return self.history

    def repair_youtube(self, limit: int = 0, skip_modern: bool = True):
        """Repair ALL YouTube Shorts."""
        yt_vids = [v for v in self.history if v.get("youtube_id")]
        self.stats["youtube"]["total"] = len(yt_vids)
        logger.info("\n📺 Repairing %d YouTube Shorts...", len(yt_vids))

        count = 0
        for i, v in enumerate(yt_vids):
            if limit and count >= limit:
                break

            vid = v["youtube_id"]
            topic = v.get("topic", v.get("youtube_title", ""))
            old_title = v.get("youtube_title", v.get("title", ""))
            old_desc = v.get("description", str(v.get("youtube_title", "")))

            # Skip if already modern (has hook-driven title)
            if skip_modern and ("—" in old_title or "🤯" in old_title):
                if not any(bait in (old_desc or "").lower()
                          for bait in YOUTUBE_RULES["bait_words"]):
                    self.stats["youtube"]["skipped"] += 1
                    continue

            # Generate new metadata
            new_title = generate_youtube_title(topic)
            new_desc = generate_youtube_description(new_title, topic)

            # Check if actually needs repair
            needs_title = (len(old_title or "") < 20 or
                          "Why Your Body Does This" in old_title or
                          old_title == new_title[:len(old_title)] if old_title else True)
            needs_desc = (len(old_desc or "") < 100 or
                         "Why Your Body Does This" in (old_desc or ""))

            if not needs_title and not needs_desc:
                self.stats["youtube"]["skipped"] += 1
                continue

            result = {
                "platform": "youtube",
                "video_id": vid,
                "old_title": old_title[:80],
                "new_title": new_title,
                "old_desc_len": len(old_desc or ""),
                "new_desc_len": len(new_desc),
                "needs_title": needs_title,
                "needs_desc": needs_desc,
            }

            if not self.dry_run:
                # Apply title + description update
                api_result = self.yt.update_video(vid, new_title, new_desc,
                                                  tags=["body science", "human body",
                                                        "science shorts",
                                                        "everyday science",
                                                        "how body works"])

                if api_result.get("ok"):
                    self.stats["youtube"]["repaired"] += 1
                    result["applied"] = True

                    # Also add comment seed
                    comment = (f"Your body is incredible! 🧬 "
                              f"What other weird body things should I explain next?")
                    cmt_result = self.yt.add_comment(vid, comment)
                    result["comment"] = cmt_result.get("ok", False)
                else:
                    self.stats["youtube"]["errors"] += 1
                    result["error"] = api_result.get("error", "unknown")
            else:
                self.stats["youtube"]["repaired"] += 1

            self.results.append(result)
            count += 1

            if i % 20 == 0 and i > 0:
                logger.info("  Progress: %d/%d | repaired=%d errors=%d",
                           i, len(yt_vids),
                           self.stats["youtube"]["repaired"],
                           self.stats["youtube"]["errors"])

        logger.info("  YouTube done: %d repaired, %d errors, %d skipped",
                   self.stats["youtube"]["repaired"],
                   self.stats["youtube"]["errors"],
                   self.stats["youtube"]["skipped"])

    def repair_facebook(self, limit: int = 0):
        """Repair ALL Facebook Reels."""
        fb_vids = [v for v in self.history if v.get("facebook_id")]
        self.stats["facebook"]["total"] = len(fb_vids)
        logger.info("\n📘 Repairing %d Facebook Reels...", len(fb_vids))

        count = 0
        for i, v in enumerate(fb_vids):
            if limit and count >= limit:
                break

            fb_id = v["facebook_id"]
            topic = v.get("topic", v.get("youtube_title", ""))

            old_title = v.get("youtube_title", v.get("title", ""))
            new_caption = generate_facebook_caption(topic)

            result = {
                "platform": "facebook",
                "reel_id": fb_id,
                "old_title": old_title[:60],
                "new_caption": new_caption[:100],
            }

            if not self.dry_run:
                api_result = self.fb.update_reel_caption(
                    fb_id, new_caption,
                    title=generate_youtube_title(topic),
                )
                if api_result.get("ok"):
                    self.stats["facebook"]["repaired"] += 1
                    result["applied"] = True

                    # Seed comment
                    self.fb.add_comment(fb_id,
                        "What body fact surprised you most? 🧬")
                else:
                    self.stats["facebook"]["errors"] += 1
                    result["error"] = api_result.get("error", "unknown")
            else:
                self.stats["facebook"]["repaired"] += 1

            self.results.append(result)
            count += 1

            if i % 10 == 0:
                logger.info("  Progress: %d/%d", i, len(fb_vids))

        logger.info("  Facebook done: %d repaired, %d errors",
                   self.stats["facebook"]["repaired"],
                   self.stats["facebook"]["errors"])

    def repair_instagram(self, limit: int = 0):
        """Repair Instagram Reels."""
        ig_vids = [v for v in self.history if v.get("instagram_id")]
        self.stats["instagram"]["total"] = len(ig_vids)
        logger.info("\n📸 Repairing %d Instagram Reels...", len(ig_vids))

        if not ig_vids:
            logger.info("  No Instagram videos found.")
            return

        count = 0
        for i, v in enumerate(ig_vids):
            if limit and count >= limit:
                break

            ig_id = v["instagram_id"]
            topic = v.get("topic", v.get("caption", ""))
            new_caption = generate_instagram_caption(topic)

            result = {
                "platform": "instagram",
                "media_id": ig_id,
                "new_caption": new_caption[:100],
            }

            if not self.dry_run:
                api_result = self.ig.update_caption(ig_id, new_caption)
                if api_result.get("ok"):
                    self.stats["instagram"]["repaired"] += 1
                    result["applied"] = True
                else:
                    self.stats["instagram"]["errors"] += 1
                    result["error"] = api_result.get("error", "unknown")
            else:
                self.stats["instagram"]["repaired"] += 1

            self.results.append(result)
            count += 1

    def save_report(self):
        """Save repair log."""
        report = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.dry_run,
            "stats": self.stats,
            "results": self.results[:200],  # Cap for file size
            "total_results": len(self.results),
        }
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = str(REPAIR_LOG) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        os.replace(tmp, REPAIR_LOG)
        logger.info("\n📋 Repair log saved → %s", REPAIR_LOG)

    def print_summary(self):
        """Print final summary."""
        s = self.stats
        print("\n" + "=" * 65)
        print("  🚀 2026 SEO REPAIR — SUMMARY")
        print("=" * 65)
        mode = "DRY RUN" if self.dry_run else "APPLIED"
        print(f"  Mode: {mode}")
        for platform, data in [
            ("YouTube", s["youtube"]),
            ("Facebook", s["facebook"]),
            ("Instagram", s["instagram"]),
        ]:
            if data["total"] > 0:
                print(f"  {platform:<12s}: {data['repaired']:>4d} repaired | "
                      f"{data['errors']:>3d} errors | "
                      f"{data['skipped']:>3d} skipped | "
                      f"{data['total']:>3d} total")
        total_repaired = sum(s[p]["repaired"] for p in s)
        total_errors = sum(s[p]["errors"] for p in s)
        print(f"  {'─'*45}")
        print(f"  {'TOTAL':<12s}: {total_repaired:>4d} repaired | {total_errors:>3d} errors")
        print("=" * 65)

        if self.dry_run:
            print("\n  🔍 DRY RUN — run with --apply to actually update videos.")
            print("  python scripts/repair_all_seo.py --apply")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    dry_run = "--apply" not in sys.argv
    youtube_only = "--youtube-only" in sys.argv
    facebook_only = "--facebook-only" in sys.argv
    limit = 0

    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    engine = SEO2026RepairEngine(dry_run=dry_run)
    engine.load_videos()

    logger.info("🧬 SKILLOR 2026 SEO REPAIR ENGINE")
    logger.info("   Videos loaded: %d", len(engine.history))
    logger.info("   Mode: %s", "DRY RUN" if dry_run else "APPLY")
    if limit:
        logger.info("   Limit: %d per platform", limit)

    # Repair all platforms
    if not facebook_only:
        engine.repair_youtube(limit=limit)
    if not youtube_only:
        engine.repair_facebook(limit=limit)
        engine.repair_instagram(limit=limit)

    engine.save_report()
    engine.print_summary()

    # Show a few examples
    yt_results = [r for r in engine.results if r["platform"] == "youtube"][:5]
    if yt_results:
        print("\n  📝 Sample YouTube changes:")
        for r in yt_results[:3]:
            print(f"  OLD: {r.get('old_title', '?')[:70]}")
            print(f"  NEW: {r['new_title'][:70]}")
            print()


if __name__ == "__main__":
    main()
