"""
src/shorts_enhancer.py

PRD "Shorts Generator" feature. MrNextep already produces Shorts-only videos
(video_editor.py hardcodes a 1080x1920 canvas and 40-55s target), so the
"convert a long video into Shorts" part of the PRD doesn't apply here.
What DOES apply and add value on top of the existing pipeline:

  - A finer-grained hook score with concrete fix suggestions (quality_checker
    already scores the hook 0-100 for the approve/reject gate; this module
    explains *why* and *what to change*, so a human reviewing a low-scoring
    video knows what to fix instead of just seeing a number)
  - Per-scene caption pacing check (words-per-second) - a scene can pass
    quality_checker's overall pacing check while still having one scene
    that flashes by unreadably fast or drags
  - Shorts-specific hashtag set (#shorts is close to mandatory for Shorts
    surfacing - separate from the general SEO tags in seo_generator.py)
  - SRT subtitle file export from the exact per-scene audio durations
    video_editor.py already computes - lets you upload real closed
    captions (accessibility + a documented small SEO/reach benefit),
    reusing timing that's otherwise only baked into burned-in captions
"""

import os
import re
import logging
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Readable range for on-screen word-by-word captions. Below this, text
# flashes by too fast to read; above this, it drags and viewers swipe away.
# Captions are shown in short two-word chunks by video_editor, so viewers can
# comfortably follow a natural cloned voice up to 4.0 words/sec. The previous
# 3.5 limit rejected otherwise healthy 30-second videos for tiny rounding or
# one-scene delivery variations (for example 3.52 words/sec).
MIN_WORDS_PER_SEC = 1.5
MAX_WORDS_PER_SEC = 4.0

SHORTS_HASHTAGS = ["#shorts", "#youtubeshorts", "#short"]


# ---------------------------------------------------------------------------
# Hook scoring with actionable feedback
# ---------------------------------------------------------------------------

_CURIOSITY_TRIGGERS = [
    "don't know", "doesn't know", "myth", "truth", "shocking",
    "secret", "discovered", "most people", "never knew",
]
_POWER_WORDS = [
    "proven", "science", "expert", "revealed", "breakthrough",
    "hidden", "trick", "hack", "amazing", "incredible",
]


# Openings that guarantee a swipe. These are the classic YouTube-native cold
# starts — they make sense at the top of a ten-minute video and are fatal in a
# feed where the viewer has given you two seconds and no context.
_COLD_OPEN_PATTERNS = (
    r"^(hi|hey|hello|welcome|what'?s up)\b",
    r"\bwelcome back\b",
    r"\bin (this|today'?s) (video|short|one)\b",
    r"^(let'?s|lets) (talk|discuss|look|dive|get into)",
    r"^(today|so today|so,? )",
    r"\bbefore we (start|begin)\b",
    r"\bsubscribe\b",
)

# Empty authority: sounds like content, promises nothing the viewer can
# picture. "Scientists discovered something interesting" scored 85 under the
# previous scorer purely because it avoided hype words.
_VAGUE_PATTERNS = (
    r"\b(something|anything|things?)\s+(interesting|amazing|weird|strange|crazy|surprising)\b",
    r"\b(scientists?|researchers?|studies|experts?)\s+(say|found|discovered|reveal)",
    r"\bfun fact\b",
    r"\bdid you know\b",
    r"\byou won'?t believe\b",
    r"\b(this|that|it)\s+(is|was)\s+(interesting|amazing|crazy|wild)\b",
)

_COLD_OPEN_RE = re.compile("|".join(_COLD_OPEN_PATTERNS), re.IGNORECASE)
_VAGUE_RE = re.compile("|".join(_VAGUE_PATTERNS), re.IGNORECASE)

# Concrete anatomy/phenomenon vocabulary. A hook naming one of these gives the
# viewer something to picture in frame one, which is what actually stops a
# thumb. Broad on purpose — this channel covers the whole body.
_CONCRETE_SUBJECTS = (
    # body parts and systems
    "eye", "eyelid", "ear", "nose", "throat", "voice", "tongue", "tooth", "teeth",
    "brain", "memory", "dream", "sleep", "yawn", "hiccup", "sneeze", "cough",
    "heart", "pulse", "blood", "vein", "lung", "breath", "stomach", "gut",
    "hunger", "nerve", "muscle", "cramp", "knee", "joint", "bone",
    "skin", "goosebump", "itch", "sweat", "blush", "hair", "hand", "foot",
    "leg", "back", "head", "chest", "spine", "jaw", "finger", "shiver",
    "clock", "light", "sound", "hormone", "cell", "energy", "balance",
    # the PHENOMENON is often the concrete thing, not the body part:
    # "Your body freezes before you hear it" names no organ but is entirely
    # picturable. Scoring only nouns marked that hook as vague.
    "twitch", "freeze", "crack", "pop", "ring", "lock", "jolt", "flutter",
    "tingle", "numb", "spin", "blur", "flush", "chill", "ache", "throb",
    "buzz", "stutter", "shake", "tremble", "clench", "gasp",
)
def _inflected_patterns(subjects: tuple) -> List[str]:
    """Build match patterns that survive ordinary English inflection.

    A trailing ``\\w*`` only catches suffixes that are APPENDED to the stem
    ("twitch" -> "twitching"). English also drops a trailing "e" before a
    vowel suffix ("shake" -> "shaking", "freeze" -> "freezing", "tingle" ->
    "tingling") and swaps "y" for "ies" ("memory" -> "memories"). The plain
    suffix regex therefore reported "Your voice starts shaking in front of
    crowds" as naming nothing concrete, even though "shake" is in this very
    list — costing the hook 25 points and pushing it under the 80 gate.
    That is what made an entire run fail with hook=55/80 while the writer
    was, in fact, on topic.

    The drop-e form is restricted to real inflections rather than ``\\w*`` so
    a clipped stem cannot swallow an unrelated word ("ache" must not match
    "achieve").
    """
    patterns: List[str] = []
    for word in subjects:
        patterns.append(word + r"\w*")
        if word.endswith("e"):
            patterns.append(word[:-1] + r"(?:ing|ed|es|y)\w*")
        if word.endswith("y"):
            patterns.append(word[:-1] + r"ies")
    return patterns


_CONCRETE_RE = re.compile(
    r"\b(?:" + "|".join(_inflected_patterns(_CONCRETE_SUBJECTS)) + r")\b",
    re.IGNORECASE,
)

# Loops the viewer feels without a question mark. A hook can open a gap purely
# through timing ("before you hear it", "the moment you stand up") or by
# leaving a reference unresolved ("...before you hear IT"). Detecting only
# why/how/what/? missed a whole class of strong hooks and pushed the writer
# toward formulaic question openers — which is itself a templating risk.
_IMPLICIT_LOOP_PATTERNS = (
    r"\b(before|until|right after|the moment|seconds? (before|after)|just as)\b",
    r"\b(but|yet|still)\b.*\b(does|do|happens|works|isn'?t|doesn'?t)\b",
    r"\b(it|this|that|something)\s*[.!]?\s*$",
    r"\b(here'?s|that'?s)\s+(why|how|what)\b",
)
_IMPLICIT_LOOP_RE = re.compile("|".join(_IMPLICIT_LOOP_PATTERNS), re.IGNORECASE)


def score_hook_detailed(hook: str) -> Dict:
    """Score a hook against what the first two seconds actually decide.

    Rewritten because the previous version mis-ranked the two cases that
    matter most: it gave "Hello everyone and welcome back to the channel" a 70
    and "Scientists discovered something interesting" an 85, while a genuinely
    strong hook like "Your eyelid keeps twitching tonight" also scored 85. A
    scorer that cannot separate a cold open from a working hook cannot gate
    anything.

    Two structural changes:

    1. The base is 0, not 35. A hook now EARNS its score. The old free 35
       points meant an empty, generic line started most of the way to a pass.
    2. Cold opens and vague-authority phrasing are penalised hard, because
       they are not merely "less good" — they are the specific failure mode
       that caps distribution before any other signal is measured.
    """
    hook = (hook or "").strip()
    words = hook.split()
    if not hook:
        return {'score': 0, 'checks': [{'name': 'present', 'passed': False,
                                        'note': 'Hook is missing.'}]}

    hook_l = hook.lower()
    checks, score = [], 0

    # --- Length (25) -------------------------------------------------------
    # 4-9 words is what fits inside the shared ~2s hook budget at this
    # channel's measured speech rate.
    length_ok = 4 <= len(words) <= 9
    checks.append({'name': 'spoken_length', 'passed': length_ok,
                   'note': f'{len(words)} words; target is 4-9 to land inside the hook budget.'})
    if length_ok:
        score += 25
    elif len(words) < 4:
        score += 5   # a fragment names a subject but promises nothing
    # over-long hooks earn nothing here

    # --- Speaks to the viewer (20) ----------------------------------------
    direct = bool(re.search(r"\b(you|your|you'?re|yourself)\b", hook_l))
    checks.append({'name': 'viewer_or_subject', 'passed': direct,
                   'note': 'Addresses the viewer directly ("you"/"your").'})
    if direct:
        score += 20

    # --- Concrete subject (25) --------------------------------------------
    concrete = bool(_CONCRETE_RE.search(hook_l))
    checks.append({'name': 'specificity', 'passed': concrete,
                   'note': 'Names something the viewer can picture in the first frame.'})
    if concrete:
        score += 25

    # --- Opens a loop (20) -------------------------------------------------
    # Explicit (a question) or implicit (unresolved timing/reference). Both
    # count: forcing every hook into "Why does..." would make the channel's
    # openings formulaic, which is its own distribution risk.
    curiosity = (
        hook_l.rstrip().endswith("?")
        or re.search(r"\b(why|how|what|when)\b", hook_l) is not None
        or any(t in hook_l for t in _CURIOSITY_TRIGGERS)
        or bool(_IMPLICIT_LOOP_RE.search(hook_l))
    )
    checks.append({'name': 'curiosity_loop', 'passed': curiosity,
                   'note': 'Opens a question or gap the viewer wants closed.'})
    if curiosity:
        score += 20

    # --- Not a cold open (10, heavy penalty) -------------------------------
    cold = bool(_COLD_OPEN_RE.search(hook_l))
    checks.append({'name': 'no_cold_open', 'passed': not cold,
                   'note': 'Starts on the subject, not on a greeting or "in this video".'})
    score += 10 if not cold else -40

    # --- Not vague authority (heavy penalty) -------------------------------
    vague = bool(_VAGUE_RE.search(hook_l))
    checks.append({'name': 'no_empty_claim', 'passed': not vague,
                   'note': 'Makes a specific promise, not "scientists found something amazing".'})
    if vague:
        score -= 35

    # --- No manipulative hype (disqualifying) ------------------------------
    # This is not a deduction, it is a veto. Fear-bait phrasing on a
    # body-science channel is an advertiser-friendliness and medical-
    # misinformation risk, not merely a weak hook — and a "doctors don't want
    # you to know" opener otherwise scores well on every other axis (it
    # addresses the viewer, opens a loop, is a fine length), so a points
    # penalty alone let it climb back into passing range.
    clickbait = any(x in hook_l for x in
                    ("doctors don't", "doctors won't", "won't believe",
                     "shocking secret", "100% real", "they don't want",
                     "big pharma", "miracle cure"))
    checks.append({'name': 'no_fake_hype', 'passed': not clickbait,
                   'note': 'Avoids manipulative or unsupported hype.'})
    if clickbait:
        return {'score': 0, 'checks': checks}

    return {'score': max(0, min(score, 100)), 'checks': checks}


# Backward/alt-compatible alias: some callers import the shorter name
# `score_hook` instead of `score_hook_detailed`. main.py calls this with
# the *whole script_data dict* (not just the hook string) and expects a
# 'suggestions' list in the result (used for hook_result.get('suggestions')),
# so this wraps score_hook_detailed to accept either input shape and always
# include 'suggestions' alongside the original 'checks' detail.
def score_hook(hook_or_script_data) -> Dict:
    """Score a hook. Accepts either the hook string directly, or a
    script_data dict (uses its 'hook' field) - main.py passes the dict.
    Returns {'score', 'checks', 'suggestions'} - 'suggestions' is a plain
    list of fix-it strings for any check that didn't pass, derived from
    score_hook_detailed's 'checks'.
    """
    if isinstance(hook_or_script_data, dict):
        hook = hook_or_script_data.get('hook', '')
    else:
        hook = hook_or_script_data or ''

    result = score_hook_detailed(hook)
    result['suggestions'] = [
        check['note'] for check in result.get('checks', [])
        if not check.get('passed', True)
    ]
    return result


# ---------------------------------------------------------------------------
# Per-scene caption pacing
# ---------------------------------------------------------------------------

def check_caption_pacing(scenes: List[Dict], audio_segments: List[Dict]) -> Dict:
    """Flags any individual scene whose words-per-second falls outside the
    readable range, even if the video's overall pacing (checked in
    quality_checker) looks fine on average. audio_segments come from
    voice_generator.generate_voice_segments() and carry the real spoken
    duration per scene."""
    issues = []
    per_scene = []

    for i, (scene, seg) in enumerate(zip(scenes, audio_segments)):
        caption = scene.get('caption', '')
        duration = max(seg.get('duration', 0), 0.01)
        word_count = len(caption.split())
        wps = word_count / duration

        status = "ok"
        if wps < MIN_WORDS_PER_SEC:
            status = "too_slow"
            issues.append(f"Scene {i+1}: {wps:.1f} words/sec - dragging, consider trimming the caption or shortening the scene.")
        elif wps > MAX_WORDS_PER_SEC:
            status = "too_fast"
            issues.append(f"Scene {i+1}: {wps:.1f} words/sec - too fast to read, consider splitting into two scenes.")

        per_scene.append({'scene': i + 1, 'words_per_sec': round(wps, 2), 'status': status})

    return {
        'per_scene': per_scene,
        'issues': issues,
        'all_readable': len(issues) == 0,
    }


# ---------------------------------------------------------------------------
# Autofix: trim captions that read too fast for their scene's spoken duration
# ---------------------------------------------------------------------------

def autofix_too_fast_captions(scenes: List[Dict], audio_segments: List[Dict]) -> List[Dict]:
    """For any scene whose words-per-second (per check_caption_pacing) is
    above MAX_WORDS_PER_SEC, trim the on-screen caption down to the number
    of words that actually fit its spoken duration at a readable pace.

    This only shortens the *on-screen caption text* - it does not touch or
    re-generate the audio, so spoken narration timing is unaffected; this
    just keeps burned-in/SRT captions from flashing by unreadably fast.
    Scenes that are already OK (or "too_slow") are returned unchanged.
    Returns a new list; the input `scenes` list/dicts are not mutated.
    """
    fixed_scenes = []
    for i, scene in enumerate(scenes):
        seg = audio_segments[i] if i < len(audio_segments) else {}
        duration = max(seg.get('duration', 0), 0.01)
        caption = scene.get('caption', '')
        words = caption.split()
        wps = len(words) / duration if words else 0

        new_scene = dict(scene)
        if wps > MAX_WORDS_PER_SEC and len(words) > 1:
            # Keep as many words as fit at the max readable pace, but
            # never trim down to nothing.
            max_words = max(1, int(duration * MAX_WORDS_PER_SEC))
            if max_words < len(words):
                trimmed = " ".join(words[:max_words]).rstrip(",;:")
                if not trimmed.endswith((".", "!", "?")):
                    trimmed += "."
                logger.info(
                    f"Scene {i+1}: autofixed caption from {len(words)} to "
                    f"{max_words} words ({wps:.1f} -> "
                    f"{max_words/duration:.1f} words/sec)"
                )
                new_scene['caption'] = trimmed
        fixed_scenes.append(new_scene)
    return fixed_scenes


# ---------------------------------------------------------------------------
# Retention prediction (heuristic, not ML - gives directional signal +
# concrete suggestions, same spirit as quality_checker's scoring)
# ---------------------------------------------------------------------------

# The ideal window is no longer hardcoded here. algorithm_policy owns it for
# every platform, so a policy change updates the writer, the renderer and this
# prediction together instead of leaving one of them optimising for a target
# the others abandoned. (This module used to advertise 40-55s while the rest
# of the pipeline had moved on.)
from algorithm_policy import (  # noqa: E402
    YOUTUBE, duration_policy, retention_gate,
)

_IDEAL_MIN_SECONDS, _IDEAL_TARGET_SECONDS, _IDEAL_MAX_SECONDS = duration_policy(YOUTUBE)


def predict_retention(script_data: Dict, audio_segments: List[Dict]) -> Dict:
    """Heuristic (non-ML) retention estimate combining hook strength,
    caption pacing, and total video length. Returns predicted_avg_retention
    and predicted_swipe_away as 0-1 fractions, plus actionable suggestions.
    Intentionally conservative/simple - it's a directional signal for the
    pipeline logs, not a trained model.

    The estimate is also compared against the platform's real distribution
    gate, so the log says "this will/won't get pushed wider" instead of
    printing a number with no reference point.
    """
    suggestions = []

    hook = script_data.get('hook', '')
    hook_score = score_hook_detailed(hook).get('score', 0)  # 0-100

    scenes = script_data.get('scenes', [])
    pacing = check_caption_pacing(scenes, audio_segments)
    unreadable_ratio = (
        len(pacing.get('issues', [])) / len(scenes) if scenes else 0
    )

    total_seconds = sum(float(s.get('duration', 0)) for s in audio_segments)

    # Base retention scales with hook strength - a weak hook loses viewers
    # before anything else in the video matters.
    retention = 0.35 + 0.45 * (hook_score / 100.0)

    # Unreadable captions cost retention roughly proportional to how much
    # of the video is affected.
    retention -= 0.25 * unreadable_ratio
    if unreadable_ratio > 0:
        suggestions.append(
            "Some captions are hard to read at their spoken pace - "
            "shortening them (or letting autofix_too_fast_captions run) "
            "should help viewers stay through those scenes."
        )

    # Length effect. Completion is a PERCENTAGE of the video's own length, so
    # every extra second makes the same gate harder to clear — a 36s Short and
    # a 55s Short both need ~50% average view percentage, but the longer one
    # has to hold viewers 10 seconds longer to get there.
    if total_seconds < _IDEAL_MIN_SECONDS:
        retention -= 0.03
        suggestions.append(
            f"Video is {total_seconds:.0f}s, under the {_IDEAL_MIN_SECONDS:.0f}s floor - "
            "too little runtime to land the arc, and very short Shorts are held to a "
            "stricter 65% completion bar."
        )
    elif total_seconds > _IDEAL_MAX_SECONDS:
        # Scaled rather than flat: 3s over is a rounding issue, 20s over is a
        # different video.
        overshoot = (total_seconds - _IDEAL_MAX_SECONDS) / max(_IDEAL_MAX_SECONDS, 1.0)
        retention -= min(0.25, 0.10 + overshoot * 0.30)
        suggestions.append(
            f"Video is {total_seconds:.0f}s against a {_IDEAL_MAX_SECONDS:.0f}s ceiling. "
            f"Cut back toward {_IDEAL_TARGET_SECONDS:.0f}s: the completion gate is a "
            "percentage, so every extra second raises the number of seconds a viewer "
            "must watch to clear it."
        )

    if hook_score < 60:
        suggestions.append(
            "Hook score is below 60 - a sharper, more specific opening "
            "line usually recovers the most retention per fix."
        )

    retention = max(0.05, min(retention, 0.95))
    swipe_away = max(0.0, min(1.0 - retention, 0.95))

    gate = retention_gate(YOUTUBE, total_seconds) if total_seconds else None
    clears_gate = bool(gate and retention >= gate)
    if gate and not clears_gate:
        suggestions.append(
            f"Predicted {retention:.0%} completion is under the {gate:.0%} gate this "
            f"length is graded on — expect the test cohort not to expand."
        )

    return {
        'predicted_avg_retention': round(retention, 3),
        'predicted_swipe_away': round(swipe_away, 3),
        'distribution_gate': round(gate, 3) if gate else None,
        'clears_gate': clears_gate,
        'seconds': round(total_seconds, 2),
        'suggestions': suggestions,
    }


# ---------------------------------------------------------------------------
# Shorts hashtags
# ---------------------------------------------------------------------------

def generate_shorts_hashtags(topic_tags: List[str], n: int = 5) -> List[str]:
    """#shorts-family tags first (near-mandatory for Shorts shelf
    placement), then the top niche tags already computed by
    seo_generator/niche_strategy - avoids re-deriving tags from scratch."""
    result = list(SHORTS_HASHTAGS)
    for t in topic_tags:
        tag = f"#{t}" if not t.startswith('#') else t
        if tag.lower() not in (x.lower() for x in result):
            result.append(tag)
        if len(result) >= n:
            break
    return result[:n]


# ---------------------------------------------------------------------------
# SRT subtitle export
# ---------------------------------------------------------------------------

def _seconds_to_srt_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(scenes: List[Dict], audio_segments: List[Dict], output_path: str = None) -> str:
    """Builds standard SRT subtitle content from each scene's caption and
    its real audio duration (same timing source video_editor.py uses for
    burned-in captions, so the uploaded closed-caption file matches what's
    on screen). Writes to output_path if given, always returns the SRT
    text either way."""
    lines = []
    t = 0.0
    for i, (scene, seg) in enumerate(zip(scenes, audio_segments), start=1):
        duration = max(seg.get('duration', 0), 0.6)
        start, end = t, t + duration
        lines.append(str(i))
        lines.append(f"{_seconds_to_srt_timestamp(start)} --> {_seconds_to_srt_timestamp(end)}")
        lines.append(scene.get('caption', '').strip())
        lines.append("")
        t = end

    srt_content = "\n".join(lines)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        logger.info(f"SRT subtitles written to {output_path}")

    return srt_content


# ---------------------------------------------------------------------------
# Combined report
# ---------------------------------------------------------------------------

def build_shorts_report(script_data: Dict, audio_segments: List[Dict], topic_tags: List[str]) -> Dict:
    """Single entry point main.py can call alongside quality_checker /
    anti_spam. Doesn't gate publishing on its own (quality_checker already
    owns the approve/reject decision) - this is diagnostic + asset output."""
    hook_detail = score_hook_detailed(script_data.get('hook', ''))
    pacing = check_caption_pacing(script_data.get('scenes', []), audio_segments)
    hashtags = generate_shorts_hashtags(topic_tags)
    retention_prediction = predict_retention(script_data, audio_segments)

    return {
        'hook_detail': hook_detail,
        'caption_pacing': pacing,
        'shorts_hashtags': hashtags,
        'retention_prediction': retention_prediction,
    }


if __name__ == "__main__":
    import json
    test_scenes = [
        {"visual": "human heart beating", "caption": "Your heart has its own brain."},
        {"visual": "close up neurons", "caption": "It contains over 40000 neurons that operate independently of your actual brain."},
    ]
    test_segments = [{"duration": 2.0}, {"duration": 3.0}]
    report = build_shorts_report(
        {"hook": "Doctors don't want you to know this about your heart...", "scenes": test_scenes},
        test_segments,
        ["darkfacts", "heartfacts", "science"],
    )
    print(json.dumps(report, indent=2))
    print(generate_srt(test_scenes, test_segments))
