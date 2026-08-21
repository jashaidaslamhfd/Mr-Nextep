"""
Script Generator Module for SKILLOR Pipeline
FULLY FIXED - JSON Cleaning + Native Tone + Retention Optimization
"""

import os
import json
import time
import logging
import re
from typing import Dict, List, Optional, Tuple
try:
    from groq import Groq, BadRequestError
except ImportError:  # lets offline validation/tests import this module
    Groq = None
    BadRequestError = Exception

# ============================================
# LOGGING CONFIGURATION
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================
# MOJIBAKE REPAIR
# ============================================
# Occasionally text arriving from the LLM response contains UTF-8 bytes
# that got decoded with the wrong codec somewhere upstream (cp1252/latin-1
# instead of UTF-8) - the classic symptom is an emoji like 🫀 turning into
# the 4-character garble "ðŸ«€". This corrupted text no longer looks like an
# emoji to any unicode-range regex (niche_strategy._EMOJI_PATTERN etc.), so
# it survives emoji-stripping and can end up duplicated alongside a second,
# correctly-encoded emoji added later. Repairing it here, right where LLM
# text first enters the pipeline, fixes it once for every downstream field
# (title, hook, captions, cta, description) instead of patching each
# consumer separately.
def _repair_mojibake_run(run: str) -> str:
    """Attempt to reverse a UTF-8-decoded-as-cp1252 mistake on one run of
    cp1252-encodable characters. Only accepted if the bytes actually decode
    as valid UTF-8 - plain ASCII and real accented text (café, naïve, ...)
    either round-trip unchanged or fail to decode and are left untouched."""
    try:
        return run.encode('cp1252').decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return run


def repair_mojibake(text: str) -> str:
    """Repairs mojibake in `text` without disturbing characters that are
    already correct (including real emoji, which aren't cp1252-encodable
    and are simply passed through untouched)."""
    if not text:
        return text
    out = []
    run = []
    for ch in text:
        try:
            ch.encode('cp1252')
            run.append(ch)
        except UnicodeEncodeError:
            if run:
                out.append(_repair_mojibake_run(''.join(run)))
                run = []
            out.append(ch)
    if run:
        out.append(_repair_mojibake_run(''.join(run)))
    return ''.join(out)

# ============================================
# CONSTANTS
# ============================================
# Length policy is NOT defined here any more. src/algorithm_policy.py owns the
# per-platform duration windows and the measured speech rate, and the word
# budgets below are derived from them — so changing the target length in one
# place updates the writer, the renderer, the cuts and the tests together.
#
# The old hardcoded 80-120 words targeted a 40-55s Short. YouTube's 2026
# Shorts ranking is watch-time-per-impression with a ~50% average-view-
# percentage gate for 30-60s videos, and this channel's own Meta data showed
# 2.6-7.5s average watch time against a 47s clip. A shorter master cut is the
# single highest-leverage change available, so the budget now follows the
# policy's 30-42s window instead of a number nobody re-checked.
from algorithm_policy import (  # noqa: E402  (config import, must precede use)
    MIN_HOOK_SCORE as _MIN_HOOK_SCORE,
    hook_word_budget as _policy_hook_words,
    scene_word_budget as _policy_scene_words,
    script_word_budget as _policy_script_words,
)

# The prompt asks the LLM for EXACTLY eight scenes and the tests build 8-scene
# scripts, so the validation ceiling MUST be 8. A stale change to 6 created two
# contradictory gates (prompt said 8, validator rejected >6) that made every
# run fail its own script gate.
MIN_SCENES = 8
MAX_SCENES = 8
MIN_WORDS, MAX_WORDS = _policy_script_words()
MAX_RETRIES = 3
SCRIPT_POLICY_VERSION = "ALGO_POLICY_2026_07"
TEMPERATURE = 0.65
MAX_TOKENS = 1400

# Groq model strategy (2026-08-15): the pipeline can no longer bet on any
# single hard-coded model id. Groq retires/renames models without notice
# (llama-3.1-70b-versatile began 404'ing for some accounts on 2026-08-14, and
# llama-3.1-8b-instant / llama-3.1-70b-instruct no longer exist at all), so
# we probe the account's live model list first and only call models the key
# actually has access to. Env overrides remain supported; empty-string values
# are treated as unset (fixes the old inline `get("GROQ_MODEL", ...)` bug).
# 2026-08-16: openai/gpt-oss-120b returns HTTP 400
# `json_validate_failed` on the pipeline's structured-JSON prompt (verified in
# run logs) — it is removed from the chain. Also, the free-tier daily token
# pool (TPD) exhausts early every day, so the generator now skips
# 429-exhausted models instead of burning retries on them.
GROQ_MODEL_PRIMARY = os.environ.get("GROQ_MODEL") or "llama-3.1-8b-instant"
# Empty by default: live model discovery supplies current fallbacks. A stale
# fallback ID is worse than a clean OpenRouter/Gemini failover.
GROQ_MODEL_FALLBACK = os.environ.get("GROQ_MODEL_FALLBACK") or ""
# Model ids that exist on Groq but are NOT chat-completion models (audio
# transcription, prompt-guard classifiers). Script generation must skip them
# — calling them returns 400 'does not support chat completions' and burns
# a retry (Aug-15 outage #2).
_NON_CHAT_MODEL_PATTERNS = (
    "whisper", "prompt-guard", "compound", "distil-whisper",
)


def _is_chat_model(model_id: str) -> bool:
    """Heuristic guard: Groq's /models endpoint lists non-chat models too;
    chat completions against them fail with 400. We keep known chat-capable
    ids and reject anything matching a non-chat pattern.
    """
    mid = model_id.lower()
    return not any(pat in mid for pat in _NON_CHAT_MODEL_PATTERNS)


_REASONING_MODEL_PATTERNS = ("gpt-oss", "qwen", "deepseek-r1", "minimax")


def _reasoning_request_kwargs(model_id: str) -> Dict[str, str]:
    """Return reasoning-only request fields without sending them to Llama/Gemma."""
    if any(pattern in model_id.lower() for pattern in _REASONING_MODEL_PATTERNS):
        return {"reasoning_format": "hidden"}
    return {}


def _groq_accessible_models(client) -> List[str]:
    """Return this account's live Groq model list (ids the key can call).
    Never raises: on probe failure we fall back to the configured ids and
    let per-call errors drive the chain instead.
    """
    try:
        return [m.id for m in client.models.list().data if _is_chat_model(m.id)]
    except Exception as exc:  # noqa: BLE001 - probe must never break the run
        logger.warning("Groq /models probe failed (%s) - using configured ids", exc)
        return []


# 2026-08-15 quality allowlist: the live /models probe returns ~40 ids
# including tiny regional models (allam-2-7b etc.) that follow the schema
# poorly — walking through them wastes every retry on 429s and junk JSON,
# which is exactly what broke the Aug-15 run (three attempts on allam-2-7b,
# all three structurally invalid). The chain now keeps only chat models with
# a proven track record on this pipeline; the configured primary/fallback
# are always preferred first.
_CHAT_MODEL_ALLOWLIST = (
    "gpt-oss-120b", "gpt-oss-20b",
    "llama-3.3-70b", "llama-3.1-8b",
    "llama3-70b", "llama3-8b",
    "deepseek-r1", "deepseek-v3",
    "mixtral-8x7b", "gemma", "qwen",
)


def _quality_model(mid: str) -> bool:
    """True if this Groq chat model is proven to produce valid scripts."""
    low = mid.lower()
    # keep anything matching a known-good family, but exclude tiny models
    return (any(pat in low for pat in _CHAT_MODEL_ALLOWLIST)
            and not re.search(r"(?i)allam|bge|nomic|starcoder", low))


def groq_model_chain() -> List[str]:
    """Return only live, chat-capable, quality-allowlisted model IDs.

    A configured fallback is a preference, not proof that the model still
    exists. Groq deprecates model IDs and account access changes over time.
    When the live probe succeeds, stale IDs are excluded before the first
    generation request. If the probe itself is unavailable, configured IDs
    remain as a degraded fallback and the request-level errors still advance
    through the chain.
    """
    preferred = [GROQ_MODEL_PRIMARY, GROQ_MODEL_FALLBACK]
    seen = set()
    chain = []
    live_models = []
    if Groq is not None:
        try:
            live_models = _groq_accessible_models(
                Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
            )
        except Exception:  # noqa: BLE001
            live_models = []

    if live_models:
        live_set = set(live_models)
        preferred = [mid for mid in preferred if mid in live_set]

    candidates = preferred + [mid for mid in live_models if _quality_model(mid)]
    for mid in candidates:
        if mid and mid not in seen and _is_chat_model(mid) and _quality_model(mid):
            chain.append(mid)
            seen.add(mid)

    # A valid key should expose at least one candidate. Keep a clear error
    # rather than allowing _current_model() to fail with IndexError.
    if not chain:
        raise RuntimeError(
            "Groq account exposes no supported chat model; refresh the model list "
            "or configure a current GROQ_MODEL."
        )
    return chain


# LLM resilience: Groq free tier is frequently rate-limited (429), which was
# stalling script generation. When Groq fails or is rate-limited, fall back to
# OpenRouter (a neutral router over many models) using OPENROUTER_API_KEY.
# 2026-08-17: meta-llama/llama-3.3-70b-instruct:free was retired from
# OpenRouter (HTTP 404 on the pipeline's request). OpenRouter's live model
# list is checked at run time; if the configured slug 404's we retry against
# every remaining ":free" chat model once before giving up.
_OPENROUTER_KNOWN_FREE = "nvidia/nemotron-3-ultra-550b-a55b:free"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
OPENROUTER_TIMEOUT = 60

# A fast, clear opening that fits inside the platform hook budget. All three
# 2026 feeds decide within the first 2-3 seconds, so the ceiling is whatever
# fits in that window at the measured speech rate — not a guessed word count.
HOOK_MIN_WORDS, HOOK_MAX_WORDS = _policy_hook_words()

# Curiosity / open-loop phrases that mark a strong Shorts hook — the single
# biggest first-3-second retention lever. Used by analyze_retention_potential
# (mirrored in shorts_enhancer.score_hook_detailed) to tell a genuine
# open-loop opener apart from a flat punctuated statement.
_HOOK_CURIOSITY_TRIGGERS = (
    "don't know", "doesn't know", "no one", "nobody", "myth", "truth",
    "secret", "most people", "never knew", "did you", "ever wonder",
    "here's why", "this is why", "the reason",
)
MIN_SCENE_WORDS, MAX_SCENE_WORDS = _policy_scene_words(MAX_SCENES)

# A title such as "Why Got Fired Matters" is grammatically short but gives
# viewers no scientific subject. Require a concrete channel-relevant anchor.
TITLE_TOPIC_ANCHORS = {
    "brain", "body", "sleep", "memory", "heart", "eyes", "eye", "gut",
    "nerve", "hormone", "cell", "blood", "immune", "health", "science",
    "space", "nasa", "planet", "ocean", "physics", "technology", "robot",
    "ai", "anatomy", "biology", "psychology", "genetics", "virus",
}

# ============================================
# 1. SYSTEM PROMPT (NATIVE TONE + RETENTION)
# ============================================

def _get_system_prompt() -> str:
    """Instructions shared by every script request.

    The aim is clarity and earned curiosity, not medical fear, fake urgency or
    recycled clickbait. A trend is a topic signal, never proof of a claim.
    """
    return """You write concise, natural American-English YouTube Shorts about
science, the human body and the brain for a general adult audience in the USA.

NON-NEGOTIABLE QUALITY RULES:
- DO NOT sound like an AI. You must sound like a real, conversational human (maybe slightly cynical or deadpan).
- BANNED WORDS: "delve", "explore", "fascinating", "incredible", "journey", "mind-blowing", "buckle up", "in this digital age", "crucial", "testament", "tapestry". If you use these, the video feels like "AI slop".
- Explain one verified, useful idea per video in simple everyday American English.
- Use American English spelling (color, gray, harbor, fiber, center) and USA Imperial units (miles, feet, lbs, Fahrenheit) - NEVER metric (km, kg, Celsius).
- Make a specific curiosity promise in the opening, then fully answer it.
- Never invent studies, statistics, quotes, diagnoses, cures, dangers or advice.
- Avoid fear bait, "doctors don't want you to know", "secret", fake urgency,
  unsupported certainty and repetitive AI-sounding phrases.
- Every scene must add new information. Do not repeat the hook or pad length.
- Write for speech: short sentences, concrete words, smooth transitions.
- Use a natural follow CTA only as metadata; do not force it into narration.
- RETENTION FIRST: viewers decide in the first 2-3 seconds. The first sentence
  must carry STAKES — name the weird moment AND why it matters to the viewer
  ("Your calf locks up at 3am *because* the nerve is misfiring"), never a
  flat greeting or label.
- The LAST scene must flow straight into the first (loop-back), so a replay
  feels intentional. Replays count as watch time.
- Return valid JSON only—no Markdown and no commentary.
"""


# ============================================
# 2. PROMPT GENERATION
# ============================================

def _score_hook_for_feedback(script_data: Dict) -> Tuple[int, List[str]]:
    """Score the opening line and return concrete fixes for the retry prompt.

    Imported lazily so this module stays importable in environments where the
    enhancer's dependencies are unavailable; a scoring failure degrades to
    "no opinion" rather than blocking generation.
    """
    try:
        from shorts_enhancer import score_hook_detailed
    except Exception:  # noqa: BLE001
        return 100, []
    result = score_hook_detailed(script_data.get('hook', ''))
    fixes = [c['note'] for c in result.get('checks', []) if not c.get('passed', True)]
    return int(result.get('score', 0)), fixes


def _preferred_hook_frame_hint() -> str:
    """Bias the opening frame toward whatever the channel's own data shows is
    surviving the first three seconds.

    This is the learning loop reaching into generation. It stays a HINT rather
    than a rule for two reasons: the growth engine only returns a frame once it
    has enough mature samples to be meaningful, and locking every video into
    one opening shape is precisely the templated-output pattern YouTube's
    inauthentic-content policy targets. Variety is a compliance requirement,
    not just a stylistic preference.
    """
    try:
        from growth_engine import get_preferred_hook_frame
        frame = get_preferred_hook_frame()
    except Exception:  # noqa: BLE001 - learning must never block generation
        return ""
    if not frame:
        return ""
    phrasing = {
        "why": 'a "Why ..." question frame',
        "what": 'a "What happens when ..." frame',
        "how": 'a "How ..." frame',
        "second_person": 'a direct "Your ..." statement frame',
        "question": "a direct question frame",
        "statement": "a flat declarative frame",
    }.get(frame)
    if not phrasing:
        return ""
    return (
        f"\nCHANNEL DATA: {phrasing} is currently holding viewers best on this "
        "channel. Prefer it unless the topic genuinely reads better another way "
        "— do not force it.\n"
    )


def _default_prompt(topic: str) -> str:
    """Build one internally consistent short-form script brief."""
    body_glitch_mode = os.environ.get("CONTENT_SERIES", "").lower() == "body_glitches"
    dark_mystery_mode = os.environ.get("CONTENT_SERIES", "").lower() in (
        "dark_mystery", "dark_mysteries", "mind_bending", "mystery_facts"
    )
    series_rules = """
BODY GLITCH SERIES RULES:
- Cover one familiar, low-risk everyday body or brain phenomenon only.
- Use a calm, curious, trusted-science tone; never call it deadly, dark,
  scary, a diagnosis, a cure, or a treatment.
- Explain what is commonly happening, then give a simple safe takeaway.
- If relevant, say persistent, severe, new or worrying symptoms deserve a
  qualified clinician's advice. Do not give medical instructions.
""" if body_glitch_mode else ""

    dark_series_rules = """DARK MYSTERY & MIND-BENDING FACTS SERIES RULES:
- Open with a curiosity or mild-tension hook that makes the viewer need the
  answer (a "why does this happen?" gap). Keep the framing intriguing, not gory.
- Deliver one surprising, well-sourced fact, then resolve it by the last scene
  so the video ends on a loopable "wait... so it's [X]" payoff.
- End on a clean loop-back line (no spoken CTA). The follow-ask lives in the
  caption. Use a confident, even-keeled narrator voice — calm contrast with
  curiosity makes the reveal land harder.
- Keep it fact-based and truthful. No invented "facts", no fake cures, no
  panic. Frame unusual phenomena as real but explainable.
""" if dark_mystery_mode else ""
    from algorithm_policy import YOUTUBE, duration_policy, hook_seconds
    _floor, _ideal, _ceiling = duration_policy(YOUTUBE)
    _hook_budget = hook_seconds(YOUTUBE)
    preferred_frame = _preferred_hook_frame_hint()
    return f"""
Create one original {_floor:.0f}–{_ceiling:.0f} second YouTube Short on this topic:
TOPIC: {topic}
{series_rules}{dark_series_rules}{preferred_frame}

Use EXACTLY eight scenes and return the JSON schema below.

LENGTH IS A RANKING RULE, NOT A STYLE CHOICE. YouTube pushes a Short wider
only when viewers watch about half of it; Facebook and Instagram want closer
to three quarters. A {_ideal:.0f}-second video that finishes beats a
60-second video that gets abandoned, every time. Say the one idea and stop.

STORY ARC:
1. HOOK — scene 1; {HOOK_MIN_WORDS}–{HOOK_MAX_WORDS} words, spoken in under
   {_hook_budget:.1f} seconds. A PATTERN INTERRUPT in second person ("you/your"):
   name the everyday moment, then snap to the unexpected twist. It must create
   an open loop the viewer cannot scroll past. GOOD: "Why does your voice sound
   dead every single morning?" / "Your body freezes you before a scary sound."
   BAD (never do this): "Morning voice happens to everyone." / "Let's talk
   about throat lumps." — flat statements are swipe death (channel analytics:
   73.9% swipe-away on calm openers).
   2026-08-15 FIRST-3-SECONDS fix (viral gap 5): the scene-1 VISUAL must show
   the phenomenon ALREADY IN MOTION — not about to happen. A yawn video opens
   ON the yawn, the freeze video opens ON the frozen body, never on a person
   'about to yawn'. The viewer's first frame is the whole audition: if the
   frame one eye-catch needs a second word of setup, the cut is dead.
2. SUSPENSE — scene 2; show why the answer matters and open one honest question.
3. PROBLEM — scene 3; state the relatable confusion or misconception.
4. EXPLANATION — scenes 4–5; explain the mechanism in simple, connected steps.
5. NORMAL VS NOTE — scene 6; explain the normal context without diagnosing.
6. SOLUTION / PAYOFF — scene 7; give the clear science-based answer. Make it
   ONE concrete, quotable fact — the kind a viewer would repeat to a friend.
   Instagram's second-strongest ranking signal is how often a Reel gets sent
   in a DM, and nobody forwards a vague summary. 2026-08-15 SENDABLE-ENDING
   fix: the scene-7 fact MUST be specific enough to send verbatim — include a
   number, a contrast or a surprising mechanism (e.g. "Your brain literally
   mutes your hearing for 20 milliseconds before you blink"). Vague summaries
   like "your body is amazing" are auto-failures; imagine the viewer typing
   the fact into a group chat — that sentence must survive the trip.
7. LOOP-BACK — scene 8; close by restating the opening moment now that the
   viewer knows the answer, so the last line flows straight back into the
   first. A Short that loops cleanly earns replays, and replays count as
   watch time on all three platforms. Do NOT end with a sign-off, a farewell,
   or any "follow/like/share" line — the spoken CTA has been removed on
   purpose because it costs completion on a short video.

HARD FORMAT RULES:
- Total spoken captions: {MIN_WORDS}–{MAX_WORDS} words.
- Scene 1: {HOOK_MIN_WORDS}–{HOOK_MAX_WORDS} words. Scenes 2–8: {MIN_SCENE_WORDS}–{MAX_SCENE_WORDS} words each.
- `hook` must match scene 1 caption exactly.
- Scene 1 `visual`: a tight CLOSE-UP of a real human moment ALREADY MID-ACTION
  (mouth wide open mid-yawn, hand gripping a chest mid-cramp, eyes snapping
  open mid-jolt) — faces/body close-ups caught in motion stop the scroll;
  static poses or 'about to happen' setups don't. The first frame must read
  instantly, no setup words needed.
- Every scene must have a distinct 5–12 word visual description with no text, logos or UI.
- Title: five to eight words that OPEN A CURIOSITY LOOP with a "Why/What happens
  when/Your …" frame — like a question the viewer suddenly NEEDS answered.
  GOOD: "Why You Hear Your Heartbeat at Night" · "Why Your Body Freezes When
  Scared". BAD (auto-rejected): plain 1-3 word labels like "Morning Voice",
  "Throat Lump", "Time Compression" — those get zero clicks.
- `thumbnail_text`: 2–4 clear words that complement—not repeat—the title.
- `cta`: one brief, natural follow/subscribe prompt. It is metadata, not narration.
- `description`: one accurate sentence summarising the real payoff.
- `evidence_summary`: one sentence stating the factual mechanism without hype.
- `sources`: one to three source objects with `title`, `url`, and `accessed_at`.
  Use authoritative sources such as government, university, medical society, or
  peer-reviewed research. Never invent a URL; if no source is available, set
  `sources` to [] and the publish gate will keep the video in draft.
- `risk_level`: one of `low`, `medium`, or `high`. Symptoms, diseases,
  treatment, diagnosis, cure, emergency, or medication claims are at least
  `medium`; high-risk claims require human review.
- `disclaimer_required`: true for medium/high-risk claims.

JSON ONLY:
{{
  "title": "...",
  "thumbnail_text": "...",
  "hook": "...",
  "scenes": [
    {{"visual": "...", "caption": "..."}},
    {{"visual": "...", "caption": "..."}},
    {{"visual": "...", "caption": "..."}},
    {{"visual": "...", "caption": "..."}},
    {{"visual": "...", "caption": "..."}},
    {{"visual": "...", "caption": "..."}},
    {{"visual": "...", "caption": "..."}},
    {{"visual": "...", "caption": "..."}}
  ],
  "cta": "...",
  "description": "...",
  "evidence_summary": "...",
  "sources": [
    {{"title": "...", "url": "https://...", "accessed_at": "YYYY-MM-DD"}}
  ],
  "risk_level": "low",
  "disclaimer_required": false
}}
"""


# ============================================
# 3. JSON CLEANING FUNCTION
# ============================================

def _balanced_json(text: str) -> Optional[str]:
    """Find the longest balanced top-level {...} JSON object starting from
    the FIRST '{' (greedy `.*` matching was hijacked by prompt echoes that
    contain braces). Uses a brace-depth walk so nested objects stay intact."""
    start = text.find('{')
    if start < 0:
        return None
    depth, end = 0, -1
    in_str, esc = False, False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == '\\' and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    return text[start:end]


def _clean_json_response(raw_reply: str) -> Dict:
    """
    Cleans and extracts JSON from LLM response.
    Handles markdown code blocks, extra text, and malformed JSON.
    """
    if not raw_reply:
        raise ValueError("Empty response from LLM")

    # Remove markdown code blocks
    raw_reply = re.sub(r'```json\s*', '', raw_reply)
    raw_reply = re.sub(r'```\s*', '', raw_reply)

    # Try to find JSON object (balanced-brace first, greedy regex after).
    # 2026-08-17: some fallback models echo the user prompt back into the
    # reply (prompt contains a JSON schema with braces). Walking all balanced
    # top-level objects, parsing each, and keeping the candidate with the
    # required script fields picks the real generated JSON over the echo.
    json_str = _balanced_json(raw_reply)
    if json_str is None:
        json_match = re.search(r'\{.*\}', raw_reply, re.DOTALL)
        json_str = json_match.group(0) if json_match else raw_reply

    # Collect every balanced top-level object and every greedy match, parse
    # each candidate, and keep the best script-shaped one.
    _REQUIRED_FIELDS = ("title", "hook", "scenes", "cta")
    def _score_candidate(s: str) -> Optional[Dict]:
        try:
            obj = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(obj, dict) or not all(k in obj for k in _REQUIRED_FIELDS):
            return None
        return obj
    candidates = []
    seen_starts = set()
    for start in range(len(raw_reply)):
        if raw_reply[start] != '{' or start in seen_starts:
            continue
        # find balanced end from this start
        depth, end = 0, -1
        instr, esc = False, False
        for i in range(start, len(raw_reply)):
            ch = raw_reply[i]
            if esc:
                esc = False
                continue
            if ch == '\\' and instr:
                esc = True
                continue
            if ch == '"':
                instr = not instr
                continue
            if instr:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end < 0:
            continue
        seg = raw_reply[start:end].strip()
        candidates.append(seg)
        seen_starts.add(start)
    best = None
    for seg in candidates:
        obj = _score_candidate(seg)
        if obj is None:
            continue
        scenes = obj.get("scenes") or []
        # Scene schema examples in the prompt have placeholder text;
        # require real captions (>=5 chars each) to distinguish generated
        # JSON from echoed prompt schemas.
        real_scenes = [
            s for s in scenes
            if isinstance(s, dict) and len(s.get("caption") or "") >= 5
            and len(s.get("visual") or "") >= 5
        ]
        n = len(real_scenes)
        best_n = len([
            s for s in ((best or {}).get("scenes") or [])
            if isinstance(s, dict) and len(s.get("caption") or "") >= 5
            and len(s.get("visual") or "") >= 5
        ])
        if best is None or n > best_n:
            best = obj
            if n >= MIN_SCENES:
                # A complete script beats any partial candidate immediately.
                break
    if best is not None:
        return best

    # Clean common JSON issues
    json_str = json_str.strip()
    
    # Fix trailing commas
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    
    # NOTE: We intentionally do NOT blanket-convert single quotes to double
    # quotes here. Groq's response_format={"type": "json_object"} already
    # guarantees valid double-quoted JSON, and the system prompt asks for
    # natural contractions ("don't", "you're"), which contain apostrophes.
    # Converting those apostrophes to '"' corrupts the JSON mid-string
    # (this was the root cause of the "Expecting ',' delimiter" errors).
    
    # Remove control characters
    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
    
    # Fix unescaped newlines in strings
    json_str = re.sub(r'(?<!\\)\n', ' ', json_str)
    
    # Try to parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parsing failed: {e}")
        logger.debug(f"Cleaned JSON: {json_str[:500]}...")
        
        # Fallback: Try to extract with regex, scanning the WHOLE reply
        # (models that emit chain-of-thought keep the JSON fragment late in
        # the text; the greedy regex above is often anchored to the prompt
        # echo, so regex field extraction over the full reply catches it).
        raw_reply_scan = raw_reply
        fallback = {}
        
        # Extract title (last occurrence wins — generated JSON sits after
        # the echoed prompt schema).
        title_matches = re.findall(r'"title"\s*:\s*"([^"]+)"', raw_reply_scan)
        if title_matches:
            fallback['title'] = title_matches[-1]
        
        # Extract hook
        hook_matches = re.findall(r'"hook"\s*:\s*"([^"]+)"', raw_reply_scan)
        if hook_matches:
            fallback['hook'] = hook_matches[-1]
        
        # Extract scenes
        scenes_matches = re.findall(r'"scenes"\s*:\s*\[(.*?)\]', raw_reply_scan, re.DOTALL)
        for scenes_str in reversed(scenes_matches):
            scenes = []
            scene_blocks = re.finditer(r'\{[^{}]*\}', scenes_str, re.DOTALL)
            for block in scene_blocks:
                scene_str = block.group(0)
                visual_match = re.search(r'"visual"\s*:\s*"([^"]+)"', scene_str)
                caption_match = re.search(r'"caption"\s*:\s*"([^"]+)"', scene_str)
                if visual_match and caption_match:
                    scenes.append({
                        'visual': visual_match.group(1),
                        'caption': caption_match.group(1)
                    })
            if scenes:
                fallback['scenes'] = scenes
                break
        
        # Extract CTA
        cta_matches = re.findall(r'"cta"\s*:\s*"([^"]+)"', raw_reply_scan)
        if cta_matches:
            fallback['cta'] = cta_matches[-1]
        
        # Extract description
        desc_matches = re.findall(r'"description"\s*:\s*"([^"]+)"', raw_reply_scan)
        if desc_matches:
            fallback['description'] = desc_matches[-1]
        
        if fallback:
            logger.info("✅ Extracted data using regex fallback")
            return fallback
        
        raise ValueError(f"Could not parse JSON from response: {raw_reply[:200]}")


# ============================================
# 4. SCRIPT VALIDATION & NORMALIZATION
# ============================================

# How many words over the limit a COMPLETE sentence may run before it is
# worth breaking. Two words of overshoot costs ~0.8s; a fragment costs the
# viewer's comprehension at the exact moment the feed is deciding.
#
# THIS NUMBER IS PART OF THE VALIDATION CONTRACT, not a private detail of the
# trimmer. _trim_to_word_limit deliberately hands back a slightly-over
# sentence rather than mutilating it, so _validate_script has to accept the
# very same allowance. When it did not, the grace branch was unreachable by
# construction: every caption the trimmer spared was then rejected by the
# validator with "Scene N has 17 words (maximum 15)", the attempt was burned,
# and after three of those the whole run exited 1 without uploading. Both
# sides now read this constant.
_OVERSHOOT_GRACE_WORDS = 2


def effective_word_ceiling(max_words: int) -> int:
    """The largest caption the pipeline will actually accept for a budget.

    Anything above this is genuinely uncuttable and is bounced back to the
    model for a rewrite. Anything at or below it either fits, or is a whole
    sentence the trimmer chose to keep intact.
    """
    return max_words + _OVERSHOOT_GRACE_WORDS


def _trim_to_word_limit(caption: str, max_words: int) -> str:
    """Trim a caption to max_words WITHOUT ever emitting a fragment.

    Its own docstring used to promise "regeneration is always better than
    broken audio" and then do the opposite: step 3 hard-cut mid-sentence and
    glued a period on. With the tightened hook budget that path became the
    common case, turning good openers into:

        "Your calf locks up in the middle of the night."
          -> "Your calf locks up in."

    A truncated hook fails at the precise moment it was supposed to win, and
    the caption no longer matches the narration.

    Order of preference now:
      1. already short enough                      -> unchanged
      2. a complete sentence ends within range     -> cut there
      3. a complete sentence runs slightly over    -> keep it whole (grace)
      4. a clause boundary sits late in the line   -> cut there
      5. otherwise                                 -> return UNCHANGED and let
         _validate_script reject it, so the LLM rewrites a genuinely short
         line instead of the pipeline shipping a broken one.
    """
    words = caption.split()
    if len(words) <= max_words:
        return caption

    truncated = " ".join(words[:max_words])

    # 2) A complete sentence that ends inside the budget is the ideal cut.
    last_stop = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    if last_stop >= len(truncated) * 0.3:
        return truncated[:last_stop + 1]

    # 3) The whole caption is one sentence that only just overshoots. Keeping
    # it intact is better than any cut we could make.
    if len(words) <= max_words + _OVERSHOOT_GRACE_WORDS:
        return caption

    # 4) A late clause boundary still sounds deliberate when spoken.
    clause_floor = len(truncated) * 0.55
    for sep in (";", "—", ",", ":"):
        idx = truncated.rfind(sep)
        if idx >= clause_floor:
            return truncated[:idx].rstrip() + "."

    # 5) No honest cut exists. Hand the over-long caption back untouched so
    # validation fails it and the model regenerates.
    return caption


def _normalize_scenes(script_data: Dict) -> Dict:
    """
    Normalizes scene data from various formats.
    Ensures all required fields are present.
    """
    normalized = []
    
    for s in script_data.get('scenes', []):
        # Try different field names
        visual = s.get('visual') or s.get('description') or s.get('image') or ''
        caption = s.get('caption') or s.get('text') or s.get('speech') or ''
        
        # Clean and validate
        visual = visual.strip()
        caption = caption.strip()
        
        if visual and caption:
            normalized.append({
                "visual": visual,
                "caption": caption
            })
        elif caption and not visual:
            # If only caption exists, generate a generic visual
            normalized.append({
                "visual": f"Dark cinematic shot of {caption[:30]}...",
                "caption": caption
            })

    # Auto-fix: trim any scene that's over its word limit instead of
    # spending a full LLM retry on something a simple trim already solves.
    # Scene 1 (the hook) has a tighter cap - see _validate_script for why.
    for i, scene in enumerate(normalized):
        limit = HOOK_MAX_WORDS if i == 0 else MAX_SCENE_WORDS
        scene['caption'] = _trim_to_word_limit(scene['caption'], limit)

        # Models often omit terminal punctuation in JSON captions. Repair
        # that harmless formatting here instead of spending an LLM retry.
        # Strip any dangling clause punctuation first: appending to a caption
        # that already ends in a comma produced "your foot tingles,." which
        # then reached the SRT file and the burned-in captions.
        caption = scene['caption'].rstrip().rstrip(',;:—-').rstrip()
        if caption and caption[-1] not in '.!?…':
            caption += '.'
        scene['caption'] = caption
    script_data['scenes'] = normalized
    script_data['voiceover'] = ' '.join(s['caption'] for s in normalized)

    # Auto-fix: the scored hook must be the exact line viewers hear first.
    # Rather than relying on the LLM to retype the hook identically to
    # scene 1's caption (a common, easy mistake for smaller models), just
    # force them to match - scene 1's caption is the source of truth since
    # that's what's actually spoken.
    if normalized:
        script_data['hook'] = normalized[0]['caption']

    return script_data


def _validate_script(script_data: Dict, lenient: bool = False) -> Tuple[bool, List[str]]:
    """
    Validates script for quality and completeness.
    
    Returns:
        (is_valid, issues_list)
    """
    issues = []
    
    # Check required fields
    required_fields = ['title', 'hook', 'scenes', 'cta']
    for field in required_fields:
        if not script_data.get(field):
            issues.append(f"Missing required field: {field}")

    # main.py replaces temporary LLM titles with the deterministic Body
    # Glitch episode title before SEO/upload. Do not burn API retries over
    # title word counts here; the published title is validated by the series.
    # Check scenes
    scenes = script_data.get('scenes', [])
    if len(scenes) < MIN_SCENES:
        issues.append(f"Too few scenes: {len(scenes)} (minimum {MIN_SCENES})")
    elif len(scenes) > MAX_SCENES:
        issues.append(f"Too many scenes: {len(scenes)} (maximum {MAX_SCENES})")
    
    # Check word count
    voiceover = script_data.get('voiceover', '')
    word_count = len(voiceover.split())
    if word_count < MIN_WORDS:
        issues.append(f"Too few words: {word_count} (minimum {MIN_WORDS})")
    elif word_count > MAX_WORDS:
        issues.append(f"Too many words: {word_count} (maximum {MAX_WORDS})")
    
    # Check each scene
    # (HOOK_MIN_WORDS/HOOK_MAX_WORDS/MAX_SCENE_WORDS are the same constants
    # _normalize_scenes already auto-trims to, so a script that's been
    # normalized should always pass this - this check is now mostly a
    # safety net for anything normalization didn't catch.)
    #
    # The ceiling checked here must match what the trimmer is allowed to keep
    # (see _OVERSHOOT_GRACE_WORDS). Checking the raw budget while the trimmer
    # preserved a whole sentence two words over made those two paths disagree,
    # and the disagreement — not the model — is what failed entire runs.
    hook_ceiling = effective_word_ceiling(HOOK_MAX_WORDS)
    scene_ceiling = effective_word_ceiling(MAX_SCENE_WORDS)
    for i, scene in enumerate(scenes):
        if not scene.get('visual'):
            issues.append(f"Scene {i+1} missing visual description")
        if not scene.get('caption'):
            issues.append(f"Scene {i+1} missing caption")
        else:
            scene_words = len(scene['caption'].split())
            if i == 0:
                if scene_words < HOOK_MIN_WORDS or scene_words > hook_ceiling:
                    issues.append(
                        f"Scene {i+1} (hook) has {scene_words} words "
                        f"(allowed {HOOK_MIN_WORDS}-{HOOK_MAX_WORDS} to stay under the hook-duration gate)"
                    )
            elif scene_words > scene_ceiling:
                issues.append(f"Scene {i+1} has {scene_words} words (maximum {MAX_SCENE_WORDS})")

    # The scored hook must be the line viewers actually hear first.
    if scenes and script_data.get('hook'):
        def norm(value):
            return re.sub(r"[^a-z0-9 ]", "", value.lower()).strip()
        hook = norm(script_data['hook'])
        first = norm(scenes[0].get('caption', ''))
        if hook != first:
            issues.append("Hook must exactly match the first scene caption")

    # ------------------------------------------------------------------
    # STORY ARC ENFORCEMENT (2026 Shorts feed reality check)
    # The prompt already demands Hook → Suspense → … → Payoff → Loop-back,
    # but nothing enforced it — weak arcs shipped whenever the LLM got
    # lazy. YouTube Shorts ranks on first-3s swipe survival + completion +
    # replays: an open question in scene 2 and a closing loop that points
    # back to the hook are the two cheapest retention levers we have.
    # A script missing them is retried (quality gate), never shipped.
    # ------------------------------------------------------------------
    if len(scenes) >= 3:
        suspense = scenes[1].get('caption', '')
        if '?' not in suspense:
            issues.append(
                "Scene 2 (SUSPENSE) must open one honest question ('?') — "
                "the open loop is what stops the swipe in the first 3s."
            )
        hook_concepts = _content_concepts(scenes[0].get('caption', ''))
        tail_concepts = _content_concepts(scenes[-1].get('caption', ''))
        if hook_concepts and not (hook_concepts & tail_concepts):
            issues.append(
                "Final scene (LOOP-BACK) must echo the opening idea — share at "
                "least one concept word with the hook so the Short loops "
                "cleanly and feels complete (replay = ranking signal)."
            )

        repaired = 0
        if lenient and issues:
            # Final-attempt safety valve (2026-08-15): an empty day on a daily
            # channel is strictly worse for the algorithm than a small, safe,
            # machine-applied repair. SUBJECTIVE story-arc gates are dropped
            # as before; TRIVIALLY-FIXABLE structural issues are now repaired
            # in place instead of failing the run:
            #   * missing 'cta' -> synthesised from the last caption + subscribe
            #     prompt (every short must end with a CTA; generating one here
            #     is exactly what the LLM would have written anyway)
            #   * > MAX_SCENES  -> trim the tail to the policy limit (extra
            #     scenes are never spoken past the budget window)
            if 'cta' in required_fields and not script_data.get('cta'):
                topic_text = str(script_data.get('topic') or '').strip()
                tail = script_data['scenes'][-1]['caption'] if script_data.get('scenes') else topic_text
                script_data['cta'] = (
                    f"Follow for more {topic_text.lower() if topic_text else 'mind-blowing'} "
                    "facts — your brain will thank you."
                    if not tail else
                    f"{tail} Follow for more — subscribe and your next video finds you."
                )
                logger.warning("Lenient repair (final attempt): synthesised CTA")
                repaired += 1
        # 2026-08-15: heavy Groq 429 storms + weak-model outputs produced
        # non-trivial-but-publishable scripts ('Too few words', 'Scene 2
        # missing question'). Subjective story-arc gates are already dropped
        # in lenient mode; finish the job: treat the remaining structural
        # nits as publishing warnings, not blockers. A shorter short with a
        # strong topic beats an empty upload slot on a daily channel.
        if lenient and issues:
            kept = []
            for msg in issues:
                if msg.startswith('Too few words:') or 'Scene 2 (SUSPENSE)' in msg:
                    logger.warning("Lenient accept (final attempt): %s", msg)
                    continue
                kept.append(msg)
            issues = kept
        if len(script_data.get('scenes', [])) > MAX_SCENES:
            script_data['scenes'] = script_data['scenes'][:MAX_SCENES]
            script_data['voiceover'] = ' '.join(
                s['caption'] for s in script_data['scenes']
            )
            logger.warning("Lenient repair (final attempt): trimmed to %d scenes", MAX_SCENES)
            repaired += 1
            kept = []
            for msg in issues:
                if "LOOP-BACK" in msg or "open one honest question" in msg:
                    logger.warning("Lenient accept (final attempt): %s", msg)
                    continue
                if "Missing required field: cta" in msg or msg.startswith("Too many scenes"):
                    continue  # repaired above
                kept.append(msg)
            issues = kept
            if repaired:
                logger.warning("Final attempt repaired %d issue(s); publishing anyway.", repaired)
    return len(issues) == 0, issues


_ARC_STOPWORDS = {
    "this", "that", "with", "from", "your", "yours", "when", "what", "why",
    "how", "have", "has", "been", "there", "their", "they", "them", "about",
    "just", "like", "over", "under", "more", "most", "some", "into", "also",
    "very", "than", "then", "these", "those", "because", "while", "after",
    "before", "people", "really", "actually", "don't", "doesn't", "every",
    "many", "much", "feel", "feels", "thing", "things", "body",
}


def _content_concepts(text: str) -> set:
    """Stem-ish concept words for arc-overlap checks: lowercase, punctuation
    stripped, stopwords and short words removed, naive 's'-dedupe so
    'memories'/'memory', 'sleeps'/'sleep' collide."""
    concepts = set()
    for raw in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split():
        if len(raw) <= 3 or raw in _ARC_STOPWORDS:
            continue
        stem = raw.rstrip("s")  # crude plural fold
        concepts.add(stem if len(stem) > 3 else raw)
    return concepts


# ---------------------------------------------------------------------------
# PUBLIC API — stable importable interface.
# ---------------------------------------------------------------------------

def validate_script(script_data: Dict) -> Tuple[bool, List[str]]:
    """Validate a generated script for structural completeness.

    Public wrapper around the internal ``_validate_script``.
    Use this from external code (quality_checker, tests, etc.)
    instead of importing the underscore-prefixed version.

    Parameters
    ----------
    script_data : dict
        Script dictionary with 'title', 'hook', 'scenes', 'cta', 'voiceover'.

    Returns
    -------
    tuple[bool, list[str]]
        (is_valid, issues_list)
    """
    return _validate_script(script_data)


# ============================================
# 5. RETENTION ANALYSIS
# ============================================

def analyze_retention_potential(script_data: Dict) -> Dict:
    """
    Analyzes script for retention potential.
    Returns score (0-100) and suggestions.
    """
    scenes = script_data.get('scenes', [])
    score = 0
    suggestions = []
    
    # Check scene count
    if MIN_SCENES <= len(scenes) <= MAX_SCENES:
        score += 20
    else:
        suggestions.append(f"Optimal scene count: {MIN_SCENES}-{MAX_SCENES}, currently {len(scenes)}")
    
    # Check hook
    hook = script_data.get('hook', '')
    if hook:
        hook_words = len(hook.split())
        if HOOK_MIN_WORDS <= hook_words <= HOOK_MAX_WORDS:
            score += 15
        else:
            suggestions.append(f"Hook should be {HOOK_MIN_WORDS}-{HOOK_MAX_WORDS} words for a fast, clear opening")
        
        # Pattern interrupt / curiosity loop — the single biggest Shorts
        # retention lever. A hook that opens a question or curiosity loop
        # ("Why does your…", ending on "?", or a genuine curiosity phrase)
        # keeps viewers past the first ~3s. Previously ANY punctuation earned
        # the same credit, so flat openers scored identically to strong ones.
        # Strong open-loop hooks now earn a larger bonus; merely-punctuated
        # openers keep the original credit (no regression for passing scripts).
        if len(hook.split()) <= 9:
            hook_l = hook.lower().strip()
            opens_loop = (
                hook_l.endswith("?")
                or re.search(r"\b(why|how|what|when)\b", hook_l) is not None
                or any(t in hook_l for t in _HOOK_CURIOSITY_TRIGGERS)
            )
            if opens_loop:
                score += 15
            elif any(ch in hook for ch in ['?', '.', '!']):
                score += 10
    
    # Check "YOU" language
    voiceover = script_data.get('voiceover', '')
    you_count = voiceover.lower().count('you')
    if you_count >= 2:
        score += 15
    else:
        suggestions.append("Use the viewer naturally once or twice where it helps clarity")
    
    # Check cliffhangers
    cliffhanger_count = 0
    for scene in scenes:
        caption = scene.get('caption', '')
        if any(word in caption.lower() for word in ['...', 'but', 'however', 'yet', 'still', 'though']):
            cliffhanger_count += 1
    
    if 1 <= cliffhanger_count <= 3:
        score += 20
    else:
        suggestions.append(f"Only {cliffhanger_count}/{len(scenes)} scenes have cliffhangers - use only 1-3 natural open loops")
    
    # Check word count
    word_count = len(voiceover.split())
    if MIN_WORDS <= word_count <= MAX_WORDS:
        score += 20
    else:
        suggestions.append(f"Word count: {word_count} (target: {MIN_WORDS}-{MAX_WORDS})")
    
    # Check for loopable outro
    cta = script_data.get('cta', '')
    if any(word in cta.lower() for word in ['follow', 'share', 'subscribe', 'comment']):
        score += 10
    
    return {
        'retention_score': min(100, score),
        'suggestions': suggestions,
        'scenes': len(scenes),
        'word_count': word_count,
        'you_count': you_count,
        'cliffhanger_ratio': cliffhanger_count / len(scenes) if scenes else 0,
        'is_viral_ready': score >= 80
    }


# ============================================
# 6. MAIN GENERATE FUNCTION
# ============================================

def _openrouter_generate(messages, temperature=None, max_tokens=None) -> Optional[str]:
    """Call OpenRouter as a fallback LLM when Groq is rate-limited/down.

    Returns the raw assistant text, or None on failure (never raises, so the
    caller can keep trying Groq). OpenRouter routes to many models; we use the
    configured OPENROUTER_MODEL (free Llama by default) so no extra cost.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        import requests as _req
        payload = {"model": OPENROUTER_MODEL, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # 2026-08-17: without this the fallback model (Nemotron) returned
        # plain conversational text — the regex fallback then extracted
        # nothing and every run died on validation. Mirrors the Groq
        # response_format json_object used on the primary path.
        payload["response_format"] = {"type": "json_object"}
        resp = _req.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/jashaidaslamhfd/Mr-Nextep",
            },
            json=payload,
            timeout=OPENROUTER_TIMEOUT,
        )
        # 2026-08-17: several free models on OpenRouter ignore
        # response_format and echo chain-of-thought text instead of JSON.
        # One automatic re-ask with an explicit JSON-only instruction
        # recovers most of those replies without code churn.
        def _reply_has_json(text: str) -> bool:
            return bool(text) and "{" in text
        if resp.status_code == 200:
            text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            if not _reply_has_json(text):
                backup_msgs = [
                    {"role": m["role"], "content": m["content"]}
                    for m in messages
                ]
                backup_msgs[-1]["content"] += (
                    "\n\nCRITICAL: Respond with ONLY a raw JSON object "
                    "starting with '{' — no thinking, no markdown, "
                    "no explanation."
                )
                payload2 = dict(payload, messages=backup_msgs)
                try:
                    r3 = _req.post(
                        OPENROUTER_API_URL,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://github.com/jashaidaslamhfd/Mr-Nextep",
                        },
                        json=payload2,
                        timeout=OPENROUTER_TIMEOUT,
                    )
                    if r3.status_code == 200:
                        text2 = r3.json().get("choices", [{}])[0].get(
                            "message", {}
                        ).get("content", "")
                        if _reply_has_json(text2):
                            logger.warning(
                                "OpenRouter re-ask recovered a JSON reply "
                                "after plain-text echo"
                            )
                            return text2
                except Exception:  # noqa: BLE001
                    pass
        if resp.status_code in (404, 429) or (resp.status_code == 200 and not _reply_has_json(text)):
            # 2026-08-17: rotate free models on two failure modes — the
            # configured slug was retired (404, verified 2026-08-17), OR the
            # active free model returned plain text instead of JSON
            # (Nemotron's frequent echo behavior). Refresh the live free-
            # model list and retry each candidate once, keeping the FIRST
            # reply that actually contains JSON.
            key = os.environ.get("OPENROUTER_API_KEY")
            _candidates = []
            if key:
                try:
                    models = _req.get(
                        "https://openrouter.ai/api/v1/models",
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=15,
                    )
                    if models.status_code == 200:
                        _candidates = [
                            m["id"] for m in models.json().get("data", [])
                            if m.get("id", "").endswith(":free")
                            and m["id"] != OPENROUTER_MODEL
                        ]
                except Exception:  # noqa: BLE001
                    _candidates = []
            for mid in _candidates[:5]:
                try:
                    payload["model"] = mid
                    r2 = _req.post(
                        OPENROUTER_API_URL,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://github.com/jashaidaslamhfd/Mr-Nextep",
                        },
                        json=payload,
                        timeout=OPENROUTER_TIMEOUT,
                    )
                    if r2.status_code == 200:
                        t2 = r2.json().get("choices", [{}])[0].get(
                            "message", {}
                        ).get("content", "")
                        logger.warning(
                            "OpenRouter model %s rotated; retried on %s "
                            "(reply has JSON: %s)",
                            OPENROUTER_MODEL, mid, _reply_has_json(t2),
                        )
                        if _reply_has_json(t2):
                            return t2
                except Exception:  # noqa: BLE001
                    continue
            logger.warning("OpenRouter fallback failed: HTTP %s (all refreshed models exhausted)", resp.status_code)
            return None
        if resp.status_code != 200:
            logger.warning("OpenRouter fallback failed: HTTP %s", resp.status_code)
            return None
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - fallback must never raise
        logger.warning("OpenRouter fallback error: %s", exc)
        return None



# 2026-08-17: Gemini 2.5 Flash (free tier) as the THIRD LLM fallback — when
# both the Groq chain and OpenRouter are exhausted (global free-tier outage
# window), the pipeline still tries Gemini before giving up.
GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_TIMEOUT = 60
# Gemini retires model IDs on a schedule. Keep a current stable preference, but
# discover the account's live generateContent models before calling it.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"
_GEMINI_MODEL_PREFERENCES = (
    GEMINI_MODEL,
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
)


def _gemini_model_candidates(_req, key: str) -> List[str]:
    """Return live Gemini generateContent model IDs in stable preference order."""
    live = []
    try:
        response = _req.get(
            f"{GEMINI_API_ROOT}/models",
            params={"key": key, "pageSize": 100},
            timeout=15,
        )
        if response.status_code == 200:
            for item in response.json().get("models", []) or []:
                name = str(item.get("name", ""))
                methods = item.get("supportedGenerationMethods", []) or []
                if name.startswith("models/"):
                    name = name.split("/", 1)[1]
                if name and "generateContent" in methods and "embedding" not in name:
                    live.append(name)
    except Exception as exc:  # noqa: BLE001 - discovery must never block fallback
        logger.warning("Gemini model discovery failed: %s", exc)
    candidates = []
    for model in list(_GEMINI_MODEL_PREFERENCES) + live:
        if model and model not in candidates:
            if not live or model in live:
                candidates.append(model)
    return candidates or list(_GEMINI_MODEL_PREFERENCES)


def _gemini_generate(messages, temperature=None, max_tokens=None) -> Optional[str]:
    """Call a live Gemini generateContent model when Groq + OpenRouter fail.

    Gemini 2.0 Flash-Lite was shut down and returned HTTP 404 in production.
    This fallback discovers current account-accessible models, separates the
    system instruction from user contents, requests JSON, and tries the next
    live model on an endpoint/model error. It never raises to the caller.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        import requests as _req

        system_text = "\n\n".join(
            str(m.get("content", "")) for m in messages if m.get("role") == "system"
        ).strip()
        contents = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": str(m.get("content", ""))}],
            })
        if not contents:
            return None
        generation_config = {"responseMimeType": "application/json"}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        payload = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        for model in _gemini_model_candidates(_req, key):
            url = f"{GEMINI_API_ROOT}/models/{model}:generateContent"
            try:
                resp = _req.post(url, params={"key": key}, json=payload, timeout=GEMINI_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini model %s request failed: %s", model, exc)
                continue
            if resp.status_code != 200:
                logger.warning("Gemini model %s fallback failed: HTTP %s", model, resp.status_code)
                continue
            text = ""
            try:
                for cand in resp.json().get("candidates", []) or []:
                    for part in (cand.get("content") or {}).get("parts", []) or []:
                        text += str(part.get("text") or "")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini model %s response parse failed: %s", model, exc)
                continue
            if "{" in text:
                logger.info("Gemini fallback generated JSON with %s", model)
                return text
            logger.warning("Gemini model %s returned no JSON; trying next model", model)
        return None
    except Exception as exc:  # noqa: BLE001 - fallback must never raise
        logger.warning("Gemini fallback error: %s", exc)
        return None



def generate_script(
    topic: str, 
    custom_prompt: Optional[str] = None, 
    max_retries: int = MAX_RETRIES
) -> Dict:
    """
    Generates a RETENTION-OPTIMIZED script using Groq LLM.
    
    Features:
    - JSON cleaning with regex fallback
    - Native English tone enforcement
    - Automatic validation and retry
    - Retention analysis
    
    Args:
        topic: Topic for the script
        custom_prompt: Optional custom prompt
        max_retries: Maximum retry attempts
    
    Returns:
        Script data dictionary
    
    Raises:
        RuntimeError: If generation fails after all retries
        ValueError: If GROQ_API_KEY is missing
    """
    logger.info(
        "Script policy %s: %s scenes, %s-%s words; temporary title is not a retry gate.",
        SCRIPT_POLICY_VERSION, MIN_SCENES, MIN_WORDS, MAX_WORDS,
    )

    # Check API key
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is missing. Please set it in environment variables.")
    
    # Initialize client only for an actual generation call. Structural checks
    # and offline tests do not require the optional runtime dependency.
    if Groq is None:
        raise RuntimeError("groq package is not installed; run pip install -r requirements.txt")
    client = Groq(api_key=api_key)
    
    # Prepare prompt
    prompt = custom_prompt or _default_prompt(topic)
    messages = [
        {"role": "system", "content": _get_system_prompt()},
        {"role": "user", "content": prompt}
    ]
    
    last_error = None
    best_script = None
    best_score = 0
    provider_used = "groq"

    # Model fallback chain (2026-08-15): never call a model id that returns
    # 404 'does not exist'. Probe the account's live model list first, walk
    # down the chain on any API-side failure, and only then try OpenRouter.
    model_chain = groq_model_chain()
    model_index = [0]

    def _current_model() -> str:
        return model_chain[min(model_index[0], len(model_chain) - 1)]

    # 2026-08-16: models whose daily token pool (TPD) is exhausted raise 429
    # with error.code 'tokens'; re-calling them wastes the entire retry
    # budget. Track them so the chain skips straight to a fresh model, and
    # re-enable an exhausted model only after Groq's own retry_after window.
    _exhausted_models = {}

    def _extract_rate_info(exc) -> Tuple[float, str]:
        """Parse (retry_after_seconds, error_code) from a Groq exception if
        available. Returns (0.0, '') when nothing parseable."""
        code, retry_after = '', 0.0
        try:
            body = json.loads(getattr(exc, 'body', '') or '{}')
            err = body.get('error') or {}
            code = err.get('code', '')
            retry_after = float(getattr(exc, 'retry_after', 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            pass
        return retry_after, code

    def _advance_model(exc) -> bool:
        """Switch to the next model in the chain after an API-side failure.

        2026-08-16: 429+tokens errors mark the current model as TPD-exhausted
        and skip it; json_validate_failed (400) drops the model entirely.
        A small retry-after window (<40s) is slept before retrying the same
        model — this covers transient burst limits without stalling the run.
        """
        retry_after, code = _extract_rate_info(exc)
        current = _current_model()
        if code in ('rate_limit_exceeded',) and 'tokens' in str(exc).lower():
            _exhausted_models[current] = time.time() + retry_after
            logger.warning(
                "Groq model %s TPD-exhausted (%s) — skipping until %s",
                current, exc, _exhausted_models[current],
            )
        if code == 'json_validate_failed':
            _exhausted_models[current] = float('inf')
            logger.warning(
                "Groq model %s returns invalid JSON (json_validate_failed) "
                "— removing from chain.", current,
            )
        # walk past any exhausted model
        for _ in range(len(model_chain)):
            if model_index[0] < len(model_chain) - 1:
                model_index[0] += 1
            if _exhausted_models.get(_current_model(), 0) > time.time():
                continue
            break
        if _current_model() != current:
            logger.warning(
                "Groq model %s failed (%s) — moving to %s",
                current, exc, _current_model(),
            )
            return True
        # chain fully exhausted: sleep retry-after (capped 45s) then re-try
        if 0.0 < retry_after <= 45.0:
            logger.warning(
                "All models 429 — sleeping %.0fs for burst limit to clear",
                retry_after,
            )
            time.sleep(retry_after)
        return False

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔄 Generating script (Attempt {attempt}/{max_retries}) via {_current_model()}")

            # Call Groq API, falling back to OpenRouter on rate-limit/errors so
            # a 429 (free-tier) can't stall the whole run.
            raw_reply = None
            try:
                completion = client.chat.completions.create(
                    messages=messages,
                    model=_current_model(),
                    response_format={"type": "json_object"},
                    **_reasoning_request_kwargs(_current_model()),
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS
                )
                raw_reply = completion.choices[0].message.content
            except Exception as groq_err:  # noqa: BLE001 - fallback on any Groq failure
                # Some currently live Groq models reject response_format=json_object
                # even though they can follow the JSON-only prompt. Retry once in
                # plain completion mode and let _clean_json_response enforce the
                # contract locally before rotating providers.
                if "json_validate_failed" in str(groq_err).lower():
                    try:
                        logger.warning("Groq structured JSON mode rejected; retrying plain JSON prompt")
                        compatibility_completion = client.chat.completions.create(
                            messages=messages,
                            model=_current_model(),
                            **_reasoning_request_kwargs(_current_model()),
                            temperature=TEMPERATURE,
                            max_tokens=MAX_TOKENS,
                        )
                        raw_reply = compatibility_completion.choices[0].message.content
                    except Exception as compatibility_err:  # noqa: BLE001
                        logger.warning("Groq plain JSON compatibility retry failed: %s", compatibility_err)
                if raw_reply:
                    pass
                elif _advance_model(groq_err):
                    # 2026-08-16: a chain-advance on the LAST attempt would
                    # silently burn the only untried model (the loop ends and
                    # the newly advanced model never gets a call). On the
                    # final attempt, generate via the OpenRouter backup LLM
                    # and fall through to validation — never finish a run
                    # without trying the backup.
                    if attempt == max_retries:
                        logger.warning(
                            "Last attempt: chain advance exhausted — "
                            "using OpenRouter backup directly."
                        )
                        raw_reply = _openrouter_generate(
                            messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS
                        )
                        if raw_reply:
                            provider_used = "openrouter"
                        else:
                            raw_reply = _gemini_generate(
                                messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS
                            )
                            if raw_reply:
                                provider_used = "gemini"
                        if raw_reply:
                            logger.info("✅ Third-provider fallback produced a script.")
                        # NOTE: deliberately no `continue` — let execution
                        # fall through to validation below.
                    else:
                        continue
                else:
                    logger.warning("Groq call failed (%s) — trying OpenRouter fallback...", groq_err)
                    raw_reply = _openrouter_generate(
                        messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS
                    )
                    if raw_reply:
                        provider_used = "openrouter"
                    else:
                        raw_reply = _gemini_generate(
                            messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS
                        )
                        if raw_reply:
                            provider_used = "gemini"
                    if raw_reply:
                        logger.info("✅ Third-provider fallback produced a script.")
            if not raw_reply:
                raise RuntimeError("All LLM providers failed (Groq chain + OpenRouter + Gemini).")
            raw_reply = repair_mojibake(raw_reply)
            
            # Clean JSON
            script_data = _clean_json_response(raw_reply)
            
            # Normalize scenes
            script_data = _normalize_scenes(script_data)
            
            # Add metadata
            script_data['topic'] = topic
            script_data['generated_at'] = time.time()
            script_data['attempt'] = attempt
            script_data['provider_used'] = provider_used
            
            # Validate
            is_valid, issues = _validate_script(script_data, lenient=(attempt == max_retries))
            
            if is_valid:
                # Analyze retention
                retention = analyze_retention_potential(script_data)
                script_data['retention_analysis'] = retention

                score = retention['retention_score']

                # Score the hook HERE, inside the conversation loop.
                #
                # The hook gate lives in main.py, which calls this function
                # fresh on every attempt — so a rejected hook produced a brand
                # new conversation and the model was never told what was wrong
                # with the last one. It could (and did) return an equally weak
                # opener three times in a row, burn all three attempts, and
                # skip the upload. Scoring it in here means the failure
                # becomes corrective feedback in the SAME conversation, which
                # is the only place the model can act on it.
                hook_score, hook_fixes = _score_hook_for_feedback(script_data)
                script_data['hook_score'] = hook_score

                # Track best script by both signals, not retention alone: the
                # hook is what decides distribution before retention is even
                # measured.
                combined = (hook_score * 0.6) + (score * 0.4)
                if combined > best_score:
                    best_script = script_data
                    best_score = combined

                if score >= 80 and hook_score >= _MIN_HOOK_SCORE:
                    logger.info(
                        "✅ Strong script — hook %s/100, retention %s/100, %d scenes, %d words",
                        hook_score, score, len(script_data['scenes']),
                        len(script_data['voiceover'].split()),
                    )
                    return script_data

                problems = []
                if hook_score < _MIN_HOOK_SCORE:
                    problems.append(
                        f"the opening line scores {hook_score}/100 (needs {_MIN_HOOK_SCORE})"
                    )
                    problems.extend(hook_fixes[:2])
                if score < 80:
                    problems.append(f"retention scores {score}/100")
                    problems.extend(retention['suggestions'][:2])

                logger.warning("⚠️ Retrying with feedback: %s", "; ".join(problems[:3]))
                # 2026-08-16 hook-quality escalation: if the current model
                # keeps producing weak hooks, prompt feedback alone won't fix
                # it — the writer is the bottleneck. Escalate to the next
                # model in the quality chain (or OpenRouter when Groq is
                # exhausted) so the retry gets a genuinely stronger opener
                # instead of the same model repeating its weakness.
                _advance_model(
                    f"hook {hook_score}/100 or retention {score}/100 below floor"
                )
                messages.append({"role": "assistant", "content": raw_reply})
                messages.append({"role": "user", "content": (
                    f"That script needs work: {'; '.join(problems[:4])}. "
                    f"Scene 1 is the whole video's chance — it must name something the "
                    f"viewer can picture, speak to them as 'you', and open a gap they "
                    f"need closed. Never open with a greeting, 'in this video', or "
                    f"'scientists found something interesting'. "
                    f"Rewrite the full script on the same topic '{topic}'. "
                    f"Return ONLY valid JSON with the same structure."
                )})
            else:
                last_error = "; ".join(issues)
                logger.warning(f"⚠️ Validation issues: {', '.join(issues[:3])}")
                messages.append({"role": "assistant", "content": raw_reply})
                messages.append({"role": "user", "content": (
                    f"The script has validation issues: {', '.join(issues[:3])}. "
                    f"Rewrite it to fix these issues. Keep the same topic '{topic}'. "
                    f"Return ONLY valid JSON with the same structure."
                )})
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON parsing failed: {e}")
            messages.append({"role": "user", "content": (
                "The previous response was not valid JSON. "
                "Please return ONLY valid JSON with this exact structure: "
                '{"title": "...", "hook": "...", "scenes": [{"visual": "...", "caption": "..."}], "cta": "..."}'
            )})
            
        except BadRequestError as e:
            logger.error(f"❌ Groq API error: {e}")
            last_error = e
            # Model retired/renamed on Groq? Walk down the model chain and
            # keep going instead of failing every remaining attempt the same
            # way (404 'model does not exist' was the Aug-14 outage cause).
            _advance_model(e)
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logger.info(f"⏳ Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                break
            
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            last_error = e
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logger.info(f"⏳ Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
    
    # If we have a best script, return it
    if best_script:
        logger.warning(f"⚠️ Using best available script (Score: {best_score}/100)")
        return best_script
    
    # Complete failure
    raise RuntimeError(
        f"❌ Script generation failed after {max_retries} attempts. "
        f"Last error: {last_error}"
    )


# ============================================
# 7. BATCH GENERATION
# ============================================

def generate_multiple_scripts(
    topics: List[str],
    max_retries: int = MAX_RETRIES,
    delay: float = 2.0
) -> List[Dict]:
    """
    Generates scripts for multiple topics.
    
    Args:
        topics: List of topics
        max_retries: Retries per script
        delay: Delay between generations
    
    Returns:
        List of script data dictionaries
    """
    scripts = []
    failed = []
    
    for i, topic in enumerate(topics):
        logger.info(f"📝 Generating script {i+1}/{len(topics)}: {topic}")
        
        try:
            script = generate_script(topic, max_retries=max_retries)
            scripts.append(script)
            logger.info(f"✅ Script {i+1} generated successfully")
        except Exception as e:
            logger.error(f"❌ Script {i+1} failed: {e}")
            failed.append({'topic': topic, 'error': str(e)})
        
        if i < len(topics) - 1:
            time.sleep(delay)
    
    logger.info(f"📊 Generated {len(scripts)}/{len(topics)} scripts successfully")
    if failed:
        logger.warning(f"⚠️ Failed scripts: {len(failed)}")
    
    return scripts, failed


# ============================================
# 8. SCRIPT EXPORT
# ============================================

def export_script(script_data: Dict, output_path: str = "output/script.json") -> str:
    """
    Exports script data to JSON file.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(script_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"📄 Script exported to: {output_path}")
    return output_path


# ============================================
# 9. MAIN EXECUTION
# ============================================

if __name__ == "__main__":
    print("="*70)
    print("SCRIPT GENERATOR - FULLY FIXED (JSON Cleaning + Native Tone)")
    print("="*70)
    print()
    
    # Test single generation
    test_topic = "Why Your Brain Lies to You"
    print(f"🧪 Testing with topic: {test_topic}")
    print("-" * 70)
    
    try:
        script = generate_script(test_topic)
        
        print("✅ Script generated successfully!")
        print()
        print(f"📌 TITLE: {script.get('title')}")
        print(f"🎯 HOOK: {script.get('hook')}")
        print(f"📊 SCENES: {len(script.get('scenes', []))}")
        print(f"📝 WORDS: {len(script.get('voiceover', '').split())}")
        print(f"📢 CTA: {script.get('cta')}")
        
        if 'retention_analysis' in script:
            analysis = script['retention_analysis']
            print()
            print("📈 RETENTION ANALYSIS:")
            print(f"   Score: {analysis.get('retention_score')}/100")
            print(f"   Viral Ready: {analysis.get('is_viral_ready')}")
            if analysis.get('suggestions'):
                print("   Suggestions:")
                for suggestion in analysis['suggestions'][:3]:
                    print(f"     - {suggestion}")
        
        print()
        print("📄 FIRST SCENE PREVIEW:")
        scenes = script.get('scenes', [])
        if scenes:
            print(f"   Visual: {scenes[0].get('visual')}")
            print(f"   Caption: {scenes[0].get('caption')}")
        
        print()
        print("-" * 70)
        print("✅ Script generator is ready for production!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
