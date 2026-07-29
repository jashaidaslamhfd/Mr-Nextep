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

MIN_SCENES = 8
MAX_SCENES = 8
MIN_WORDS, MAX_WORDS = _policy_script_words()
MAX_RETRIES = 3
SCRIPT_POLICY_VERSION = "ALGO_POLICY_2026_07"
TEMPERATURE = 0.65
MAX_TOKENS = 1400

# Groq model strategy: prefer the strongest general model; if Groq ever
# retires/renames it, auto-downgrade to the known-good 8B instant model for
# the rest of the run instead of burning all retries on dead calls.
GROQ_MODEL_PRIMARY = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_MODEL_FALLBACK = "llama-3.1-8b-instant"
_model_downgraded = False

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
- Explain one verified, useful idea per video in simple everyday American English.
- Use American English spelling (color, gray, harbor, fiber, center) and USA Imperial units (miles, feet, lbs, Fahrenheit) - NEVER metric (km, kg, Celsius).
- Make a specific curiosity promise in the opening, then fully answer it.
- Never invent studies, statistics, quotes, diagnoses, cures, dangers or advice.
- Avoid fear bait, "doctors don't want you to know", "secret", fake urgency,
  unsupported certainty and repetitive AI-sounding phrases.
- Every scene must add new information. Do not repeat the hook or pad length.
- Write for speech: short sentences, concrete words, smooth transitions.
- Use a natural follow CTA only as metadata; do not force it into narration.
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
    series_rules = """
BODY GLITCH SERIES RULES:
- Cover one familiar, low-risk everyday body or brain phenomenon only.
- Use a calm, curious, trusted-science tone; never call it deadly, dark,
  scary, a diagnosis, a cure, or a treatment.
- Explain what is commonly happening, then give a simple safe takeaway.
- If relevant, say persistent, severe, new or worrying symptoms deserve a
  qualified clinician's advice. Do not give medical instructions.
""" if body_glitch_mode else ""
    from algorithm_policy import YOUTUBE, duration_policy, hook_seconds
    _floor, _ideal, _ceiling = duration_policy(YOUTUBE)
    _hook_budget = hook_seconds(YOUTUBE)
    preferred_frame = _preferred_hook_frame_hint()
    return f"""
Create one original {_floor:.0f}–{_ceiling:.0f} second YouTube Short on this topic:
TOPIC: {topic}
{series_rules}{preferred_frame}

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
2. SUSPENSE — scene 2; show why the answer matters and open one honest question.
3. PROBLEM — scene 3; state the relatable confusion or misconception.
4. EXPLANATION — scenes 4–5; explain the mechanism in simple, connected steps.
5. NORMAL VS NOTE — scene 6; explain the normal context without diagnosing.
6. SOLUTION / PAYOFF — scene 7; give the clear science-based answer. Make it
   ONE concrete, quotable fact — the kind a viewer would repeat to a friend.
   Instagram's second-strongest ranking signal is how often a Reel gets sent
   in a DM, and nobody forwards a vague summary.
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
- Scene 1 `visual`: a tight CLOSE-UP of a real human moment (mouth frowning at
  a mirror, hand on a chest, wide-open sleepy eyes) — faces/body close-ups stop
  the scroll; abstract wide shots don't.
- Every scene must have a distinct 5–12 word visual description with no text, logos or UI.
- Title: five to eight words that OPEN A CURIOSITY LOOP with a "Why/What happens
  when/Your …" frame — like a question the viewer suddenly NEEDS answered.
  GOOD: "Why You Hear Your Heartbeat at Night" · "Why Your Body Freezes When
  Scared". BAD (auto-rejected): plain 1-3 word labels like "Morning Voice",
  "Throat Lump", "Time Compression" — those get zero clicks.
- `thumbnail_text`: 2–4 clear words that complement—not repeat—the title.
- `cta`: one brief, natural follow/subscribe prompt. It is metadata, not narration.
- `description`: one accurate sentence summarising the real payoff.

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
  "description": "..."
}}
"""


# ============================================
# 3. JSON CLEANING FUNCTION
# ============================================

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
    
    # Try to find JSON object
    json_match = re.search(r'\{.*\}', raw_reply, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)
    else:
        json_str = raw_reply
    
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
        
        # Fallback: Try to extract with regex
        fallback = {}
        
        # Extract title
        title_match = re.search(r'"title"\s*:\s*"([^"]+)"', json_str)
        if title_match:
            fallback['title'] = title_match.group(1)
        
        # Extract hook
        hook_match = re.search(r'"hook"\s*:\s*"([^"]+)"', json_str)
        if hook_match:
            fallback['hook'] = hook_match.group(1)
        
        # Extract scenes
        scenes_match = re.search(r'"scenes"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
        if scenes_match:
            scenes_str = scenes_match.group(1)
            scenes = []
            # Find all scene objects
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
        
        # Extract CTA
        cta_match = re.search(r'"cta"\s*:\s*"([^"]+)"', json_str)
        if cta_match:
            fallback['cta'] = cta_match.group(1)
        
        # Extract description
        desc_match = re.search(r'"description"\s*:\s*"([^"]+)"', json_str)
        if desc_match:
            fallback['description'] = desc_match.group(1)
        
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
_OVERSHOOT_GRACE_WORDS = 2


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
    for i, scene in enumerate(scenes):
        if not scene.get('visual'):
            issues.append(f"Scene {i+1} missing visual description")
        if not scene.get('caption'):
            issues.append(f"Scene {i+1} missing caption")
        else:
            scene_words = len(scene['caption'].split())
            if i == 0:
                if scene_words < HOOK_MIN_WORDS or scene_words > HOOK_MAX_WORDS:
                    issues.append(
                        f"Scene {i+1} (hook) has {scene_words} words "
                        f"(allowed {HOOK_MIN_WORDS}-{HOOK_MAX_WORDS} to stay under the 4s hook-duration gate)"
                    )
            elif scene_words > MAX_SCENE_WORDS:
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

    if lenient and issues:
        # Final-attempt safety valve: drop only the two SUBJECTIVE story-arc
        # gates (a missing scene-2 "?" or a loop-back line that does not reuse
        # a hook concept word). Those shorts are still good, publishable
        # shorts; an empty day on a daily channel is strictly worse for the
        # algorithm. Structural gates (fields, scene count, word counts,
        # hook == first caption) stay hard on every attempt.
        kept = []
        for msg in issues:
            if "LOOP-BACK" in msg or "open one honest question" in msg:
                logger.warning("Lenient accept (final attempt): %s", msg)
                continue
            kept.append(msg)
        issues = kept

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
    
    global _model_downgraded  # set in the BadRequestError handler below
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔄 Generating script (Attempt {attempt}/{max_retries})")
            
            # Call Groq API
            completion = client.chat.completions.create(
                messages=messages,
                model=(GROQ_MODEL_FALLBACK if _model_downgraded else GROQ_MODEL_PRIMARY),
                response_format={"type": "json_object"},
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS
            )
            
            raw_reply = completion.choices[0].message.content
            raw_reply = repair_mojibake(raw_reply)
            
            # Clean JSON
            script_data = _clean_json_response(raw_reply)
            
            # Normalize scenes
            script_data = _normalize_scenes(script_data)
            
            # Add metadata
            script_data['topic'] = topic
            script_data['generated_at'] = time.time()
            script_data['attempt'] = attempt
            
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
            # Model retired/renamed on Groq? Downgrade once and keep going
            # instead of failing every remaining attempt the same way.
            if not _model_downgraded and ("model" in str(e).lower() or "decommission" in str(e).lower()):
                _model_downgraded = True
                logger.warning(f"Groq primary model rejected - switching to {GROQ_MODEL_FALLBACK} for the rest of this run")
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
