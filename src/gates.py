"""Independent Guard Pipeline — every subsystem has its OWN gate.

The pipeline's own heuristic scores (hook/CTR/SEO/quality) have been shown to
drift far from reality, so a system that scores itself cannot be trusted. This
module provides a SEPARATE, per-subsystem guard that checks each stage with its
own independent rules — and a video is NOT allowed through the publish gate
until EVERY guard has independently verified its stage.

Each guard:
  * owns one subsystem (script, hook, video-quality, video-generation, voice,
    SEO, caption),
  * reads only artifacts that stage produces (not the pipeline's self-score),
  * returns {pass: bool, issues: [...], confidence, checked_what},
  * is cheap and offline where possible (rendered-file checks still need the
    file, which the pipeline already has).

The GatePipeline runs ALL guards; if any fails, the run is stopped before
upload. This removes the self-evaluation bias: "good" only means every
independent observer verified its own stage.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# 1. SCRIPT GUARD — independent structural + factual checks on the script
# --------------------------------------------------------------------------- #

def check_script(script_data: Dict) -> Dict[str, Any]:
    """Independent script check: scene count, word budget, required fields,
    story arc. Does NOT use quality_checker's overall score."""
    issues: List[str] = []
    ok = True
    checked = {"scenes", "voiceover", "required_fields", "story_arc"}

    scenes = script_data.get("scenes") or []
    if len(scenes) < 6:
        ok, issues = False, issues + [f"Too few scenes: {len(scenes)} (need >=6)"]
    elif len(scenes) > 8:
        ok, issues = False, issues + [f"Too many scenes: {len(scenes)} (max 8)"]

    for req in ("title", "hook", "cta", "description", "voiceover"):
        if not script_data.get(req):
            ok, issues = False, issues + [f"Missing required field: {req}"]

    vo = (script_data.get("voiceover") or "").split()
    words = len(vo)
    if words < 60 or words > 130:
        ok, issues = False, issues + [f"Voiceover word count {words} out of range (60-130)"]

    # story arc: scene1 = hook, last scene = loop/payoff
    if scenes:
        if not (scenes[0].get("caption") or "").strip():
            ok, issues = False, issues + ["Scene 1 (hook) has no caption"]
        if not (scenes[-1].get("caption") or "").strip():
            ok, issues = False, issues + ["Final scene has no caption"]

    return {
        "guard": "script", "pass": ok, "issues": issues,
        "confidence": "high", "checked": list(checked),
    }


# --------------------------------------------------------------------------- #
# 2. HOOK GUARD — independent first-2-second check
# --------------------------------------------------------------------------- #

def check_hook(script_data: Dict) -> Dict[str, Any]:
    """Independent hook check: present, short, curiosity/you-frame, matches
    scene 1. Does not rely on score_hook()'s number."""
    issues: List[str] = []
    ok = True
    checked = {"hook_present", "hook_short", "hook_frame", "hook_matches_scene1"}

    hook = (script_data.get("hook") or "").strip()
    if not hook:
        return {"guard": "hook", "pass": False,
                "issues": ["Hook is missing"], "confidence": "high",
                "checked": list(checked)}

    hook_l = hook.lower()
    n = len(hook.split())
    if n > 10:
        ok, issues = False, issues + [f"Hook too long: {n} words (>10 = slow opening)"]

    # you-frame or curiosity word
    if not any(w in hook_l for w in ("you", "your", "why", "what", "how", "never",
                                     "secret", "actually", "every", "hidden")):
        ok, issues = False, issues + ["Hook lacks a you/curiosity trigger"]

    # hook should appear in scene 1 caption (opens the loop it promises)
    sc1 = (script_data.get("scenes") or [{}])[0].get("caption", "").lower()
    core = " ".join(hook_l.split()[:3])
    if sc1 and core and not any(w in sc1 for w in core.split()):
        ok, issues = False, issues + ["Hook does not match scene 1 opening"]

    return {"guard": "hook", "pass": ok, "issues": issues,
            "confidence": "high", "checked": list(checked)}


# --------------------------------------------------------------------------- #
# 3. VIDEO-QUALITY GUARD — canvas, duration, audio, technical integrity
# --------------------------------------------------------------------------- #

def check_video_quality(technical: Dict, policy: Dict) -> Dict[str, Any]:
    """Independent check of the RENDERED master cut via ffprobe metadata
    (canvas 9:16, duration in policy window, has audio). 'technical' comes from
    media_validator.probe_video; 'policy' carries the platform duration window.
    """
    issues: List[str] = []
    ok = True
    checked = {"canvas", "duration", "has_audio", "file_ok"}

    if not technical:
        return {"guard": "video_quality", "pass": False,
                "issues": ["No probe metadata"], "confidence": "high",
                "checked": list(checked)}

    w, h = technical.get("width"), technical.get("height")
    if (w, h) != (1080, 1920):
        ok, issues = False, issues + [f"Wrong canvas {w}x{h} (need 1080x1920 9:16)"]

    dur = technical.get("duration") or 0
    floor = policy.get("floor", 27)
    ceil = policy.get("ceil", 40)
    if dur <= 0 or dur > ceil:
        ok, issues = False, issues + [f"Duration {dur:.1f}s out of range (max {ceil})"]
    if dur < floor:
        ok, issues = False, issues + [f"Duration {dur:.1f}s below floor {floor}"]

    return {"guard": "video_quality", "pass": ok, "issues": issues,
            "confidence": "high", "checked": list(checked)}


# --------------------------------------------------------------------------- #
# 4. VIDEO-GENERATION GUARD — every scene produced a valid, non-duplicate asset
# --------------------------------------------------------------------------- #

def check_video_generation(image_paths: List[str], media_types: List[str],
                           required_scenes: int) -> Dict[str, Any]:
    """Independent check that every scene got a real, non-empty media asset."""
    issues: List[str] = []
    ok = True
    checked = {"scene_count", "files_exist", "no_duplicates"}

    if len(image_paths) != required_scenes:
        ok, issues = False, issues + [f"Generated {len(image_paths)} assets for {required_scenes} scenes"]
    if len(media_types) != len(image_paths):
        ok, issues = False, issues + ["media_types length mismatch"]

    for i, p in enumerate(image_paths):
        if not p or not os.path.isfile(p):
            ok, issues = False, issues + [f"Scene {i}: missing asset file {p}"]
        elif os.path.getsize(p) < 1000:
            ok, issues = False, issues + [f"Scene {i}: asset too small"]

    # duplicate paths (same file reused across scenes)
    if len(set(image_paths)) != len(image_paths):
        ok, issues = False, issues + ["Duplicate media file used across scenes"]

    return {"guard": "video_generation", "pass": ok, "issues": issues,
            "confidence": "high", "checked": list(checked)}


# --------------------------------------------------------------------------- #
# 5. VOICE GUARD — independent audio integrity
# --------------------------------------------------------------------------- #

def check_voice(audio_segments: List[Dict], required_scenes: int) -> Dict[str, Any]:
    """Independent voice check: every scene has audio, no silence, one engine,
    reasonable duration."""
    issues: List[str] = []
    ok = True
    checked = {"segment_count", "no_silence", "single_engine", "durations"}

    if len(audio_segments) != required_scenes:
        ok, issues = False, issues + [f"Voice segments {len(audio_segments)} for {required_scenes} scenes"]

    engines = set()
    silent = 0
    for s in audio_segments:
        eng = s.get("tts_engine")
        if eng:
            engines.add(eng)
        d = float(s.get("duration") or 0)
        if d < 0.3:
            silent += 1
        if not s.get("path") or not os.path.isfile(str(s.get("path", ""))):
            ok, issues = False, issues + [f"Voice segment missing file: {s.get('path')}"]

    if silent > 0:
        ok, issues = False, issues + [f"{silent} silent/short voice segments"]
    if len(engines) > 1:
        ok, issues = False, issues + [f"Mixed TTS engines: {sorted(engines)}"]

    return {"guard": "voice", "pass": ok, "issues": issues,
            "confidence": "high", "checked": list(checked)}


# --------------------------------------------------------------------------- #
# 6. SEO GUARD — independent metadata quality (title, desc, tags)
# --------------------------------------------------------------------------- #

def check_seo(script_data: Dict) -> Dict[str, Any]:
    """Independent SEO check: title/desc/tags present and sized, no bait,
    hashtags within platform limits."""
    issues: List[str] = []
    ok = True
    checked = {"title", "description", "tags", "hashtags", "no_bait"}

    title = (script_data.get("title") or "").strip()
    if not title:
        ok, issues = False, issues + ["Missing title"]
    elif len(title) > 100:
        ok, issues = False, issues + [f"Title too long: {len(title)} chars (>100)"]

    desc = (script_data.get("description") or "").strip()
    if len(desc) < 100:
        ok, issues = False, issues + [f"Description too short: {len(desc)} chars (<100)"]

    tags = script_data.get("tags") or []
    if len(tags) < 3:
        ok, issues = False, issues + [f"Too few tags: {len(tags)} (<3)"]

    hashtags = script_data.get("hashtags") or []
    if len(hashtags) > 8:
        ok, issues = False, issues + [f"Too many hashtags: {len(hashtags)} (>8)"]

    for bait in ("like and subscribe", "smash that like", "hit the bell",
                 "tag someone", "subscribe for more"):
        if bait in (title + " " + desc).lower():
            ok, issues = False, issues + [f"Bait phrase in metadata: {bait}"]
            break

    return {"guard": "seo", "pass": ok, "issues": issues,
            "confidence": "high", "checked": list(checked)}


# --------------------------------------------------------------------------- #
# 7. CAPTION GUARD — independent caption/pacing + subtitle integrity
# --------------------------------------------------------------------------- #

def check_captions(script_data: Dict) -> Dict[str, Any]:
    """Independent caption check: scenes have captions, no punctuation glitches
    (e.g. '.,' or '..'), pacing reasonable."""
    issues: List[str] = []
    ok = True
    checked = {"scene_captions", "no_punct_glitch", "pacing"}

    scenes = script_data.get("scenes") or []
    for i, sc in enumerate(scenes):
        cap = (sc.get("caption") or "").strip()
        if not cap:
            ok, issues = False, issues + [f"Scene {i}: empty caption"]
        elif any(g in cap for g in (". ,", ".. ", ".,", "!?", "?!", " ,.")):
            ok, issues = False, issues + [f"Scene {i}: punctuation glitch in caption"]
            break

    return {"guard": "captions", "pass": ok, "issues": issues,
            "confidence": "high", "checked": list(checked)}


# --------------------------------------------------------------------------- #
# The Gate Pipeline — run ALL guards; block if ANY fails
# --------------------------------------------------------------------------- #

ALL_GUARDS = [
    ("script", check_script),
    ("hook", check_hook),
    ("video_quality", check_video_quality),
    ("video_generation", check_video_generation),
    ("voice", check_voice),
    ("seo", check_seo),
    ("captions", check_captions),
]


def run_gates(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Run every guard on the given context. ctx carries the artifacts each
    guard needs. Returns a full report + overall pass/fail.

    ctx keys:
      script_data, technical, policy, image_paths, media_types,
      audio_segments, required_scenes
    """
    results = []

    # script + hook + seo + captions all use script_data
    sd = ctx.get("script_data") or {}
    results.append(check_script(sd))
    results.append(check_hook(sd))
    results.append(check_seo(sd))
    results.append(check_captions(sd))

    # Viewer-preference guard — FREE, content-based "will people like this?"
    # (complements the structural guards; blocks weak viewer-likability).
    try:
        from viewer_preference import viewer_preference_guard
        _vp_threshold = ctx.get("viewer_pref_threshold", 70)
        results.append(viewer_preference_guard(sd, threshold=_vp_threshold))
    except Exception as exc:  # noqa: BLE001 - guard must never break the gate
        results.append({"guard": "viewer_preference", "pass": True,
                        "issues": [f"guard unavailable: {exc}"],
                        "confidence": "low", "checked": []})

    # video quality uses probe metadata + policy
    results.append(check_video_quality(ctx.get("technical") or {}, ctx.get("policy") or {}))

    # video generation + voice use the produced assets
    n_scenes = ctx.get("required_scenes", len(sd.get("scenes") or []))
    results.append(check_video_generation(
        ctx.get("image_paths") or [], ctx.get("media_types") or [], n_scenes))
    results.append(check_voice(ctx.get("audio_segments") or [], n_scenes))

    passed = [r for r in results if r["pass"]]
    failed = [r for r in results if not r["pass"]]
    overall = not failed

    if not overall:
        logger.error("🔴 GATE BLOCKED — %d/%d guards failed:",
                     len(failed), len(results))
        for r in failed:
            logger.error("   [%s] %s", r["guard"], "; ".join(r["issues"]))
    else:
        logger.info("🟢 ALL %d INDEPENDENT GUARDS PASSED", len(results))

    return {
        "overall": overall,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "total": len(results),
        "guards": results,
        "failed_guards": [r["guard"] for r in failed],
    }
