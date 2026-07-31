#!/usr/bin/env python3
"""
scripts/meta_seo_repair.py — Meta (Facebook + Instagram) Reels SEO repair.

Why this exists
---------------
15/15 Facebook reels uploaded by SKILLOR had their captions TRUNCATED mid-sentence
("...and a simple way to redu", "...why your body shivers when you're extremely ner")
because the caption writer appended "Learn..." after a hook that was already at
the Meta length cap. Truncated captions:
  - break Meta's on-topic classifier (UTIS) so reels aren't bucketed into the
    right interest audiences,
  - miss every hashtag and follow CTA,
  - look low-quality in the Reels feed.
3/3 Instagram reels had blank / generic captions and no fold-friendly first line.

This script:
  1. Lists every reel the page / IG business account has published.
  2. Rebuilds a tight caption for each one: a ≤88-char curiosity lead (IG fold-
     safe), a 130-140 char body sentence, a follow CTA, and hygiene-checked tags.
  3. Scores the old vs new caption (0-10). Only patches when the new caption
     is clearly better (score gap OR truncated OR cross-posted YouTube tags).
  4. Optionally posts a seed comment on reels with 0 comments (kick-starts the
     engagement signal Meta's algorithm waits for on a cold page).
  5. Always idempotent: re-running doesn't double-patch or add duplicate tags.
  6. Offline-safe: compiles, imports and unit-tests without a token.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import urllib.request
import urllib.parse
import urllib.error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

TOKEN = os.environ.get("FB_ACCESS_TOKEN", "")
PAGE_ID = os.environ.get("FB_PAGE_ID") or os.environ.get("FACEBOOK_PAGE_ID", "")
IG_USER = os.environ.get("INSTAGRAM_USER_ID", "")
API = os.environ.get("FB_API_VERSION", "v23.0")

UPLOAD_STATE_PATH = DATA / "upload_state.json"
HISTORY_PATH = DATA / "video_history.json"
REPAIR_LOG_PATH = DATA / f"meta_seo_repair_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

# ---------------------------------------------------------------------------
# Graph helpers (kept tiny — no heavy SDK dependency so the workflow stays
# fast and the script works on the bare runner).
# ---------------------------------------------------------------------------

def _gget(path: str, **params) -> Dict[str, Any]:
    url = f"https://graph.facebook.com/{API}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": {"message": str(e), "code": e.code}}


def _gpost(path: str, **params) -> Dict[str, Any]:
    url = f"https://graph.facebook.com/{API}/{path.lstrip('/')}"
    data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    req = urllib.request.Request(url, data=data, headers={"Authorization": f"Bearer {TOKEN}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": {"message": str(e), "code": e.code}}


# Keep module-level short aliases used elsewhere.
gget = _gget
gpost = _gpost

PAGE = PAGE_ID  # convenient alias used in _list_fb

# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

_STOP = {"the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for",
        "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "can", "could", "this", "that", "these", "those", "you", "your", "yours",
        "i", "me", "my", "we", "us", "our", "it", "its", "they", "them", "their",
        "what", "when", "where", "why", "how", "if", "then", "than", "just",
        "really", "about", "into", "over", "out", "up", "down", "off", "why",
        "here", "there", "so", "because", "learn", "discover", "find", "ever",
        "noticed", "know", "did", "wonder", "wondered", "feel", "felt"}

_FRAGMENT_TAIL = {"when", "and", "but", "or", "do", "to", "of", "in", "on", "at",
                  "up", "like", "for", "with", "the", "a", "an", "your", "you",
                  "is", "are", "extremely", "ner", "red", "sim", "qui", "sim",
                  "a", "si", "sim", "b", "disc", "qui", "scared", "scary",
                  "col", "red", "caus", "sci", "no", "hyp", "discov", "simpl",
                  "scientist", "link", "sh"}

_BODY_PARTS = ("calf", "leg", "foot", "feet", "knee", "knees", "hand", "hands",
              "finger", "fingers", "arm", "eye", "eyes", "ear", "ears", "nose",
              "mouth", "throat", "neck", "back", "stomach", "gut", "chest",
              "heart", "lung", "brain", "skin", "hair", "teeth", "tooth",
              "tongue", "lip", "voice", "body", "muscle", "bone", "joint",
              "voice", "lump", "pupil", "vision")
_BODY_PART_RE = re.compile(rf"\b({'|'.join(_BODY_PARTS)})\b", re.I)

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F000-\U0001F2FF"
    "]+", flags=re.UNICODE)

# Exhaustive lead-in patterns that the previous caption writer / hook generator
# prepended. We strip ALL of them iteratively so stacking ("Ever noticed Have you
# ever noticed X") collapses cleanly to X.
_LEAD_STRIP_PATTERNS = [
    r"^have\s+you\s+ever\s+(?:noticed|wondered|felt|seen|experienced|had|thought(?:\s+about)?|asked\s+yourself)\s+",
    r"^did\s+you\s+ever\s+(?:notice|wonder|feel|see|experience|have|think)\s+",
    r"^do\s+you\s+ever\s+(?:notice|wonder|feel|see|experience|have|think)\s+",
    r"^ever\s+(?:noticed?|wondered?|felt?|seen?|experienced?|had|thought(?:\s+about)?|asked\s+yourself)\s+",
    r"^you've\s+noticed\s+it\s+before\s*,\s*but\s+why\s+do\s+",
    r"^you\s+know\s+that\s+feeling\s+(?:when|where|of)\s+",
    r"^do\s+you\s+know\s+why\s+",
    r"^did\s+you\s+know\s+",
    r"^here(?:'s| is)\s+why\s+",
    r"^here(?:'s| is)\s+the\s+science\s+behind\s+",
    r"^what\s+happens\s+(?:when|if)\s+",
    r"^why\s+do\s+",
    r"^why\s+does\s+",
    r"^why\s+is\s+",
    r"^the\s+reason\s+why\s+",
    r"^learn\s+(?:why|how|what|about)\s+",
    r"^discover\s+(?:why|how|what|about)\s+",
    r"^find\s+out\s+(?:why|how|what)\s+",
    r"^here(?:'s| is)\s+",
    r"^ever\s+wondered\s+why\s+",
    r"^you\s+know\s+",
]
_LEAD_STRIP_RES = [re.compile(p, re.I) for p in _LEAD_STRIP_PATTERNS]

_LEAD_TAIL_RE = re.compile(r"\s*[—\-–]{1,3}\s*the\s+science\.?\s*$", re.I)

# Hashtag hygiene
_BANNED_TAGS = {"#shorts", "#youtubeshorts", "#ytshorts", "#fyp", "#foryou",
                "#foryoupage", "#viral", "#viralshorts", "#fypシ", "#viralreels",
                "#trending", "#reels", "#reelsfb", "#reelsinstagram", "#share",
                "#likeforlike", "#followforfollowback", "#followme", "#tagafriend",
                "#tagyourfriends", "#subscribetomychannel", "#linkinbio",
                "#subscribe", "#like", "#comment", "#sharethis", "#repost"}

_BODY_HASHTAGS_FB = ["#BodyScience", "#HumanBody", "#ScienceFacts"]
_BODY_HASHTAGS_IG = ["#BodyScience", "#HumanBodyFacts", "#ScienceExplained",
                     "#EverydayScience", "#BiologyFacts"]

_PILLAR_TAGS = {
    "eye":   ["#VisionFacts", "#EyeHealth"],
    "ear":   ["#EarScience", "#Tinnitus", "#AuditorySystem"],
    "brain": ["#Neuroscience", "#BrainFacts", "#PsychologyFacts"],
    "heart": ["#HeartHealth", "#CardioFacts"],
    "muscle":["#MuscleFacts", "#JointHealth", "#Cramps"],
    "gut":   ["#GutHealth", "#DigestiveHealth"],
    "skin":  ["#SkinScience", "#DermatologyFacts"],
    "breath":["#Breathing", "#RespiratoryHealth"],
    "nerve": ["#NervousSystem", "#NerveFacts"],
}

_BODY_KEYWORDS = {
    "calf": ("#CalfCramps", "#MuscleFacts"),
    "cramp": ("#Cramps", "#MuscleFacts"),
    "ear": ("#EarScience", "#Hearing"),
    "ring": ("#Tinnitus", "#EarHealth"),
    "throat": ("#ThroatFacts", "#WhyWeCry"),
    "lump": ("#Emotions", "#BodyResponse"),
    "freeze": ("#FearResponse", "#FightOrFlight"),
    "shiver": ("#Goosebumps", "#FearResponse"),
    "yawn": ("#Yawning", "#Contagious"),
    "knee": ("#JointHealth", "#BodyFacts"),
    "crack": ("#JointHealth", "#CrackingJoints"),
    "mouth": ("#DryMouth", "#NervousSystem"),
    "wake": ("#MorningVoice", "#VocalCords"),
    "voice": ("#VoiceFacts", "#SpeechScience"),
    "song": ("#Earworm", "#BrainFacts"),
    "stuck": ("#Earworm", "#BrainLoops"),
    "forget": ("#DoorwayEffect", "#MemoryFacts"),
    "room": ("#DoorwayEffect", "#MemoryFacts"),
    "scary": ("#FearResponse", "#HorrorMovies"),
    "movie": ("#FearResponse", "#BodyFacts"),
    "gut": ("#GutHealth", "#Microbiome"),
    "bacteria": ("#GutHealth", "#Microbiome"),
    "brush": ("#GagReflex", "#DentalFacts"),
    "teeth": ("#GagReflex", "#DentalFacts"),
    "wrinkle": ("#SkinScience", "#WaterHands"),
    "water": ("#SkinScience", "#PruneyFingers"),
    "deja": ("#DejaVu", "#BrainFacts"),
    "familiar": ("#DejaVu", "#BrainFacts"),
    "heartbeat": ("#HeartHealth", "#BodyPulse"),
    "heart": ("#HeartFacts", "#Cardio"),
    "dizzy": ("#Orthostatic", "#StandingUpFast"),
    "stand": ("#DizzySpells", "#BloodFlow"),
    "numb": ("#SleepingFoot", "#NerveCompression"),
    "sleep": ("#SleepFacts", "#Parasomnia"),
    "foot": ("#NerveFacts", "#PinsAndNeedles"),
    "hungry": ("#Hunger", "#BodyClock"),
    "hunger": ("#HungerHormones", "#CircadianRhythm"),
    "gag": ("#GagReflex", "#ThroatFacts"),
    "tongue": ("#BurnedTongue", "#TasteBuds"),
    "ice": ("#BrainFreeze", "#ColdFood"),
    "sweet": ("#TasteFacts", "#Sugar"),
}


def _clean(s: str) -> str:
    if s is None:
        return ""
    s = _EMOJI_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _sentence(s: str) -> str:
    s = _clean(s)
    if not s:
        return s
    if s[-1] not in ".!?…\"'":
        s += "."
    return s


def _strip_bait(s: str) -> str:
    """Remove explicit engagement-ask sentences so we don't fight Meta anti-bait
    filters ('like and share', 'tag a friend', 'link in bio', subscribe etc.).
    'Follow' is kept because the CTA is genuine and not ask-for-engagement bait.
    """
    out_lines = []
    for line in re.split(r"(?<=[.!?…])\s+", s):
        l = line.strip()
        low = l.lower()
        if re.search(r"\b(like|share|tag|comment|subscribe|hit the bell|turn on notifications|link in bio)\b", low):
            # Only strip if it's an ASK, not a mention
            if re.search(r"\b(please|do not forget|don't forget|make sure|go ahead|smash|hit)\b|\?$", low) \
               or "like and share" in low or "tag a friend" in low or "tag your" in low \
               or "subscribe to" in low or "link in bio" in low:
                continue
        out_lines.append(l)
    return " ".join(out_lines).strip()


# ---------------------------------------------------------------------------
# Phrase extraction
# ---------------------------------------------------------------------------

def _strip_lead_in(text: str) -> str:
    t = _clean(text)
    # Iteratively strip stacked lead-ins ("Ever noticed Have you ever noticed")
    for _ in range(6):
        t0 = t
        for rx in _LEAD_STRIP_RES:
            t = rx.sub("", t, count=1)
            t = t.lstrip(",;:-— ").rstrip()
        if t == t0:
            break
    return t


def _strip_tail_fragments(text: str) -> str:
    t = _clean(text)
    # Strip trailing fragment + "Learn"/"Discover" lead (double truncation pattern).
    t = re.sub(r"\s+(?:learn|discover|find\s+out)\b.*$", "", t, flags=re.I).rstrip(",;:-— ")
    words = t.split()
    while words and words[-1].lower().strip("',.!?;:") in _FRAGMENT_TAIL:
        words.pop()
    return " ".join(words).rstrip(",;:-— ")


def _strip_lead_fragments(text: str) -> str:
    t = _clean(text)
    words = t.split()
    while words and words[0].lower().strip("',.!?;:") in {"do", "and", "but", "like", "up",
                                                          "to", "the", "a", "an", "you",
                                                          "your", "when", "if"}:
        # Only drop these if what remains is still a valid phrase (>=2 words)
        if len(words) > 2:
            words.pop(0)
        else:
            break
    return " ".join(words).lstrip(",;:-— ")


def _phrase_from_line(line: str) -> str:
    t = _clean(line)
    t = _strip_tail_fragments(t)
    t = _strip_lead_in(t)
    t = _strip_tail_fragments(t)
    t = _strip_lead_fragments(t)
    return _clean(t)


def _core_for_lead(hook_text: str) -> str:
    """Extract the core topic phrase (no lead-ins, no tails, usable as the body
    of a rebuilt lead question)."""
    h = _clean(hook_text)
    if not h:
        return "everyday body science"
    # Take the first line/sentence only — multi-line hooks are body.
    h = re.split(r"\n+", h)[0]
    h = re.split(r"(?<=[.!?…])\s", h)[0]
    h = _LEAD_TAIL_RE.sub("", h)
    h = _strip_tail_fragments(h)
    h = _strip_lead_in(h)
    h = _strip_tail_fragments(h)
    h = _strip_lead_fragments(h)
    return _clean(h) or "everyday body science"


# ---------------------------------------------------------------------------
# Grammar helpers (a / an, capitalisation, plural detection)
# ---------------------------------------------------------------------------

_VOWEL_SOUND = re.compile(r"^[aeiou]", re.I)


def _needs_indefinite_article(word: str) -> bool:
    w = word.lower().lstrip("'\"")
    if w.startswith(("hon", "hour")):
        return True
    return bool(_VOWEL_SOUND.match(w))


def _looks_plural(word: str) -> bool:
    w = word.lower().rstrip("',.!?;:")
    if w.endswith("ies") and len(w) > 4:
        return True
    if w.endswith("es") and not w.endswith(("ses", "sses", "shes", "ches", "tches")):
        # Not a perfect heuristic; err on the side of "don't prepend a".
        return w[-3] not in "sxz"
    if w.endswith("s") and not w.endswith(("ss", "us", "is", "os")):
        return True
    return False


def _starts_with_bare_singular_noun(core: str) -> bool:
    """Return True if the core starts with a singular countable noun with no
    determiner (so we want to prepend 'a' / 'an'). e.g. 'lump in your throat' → True.
    """
    c = _clean(core)
    if not c:
        return False
    words = [w.strip("',.!?;:\")(") for w in c.split()]
    if len(words) < 2:
        return False
    first = words[0].lower()
    if not first or not first[0].isalpha():
        return False
    if first in {"a", "an", "the", "your", "my", "this", "that", "his", "her", "our", "their", "some"}:
        return False
    if first in {"you", "when", "if", "after", "what", "why", "how", "i", "we", "it",
                 "and", "but", "or", "so", "just", "really", "ever", "here", "there",
                 "one", "two", "three"}:
        return False
    if first.endswith("ing") or first.endswith("ed"):
        return False
    second = words[1].lower().strip("',.!?;:")
    if second not in {"in", "on", "at", "up", "down", "out", "off", "inside", "when",
                      "your", "my", "the", "a", "an", "under", "behind", "like"}:
        return False
    if not re.match(r"^[a-z]{3,}$", first):
        return False
    if _looks_plural(first):
        return False
    return True


def _prepend_article_if_needed(core: str) -> str:
    if _starts_with_bare_singular_noun(core):
        first = core.split()[0]
        article = "an" if _needs_indefinite_article(first) else "a"
        return f"{article} {core}"
    return core


def _lowercase_first(text: str) -> str:
    if not text:
        return text
    parts = text.split(None, 1)
    if len(parts) == 1:
        return parts[0].lower()
    return parts[0].lower() + (" " + parts[1] if len(parts) > 1 else "")


def _capitalise_first(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


# ---------------------------------------------------------------------------
# Lead (curiosity first line)
# ---------------------------------------------------------------------------

_PP_VERBS = ("woken", "felt", "seen", "gotten", "had", "been",
            "wondered", "thought", "asked", "noticed")
_PP_RE = re.compile(rf"^({'|'.join(_PP_VERBS)})\b", re.I)


def _build_lead(hook_text: str) -> str:
    """One complete curiosity-driven sentence, <= 88 chars for IG."""
    core0 = _core_for_lead(hook_text) or "everyday body science"
    core0 = _prepend_article_if_needed(core0)

    low = core0.lower()
    starts_with_you = bool(re.match(r"^you\b", low))
    when_at_start = bool(re.match(r"^(when|if|after)\s+you\b", low))
    starts_with_pp = bool(_PP_RE.match(core0))

    if starts_with_pp:
        def fmt(h: str) -> str: return f"Have you ever {_lowercase_first(h)}?"
    elif starts_with_you or when_at_start:
        def fmt(h: str) -> str:
            lh = _lowercase_first(h)
            if re.match(r"^(when|if|after)\s+you\b", lh):
                return f"What happens {lh}?"
            return f"What happens when {lh}?"
    elif _BODY_PART_RE.search(core0):
        core0 = _lowercase_first(core0)
        def fmt(h: str) -> str: return f"Ever noticed {_lowercase_first(h)}?"
    elif re.search(r"\b(why|reason|causes?|because)\b", low):
        def fmt(h: str) -> str: return f"Here's why {_lowercase_first(h)}?"
    else:
        def fmt(h: str) -> str: return f"{_capitalise_first(h)} — the science."

    def _try(core_text: str) -> str:
        lead = fmt(core_text)
        if not lead.endswith((".", "!", "?", "…")):
            if lead.startswith(("Ever noticed ", "What happens ", "Have you ever ",
                                "Did you ever ", "Do you ever ", "Here's why ")):
                lead += "?"
            else:
                lead += "."
        if lead.startswith("Have you ever ") and lead.endswith("."):
            lead = lead[:-1] + "?"
        return lead

    raw_core = core0
    lead = _try(raw_core)
    if len(lead) > 88:
        words = raw_core.split()
        lo, hi = 1, len(words)
        best = raw_core
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = " ".join(words[:mid])
            if len(_try(candidate)) <= 88:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        lead = _try(best)
    return _sentence(lead)


def _rebuild_from_caption(existing: str) -> Tuple[str, str]:
    parts = [_clean(p) for p in re.split(r"\n+", existing) if _clean(p)]
    first = parts[0] if parts else "Body science"
    hook_text = _phrase_from_line(first)
    topic_words = [w for w in re.findall(r"[A-Za-z']+", _strip_lead_in(hook_text))
                   if w.lower() not in _STOP and len(w) > 2]
    topic_phrase = " ".join(topic_words[:6]) or "body science"
    return _build_lead(hook_text), topic_phrase


# ---------------------------------------------------------------------------
# Topic tags
# ---------------------------------------------------------------------------

def _topic_tags(topic: str, core: str, max_extra: int = 3) -> List[str]:
    tags: List[str] = []
    hay = f"{topic or ''} {core or ''}".lower()
    for kw, tlist in _BODY_KEYWORDS.items():
        if kw in hay:
            for t in tlist:
                ht = "#" + t
                if ht not in tags:
                    tags.append(ht)
    for pillar, plist in _PILLAR_TAGS.items():
        if re.search(rf"\b{pillar}\b", hay):
            for t in plist[:1]:
                ht = "#" + t
                if ht not in tags:
                    tags.append(ht)
            break
    return tags[:max_extra]


def _enforce_tag_count(tags: List[str], mn: int, mx: int) -> List[str]:
    out = []
    seen = set()
    for t in tags:
        if not t.startswith("#"):
            t = "#" + t
        t = re.sub(r"[^A-Za-z0-9_#]", "", t)
        if t.lower() in _BANNED_TAGS:
            continue
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
        if len(out) >= mx:
            break
    while len(out) < mn:
        for fb in ["#BodyScience", "#HumanBody", "#ScienceFacts",
                    "#EverydayScience", "#BiologyFacts"]:
            if fb.lower() not in seen:
                out.append(fb)
                seen.add(fb.lower())
                break
        else:
            break
    return out[:mx]


def _follow_line(topic: str, platform: str) -> str:
    low = (topic or "").lower()
    if platform == "ig":
        return "Follow for one body mystery explained every day."
    if platform == "fb":
        options = [
            "Follow along for the things your body does and why.",
            "Follow for short, accurate body science daily.",
            "Follow for one body mystery explained every day.",
            "Follow — everyday biology, no hype.",
        ]
        idx = int(hashlib.sha256(low.encode()).hexdigest()[:8], 16) % len(options)
        return options[idx]
    return "Follow for body science."


# ---------------------------------------------------------------------------
# Body-sentence embedding
# ---------------------------------------------------------------------------

_STARTS_CLAUSE_RE = re.compile(r"^(when|if|after|because|while|as|during)\b", re.I)

_IRREGULAR_PP = {
    "woken": "wake", "woken up": "wake up",
    "had": "have", "felt": "feel", "seen": "see",
    "gotten": "get", "got": "get", "been": "are",
    "noticed": "notice", "wondered": "wonder",
    "thought": "think", "asked": "ask",
}


def _de_pp(verb: str) -> str:
    v = verb.lower()
    if v in _IRREGULAR_PP:
        return _IRREGULAR_PP[v]
    if v.endswith("ied") and len(v) > 3:
        return v[:-3] + "y"
    if v.endswith("ed") and len(v) > 3:
        cand = v[:-2]
        if cand.endswith("dd") or cand.endswith("tt") or cand.endswith("gg"):
            cand = cand[:-1]
        return cand
    return v


def _as_when_you_clause(body: str) -> str:
    words = body.strip().split()
    if not words:
        return "when you experience this"
    first = words[0].lower()
    rest = words[1:]
    if first in {"woken", "gotten", "got"} and rest and rest[0].lower() == "up":
        present = _de_pp(first + " up")
        rest = rest[1:]
        return "when you " + present + (" " + " ".join(rest) if rest else "")
    present = _de_pp(first)
    return "when you " + present + (" " + " ".join(rest) if rest else "")


_HAVE_YOU_EVER_EMBED_RE = re.compile(r"^have\s+you\s+ever\s+(.+)$", re.I)


def _embed_core(core: str) -> str:
    raw = _LEAD_TAIL_RE.sub("", core or "").rstrip(".!?…,;:")
    m = _HAVE_YOU_EVER_EMBED_RE.match(raw)
    if m:
        return _as_when_you_clause(m.group(1))
    c = _lowercase_first(raw)
    if _PP_RE.match(c):
        return _as_when_you_clause(c)
    if c.startswith("you ") or c.startswith("you're ") or c.startswith("you've ") or c.startswith("you'll "):
        return f"what happens when {c}"
    if c.startswith("your "):
        return c
    if _STARTS_CLAUSE_RE.match(c):
        return f"what happens {c}"
    words = c.split()
    if words and len(words) <= 5 and not _BODY_PART_RE.match(c):
        first = words[0]
        if re.match(r"^\w+(ing|ed|en|uck|tuck|tuck)$", first) or first in {"stuck", "lost", "dizzy", "tired", "hoarse", "numb"}:
            return f"what happens when you're {c}"
    return c


def _finalise(lines: List[str], max_chars: int) -> str:
    text = "\n\n".join(l for l in lines if l).strip()
    if text and text[-1] not in ".!?…\"'":
        text += "."
    return _strip_bait(text)[:max_chars]


def _first_sentence_cap(core: str, cap: int) -> str:
    t = _clean(core)
    if len(t) <= cap:
        return t
    cut = t[:cap].rsplit(" ", 1)[0].rstrip(",;:")
    if not cut:
        cut = t[:cap]
    return cut


# ---------------------------------------------------------------------------
# Per-platform caption builders
# ---------------------------------------------------------------------------

def build_fb_caption(topic: str, hook: str) -> str:
    lead = _build_lead(hook or topic)
    body_core = _core_for_lead(hook or topic)
    body = _first_sentence_cap(
        f"Here's a quick look at the science behind {_embed_core(body_core)} — short, accurate, no hype.",
        140,
    )
    tags = _BODY_HASHTAGS_FB + _topic_tags(topic, body_core)
    hashtags = _enforce_tag_count(tags, 2, 5)
    lines = [lead, _sentence(body), _follow_line(topic, "fb")]
    if hashtags:
        lines.append(" ".join(hashtags))
    return _finalise(lines, 2000)


def build_ig_caption(topic: str, hook: str) -> str:
    lead_full = _build_lead(hook or topic)
    first = lead_full
    if len(first) > 90:
        first = _first_sentence_cap(first, 86) + "…"
    body_core = _core_for_lead(hook or topic)
    body = _first_sentence_cap(
        f"Here's the body science behind {_embed_core(body_core)} — quick, accurate, no hype.",
        130,
    )
    tags = _BODY_HASHTAGS_IG + _topic_tags(topic, body_core, max_extra=2)
    hashtags = _enforce_tag_count(tags, 3, 7)
    lines = [_sentence(first), _sentence(body), _follow_line(topic, "ig")]
    if hashtags:
        lines.append(" ".join(hashtags))
    return _finalise(lines, 2100)


# ---------------------------------------------------------------------------
# Caption quality scoring (0-10)
# ---------------------------------------------------------------------------

def _looks_truncated_caption(c: str) -> bool:
    c = (c or "").strip()
    if not c:
        return True
    if c[-1] not in ".!?…\"'":
        return True
    last_word = c.split()[-1].lower().strip("',.!?;:\")(") if c.split() else ""
    if last_word in _FRAGMENT_TAIL:
        return True
    return False


def _cross_posted(c: str) -> bool:
    return bool(re.search(r"#shorts|#youtubeshorts|#ytshorts|subscribe to my youtube",
                          (c or ""), re.I))


def caption_score(c: str) -> int:
    s = (c or "").strip()
    if not s:
        return 0
    score = 0
    if len(s) >= 40:
        score += 2
    if s[-1] in ".!?…\"'":
        score += 2
    if not _looks_truncated_caption(s):
        score += 2
    if re.search(r"\b[Ff]ollow\b", s):
        score += 1
    if re.search(r"#[A-Za-z0-9_]+", s):
        score += 1
    if not _cross_posted(s):
        score += 1
    if re.search(r"\b(body|bodies|science|biolog|brain|muscle|nerve|skin|heart|gut|eye|ear|sleep|why|how|your)\b",
                 s, re.I):
        score += 1
    return score


def seed_comment_text(seed: str) -> str:
    opts = [
        f"Have you ever noticed this with {seed}? Drop a 👇 if it's happened to you.",
        f"Curious — did you already know why {seed} happens?",
        f"Which body question should I explain next about {seed}?",
        f"Has {seed} ever happened at the worst possible time?",
    ]
    idx = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % len(opts)
    return opts[idx]


# ---------------------------------------------------------------------------
# Local indexes
# ---------------------------------------------------------------------------

def _fingerprints():
    history = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else []
    state = json.loads(UPLOAD_STATE_PATH.read_text()) if UPLOAD_STATE_PATH.exists() else {}
    fps: Dict[str, Dict[str, Any]] = {}
    by_ytid: Dict[str, str] = {}
    for h in history:
        fp = h.get("content_fingerprint")
        ytid = h.get("youtube_video_id")
        rec = {
            "fingerprint": fp,
            "topic": h.get("topic") or "",
            "title": h.get("title") or "",
            "hook": h.get("hook") or "",
            "summary": h.get("summary") or h.get("description") or "",
            "youtube_video_id": ytid,
        }
        if fp:
            fps[fp] = {**fps.get(fp, {}), **rec}
        if ytid:
            by_ytid[ytid] = fp
    for fp, st in state.items():
        if not isinstance(st, dict):
            continue
        entry = fps.setdefault(fp, {"fingerprint": fp})
        if st.get("youtube_video_id") and not entry.get("youtube_video_id"):
            entry["youtube_video_id"] = st["youtube_video_id"]
            by_ytid[st["youtube_video_id"]] = fp
        for plat in ("facebook", "instagram"):
            blk = st.get(plat) or {}
            rid = blk.get("video_id") or blk.get("media_id")
            if rid:
                entry.setdefault(plat, {})["id"] = rid
        if not entry.get("title") and st.get("title"):
            entry["title"] = st["title"]
    return fps, by_ytid


def _best_text(rid: str, live: str, index: Dict[str, Dict]) -> Tuple[str, str]:
    e = index.get(rid, {})
    hook = _clean(e.get("hook") or "")
    topic = _clean(e.get("topic") or e.get("title") or "")
    if hook and len(hook.split()) >= 4:
        lead = _build_lead(_phrase_from_line(hook))
        if not topic:
            topic_words = [w for w in re.findall(r"[A-Za-z']+", hook)
                           if w.lower() not in _STOP and len(w) > 2]
            topic = " ".join(topic_words[:6]) or hook
        return lead, topic
    return _rebuild_from_caption(live)


# ---------------------------------------------------------------------------
# Live listing
# ---------------------------------------------------------------------------

def _list_fb() -> List[Dict[str, Any]]:
    out = []
    cursor = None
    for _ in range(5):
        params = {"limit": 25, "fields": "id,description,created_time,permalink_url"}
        if cursor:
            params["after"] = cursor
        res = _gget(f"{PAGE}/video_reels", **params)
        for r in res.get("data", []):
            out.append({
                "id": r["id"],
                "description": r.get("description") or "",
                "created_time": r.get("created_time"),
                "permalink": r.get("permalink_url"),
            })
        paging = res.get("paging", {}).get("cursors", {})
        cursor = paging.get("after")
        if not cursor:
            break
    return out


def _list_ig() -> List[Dict[str, Any]]:
    if not IG_USER:
        return []
    out = []
    cursor = None
    for _ in range(5):
        params = {"limit": 25, "fields": "id,caption,timestamp,permalink,media_type"}
        if cursor:
            params["after"] = cursor
        res = _gget(f"{IG_USER}/media", **params)
        for m in res.get("data", []):
            if m.get("media_type") != "VIDEO":
                continue
            out.append({
                "id": m["id"],
                "caption": m.get("caption") or "",
                "timestamp": m.get("timestamp"),
                "permalink": m.get("permalink"),
            })
        paging = res.get("paging", {}).get("cursors", {})
        cursor = paging.get("after")
        if not cursor:
            break
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Meta (FB + IG) SEO repair for existing Reels")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed-comment", action="store_true", default=True)
    ap.add_argument("--no-seed-comment", dest="seed_comment", action="store_false")
    args = ap.parse_args()

    if not TOKEN:
        print("ERROR: FB_ACCESS_TOKEN missing.", file=sys.stderr); return 2
    if not PAGE_ID:
        print("ERROR: FB_PAGE_ID missing.", file=sys.stderr); return 2
    if not args.apply and not args.dry_run:
        print("No action specified — defaulting to --dry-run."); args.dry_run = True

    fps, _by_ytid = _fingerprints()
    by_fbid, by_igid = {}, {}
    for fp, e in fps.items():
        if (e.get("facebook") or {}).get("id"):
            by_fbid[e["facebook"]["id"]] = e
        if (e.get("instagram") or {}).get("id"):
            by_igid[e["instagram"]["id"]] = e

    fb_live = _list_fb()
    ig_live = _list_ig()

    log: Dict[str, Any] = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "mode": "dry-run" if args.dry_run else "apply",
        "facebook": [], "instagram": [], "warnings": [],
    }

    # ---------- Facebook ----------
    fb_candidates = []
    for r in fb_live:
        rid = r["id"]
        existing = r.get("description") or ""
        hook, topic = _best_text(rid, existing, by_fbid)
        new_cap = build_fb_caption(topic, hook)
        score_old = caption_score(existing)
        score_new = caption_score(new_cap)
        same = existing.strip() == new_cap.strip()
        trunc = _looks_truncated_caption(existing)
        cross = _cross_posted(existing)
        needs_repair = (not same) and (score_new > score_old or trunc or cross)
        soc = _gget(rid, fields="likes.summary(true),comments.summary(true),from.id")
        likes = (soc.get("likes", {}).get("summary") or {}).get("total_count")
        comments = (soc.get("comments", {}).get("summary") or {}).get("total_count")
        r.update({"new_caption": new_cap, "score_old": score_old, "score_new": score_new,
                  "needs_repair": needs_repair, "likes": likes, "comments": comments})
        if needs_repair or (args.seed_comment and (comments or 0) == 0):
            fb_candidates.append(r)
    fb_candidates.sort(key=lambda x: (x["score_old"], x.get("created_time") or ""))
    if args.limit:
        fb_candidates = fb_candidates[:args.limit]

    print(f"\n=== FACEBOOK: {len(fb_live)} reels scanned, {len(fb_candidates)} need action ===\n")
    for r in fb_candidates[:50]:
        print(f"[{r['id']}] score {r['score_old']}->{r['score_new']} L={r.get('likes')} C={r.get('comments')}")
        print(f"  OLD: {(r['description'] or '(empty)')[:160]}")
        print(f"  NEW: {r['new_caption'][:240]}")
        entry = {"id": r["id"], "permalink": r.get("permalink"),
                 "old_score": r["score_old"], "new_score": r["score_new"],
                 "old_caption": r["description"], "new_caption": r["new_caption"]}
        if args.apply and r["needs_repair"]:
            res = _gpost(rid, description=r["new_caption"])
            entry["edit_result"] = res
            if "error" in res:
                log["warnings"].append(f"FB {rid} edit failed: {res}")
                print(f"  ❌ caption edit failed: {res}")
            else:
                print(f"  ✅ caption updated")
        if args.apply and args.seed_comment and (r.get("comments") or 0) == 0:
            topic_for_seed = _best_text(rid, r.get("description") or "", by_fbid)[1]
            seed = seed_comment_text(topic_for_seed)
            cres = _gpost(rid + "/comments", message=seed)
            entry["seed_comment"] = {"text": seed, "result": cres}
            if "error" in cres:
                log["warnings"].append(f"FB {rid} comment failed: {cres}")
            else:
                print(f"  ✅ seed comment posted")
        log["facebook"].append(entry)

    # ---------- Instagram ----------
    ig_candidates = []
    for m in ig_live:
        mid = m["id"]
        existing = m.get("caption") or ""
        hook, topic = _best_text(mid, existing, by_igid)
        new_cap = build_ig_caption(topic, hook)
        score_old = caption_score(existing)
        score_new = caption_score(new_cap)
        same = existing.strip() == new_cap.strip()
        needs = (not same) and (score_new > score_old
                                or _looks_truncated_caption(existing)
                                or _cross_posted(existing))
        m.update({"new_caption": new_cap, "score_old": score_old,
                  "score_new": score_new, "needs_repair": needs})
        if needs:
            ig_candidates.append(m)
    ig_candidates.sort(key=lambda x: (x["score_old"], x.get("timestamp") or ""))
    if args.limit:
        ig_candidates = ig_candidates[:args.limit]

    print(f"\n=== INSTAGRAM: {len(ig_live)} media scanned, {len(ig_candidates)} need caption repair ===\n")
    for m in ig_candidates[:50]:
        print(f"[{m['id']}] score {m['score_old']}->{m['score_new']}")
        print(f"  OLD: {(m['caption'] or '(empty)')[:160]}")
        print(f"  NEW: {m['new_caption'][:240]}")
        entry = {"id": m["id"], "permalink": m.get("permalink"),
                 "old_score": m["score_old"], "new_score": m["score_new"],
                 "old_caption": m["caption"], "new_caption": m["new_caption"]}
        if args.apply:
            res = _gpost(m["id"], caption=m["new_caption"])
            entry["edit_result"] = res
            if "error" in res:
                log["warnings"].append(f"IG {m['id']} caption edit failed: {res}")
                print(f"  ❌ edit failed: {res}")
            else:
                print(f"  ✅ caption updated")
        log["instagram"].append(entry)

    REPAIR_LOG_PATH.parent.mkdir(exist_ok=True)
    with open(REPAIR_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"\nLog: {REPAIR_LOG_PATH}")
    print(f"Facebook actions: {len(log['facebook'])} | Instagram actions: {len(log['instagram'])}")
    if log["warnings"]:
        print(f"⚠️  warnings: {len(log['warnings'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
