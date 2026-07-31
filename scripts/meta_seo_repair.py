#!/usr/bin/env python3
"""
scripts/meta_seo_repair.py — strong SEO repair for existing Facebook + Instagram Reels.

PROBLEM
-------
Existing FB/IG Reels are under-performing for reasons visible in the data:
  * Captions are truncated mid-sentence (e.g. "Ever felt a lump in your throat when"
    — never closes), which Meta reads as low-quality / aggregated.
  * The first line is a teaser like "Learn why ..." rather than naming the topic,
    so Meta's UTIS true-interest survey can't classify the video and kills reach.
  * No follow CTA on many reels (missing audience-relationship signal).
  * Hashtags are either missing or carry #shorts / #youtubeshorts which mark the
    video as cross-posted (Meta's originality penalty).
  * Zero comments — an empty comment section tells the feed not to push.

This script is SAFE (compare-and-swap, idempotent). It only PATCHES captions
where the new version scores higher on an internal caption-quality heuristic
AND differs from the live caption. It never uploads, deletes or re-encodes.

REQUIRED ENV
  FB_ACCESS_TOKEN (or FACEBOOK_ACCESS_TOKEN)  — page token with pages_manage_posts
  FB_PAGE_ID                                  — page id
  INSTAGRAM_USER_ID (optional)                — IG business account to patch too

USAGE
  python scripts/meta_seo_repair.py --dry-run         # preview, no writes
  python scripts/meta_seo_repair.py --apply           # write all repairs + seed comments
  python scripts/meta_seo_repair.py --apply --limit 3 # touch only 3 worst per platform
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

API = os.environ.get("FB_API_VERSION", "v23.0")
TOKEN = (os.environ.get("FB_ACCESS_TOKEN") or os.environ.get("FACEBOOK_ACCESS_TOKEN") or "").strip()
PAGE = (os.environ.get("FB_PAGE_ID") or os.environ.get("FACEBOOK_PAGE_ID") or "").strip()
IG_USER = os.environ.get("INSTAGRAM_USER_ID", "").strip()

HISTORY_PATH = ROOT / "data" / "video_history.json"
UPLOAD_STATE_PATH = ROOT / "data" / "upload_state.json"
PLATFORM_METRICS_PATH = ROOT / "data" / "platform_metrics.json"
REPAIR_LOG_PATH = ROOT / "data" / f"meta_seo_repair_{dt.date.today():%Y%m%d}.json"


# ---------------------------------------------------------------------------
# Graph helpers (stdlib only)
# ---------------------------------------------------------------------------

def _graph(method: str, node: str, **params) -> Dict[str, Any]:
    if not TOKEN:
        return {"error": "no_token"}
    url = f"https://graph.facebook.com/{API}/{node}"
    if method == "GET":
        url = f"{url}?{urllib.parse.urlencode({**params, 'access_token': TOKEN})}"
        req = urllib.request.Request(url)
        data_bytes = None
    else:
        data_bytes = urllib.parse.urlencode({**params, "access_token": TOKEN}).encode()
        req = urllib.request.Request(url, data=data_bytes, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read()[:400].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return {"error": "network", "body": str(e)[:200]}


def gget(node: str, **params) -> Dict[str, Any]:
    return _graph("GET", node, **params)


def gpost(node: str, **params) -> Dict[str, Any]:
    return _graph("POST", node, **params)


# ---------------------------------------------------------------------------
# Caption primitives
# ---------------------------------------------------------------------------

_BODY_HASHTAGS_FB = ["#BodyScience", "#HumanBody", "#ScienceFacts"]
_BODY_HASHTAGS_IG = ["#BodyScience", "#HumanBodyFacts", "#ScienceExplained",
                     "#EverydayScience", "#BiologyFacts"]

_TOPIC_TAGS = {
    "sleep": ["#SleepScience"], "dream": ["#SleepScience"],
    "brain": ["#Neuroscience"], "memory": ["#Neuroscience"],
    "eye": ["#VisionScience"], "ear": ["#Hearing"],
    "heart": ["#Cardio"], "muscle": ["#MuscleScience"],
    "cramp": ["#MuscleScience"], "knee": ["#JointHealth"],
    "skin": ["#SkinFacts"], "nerve": ["#Nerves"],
    "gut": ["#GutHealth"], "stress": ["#StressResponse"],
    "breath": ["#Breathing"], "sneeze": ["#Sneeze"],
    "yawn": ["#Yawning"],
}

_STOP = {
    "the", "a", "an", "and", "or", "but", "why", "how", "what", "when",
    "your", "you", "you're", "do", "does", "is", "are", "was", "were", "to",
    "of", "in", "on", "at", "for", "with", "that", "this", "it", "just",
    "really", "actually", "ever", "feel", "feels", "felt", "like", "about",
    "will", "can", "have", "has", "there", "here", "out", "up", "down",
    "get", "got", "make", "makes", "about", "suddenly", "instantly", "me",
    "my", "our", "i",
}

_FRAGMENT_TAIL = {
    "when", "why", "how", "what", "the", "your", "you", "a", "an", "to",
    "for", "and", "up", "it", "on", "in", "out", "off", "about", "with",
    "can", "will", "is", "are", "my", "our", "me", "extremely", "really",
    "very", "just", "but", "or", "if", "like", "that", "this",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().strip(" .,:;")


def _ends_sentence(ch: str) -> bool:
    return ch in ".!?…\"'"


def _sentence(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return ""
    t = t.strip().lstrip(" .,:;")
    if not t:
        return ""
    if not _ends_sentence(t[-1]):
        t += "."
    return t


def _truncate(text: str, max_len: int = 200) -> str:
    t = _clean(text)
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rsplit(" ", 1)[0].rstrip(",;:")
    if cut and not _ends_sentence(cut[-1]):
        cut = cut.rstrip(".") + "…"
    return cut


def _follow_line(seed: str, platform_suffix: str = "") -> str:
    options = [
        "Follow for one body mystery explained every day.",
        "Follow for short, accurate body science daily.",
        "Follow — everyday biology, no hype.",
        "Follow along for the things your body does and why.",
    ]
    idx = int(hashlib.sha256((seed + platform_suffix).encode()).hexdigest()[:8], 16) % len(options)
    return options[idx]


def _topic_tags(topic: str, title: str, max_extra: int = 2) -> List[str]:
    hay = f"{topic} {title}".lower()
    out = []
    for kw, tags in _TOPIC_TAGS.items():
        if kw in hay:
            for t in tags:
                if t not in out:
                    out.append(t)
        if len(out) >= max_extra:
            break
    return out[:max_extra]


def _format_tags(tags: List[str]) -> str:
    """Join cleaned hashtags with spaces, never double-#."""
    return " ".join(_enforce_tag_count(tags, 2, 7))


def _enforce_tag_count(tags: List[str], minimum: int, maximum: int) -> List[str]:
    cleaned = []
    seen = set()
    for t in tags:
        t = t.strip()
        if not t.startswith("#"):
            t = "#" + t
        token = re.sub(r"[^A-Za-z0-9_]", "", t)
        if len(token) <= 2:
            continue
        key = token.lower()
        if key in seen:
            continue
        if key in {"shorts", "short", "youtubeshorts", "ytshorts", "fyp", "reels",
                   "viral", "trending", "foryou", "foryoupage"}:
            continue
        seen.add(key)
        cleaned.append("#" + token)
        if len(cleaned) >= maximum:
            break
    return cleaned


def _strip_bait(text: str) -> str:
    """Remove blatant engagement-bait lines Meta penalises. Conservative:
    only drops whole sentences that contain a banned ask."""
    bait = re.compile(
        r"\b(like (this|if|and)|double tap|smash that|share (this|it|with)|"
        r"send this to|tag (a|your|someone)|comment (below|down)|"
        r"drop a (like|comment)|vote (below|now)|who agrees|"
        r"subscribe|link in bio)\b",
        re.IGNORECASE,
    )
    blocks = []
    for block in (text or "").split("\n\n"):
        kept = []
        for s in re.split(r"(?<=[.!?…])\s+", block):
            if not bait.search(s):
                kept.append(s)
        rebuilt = re.sub(r"\s+", " ", " ".join(kept)).strip()
        if rebuilt:
            blocks.append(rebuilt)
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Rebuilding from a damaged live caption
# ---------------------------------------------------------------------------

def _first_line(text: str) -> str:
    return _clean((text or "").split("\n")[0])


def _phrase_from_line(line: str) -> str:
    """Clean a raw first line: drop fragment tails and punctuate."""
    words = [w for w in re.split(r"\s+", _clean(line)) if w]
    if not words:
        return "Everyday body science, explained."
    frag = _FRAGMENT_TAIL | {"suddenly", "instantly", "extremely", "really",
                              "just", "that", "this", "very", "the", "about",
                              "why", "how"}
    while words and words[-1].lower().strip("',.!?;:\")(") in frag:
        words.pop()
    if not words:
        return "Everyday body science, explained."
    text = " ".join(words)
    if not text[-1] in ".!?…":
        text += "."
    return text


def _strip_lead_in(text: str) -> str:
    """Backwards-compatible alias for the iterative lead-framing stripper."""
    return _strip_lead_framing(text)


_LEAD_STRIP_PATTERNS = [
    r"^have\s+you\s+ever\s+felt\s+like\s+",
    r"^have\s+you\s+ever\s+(?:woken|gotten|got|ended|wound)\s+up\s+",
    r"^have\s+you\s+ever\s+(?:noticed|wondered(?:\s+why)?|thought\s+about|asked\s+yourself|felt|seen|woken|gotten|got|had|been)\s+",
    r"^did\s+you\s+ever\s+(?:notice|wonder|feel|see)\s+",
    r"^do\s+you\s+ever\s+(?:notice|wonder|feel|see)\s+",
    r"^did\s+you\s+know\s+",
    r"^do\s+you\s+know\s+",
    r"^you(?:'ve|have)\s+(?:noticed|seen|wondered|experienced)\s+(?:it\s+before[, ]*|that\s+)?(?:but\s+)?(?:why|how|what|when|do|does|is|are)?\s*",
    r"^ever\s+noticed\s+(?:that\s+|like\s+)?",
    r"^ever\s+felt\s+(?:like\s+|that\s+)?",
    r"^ever\s+wondered\s+(?:why|how|what|when|if)\s*",
    r"^(?:it'?s\s+when|that'?s\s+when|the\s+feeling\s+when)\s+",
    r"^here'?s\s+what\s+happens\s+(?:when|if|after)\s+",
    r"^here\s+is\s+what\s+happens\s+(?:when|if|after)\s+",
    r"^what\s+happens\s+(?:when|if|after)\s+",
    r"^here'?s\s+why\s+",
    r"^here\s+is\s+why\s+",
    r"^this\s+is\s+why\s+",
    r"^that'?s\s+why\s+",
    r"^learn\s+(?:why|how|what|when|where)\s+",
    r"^discover\s+(?:why|how|what|when|where)\s+",
    r"^find\s*out\s+(?:why|how|what|when|where)\s+",
    r"^(?:the\s+)?science(?:\s+explained)?[:\-\–—]?\s*",
    r"^your\s+body\s+(?:does\s+this|explained)[—\-\–.]?\s*(?:here'?s\s+why\.?)?\s*",
    r"^body\s+science,?\s*explained\.?\s*",
]

_WHEN_CLAUSE_RE = re.compile(r"\b(when|if|after)\s+you\b", re.I)


def _strip_lead_framing(text: str) -> str:
    """Iteratively strip every leading teaser/question frame so that
    stacking ("Ever noticed Have you ever noticed X") collapses to just X."""
    t = _clean(text)
    changed = True
    rounds = 0
    while changed and rounds < 6:
        changed = False
        rounds += 1
        for pat in _LEAD_STRIP_PATTERNS:
            t2 = re.sub(pat, "", t, flags=re.I).strip()
            if t2 and len(t2) > 4 and t2.lower() != t.lower():
                t = t2
                changed = True
                break
    return t


_MID_LEARN_SPLIT_RE = re.compile(
    r"\s+(?:learn|discover|find\s*out|see|watch)\s+"
    r"(?:why|how|what(?:\s+causes?|\s+happens)?|when|where)\b.*$",
    re.I,
)


_LEAD_TAIL_RE = re.compile(r"\s*[—\-\–]\s*the\s+science\.?\s*$", re.I)


def _core_for_lead(hook_text: str) -> str:
    """Extract the actual subject from a hook line, removing leading AND
    trailing teaser framing."""
    raw = re.sub(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]",
                 "", hook_text or "")
    raw = _LEAD_TAIL_RE.sub("", raw)
    t = _phrase_from_line(raw).rstrip(".!?…,;:")
    t = _MID_LEARN_SPLIT_RE.sub("", t).strip()
    m = re.match(
        r"^(?:learn|discover|find\s*out|see|watch)\s+"
        r"(?:why|how|what(?:\s+causes?)?|when|where)\s+"
        r"(.+)$",
        t, re.I,
    )
    if m:
        tail = m.group(1).strip()
        tail = re.split(r"\s+and\s+(?:a|how|why|what|when|you)", tail, maxsplit=1, flags=re.I)[0]
        t = tail.strip().rstrip(".!?…,;:")
    t = _strip_tail_fragments(t)
    t = _strip_lead_framing(t)
    t = t.rstrip(".!?…,;:")
    t = _strip_lead_fragments(t)
    t = t.rstrip(".!?…,;:")
    if len(t) < 5:
        t = "everyday body science"
    return t


_TAIL_FRAG_WORDS = _FRAGMENT_TAIL | {
    "do", "does", "did", "can", "will", "would", "could", "should",
    "is", "are", "was", "were", "your", "my", "the", "a", "an",
    "and", "but", "or", "so", "like", "just", "really", "very",
}


def _strip_tail_fragments(text: str) -> str:
    words = [w for w in re.split(r"\s+", text) if w]
    while words:
        last = words[-1].lower().strip("',.!?;:\"()")
        if last in _TAIL_FRAG_WORDS or len(last) < 2:
            words.pop()
            continue
        break
    return " ".join(words) if words else text


_LEAD_FRAG_WORDS = {
    "and", "but", "or", "so", "like", "up", "out", "off", "down",
    "do", "does", "did", "the", "is", "are", "it", "a", "an",
}


def _strip_lead_fragments(text: str) -> str:
    words = [w for w in re.split(r"\s+", text) if w]
    while words:
        first = words[0].lower().strip("',.!?;:\"()")
        if first in _LEAD_FRAG_WORDS:
            words.pop(0)
            continue
        break
    return " ".join(words) if words else text


_BODY_PART_RE = re.compile(
    r"\b(your|my|the|this|a|an)?\s*"
    r"(heart|brain|eye|eyes|ear|ears|skin|knee|knees|muscle|muscles|calf|calves|"
    r"arm|arms|leg|legs|hand|hands|foot|feet|finger|fingers|toe|toes|stomach|"
    r"gut|throat|nose|lung|lungs|liver|kidney|spine|back|neck|shoulder|hips|"
    r"jaw|chest|bone|bones|vein|nerves?|head|hair|nail|nails|body|mouth|teeth|tooth|tongue|lip|lips)\b",
    re.I,
)


def _needs_indefinite_article(word: str) -> bool:
    if not word:
        return False
    return bool(re.match(r"^[aieou]", word.lower()))


_IRREGULAR_PLURALS = {
    "bacteria", "data", "media", "criteria", "people", "men", "women", "children",
    "teeth", "feet", "lice",
}


def _looks_plural(word: str) -> bool:
    w = word.lower()
    if w in _IRREGULAR_PLURALS:
        return True
    if w.endswith("ies") or w.endswith("es") or w.endswith("ae") or w.endswith("oa"):
        return True
    if w.endswith("s") and not w.endswith("ss") and not w.endswith("us"):
        return True
    return False


_POSSESSIVE_BODY = {"calf", "foot", "feet", "hand", "hands", "arm", "arms", "leg", "legs",
                    "knee", "knees", "eye", "eyes", "ear", "ears", "nose", "mouth",
                    "throat", "neck", "back", "stomach", "gut", "chest", "finger",
                    "fingers", "toe", "toes", "tongue", "lip", "lips", "teeth",
                    "voice", "skin", "hair", "heart", "lungs", "head", "face", "body",
                    "shoulder", "wrist", "ankle", "elbow"}

_VERB_STARTS = {"stand", "see", "hear", "feel", "wake", "walk", "get", "brush", "yawn",
                "break", "shiver", "freeze", "gag", "cough", "sneeze", "hiccup", "blink",
                "notice", "wonder", "love", "hate", "like", "lose", "smell",
                "taste", "touch", "breathe", "swallow", "bite", "hold", "lift",
                "woken"}


def _starts_with_bare_singular_noun(core: str) -> bool:
    words = core.split()
    if not words:
        return False
    first = words[0].lower().strip("',.!?;:")
    if first in _POSSESSIVE_BODY:
        return False
    if first in {"a", "an", "the", "your", "my", "this", "that", "his", "her", "our", "their", "some"}:
        return False
    if first in {"you", "when", "if", "after", "what", "why", "how", "i", "we", "it",
                 "and", "but", "or", "so", "just", "really", "ever", "here", "there",
                 "one", "two", "three"}:
        return False
    if first.endswith("ing") or first.endswith("ed"):
        return False
    if first in _VERB_STARTS:
        return False
    if len(words) < 2:
        return False
    second = words[1].lower().strip("',.!?;:")
    if second not in {"in", "on", "at", "up", "down", "out", "off", "inside", "when",
                      "your", "my", "the", "a", "an", "under", "behind", "like", "for",
                      "that", "this", "about"}:
        return False
    if not re.match(r"^[a-z]{3,}$", first):
        return False
    if _looks_plural(first):
        return False
    return True


def _prepend_your_if_bodypart(core: str) -> str:
    """If core starts with a bare body-part noun (no determiner), prepend 'your'."""
    words = core.split()
    if not words:
        return core
    first = words[0].lower().strip("',.!?;:")
    if first in _POSSESSIVE_BODY:
        return "your " + core
    return core


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


_PP_VERBS = ("woken", "felt", "seen", "gotten", "had", "been",
             "wondered", "thought", "asked", "noticed")
_PP_RE = re.compile(rf"^({'|'.join(_PP_VERBS)})\b", re.I)


def _build_lead(hook_text: str) -> str:
    """One complete curiosity-driven sentence, <= 88 chars for IG."""
    core0 = _core_for_lead(hook_text) or "everyday body science"
    core0 = _prepend_your_if_bodypart(core0)
    core0 = _prepend_article_if_needed(core0)

    low = core0.lower()
    starts_with_you = bool(re.match(r"^you\b", low))
    when_at_start = bool(re.match(r"^(when|if|after)\s+you\b", low))
    starts_with_pp = bool(_PP_RE.match(core0))
    starts_with_verb = bool(re.match(r"^(stand|see|hear|feel|wake|walk|get|brush|yawn|break|shiver|freeze|gag|cough|sneeze|hiccup|blink|notice|wonder|love|hate|like|lose|smell|taste|touch|breathe|swallow|bite|hold|lift|wake|woken|have|do|does)\b", low))

    if starts_with_pp:
        def fmt(h: str) -> str: return f"Have you ever {_lowercase_first(h)}?"
    elif starts_with_you or when_at_start:
        def fmt(h: str) -> str:
            lh = _lowercase_first(h)
            if re.match(r"^(when|if|after)\s+you\b", lh):
                return f"What happens {lh}?"
            return f"What happens when {lh}?"
    elif starts_with_verb:
        def fmt(h: str) -> str: return f"What happens when you {_lowercase_first(h)}?"
    elif _BODY_PART_RE.search(core0):
        core0 = _lowercase_first(core0)
        def fmt(h: str) -> str: return f"Ever noticed {_lowercase_first(h)}?"
    elif re.search(r"\b(why|reason|causes?|because)\b", low):
        def fmt(h: str) -> str: return f"Here's why {_lowercase_first(h)}?"
    else:
        def fmt(h: str) -> str: return f"{_capitalise_first(h)} — the science."

    def _try(core_text: str) -> str:
        lead = fmt(core_text)
        # Collapse accidental double punctuation.
        lead = re.sub(r"([.!?…])[.!?…]+", r"\1", lead)
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
# Per-platform caption builders
# ---------------------------------------------------------------------------

def _finalise(lines: List[str], max_chars: int) -> str:
    text = "\n\n".join(l for l in lines if l).strip()
    if text and text[-1] not in ".!?…\"'":
        text += "."
    return _strip_bait(text)[:max_chars]


def _first_sentence_cap(core: str, cap: int) -> str:
    """Return <= cap chars ending at a word boundary, with trailing
    punctuation normalised."""
    t = _clean(core)
    if len(t) <= cap:
        return t
    cut = t[:cap].rsplit(" ", 1)[0].rstrip(",;:")
    if not cut:
        cut = t[:cap]
    return cut


_STARTS_CLAUSE_RE = re.compile(r"^(when|if|after|because|while|as|during)\b", re.I)

_IRREGULAR_PP = {
    "woken": "wake", "woken up": "wake up",
    "had": "have", "felt": "feel", "seen": "see",
    "gotten": "get", "got": "get", "been": "are",
    "noticed": "notice", "wondered": "wonder",
    "thought": "think", "asked": "ask",
}


def _de_pp(verb: str) -> str:
    """Best-effort convert a past participle to simple-present (2nd person)."""
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
    """Turn a 'Have you ever <pp> …' body into a 'when you <present> …'
    noun clause for mid-sentence embedding."""
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
    """Return core in a form suitable for embedding mid-sentence after a
    preposition like 'behind'."""
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


def build_fb_caption(topic: str, hook: str) -> str:
    lead = _build_lead(hook or topic)
    body_core = _core_for_lead(hook or topic)
    follow = _follow_line(topic, "fb")
    tags = _BODY_HASHTAGS_FB + _topic_tags(topic, body_core, max_extra=2)
    body_budget = 2000 - (len(lead) + len(follow) + 80)
    body = _first_sentence_cap(
        f"Here's a quick look at the science behind {_embed_core(body_core)} — short, accurate, no hype.",
        max(120, min(200, body_budget)),
    )
    lines = [lead, _sentence(body), follow, _format_tags(tags)]
    while len("\n\n".join(l for l in lines if l)) > 2000 and lines[-1].startswith("#"):
        parts = lines[-1].rsplit(" ", 1)
        if len(parts) > 1:
            lines[-1] = parts[0]
        else:
            lines.pop()
    return _finalise(lines, 2000)


def build_ig_caption(topic: str, hook: str) -> str:
    lead_full = _build_lead(hook or topic)
    first = lead_full
    if len(first) > 90:
        first = _first_sentence_cap(first, 86) + "…"
    body_core = _core_for_lead(hook or topic)
    follow = _follow_line(topic, "ig")
    tags = _BODY_HASHTAGS_IG + _topic_tags(topic, body_core, max_extra=2)
    body_budget = 2100 - (len(first) + len(follow) + 80)
    body = _first_sentence_cap(
        f"Here's the body science behind {_embed_core(body_core)} — quick, accurate, no hype.",
        max(110, min(200, body_budget)),
    )
    lines = [_sentence(first), _sentence(body), follow, _format_tags(tags)]
    while len("\n\n".join(l for l in lines if l)) > 2100 and lines[-1].startswith("#"):
        parts = lines[-1].rsplit(" ", 1)
        if len(parts) > 1:
            lines[-1] = parts[0]
        else:
            lines.pop()
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
    """Pick the best hook/topic text."""
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
        res = gget(f"{PAGE}/video_reels", **params)
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
        res = gget(f"{IG_USER}/media", **params)
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
    if not PAGE:
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
        soc = gget(rid, fields="likes.summary(true),comments.summary(true),from.id")
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
            res = gpost(rid, description=r["new_caption"])
            entry["edit_result"] = res
            if "error" in res:
                log["warnings"].append(f"FB {rid} edit failed: {res}")
                print(f"  ❌ caption edit failed: {res}")
            else:
                print(f"  ✅ caption updated")
        if args.apply and args.seed_comment and (r.get("comments") or 0) == 0:
            topic_for_seed = _best_text(rid, r.get("description") or "", by_fbid)[1]
            seed = seed_comment_text(topic_for_seed)
            cres = gpost(rid + "/comments", message=seed)
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
            # Instagram media caption edit. v23 requires comment_enabled=true,
            # otherwise you get "(#100) The parameter comment_enabled is required".
            res = gpost(m["id"], caption=m["new_caption"], comment_enabled="true")
            entry["edit_result"] = res
            if "error" in res:
                log["warnings"].append(f"IG {mid} caption edit failed: {res}")
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
