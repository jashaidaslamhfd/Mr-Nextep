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
# Body-science noun anchors. A "Why Your X" head only stays grammatical when
# X is anchored to a real biological subject. Topics that reduce to subjects
# without any anchor below (e.g. "Funny Video Science", "Regression Mean")
# produced live gibberish titles — see the 2026-08-15 title-quality fix.
_SUBJECT_ANCHORS = {
    "brain", "body", "mind", "sleep", "memory", "muscle", "nerve", "eye",
    "eyes", "heart", "skin", "pain", "dream", "dreams", "reflex", "signal",
    "hormone", "cell", "blood", "immune", "gut", "stomach", "lungs", "breath",
    "voice", "ear", "ears", "hair", "teeth", "jaw", "spine", "bone", "skin",
    "fever", "yawn", "yawning", "sneeze", "sneezing", "twitch", "cramp",
    "itch", "goosebumps", "hiccup", "hiccups", "blush", "sweat", "freeze",
    "shiver", "shiver", "freeze", "atonia", "paralysis", "inertia", "circadian",
    "retention", "focus", "attention", "emotion", "fear", "stress", "anxiety",
    "panic", "calm", "fatigue", "groggy", "insomnia", "nap", "caffeine",
    "adrenaline", "cortisol", "melatonin", "serotonin", "dopamine",
    "vision", "hearing", "taste", "smell", "touch", "balance", "posture",
    "breathing", "heart rate", "pulse", "blood pressure", "temperature",
    "hour", "hours", "minute", "minutes", "second", "seconds",
    "cold", "heat", "warmth", "pressure", "gravity", "motion", "time",
    "science", "fact", "facts", "signal", "glitch", "quirk", "habit",
    "instinct", "survival", "evolution", "genetics", "dna", "aging",
}
# Category words that belong in a search-friendly TITLE ("The Science Of X")
# but do NOT count as a real noun subject for the "Why Your X" head — "Funny
# Video Science" contains "science" yet is still gibberish.
_SUBJECT_CATEGORY_WORDS = {"science", "fact", "facts", "signal"}
# A head must not be anchored ONLY by category words; the remaining tokens
# must themselves be meaningful (no malformed-marker junk).
# Words that can never open a coherent "Why Your X" noun head on their own —
# if the first token is one of these, fall back to the "Why X Happens" frame.
_HEAD_VERB_OPENERS = {
    "feel", "feeling", "get", "getting", "have", "having", "be", "being",
    "go", "going", "fall", "falling", "make", "makes", "making", "give",
    "gives", "giving", "do", "does", "doing", "see", "seeing", "hear",
    "hearing", "watch", "watching", "run", "running", "turn", "turning",
    "work", "works", "working", "grow", "growing", "lose", "losing",
    "stop", "stopped", "stopping", "keep", "keeps", "keeping", "forget",
    "forgot", "remember", "remembers", "remembering", "laugh", "laughing",
    "cry", "crying", "talk", "talking", "think", "thinking", "know",
    "knew", "understand", "try", "trying", "happen", "happens", "happened",
}
# Words that usually mark a malformed/LLM-leaked topic rather than a real
# body-science subject (e.g. "Why a 'Funny' Video Is Science" variants).
_MALFORMED_MARKERS = {"video", "videos", "mean", "means", "matters", "funny",
                      "random", "explain", "explained", "regression"}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().strip("-–—: ")

def _topic_fallback_title(topic: str, limit: int = 8) -> str:
    """A clean, always-grammatical fallback built straight from the topic.

    Keeps the topic's own words (trimmed to `limit`) so the fallback is
    always grammatical; a malformed topic never surfaces as a gibberish
    two-part title.
    """
    # The original topic text is always grammatical, so the fallback keeps it
    # intact (trimmed to the word budget) instead of rebuilding it from
    # keywords. Only stray emoji are removed — never the words. Stripping the
    # "why your / what happens when" frames here is what destroyed titles
    # like "Why Your Brain Freezes When Falling Asleep" (2026-08-15 fix).
    clean = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "",
                   _clean(topic)).strip()
    if not clean:
        return "Science Made Simple Today"
    words = [w for w in clean.split() if w.strip()
             and not set(w) <= set(".,!?-'\"")
             and w.strip("'\"").lower() not in _MALFORMED_MARKERS]
    out = _title_case(" ".join(words[:limit]))
    if not out:
        # Fully malformed topic (nothing readable left) — generic anchor title.
        return "Science Made Simple Today"
    return strip_bait(out)


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

    # Drop the "Why Your Body Does This: X" frame (the branded series frame
    # stored in repo topics). The loose "why your body" prefix is intentionally
    # REMOVED here — "Why Your Body Jerks to Sleep" must keep "Body" as its
    # subject, which the loose strip destroyed (2026-08-15 fix).
    for prefix in ("why your body does this:", "why your body does this",
                   "your body does this:"):
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

    # Keep only meaningful words, cap at 5 so the subject stays clean &
    # short. Body-science anchors are NEVER dropped (even stop-like ones such
    # as "body"/"brain" which were lost in the old filter). A 2026-08-15
    # quality fix: the subject must retain its concrete noun, e.g. "Body
    # Jerks to Sleep" must not shrink to "Jerks Sleep".
    words = []
    for w in clean.split():
        if not w:
            continue
        low = w.lower().rstrip("s,.!?")
        if low in _SUBJECT_ANCHORS:
            words.append(w)
        elif w.lower() in _STOP and len(w) <= 3 and words:
            continue
        else:
            words.append(w)
        if len(words) >= 5:
            break
    subject = " ".join(words)
    return subject.strip() or clean


def _day_is_filler(word: str, words: list[str]) -> bool:
    """'day' is filler in 'every day' / 'all day'; a bare 'day' is a noun."""
    idx = next(i for i, w in enumerate(words) if w.lower() == word.lower())
    before = words[idx-1].lower() if idx > 0 else ""
    return before in {"every", "all", "each", "any"}


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
    # 2026-08-15 fix: "day" is filler only in pairs like "every day" / "all
    # day". A bare "day" is a real subject noun ("Bad Day") and must not be
    # eaten by the drop list.
    kept = []
    for i, w in enumerate(words):
        low = w.lower()
        # 2026-08-15 fix: "day" is filler ONLY in the pairs "every day" /
        # "all day". A bare "day" is a real subject noun ("Bad Day") — the old
        # filter dropped it, producing "Why Your Brain Rewrites Bad".
        is_paired_filler = (
            low == "day" and i > 0
            and words[i-1].lower() in {"every", "all", "each", "any"}
        )
        # Drop every filler word, but spare a bare "day" — it is a real
        # noun ("Bad Day"). Only the paired "every day"/"all day" drops.
        if low in drop_words and (low != "day" or is_paired_filler):
            continue
        kept.append(w)
    # Leftover frame words ("Why Brain Rewrites a Bad Day") are never part of
    # the noun core — strip them here so _pick_head cannot build
    # "Why Your Why ...".
    while kept and kept[0].lower() in {"why", "how"}:
        kept = kept[1:]
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
    lower_core = core.lower()
    tokens = lower_core.split()
    clean_tokens = [tok.rstrip("s,.!?") for tok in tokens]
    has_strong_anchor = any(
        tok in _SUBJECT_ANCHORS and tok not in _SUBJECT_CATEGORY_WORDS
        for tok in clean_tokens
    )
    has_any_anchor = any(tok in _SUBJECT_ANCHORS for tok in clean_tokens)
    opens_as_verb = first in _HEAD_VERB_OPENERS
    # Junk subjects contain malformed-marker words ("video", "mean", "funny",
    # "regression"...). Even "Regression Mean Brain" must not be published.
    has_junk = any(tok in _MALFORMED_MARKERS for tok in clean_tokens)
    is_action = (first in action_verbs or first.endswith("ing")) and not has_any_anchor
    if any(core.lower().startswith(h) for h in noun_hint):
        is_action = False
    # 2026-08-15 title-quality fix: never build "Why Your {garbage}". The
    # "Why Your X" frame only stays grammatical when X anchors to a real
    # biological subject with no malformed-marker junk; otherwise use the
    # always-grammatical "Why X Happens" frame. Examples of subjects caught
    # here: "Funny Video Science", "Regression Mean", "Atonia Fail".
    if has_junk or (not has_strong_anchor and not opens_as_verb
                    and not core.endswith("ing")):
        return f"Why {core} Happens" if tokens else f"Why This Happens"
    if (is_action or opens_as_verb) and has_anchor and not has_strong_anchor:
        # "Why Your X" for a weakly-anchored subject still reads broken
        # ("Why Your Cold Hands"); prefer the Happens frame.
        return f"Why {core} Happens"
    if is_action or opens_as_verb:
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
    # 2026-08-15 title-quality fix: if the generated head still fails the
    # gibberish guard (malformed topic input), abandon the template entirely
    # and fall back to the topic's own phrasing — it is always grammatical.
    check = validate_title(title, max_chars=max_chars)
    if not check["ok"]:
        fallback = _topic_fallback_title(topic)
        fallback = strip_bait(fallback)
        if len(fallback) + 3 <= max_chars:
            import random as _rnd
            fallback += " " + _rnd.choice(HOOK_EMOJIS)
        title = fallback[:max_chars].strip()
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
    if _head_is_incoherent(t):
        result["ok"] = False
        result["issues"].append("head is not a real subject (gibberish guard)")
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


def _head_is_incoherent(title: str) -> bool:
    """Detect titles whose opening head is not a real English subject.

    Catches the live gibberish patterns seen on 2026-08-15:
      "Why Your Funny Video Science — ..."
      "Why Get Funny Videos From Happens — ..."
    A head built as "Why Your X" is only coherent when X contains a
    body-science anchor; "Why X Happens" must not chain two bare verbs.
    """
    lowered = _clean(title).lower()
    head = lowered.split("—")[0].split(" - ")[0].strip()
    m = re.match(r"^(why (your|you)\s+)?(.+)$", head)
    if not m:
        return False
    words = m.group(3).split()
    if not words:
        return True
    clean_words = [w.rstrip("s,.!?") for w in words]
    # A malformed input that leaked into the hook like "Why Get Funny Videos"
    # starts the head itself with a bare verb — never coherent.
    if clean_words[0] in _HEAD_VERB_OPENERS:
        return True
    # Junk-marker words anywhere in the head ("Funny Video", "Regression Mean")
    # make it incoherent even if a category word like "science"/"brain" appears.
    if any(w in _MALFORMED_MARKERS for w in clean_words):
        return True
    # If none of the head tokens anchor to a real subject, the head is junk.
    if not any(w in _SUBJECT_ANCHORS for w in clean_words):
        return True
    # A head anchored ONLY by category words ("Video Science", "Mean Brain"...)
    # with everything else being junk is still incoherent.
    strong = [w for w in clean_words
              if w in _SUBJECT_ANCHORS and w not in _SUBJECT_CATEGORY_WORDS]
    if not strong:
        return True
    return False
