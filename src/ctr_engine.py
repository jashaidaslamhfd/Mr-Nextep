"""High-CTR title & metadata engine for 2026 Shorts.

Modern Shorts CTR is won or lost in the title, first frame and thumbnail
before a single second is watched. This module generates curiosity-driven,
keyword-backed titles and hook lines that maximise click-through without
crossing into the engagement-bait that every 2026 feed demotes.

Used both for the deep-repair of already-uploaded videos and for future
uploads (src/main.py reads generate_high_ctr_title via the SEO step).

Design rules:
  * Pure functions — deterministic-ish, offline, testable.
  * Curiosity gap, not clickbait: titles raise a question the video answers.
  * Two-part structure: hook phrase + payoff hint, kept under the platform
    character budget so mobile feeds don't truncate.
  * Keyword terms kept so search/recommendation still matches.
  * Bait words (subscribe / smash like / tag someone) are stripped — those
    hurt 2026 completion and are treated as spam.
"""

from __future__ import annotations

import os
import re

# Power words that lift CTR in short-form 2026 feeds (curiosity + urgency).
POWER_WORDS = [
    "why", "real", "strange", "secret", "never", "actually", "every",
    "worst", "best", "shocking", "hidden", "weird", "crazy", "finally",
    "silently", "forever", "while", "without", "surprisingly",
]

# Emoji hooks — used sparingly (1 per title) to add visual contrast in the
# feed, which measurably raises CTR. Kept minimal & on-topic.
HOOK_EMOJIS = ["🧠", "⚡", "🫀", "👁️", "🌙", "🦠", "🔬", "😱", "🤯", "💥", "🪞", "🌀"]

# 2026-08 retention-first pass: the channel's own data showed the one-emoji
# machine template ("Why Your X 🫀" on 100+ videos) coinciding with template-
# detection demotion. TITLE_EMOJI_OFF=true (the new default) strips ALL emoji
# from repaired/new titles — a clean curiosity question outperforms the
# template. The guarantee lives in strip_emoji() and is enforced at the end of
# every exported title/hook, not only at generation time.
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\U0001F900-\U0001FA9F]"
)


def strip_emoji(text: str) -> str:
    """Strip every emoji/grapheme from a title. Idempotent; whitespace cleaned."""
    return re.sub(r"\s+", " ", EMOJI_RE.sub("", text)).strip().strip("-–—: ")


def _emoji_off() -> bool:
    """Operator switch (env or GitHub Actions env): true = no emoji ever."""
    return os.environ.get("TITLE_EMOJI_OFF", "true").strip().lower() in (
        "1", "true", "yes",
    )

BAIT_WORDS = [
    "subscribe", "like and subscribe", "smash that like", "hit the bell",
    "comment below", "tag someone", "share this", "follow for more", "like share",
]

_STOP = {
    "a", "an", "the", "and", "or", "but", "so", "of", "to", "in", "on",
    "for", "with", "your", "you", "is", "are", "was", "do", "does",
}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().strip("-–—: ")


def strip_bait(text: str) -> str:
    lowered = text.lower()
    for word in BAIT_WORDS:
        if word in lowered:
            text = re.sub(re.escape(word), "", text, flags=re.IGNORECASE)
    return _clean(re.sub(r"\s{2,}", " ", text))


def _topic_short(topic: str) -> str:
    """Extract a compact subject (<=5 words) from a topic/title for the hook.

    Handles the repo's real topic formats:
      'feeling like hours passed in minutes'   -> 'Hours Pass Like Minutes'
      'Why Your Body Does This: Memory Boost'  -> 'Memory Boost'
      'yawning spreading instantly person to person' -> 'Yawning Spreads'
      'Sleep Paralysis'                        -> 'Sleep Paralysis'
    """
    clean = _clean(topic)
    if not clean:
        return ""

    # Strip emoji
    clean = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", clean).strip()
    lowered = clean.lower()

    # Drop the "Why Your Body Does This: X" / "Why Your Body X" frames
    for prefix in ("why your body does this:", "why your body does this",
                   "why your body", "your body does this:", "your body"):
        if lowered.startswith(prefix):
            clean = clean[len(prefix):].strip(": ")
            lowered = clean.lower()
            break

    # Drop leading "why do you / why does / what happens when / feeling like"
    for prefix in ("what happens in the last seconds before you",
                   "what happens when", "feeling like you've", "feeling like",
                   "why do you", "why does your", "why does the",
                   "why you feel", "why your", "why you"):
        if lowered.startswith(prefix):
            clean = clean[len(prefix):].strip(" ?:,.!").strip()
            lowered = clean.lower()
            break

    # Strip "vice versa" and trailing filler
    clean = re.sub(r"\bvice versa\b", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\bfrom person to person\b", "", clean, flags=re.IGNORECASE).strip()

    # Keep only meaningful words, cap at 4 so the subject stays clean & short.
    words = []
    for w in clean.split():
        if not w:
            continue
        if w.lower() in _STOP and len(w) <= 3 and words:
            continue
        words.append(w)
        if len(words) >= 4:
            break
    subject = " ".join(words)
    return subject.strip() or clean


def _normalize_subject(subject: str) -> str:
    """Make the subject fit the "Why Your X" noun frame.

    Repairs the real-world inputs the repair engine feeds in:
      'We Got Fired in Animal Hospital Anomaly' -> 'Animal Hospital Anomaly'
      'Cold Hands Summer'                       -> 'Cold Hands'
      'Yawning Spreading Instantly'             -> 'Yawning Spreading'
    Keeps the most concrete noun phrase at the end (the keyword) and drops
    stray all-caps verbs, season fillers and duplicated gerund tails.
    """
    words = subject.split()
    drop_words = {
        "summer", "winter", "autumn", "spring", "every", "day", "night",
        "instantly", "suddenly", "automatically", "randomly",
    }
    kept = [w for w in words if w.lower() not in drop_words]
    # strip a leading ALL-CAPS verb/phrase that leaked in ("WE GOT FIRED")
    if kept and kept[0].isupper() and len(kept[0]) > 1 and kept[0].isalpha():
        kept = kept[1:]
    # collapse a duplicated tail: 'Yawning Spreading Spreading' -> 'Yawning Spreading'
    if len(kept) >= 2 and kept[-1].lower() == kept[-2].lower():
        kept = kept[:-1]
    return " ".join(kept) or subject


def _pick_head(subject: str) -> str:
    """Choose a readable, high-CTR opening phrase for a (already short) subject.

    Prefers the clean "Why Your X" frame for noun phrases and the always-
    grammatical "Why X Happens" for verb/action subjects. Returns just the
    head (no payoff) — the caller appends the payoff suffix.
    """
    core = _normalize_subject(subject)
    first = (core.split() or [""])[0].lower()

    action_verbs = {
        "feel", "feeling", "get", "getting", "have", "having", "be", "being",
        "go", "going", "fall", "falling", "freeze", "freezing", "shake",
        "shaking", "twitch", "twitching", "spread", "spreading", "cramp",
        "cramping", "sneeze", "sneezing", "jerk", "dream", "dreaming",
        "hiccup", "blink", "blinking", "tremble", "trembling", "burn",
        "itching", "wake", "waking", "sleep", "sleeping", "yawn", "yawning",
        "dizzy", "flush", "sweat", "stand", "standing", "breathe", "breathing",
        "smell", "see", "hear", "feel", "watch", "taste",
    }
    noun_hint = ("syndrome", "paralysis", "effect", "reflex", "jerk", "cramp",
                 "delusion", "response", "reason", "glitch", "disease",
                 "disorder", "condition", "science", "memory", "dream",
                 "paralysis", "palsy", "aphasia", "amnesia")

    is_action = first in action_verbs or first.endswith("ing")
    if any(core.lower().startswith(h) for h in noun_hint):
        is_action = False

    if is_action:
        return f"Why {core} Happens"
    return f"Why Your {core}"


def _title_case(subject: str) -> str:
    """Title-case a subject, preserving small connector words in lowercase."""
    out = []
    for i, w in enumerate(subject.split()):
        low = w.lower()
        if i > 0 and low in _STOP and len(w) <= 3:
            out.append(low)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def generate_high_ctr_title(topic: str, *, platform: str = "youtube") -> str:
    """Build a two-part, curiosity-driven, keyword-backed CTR title.

    Format examples:
      Why Hours Pass Like Minutes — The Real Reason 🤯
      Memory Boost While You Sleep — The Hidden Signal 🧠
      Why Yawning Spreads — What Your Brain Is Doing ⚡
    """
    subject = _topic_short(topic)
    if not subject:
        subject = "This Everyday Body Fact"
    subject = _title_case(subject)

    # Normalise the core for _pick_head: strip any leftover leading
    # "why/your/a/an/the" so we never build "Why Your Your X" or "Why Why X".
    core = re.sub(
        r"^(why\s+your\s+|why\s+|your\s+|a\s+|an\s+|the\s+)",
        "", subject, flags=re.IGNORECASE,
    ).strip()
    core = _normalize_subject(core)
    core = _title_case(core) if core else subject

    head = _pick_head(core)
    payoff = _pick_payoff(head, core)

    max_chars = 58 if platform == "youtube" else 55
    title = f"{head} — {payoff}"
    import random
    if len(title) + 3 <= max_chars:
        title += " " + random.choice(HOOK_EMOJIS)
    title = strip_bait(title)
    if _emoji_off():
        title = strip_emoji(title)
    # never exceed the mobile budget
    return title[:max_chars].strip()


def _pick_payoff(head: str, subject: str) -> str:
    """Choose a CTR payoff hint without over-promising (no engagement bait)."""
    candidates = [
        "The Real Reason",
        "A Hidden Body Signal",
        "Why It Actually Happens",
        "The Science Behind It",
        "What Your Brain Is Doing",
        "The Surprising Truth",
    ]
    # deterministic-ish pick based on subject hash so re-runs are stable
    seed = sum(ord(c) for c in subject) % len(candidates)
    return candidates[seed]


def generate_ctr_hook_line(topic: str) -> str:
    """A first-line caption/description hook that drives the click."""
    subject = _topic_short(topic)
    hooks = [
        f"Your {subject} isn't random — here's the actual science.",
        f"Most people have no idea why {subject} happens.",
        f"The real reason {subject} — explained in under a minute.",
        f"What {subject} really means (it's weirder than you think).",
    ]
    seed = sum(ord(c) for c in subject) % len(hooks)
    hook = strip_bait(hooks[seed])
    if _emoji_off():
        hook = strip_emoji(hook)
    return hook


def validate_title(title: str, *, max_chars: int = 60) -> dict:
    """Score a title for CTR health so repair only touches weak ones."""
    result = {"ok": True, "issues": []}
    t = _clean(title)
    if len(t) < 15:
        result["ok"] = False
        result["issues"].append("too short for a curiosity gap")
    if len(t) > max_chars:
        result["ok"] = False
        result["issues"].append("may truncate on mobile feeds")
    if not any(pw in t.lower() for pw in POWER_WORDS):
        result["ok"] = False
        result["issues"].append("no curiosity/power word")
    lowered = t.lower()
    for bait in BAIT_WORDS:
        if bait in lowered:
            result["ok"] = False
            result["issues"].append(f"engagement bait: {bait}")
            break
    if _emoji_off() and EMOJI_RE.search(t):
        result["ok"] = False
        result["issues"].append("emoji present while TITLE_EMOJI_OFF is enabled")
    return result
