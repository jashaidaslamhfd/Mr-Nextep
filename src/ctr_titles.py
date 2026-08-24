"""CTR booster for US YouTube Shorts titles (Mr-Nextep).

Adds an LLM-generated layer of high-CTR title candidates on top of the
rule-based frames in ``seo_generator.generate_title_options()``.

Why: the rule-based frames ("Why X Works", "How X Works") are safe but
template-heavy; 2026 Shorts feeds suppress template output and viewers
respond to novelty. Viral US Shorts CTR patterns that outperform plain
frames: (1) numbers/specificity, (2) "This Is Why" constructions, (3)
personal-second-person stakes ("Your ...", "Doctors Can't Explain"),
(4) unresolved curiosity gaps ("What Happens To Your ...", "The Truth
About ..."). This module generates up to 4 such candidates per video
via OpenRouter (free tier) and falls back to rule-based patterns if the
LLM fails - a title drop must never stop a run.

2026-08-21: first implementation. Toggle: ``CTR_TITLES=false`` disables
the LLM layer entirely (rule-based only, pre-change behaviour).
"""

import os
import re

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:  # pragma: no cover - requests is a core dep
    _HAS_REQUESTS = False

CTR_TITLES_OFF = os.environ.get("CTR_TITLES", "true").strip().lower() in (
    "false", "0", "no", "off",
)
# Never exceed Shorts' safe mobile display width (title is overlaid in feed)
CTR_TITLE_MAX_CHARS = 55
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CTR_TIMEOUT = 45


# ----------------------------------------------------------------------------
# Rule-based viral patterns (always available, no LLM needed)
# ----------------------------------------------------------------------------

def _rule_patterns(topic: str) -> list:
    """Deterministic high-CTR constructions built from the topic itself."""
    low = topic.lower().strip().rstrip(".")
    # Normalise a question into a noun phrase subject:
    # "why your knees crack" -> "knees cracking", "why the heart beats"
    # -> "heartbeats". Kept simple and grammatical: keep the core noun(s)
    # plus a gerund/verb so constructions like "Your X" stay readable.
    phrase = re.sub(r"^why (do|does) (your|the|a|an) ", "", low)
    phrase = re.sub(r"^why (your|the|a|an) ", "", phrase)
    phrase = re.sub(r"^(the |a |an )", "", phrase).strip()
    if not phrase:
        return []
    words = phrase.split()
    # Only add a gerund when the final word is plausibly a verb that accepts
    # "-ing" (short, not already a noun/adjective tail like "night", "fast").
    # "why the heart beats faster at night" must stay as-is: "...At Nighting"
    # is worse than no gerund at all.
    verb_like_last = len(words[-1]) <= 7 and not words[-1].endswith((
        "ight", "ast", "oon", "eek", "oom", "eep", "eal", "ood", "eet", "ain",
    ))
    if words and verb_like_last and not words[-1].endswith("ing"):
        words = words[:-1] + [words[-1] + "ing"]
    phrase = " ".join(words)

    # Drop words from the end while the phrase no longer fits a 55-char
    # budget once wrapped in the longest construction below.
    budget = CTR_TITLE_MAX_CHARS - len("99% Of People Don't Know This About ")
    while phrase and len(f"X {phrase}") > budget:
        words.pop()
        phrase = " ".join(words)

    patterns = [
        f"This Is Why Your {phrase}".title(),
        f"What Really Happens When Your {phrase}".title(),
        f"The Truth About {phrase}".title(),
        f"7 Signs Your Body Is {phrase}".title(),
        f"99% Of People Don't Know This About {phrase}".title(),
        f"Your {phrase.title()} Is Trying To Warn You".title(),
        f"Science Can't Fully Explain {phrase}".title(),
    ]
    return list(dict.fromkeys(patterns))[:4]


def _llm_patterns(topic: str, seed_title: str) -> list:
    """Ask a free-tier LLM for 4 novel viral title angles."""
    if not _HAS_REQUESTS:
        return []
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return []
    model = os.environ.get("CTR_TITLE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    prompt = (
        f"You are a US YouTube Shorts title writer for a science/body facts "
        f"channel. Topic: \"{topic}\". Current working title: \"{seed_title}\". "
        f"Write exactly 4 new title candidates that would get a high click "
        f"through rate in the US Shorts feed. Use proven patterns: numbers "
        f"and specificity, \"This Is Why\" constructions, personal second-person "
        f"stakes (\"your\"), unresolved curiosity gaps (\"The Truth About\", "
        f"\"Science Can't Explain\"). No emoji, no clickbait that is false, "
        f"no ALL CAPS, max {CTR_TITLE_MAX_CHARS} characters each. Return ONLY "
        f"a JSON array of 4 strings, nothing else."
    )
    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.8},
            timeout=CTR_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        text = resp.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return []
        items = [s.strip().strip('"').strip("'") for s in
                 m.group(0)[1:-1].split(",")]
        return [
            _clean_ctr_title(t)
            for t in items
            if t and len(t.strip()) >= 10
        ][:4]
    except Exception:  # noqa: BLE001 - LLM layer is advisory
        return []


def _clean_ctr_title(raw: str) -> str:
    """Clip to the mobile-safe length without breaking a word."""
    t = re.sub(r"\s+", " ", raw).strip()
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", t)
    if len(t.encode("utf-8")) <= CTR_TITLE_MAX_CHARS:
        return t
    words = t.split()
    out = []
    for w in words:
        if len((" ".join(out + [w])).encode("utf-8")) > CTR_TITLE_MAX_CHARS:
            break
        out.append(w)
    return " ".join(out).rstrip(" ,.")


def get_ctr_title_options(topic: str, seed_title: str) -> list:
    """Return high-CTR title candidates. LLM first (novelty), rule-based
    patterns always appended so a fully-degraded LLM still adds value."""
    # Re-read the env var at call time (module-level CTR_TITLES_OFF is frozen
    # at import, so an operator change mid-run would otherwise be invisible).
    off = os.environ.get("CTR_TITLES", "true").strip().lower() in (
        "false", "0", "no", "off",
    )
    if off:
        return []
    try:
        options = _llm_patterns(topic, seed_title)
    except Exception:  # noqa: BLE001 - LLM layer must never break a run
        options = []
    options.extend(_rule_patterns(topic))
    # De-dup while keeping LLM options first (novelty priority)
    seen, unique = set(), []
    for opt in options:
        key = opt.lower()
        if key not in seen:
            seen.add(key)
            unique.append(opt)
    return unique[:5]
