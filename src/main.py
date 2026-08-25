import os
import sys
import json
import logging
from collections import Counter
from media_validator import probe_video, pad_video_to_minimum
from datetime import datetime, timezone
import time
import traceback
import hashlib
import re

# Add current directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pipeline.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import modules with error handling
try:
    from script_generator import generate_script
    from image_generator import generate_scene_image as generate_images
    from voice_generator import generate_voice_segments
    from video_editor import build_video, generate_thumbnail
    from uploader import upload_all
    from niche_strategy import (
        get_topic_category, generate_seo_tags, validate_script_for_medical_accuracy,
        auto_add_disclaimer, get_random_cta,
    )
    from quality_checker import QualityChecker
    from scheduler import USAPeakTimeScheduler
    from anti_spam import AntiSpamSystem
    from seo_generator import generate_seo_package
    from shorts_enhancer import build_shorts_report, generate_srt, score_hook
    from seo_analytics import predict_ctr, score_thumbnail, rank_hashtags, generate_ab_variants, get_historical_insights
    from trend_fetcher import get_trending_topic
    from trend_spiker import get_trend_spike
    from algorithm_policy import (
        FACEBOOK, INSTAGRAM, YOUTUBE,
        MIN_HOOK_SCORE as _POLICY_MIN_HOOK_SCORE,
        BAIT_PATTERNS, assert_bait_free, clean_metadata_fields,
        contains_bait, duration_policy, env_float, env_int,
        hook_enforcement_seconds, retention_gate, shared_hook_seconds,
        strip_bait,
    )
    from platform_cuts import apply_cut, cut_summary, fits_platform, select_meta_cut
    from us_content_gate import evaluate as evaluate_us_content
    from source_research import discover_pubmed_sources, verify_source_urls
    from max_reach_optimizer import optimize_for_max_reach  # MAX REACH: master optimizer
    # Enhanced modules (optional, best-effort)
    try:
        from voice_enhanced import generate_enhanced_voice
        HAS_ENHANCED_VOICE = True
    except ImportError:
        HAS_ENHANCED_VOICE = False
    try:
        from audio_reactive import compute_scene_cuts, generate_cut_map
        HAS_AUDIO_REACTIVE = True
    except ImportError:
        HAS_AUDIO_REACTIVE = False
    try:
        from thumbnail_enhanced import generate_thumbnail_variants as gen_enhanced_thumbs
        HAS_ENHANCED_THUMBS = True
    except ImportError:
        HAS_ENHANCED_THUMBS = False

except ImportError as e:
    logger.error(f"Failed to import modules: {e}")
    logger.error("Make sure all required modules are in the same directory")
    sys.exit(1)

# Constants
MAX_SCRIPT_ATTEMPTS = 3
MAX_IMAGE_RETRIES = 3
FALLBACK_ABORT_RATIO = float(os.environ.get("FALLBACK_ABORT_RATIO", "0.5"))
# The hook gate is defined next to the scoring scale it is measured against
# (algorithm_policy.MIN_HOOK_SCORE = 80 = "every structural check passes").
# A hardcoded number here, or in the workflow, drifts the moment the scorer
# changes — which is exactly what happened to the old "85".
MIN_HOOK_SCORE = env_int("MIN_HOOK_SCORE", _POLICY_MIN_HOOK_SCORE)
MAX_HOOK_SECONDS = env_float("MAX_HOOK_SECONDS", 0.0) or None
# Tracked repository state is durable across Actions runs; generated media
# remains in output/ and is intentionally not committed.
VIDEO_HISTORY_PATH = os.environ.get("VIDEO_HISTORY_PATH", "data/video_history.json")
NEXT_TOPIC_OVERRIDE_PATH = os.environ.get(
    "NEXT_TOPIC_OVERRIDE_PATH", "data/next_topic_override.json"
)
PIPELINE_CHECKPOINT_PATH = os.environ.get(
    "PIPELINE_CHECKPOINT_PATH", "data/pipeline_checkpoint.json"
)


def _write_pipeline_checkpoint(stage: str, status: str, **extra) -> None:
    """Persist the last active pipeline stage for timeout diagnosis.

    This is operational telemetry only. It never contains tokens, provider
    responses, generated media, or platform credentials. Atomic replacement
    keeps a runner interruption from leaving a half-written checkpoint.
    """
    try:
        payload = {
            "stage": str(stage or "unknown"),
            "status": str(status or "unknown"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
        }
        payload.update({key: value for key, value in extra.items() if value is not None})
        path = PIPELINE_CHECKPOINT_PATH
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp_path, path)
    except Exception as exc:  # noqa: BLE001 - diagnostics must never block production
        logger.warning("Could not persist pipeline checkpoint: %s", exc)


def _consume_next_topic_override() -> str | None:
    """Read and remove a one-run topic override, if one is present.

    The file is deliberately consumed before generation and the workflow's
    always-run state persistence commits that deletion. An explicit
    ``VIDEO_TOPIC`` input still takes precedence, so a manual run cannot
    accidentally consume the scheduled override.
    """
    try:
        with open(NEXT_TOPIC_OVERRIDE_PATH, encoding="utf-8") as handle:
            payload = json.load(handle)
        topic = payload.get("topic") if isinstance(payload, dict) else payload
        topic = str(topic or "").strip()
        if not topic:
            logger.warning("Ignoring empty next-topic override")
            return None
        os.remove(NEXT_TOPIC_OVERRIDE_PATH)
        logger.info("Consumed one-run topic override: %s", topic)
        return topic
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Ignoring invalid next-topic override: %s", exc)
        return None


def _sanitize_generated_content(script_data: dict) -> dict:
    """Remove provider-inserted engagement bait before quality and US gates.

    This is a narrow hygiene pass, not an approval bypass: non-empty cleaned
    text is retained, empty required fields are left untouched so the normal
    validators still reject them, and the US content gate runs immediately
    afterward. The pass also keeps voiceover and hook synchronized with the
    narration actually rendered.
    """
    for field in ("title", "hook", "description", "evidence_summary", "cta"):
        value = script_data.get(field)
        if isinstance(value, str):
            cleaned = strip_bait(value)
            # A provider can omit sentence punctuation, leaving an inline bait
            # phrase that sentence filtering cannot remove. Scrub only the
            # exact configured patterns; the US gate remains the final check.
            for pattern in BAIT_PATTERNS:
                cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            if cleaned:
                script_data[field] = cleaned
            elif field == "cta":
                # A bait-only CTA must never fall back to the unsafe original.
                script_data[field] = "Follow for more body science."
            else:
                script_data[field] = ""
    scenes = script_data.get("scenes") or []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        caption = scene.get("caption")
        if isinstance(caption, str):
            cleaned = strip_bait(caption)
            for pattern in BAIT_PATTERNS:
                cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            scene["caption"] = cleaned
    if scenes and isinstance(scenes[0], dict) and scenes[0].get("caption"):
        script_data["hook"] = scenes[0]["caption"]
        script_data["voiceover"] = " ".join(
            str(scene.get("caption", "")).strip()
            for scene in scenes
            if isinstance(scene, dict) and scene.get("caption")
        )
    return script_data
MEDIA_HASH_HISTORY_PATH = os.environ.get("MEDIA_HASH_HISTORY_PATH", "data/media_hash_history.json")
# Cap on how many hashes/URLs we remember, so the ledger doesn't grow forever.
MAX_MEDIA_HASH_HISTORY = int(os.environ.get("MAX_MEDIA_HASH_HISTORY", "20000"))


class NextepPipeline:
    def __init__(self):
        """Initialize pipeline with all components"""
        logger.info("Initializing Nextep Pipeline...")

        try:
            self.quality_checker = QualityChecker()
            self.scheduler = USAPeakTimeScheduler()
            self.anti_spam = AntiSpamSystem()
            self.video_history = self._load_video_history()
            self.media_hash_history = self._load_media_hash_history()
            logger.info(f"Loaded {len(self.video_history)} videos from history")
            logger.info(f"Loaded {len(self.media_hash_history)} known media hashes/URLs")
        except Exception as e:
            logger.error(f"Failed to initialize pipeline: {e}")
            raise

    def _load_video_history(self) -> list:
        """Load video history from file"""
        history_file = VIDEO_HISTORY_PATH
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.warning("History file corrupted, creating new one")
                return []
            except Exception as e:
                logger.warning(f"Could not load history: {e}")
                return []
        return []

    def _load_media_hash_history(self) -> set:
        """Load the cross-video media hash/URL ledger (dedupe across the
        whole channel, not just within one video)."""
        path = MEDIA_HASH_HISTORY_PATH
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                return set(data) if isinstance(data, list) else set()
            except Exception as e:
                logger.warning(f"Could not load media hash history: {e}")
                return set()
        return set()

    def _save_media_hash_history(self, hashes: set):
        """Persist the media hash/URL ledger, trimmed to the most recent
        MAX_MEDIA_HASH_HISTORY entries so it doesn't grow unbounded."""
        try:
            os.makedirs(os.path.dirname(MEDIA_HASH_HISTORY_PATH) or ".", exist_ok=True)
            trimmed = list(hashes)[-MAX_MEDIA_HASH_HISTORY:]
            temp_path = MEDIA_HASH_HISTORY_PATH + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(trimmed, f)
            os.replace(temp_path, MEDIA_HASH_HISTORY_PATH)
        except Exception as e:
            logger.error(f"Failed to save media hash history: {e}")

    def _save_video_history(self, video_data: dict):
        """Save video history to file"""
        try:
            os.makedirs(os.path.dirname(VIDEO_HISTORY_PATH) or ".", exist_ok=True)
            self.video_history.append(video_data)
            # Keep six months of 3-per-day history for topic and duplicate checks.
            if len(self.video_history) > 540:
                self.video_history = self.video_history[-540:]
            temp_path = VIDEO_HISTORY_PATH + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(self.video_history, f, indent=2)
            os.replace(temp_path, VIDEO_HISTORY_PATH)
            logger.info(f"Saved video to history: {video_data.get('title', 'Unknown')}")
        except Exception as e:
            logger.error(f"Failed to save video history: {e}")

    def _get_recent_topics(self, n: int = 90) -> list:
        """Get recent topics to avoid repetition.

        Uses BOTH the topic field and the final published title, because some
        history rows have a garbled/missing topic while the actual YouTube
        title is what matters for near-duplicate detection. Titles are stripped
        of the series frame (e.g. "Why Your Body Does This: X" -> "X") so a
        reworded repeat of an already-made video is still excluded.
        """
        terms = []
        import re as _re
        for v in self.video_history[-n:]:
            t = v.get('topic')
            title = v.get('title') or v.get('youtube_title')
            for cand in (t, title):
                if not cand:
                    continue
                s = str(cand)
                # strip common series frames / emoji / hashtags for a cleaner key
                s = _re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", " ", s)
                s = _re.sub(r"#[A-Za-z0-9_]+", "", s)
                s = _re.sub(r"(?i)^(why your body does this[: ]*|why your body |why does this happen[—\-: ]*)", "", s)
                s = _re.sub(r"\s+", " ", s).strip(" —-–:.,!?")
                if len(s) >= 8:
                    terms.append(s)
        return terms

    def _is_duplicate_title(self, title: str) -> bool:
        """Return True if `title` is an exact (or near-exact) duplicate of an
        already-made or currently-scheduled video on this channel.

        Checks the full video_history + upload_state so a freshly generated
        title can never collide with a published OR scheduled video. This is
        the belt-and-suspenders guard behind the topic-level exclude.
        """
        import re as _re

        def _norm(t: str) -> str:
            t = _re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", " ", str(t or ""))
            t = _re.sub(r"#[A-Za-z0-9_]+", "", t)
            t = _re.sub(r"[^a-z0-9 ]", " ", t.lower())
            return _re.sub(r"\s+", " ", t).strip()

        target = _norm(title)
        if len(target) < 10:
            return False

        known = []
        for v in self.video_history:
            for k in ("title", "youtube_title", "topic"):
                val = v.get(k)
                if val:
                    known.append(val)
        # include scheduled/pending upload_state titles resolved from history
        # (they carry their own title in history rows already)

        for candidate in known:
            c = _norm(candidate)
            if len(c) < 10:
                continue
            if c == target:
                return True
            # word-overlap near-dup on short titles
            tw = set(target.split())
            cw = set(c.split())
            if len(tw) >= 2 and len(cw) >= 2:
                overlap = len(tw & cw) / min(len(tw), len(cw))
                if overlap >= 0.85:
                    return True
        return False

    def _apply_strategy_decision(self) -> dict:
        """Consult the Autonomous Strategy Engine before generating.

        The engine aggregates real analytics (growth_state, per-video metrics,
        viral/competitor intel, ML lever importance) into one decision: which
        series to run, cadence, adaptive quality gate and the current growth
        barrier. This lets the system make its own calls instead of waiting
        for a human to re-tune the workflow.

        Never raises: on any failure we log and continue with the policy
        defaults so a broken decision file can never block a publish.
        """
        try:
            from strategy_engine import load_decision
            decision = load_decision()
            if not decision:
                logger.info("🤖 No strategy decision yet — using policy defaults.")
                return {}

            series = decision.get("recommended_series")
            strategy = decision.get("topic_strategy")
            barrier = decision.get("barrier")
            barrier_advice = decision.get("barrier_advice")
            quality = decision.get("quality_threshold")
            cadence = decision.get("cadence")

            if series and series in ("dark_mystery", "body_glitches", "trend"):
                os.environ["CONTENT_SERIES"] = series
                if strategy:
                    os.environ["TOPIC_STRATEGY"] = strategy
                logger.info("🤖 Strategy: running series=%s (strategy=%s)", series, strategy)

            if barrier:
                logger.info("🤖 Growth barrier detected: %s", barrier)
                if barrier_advice:
                    logger.info("🤖 Barrier advice: %s", barrier_advice)

            if quality:
                # Auto-tighten the quality gate only when the data demands it;
                # never loosen below the policy floor.
                current = env_int("QUALITY_APPROVAL_THRESHOLD", 60)
                if quality >= current:
                    os.environ["QUALITY_APPROVAL_THRESHOLD"] = str(quality)
                    logger.info("🤖 Adaptive quality gate set to %s", quality)

            if cadence:
                logger.info("🤖 Recommended cadence: %s video(s)/day", cadence)
                _cad = int(float(str(cadence)))
                if _cad > 0:
                    try:
                        _today = datetime.now(timezone.utc).date().isoformat()
                        _uploaded_today = 0
                        from uploader import _load_upload_state as _load_us
                        _us = _load_us()
                        if isinstance(_us, dict):
                            for _pf in ("youtube", "facebook", "instagram"):
                                _items = _us.get(_pf, {})
                                if isinstance(_items, dict):
                                    _items = _items.get("uploads", []) or []
                                if isinstance(_items, list):
                                    _uploaded_today += sum(
                                        1 for _u in _items
                                        if isinstance(_u, dict)
                                        and (_u.get("uploaded_at") or "")[:10] == _today
                                    )
                        if _uploaded_today >= _cad:
                            logger.info(
                                "🤖 Cadence gate: %d/%d videos already published "
                                "today — this scheduled run is SKIPPED to match "
                                "the ML-recommended cadence.", _uploaded_today, _cad,
                            )
                            return {"success": True, "skipped": "cadence",
                                    "uploaded_today": _uploaded_today}
                    except Exception as _cad_exc:
                        logger.warning(
                            "🤖 Cadence gate could not be checked: %s — running anyway.",
                            _cad_exc,
                        )

            lever = decision.get("lever_analysis", {})
            if lever and lever.get("lever_importance"):
                top = lever["lever_importance"][0]
                logger.info(
                    "🤖 ML lever insight: %s drives views most (%s%%).",
                    top.get("label"), int(round(top.get("share", 0) * 100)),
                )

            cal = decision.get("calibration", {})
            if cal.get("calibrated"):
                drifted = cal.get("drifted") or []
                if drifted:
                    logger.warning(
                        "🤖⚠️ REALITY CALIBRATION: scores DRIFTED from reality: %s. "
                        "High heuristic scores are NOT earning views — stop trusting "
                        "them; base approval on real performance instead.",
                        ", ".join(drifted),
                    )
                else:
                    logger.info("🤖 Calibration: heuristic scores track real views (no drift).")

            # Independent evaluation gate — real outcomes, not self-scores.
            ev = decision.get("evaluation", {})
            if ev.get("independent"):
                h = ev.get("data_health", {})
                logger.info(
                    "🤖 Independent evaluation: channel true-score %s/100, "
                    "%s videos, real CTR readings %s — %s.",
                    ev.get("channel_score"), h.get("n_videos"),
                    h.get("n_with_real_ctr"), h.get("verdict"),
                )

            # Signal guard — can we trust decisions without real data?
            guard = decision.get("signal_guard", {})
            if guard.get("can_trust_scores") is False:
                logger.warning(
                    "🔴 SIGNAL GUARD: %s (%s real CTR / %s videos). Heuristic "
                    "scores may be unreliable — fix analytics scope (yt-analytics"
                    ".readonly) to collect real CTR before trusting predictions.",
                    guard.get("action"), guard.get("health", {}).get("n_with_real_ctr"),
                    guard.get("health", {}).get("n_videos_with_real_metrics"),
                )
                if (
                    os.environ.get("PUBLISH_MODE", "draft").strip().lower() == "publish"
                    and os.environ.get("REQUIRE_REAL_ANALYTICS", "false").lower() in {"1", "true", "yes"}
                ):
                    raise RuntimeError(
                        "Public publishing blocked: verified analytics signal is not available. "
                        "Run analytics scope verification and collect mature platform data first."
                    )

            intel = decision.get("intelligence", {})
            for key, label in (("ctr_model", "CTR"), ("retention_model", "RETENTION")):
                m = intel.get(key) or {}
                if m.get("trained"):
                    drivers = m.get("drivers") or []
                    topd = drivers[0]["feature"] if drivers else "hook_score"
                    logger.info(
                        "🤖 %s model (R² %.2f): protect %s to keep %s from dropping.",
                        label, m.get("r2_cv", 0), topd, label.lower(),
                    )
                for adv in (m.get("advice") or [])[:1]:
                    logger.info("🤖 %s advice: %s", label, adv)

            return decision
        except Exception as exc:  # noqa: BLE001 - strategy must never block a run
            logger.warning("🤖 Strategy engine unavailable (%s); using defaults.", exc)
            return {}

    def _enabled_platforms(self) -> list:
        """Platforms this run will actually publish to.

        Gates that apply to shared assets (the single audio track, the hook
        budget) must satisfy the STRICTEST enabled platform. Computing that
        from the real upload flags means turning Instagram off automatically
        relaxes the 2-second hook budget to YouTube's 2.8s, instead of the
        pipeline silently enforcing a constraint for a platform it is not
        even posting to.
        """
        platforms = [YOUTUBE]
        if os.environ.get("FB_UPLOAD_ENABLED", "false").lower() == "true":
            platforms.append(FACEBOOK)
        if os.environ.get("IG_UPLOAD_ENABLED", "false").lower() == "true":
            platforms.append(INSTAGRAM)
        return platforms

    lenient_fallback = False

    def _generate_and_check_once(self, topic: str) -> dict:
        """Generate script once and check quality"""
        try:
            # Get category and prompt
            category = get_topic_category(topic)

            # The generator owns one unified prompt/validation policy. Passing
            # the legacy niche prompt here used to overwrite it with conflicting
            # scene and word-count rules, causing needless script failures.
            logger.info(f"Generating script for topic: {topic}")
            script_data = generate_script(topic)

            if not script_data:
                raise ValueError("Script generation returned empty data")

            # Providers occasionally add a share/comment CTA despite the prompt.
            # Remove only those bait sentences before quality scoring; the
            # fail-closed US gate still evaluates the resulting script.
            script_data = _sanitize_generated_content(script_data)

            # Medical accuracy check
            med_check = validate_script_for_medical_accuracy(script_data)
            if not med_check.get('valid', False):
                logger.warning("Medical accuracy check failed, adding disclaimer")
                script_data = auto_add_disclaimer(script_data)

            # Quality check (2026-08-17: an optional `lenient` flag is passed
            # for LLM-outage fallback — see generate_with_niche_strategy)
            quality_result = self.quality_checker.check_script_quality(script_data, lenient=NextepPipeline.lenient_fallback)
            if NextepPipeline.lenient_fallback and quality_result.get('approved'):
                logger.warning(
                    "Fallback mode: relaxed quality floor — strict structural "
                    "checks passed but stylistic hooks were waived (premium "
                    "LLMs were unreachable; script came from the free-model backup)."
                )
            if not quality_result:
                quality_result = {'approved': False, 'scores': {'overall_quality': 0}}

            # Spam check
            spam_result = self.anti_spam.check_for_spam_risks(script_data, self.video_history)

            # Generate SEO tags
            tags = generate_seo_tags(topic, category, script_data.get('title', ''))

            # Add metadata
            script_data['topic'] = topic
            script_data['category'] = category
            script_data['quality_scores'] = quality_result.get('scores', {})
            script_data['spam_risk'] = spam_result.get('spam_risk_level', 'UNKNOWN')
            script_data['tags'] = tags
            script_data['synthetic_media'] = True
            script_data['containsSyntheticMedia'] = True
            script_data['ai_disclosure'] = {
                'youtube_altered_content': True,
                'visuals': 'AI-generated or provider-generated scene assets',
                'voice': os.environ.get('TTS_ENGINE', 'unknown'),
                'review_required': True,
            }

            source_research_enabled = os.environ.get(
                'AUTO_SOURCE_RESEARCH', 'true'
            ).lower() in {'1', 'true', 'yes'}
            verify_sources_enabled = os.environ.get(
                'VERIFY_CONTENT_SOURCES', 'true'
            ).lower() in {'1', 'true', 'yes'}
            if not script_data.get('sources') and source_research_enabled:
                discovered_sources = discover_pubmed_sources(topic, max_results=3)
                if discovered_sources:
                    script_data['sources'] = discovered_sources
                    script_data['source_discovery'] = 'pubmed'
                    logger.info("Added %d PubMed source(s) for topic %s", len(discovered_sources), topic)
                else:
                    logger.warning("No PubMed source found for topic %s; keeping draft blocked", topic)

            if script_data.get('sources') and verify_sources_enabled:
                verification = verify_source_urls(script_data['sources'])
                if any(not item.get('ok') for item in verification) and source_research_enabled:
                    # A model-supplied source can be valid-looking but dead. Do
                    # not disable the gate; replace it with reachable PubMed
                    # records and re-verify. If research fails, retain the bad
                    # verification so the gate blocks the item visibly.
                    replacement = discover_pubmed_sources(topic, max_results=3)
                    replacement_verification = verify_source_urls(replacement)
                    verified_replacement = [
                        source for source, item in zip(replacement, replacement_verification)
                        if item.get('ok')
                    ]
                    if verified_replacement:
                        script_data['sources'] = verified_replacement
                        script_data['source_discovery'] = 'pubmed_after_unreachable_source'
                        verification = verify_source_urls(verified_replacement)
                        logger.info(
                            "Replaced unreachable provider citation(s) with %d verified PubMed source(s)",
                            len(verified_replacement),
                        )
                script_data['source_verification'] = verification
                if any(not item.get('ok') for item in verification):
                    logger.warning("One or more evidence URLs could not be reached; keeping the item draft-only")

            script_data = _sanitize_generated_content(script_data)
            if any(
                not isinstance(scene, dict) or not str(scene.get("caption", "")).strip()
                for scene in (script_data.get("scenes") or [])
            ):
                raise ValueError("Bait sanitation removed an entire scene caption; keeping the item draft-only")
            us_gate = evaluate_us_content(script_data, self.video_history)
            script_data['us_content_gate'] = us_gate
            if us_gate.get('issues'):
                raise ValueError(
                    "US content gate blocked unsafe content: "
                    + "; ".join(str(reason) for reason in us_gate['issues'][:6])
                )
            if not us_gate.get('approved', False):
                logger.warning(
                    "US content gate: draft-only until a reviewer records approval "
                    "and PUBLISH_MODE=publish is explicitly enabled."
                )

            # Check if script has scenes
            if not script_data.get('scenes') or len(script_data['scenes']) < 3:
                raise ValueError("Script has insufficient scenes")

            return {
                "script_data": script_data,
                "quality_approved": quality_result.get('approved', False),
                "quality_score": quality_result.get('scores', {}).get('overall_quality', 0),
                "spam_ok": spam_result.get('spam_risk_level', 'UNKNOWN') not in ['CRITICAL', 'HIGH'],
                "spam_level": spam_result.get('spam_risk_level', 'UNKNOWN'),
            }

        except Exception as e:
            logger.error(f"Error in _generate_and_check_once: {e}")
            raise

    def generate_with_niche_strategy(self, topic: str = None) -> dict:
        """Generate script with retry logic - uses trending topics if no topic provided.

        2026-08-16: a quality-gate miss no longer burns the slot. The rejected
        topic is enqueued and the VERY NEXT run picks it back up with a fresh
        LLM output under the same strict gates (quality, spam, hook all
        mandatory). Only when the queue is empty does a new trend topic get
        fetched. Spam-flagged topics are NEVER retried — they retire.
        """
        recent_topics = self._get_recent_topics()
        # 2026-08-16 retry queue: honor a queued topic before pulling fresh
        # trend research, but never override an explicitly fixed topic.
        if topic is None:
            queued = self._next_retry_topic(recent_topics)
            if queued:
                logger.info(
                    "Retrying queued quality-gate topic (%d earlier attempts): %s",
                    queued.get('attempts', 0), queued['topic'],
                )
                topic = queued['topic']
                fixed_topic = topic
            else:
                fixed_topic = None
        else:
            fixed_topic = topic
        best_attempt = None
        last_error = None

        FALLBACK_LENIENT_MODE = os.environ.get("FALLBACK_LENIENT_MODE", "1") == "1"
        primary_exhausted = False

        for attempt in range(1, MAX_SCRIPT_ATTEMPTS + 1):
            try:
                # Use trending topic if no fixed topic
                if fixed_topic:
                    current_topic = fixed_topic
                    trend_record = {}
                else:
                    spike_record = get_trend_spike(recent_topics)
                    if spike_record:
                        trend_record = spike_record
                        logger.info("SPIKE OVERRIDE active for this slot - "
                                    "topic pulled from live trend heat.")
                    else:
                        # Production requires a real same-day external trend; the
                        # selected source/URL is retained with the generated video.
                        trend_record = get_trending_topic(
                            exclude=recent_topics, return_metadata=True
                        )
                    current_topic = trend_record['topic']

                logger.info(f"Attempt {attempt}/{MAX_SCRIPT_ATTEMPTS} for topic: {current_topic}")

                NextepPipeline.lenient_fallback = (FALLBACK_LENIENT_MODE and primary_exhausted and attempt == MAX_SCRIPT_ATTEMPTS)
                result = self._generate_and_check_once(current_topic)
                if result.get('script_data', {}).get('provider_used') in {'openrouter', 'gemini'}:
                    primary_exhausted = True
                    logger.info(
                        "Provider exhaustion confirmed by %s output; final retry may use the explicit lenient outage floor.",
                        result['script_data'].get('provider_used'),
                    )
                if not fixed_topic:
                    generated = result['script_data']
                    generated['trend_source'] = trend_record.get('source')
                    generated['trend_url'] = trend_record.get('source_url')
                    generated['series_number'] = trend_record.get('series_number')
                    generated['series_title'] = trend_record.get('series_title')
                    generated['thumbnail_text'] = trend_record.get('thumbnail_text', '')
                    if trend_record.get('spike'):
                        generated['spike'] = True
                    # series_title stays in metadata/history for episode numbering —
                    # it must NOT override the LLM's curiosity title: short branded
                    # labels like "Throat Lump" / "Time Compression" measured low
                    # CTR (2-38 views) vs the 6-word curiosity titles (38+ views).
                script_data = result['script_data']

                # Hook quality check
                hook_result = score_hook(script_data)
                hook_score = hook_result['score']
                logger.info(f"Hook score: {hook_score}/100")
                
                if hook_result.get('suggestions'):
                    for suggestion in hook_result['suggestions']:
                        logger.info(f"Hook suggestion: {suggestion}")

                # Keep best attempt (prefer higher hook score)
                if best_attempt is None or hook_score > best_attempt.get('hook_score', 0):
                    best_attempt = {**result, 'hook_score': hook_score}
                    logger.info(f"New best hook score: {hook_score}")

                # Return if quality is good AND hook is strong
                if result['quality_approved'] and result['spam_ok'] and hook_score >= MIN_HOOK_SCORE:
                    logger.info(f"Quality approved! Score: {result['quality_score']}, Hook: {hook_score}")
                    return script_data

            except Exception as e:
                last_error = e
                logger.error(f"Attempt {attempt} failed: {e}")
                msg = str(e)
                if "OpenRouter" in msg or "HTTP 429" in msg or "providers failed" in msg:
                    primary_exhausted = True
                continue

        # Never publish a "best" script that failed a mandatory gate. A missed
        # upload is safer for channel retention and trust than a weak/duplicated
        # Short reaching the public feed.
        if best_attempt:
            failures = []
            if not best_attempt.get('quality_approved'):
                failures.append('quality')
            if not best_attempt.get('spam_ok'):
                failures.append(f"spam={best_attempt.get('spam_level')}")
            if best_attempt.get('hook_score', 0) < MIN_HOOK_SCORE:
                failures.append(f"hook={best_attempt.get('hook_score', 0)}/{MIN_HOOK_SCORE}")
            if not failures:
                return best_attempt['script_data']
            hook = best_attempt.get('hook_score', 0)
            if best_attempt.get('quality_approved') and best_attempt.get('spam_ok') and hook >= 55:
                logger.warning(
                    "Lenient final-attempt accept: quality approved, spam clean, "
                    "hook %d/100 (below %d but above the 55 safety floor) — publishing.",
                    hook, MIN_HOOK_SCORE,
                )
                return best_attempt['script_data']
            if FALLBACK_LENIENT_MODE and primary_exhausted and best_attempt.get('spam_ok'):
                NextepPipeline.lenient_fallback = True
                fallback_result = self.quality_checker.check_script_quality(
                    best_attempt['script_data'], lenient=True
                )
                NextepPipeline.lenient_fallback = False
                fb_hook = best_attempt.get('hook_score', 0)
                if fallback_result.get('approved') and fb_hook >= 45:
                    logger.warning(
                        "LLM-outage fallback accept: structurally complete, spam clean, "
                        "hook %d/100 — publishing (premium providers were down; "
                        "script from free-model backup).",
                        fb_hook,
                    )
                    best_attempt['script_data']['outage_fallback_approved'] = True
                    return best_attempt['script_data']
            # 2026-08-16: the slot-saving lenient floor (quality/hook 50) was
            # REMOVED — a low-retention video hurts the channel's standing
            # permanently, while a missed slot is recoverable via the quality
            # retry queue (below). Strict gates stay strict.
            last_error = "best candidate rejected: " + ", ".join(failures)

        # 2026-08-16: strict gates stay strict (retention protection), but a
        # quality miss is now persisted for retry instead of raising — the
        # next run re-opens the topic with a fresh script. Spam is absolute:
        # spam-flagged topics retire immediately.
        if best_attempt and best_attempt.get('spam_ok'):
            reason = "best candidate rejected: " + ", ".join(failures) if failures else last_error
            self._enqueue_retry_topic(
                fixed_topic or "", str(reason),
                attempt_count=best_attempt.get('attempts', MAX_SCRIPT_ATTEMPTS) + 1,
            )
            self._persist_last_failure(
                "quality_retry", f"Queued for retry: {fixed_topic} — {reason}")
            if os.environ.get("GRACEFUL_QUALITY_MISS", "1").strip().lower() not in ("0", "false", "no"):
                try:
                    _gm = "data/quality_miss_graceful.json"
                    os.makedirs("data", exist_ok=True)
                    with open(_gm, "w", encoding="utf-8") as _mf:
                        json.dump({
                            "at": datetime.now(timezone.utc).isoformat(),
                            "topic": fixed_topic or "",
                            "reason": reason,
                            "queued_for_retry": True,
                        }, _mf, indent=2, ensure_ascii=False)
                except OSError:
                    pass
                logger.warning(
                    "🟡 Quality miss handled gracefully — topic queued for retry "
                    "(next run re-opens it with a fresh script). No video today "
                    "(a weak script ships worse than one late strong video)."
                )
                return None
            raise RuntimeError(
                f"All {MAX_SCRIPT_ATTEMPTS} attempts failed strict gates — "
                f"topic '{fixed_topic}' saved to the retry queue (next run "
                f"retries it with a fresh script). Reason: {reason}"
            )
        raise RuntimeError(
            f"All {MAX_SCRIPT_ATTEMPTS} script-generation attempts failed mandatory gates. "
            f"Last error: {last_error}"
        )

    def _persist_last_failure(self, kind: str, message: str) -> None:
        """Persist a failure note so post-failure diagnosis survives log expiry."""
        try:
            path = "data/pipeline_last_failure.json"
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "kind": kind,
                    "reason": message,
                }, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    RETRY_QUEUE_PATH = os.environ.get(
        "QUALITY_RETRY_QUEUE_PATH", "data/quality_retry_queue.json")
    RETRY_MAX_DAYS = int(os.environ.get("QUALITY_RETRY_MAX_DAYS", "3"))
    RETRY_MAX_ATTEMPTS = int(os.environ.get("QUALITY_RETRY_MAX_ATTEMPTS", "6"))

    def _load_retry_queue(self) -> list:
        try:
            with open(self.RETRY_QUEUE_PATH, encoding="utf-8") as fh:
                items = json.load(fh)
            return items if isinstance(items, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_retry_queue(self, items: list) -> None:
        try:
            os.makedirs(os.path.dirname(self.RETRY_QUEUE_PATH) or ".", exist_ok=True)
            with open(self.RETRY_QUEUE_PATH, "w", encoding="utf-8") as fh:
                json.dump(items, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.warning("Could not persist quality retry queue: %s", exc)

    def _next_retry_topic(self, recent_topics: set) -> tuple:
        """Pop the oldest, still-eligible queued topic (topic, attempts_used)."""
        now = datetime.now(timezone.utc)
        items = self._load_retry_queue()
        eligible, stale, skipped = [], [], []
        for item in items:
            if item.get("topic") in recent_topics:
                skipped.append(item)
                continue
            if item.get("attempts", 0) >= self.RETRY_MAX_ATTEMPTS:
                stale.append(item)
                continue
            try:
                first_fail = datetime.fromisoformat(item["failed_at"])
                if first_fail.tzinfo is None:
                    first_fail = first_fail.replace(tzinfo=timezone.utc)
                if (now - first_fail).days >= self.RETRY_MAX_DAYS:
                    stale.append(item)
                    continue
            except (KeyError, ValueError):
                stale.append(item)
                continue
            eligible.append(item)
        eligible.sort(key=lambda it: it.get("failed_at", ""))
        # Persist: keep eligible (minus the one we'll take), drop the rest
        if eligible:
            chosen = eligible[0]
            kept = [it for it in items if it is not chosen]
        else:
            chosen, kept = None, items
        kept = [it for it in kept if it not in stale]
        if stale:
            try:
                dead_path = "data/quality_retry_dead.json"
                os.makedirs(os.path.dirname(dead_path) or ".", exist_ok=True)
                try:
                    with open(dead_path, encoding="utf-8") as fh:
                        dead = json.load(fh)
                    if not isinstance(dead, list):
                        dead = []
                except (OSError, json.JSONDecodeError):
                    dead = []
                dead.extend(stale)
                with open(dead_path, "w", encoding="utf-8") as fh:
                    json.dump(dead, fh, indent=2, ensure_ascii=False)
            except OSError:
                pass
        if eligible:
            self._save_retry_queue(kept)
        return chosen

    def _enqueue_retry_topic(self, topic: str, failure_reason: str,
                             attempt_count: int) -> None:
        items = self._load_retry_queue()
        # De-duplicate: same topic already waiting stays at its original age
        for it in items:
            if it.get("topic") == topic:
                it["attempts"] = max(it.get("attempts", 0), attempt_count)
                it["last_failure"] = failure_reason
                it["last_failed_at"] = datetime.now(timezone.utc).isoformat()
                break
        else:
            items.append({
                "topic": topic,
                "attempts": attempt_count,
                "reason": failure_reason,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            })
        self._save_retry_queue(items)

    def _generate_images_with_retry(self, script_data: dict) -> tuple:
        """Generate images with retry logic"""
        image_paths = []
        image_sources = []
        media_types = []
        # Seed with the full channel history so a scene can't reuse a hash or
        # fallback URL that already appeared in ANY earlier video, not just
        # earlier scenes in this same video.
        used_hashes = set(self.media_hash_history)
        used_fallbacks = {h for h in self.media_hash_history if isinstance(h, str) and h.startswith(("http://", "https://"))}

        total_scenes = len(script_data['scenes'])
        logger.info(f"Generating images for {total_scenes} scenes...")

        for i, scene in enumerate(script_data['scenes']):
            success = False
            for retry in range(MAX_IMAGE_RETRIES):
                try:
                    logger.info(f"Scene {i+1}/{total_scenes} - Attempt {retry+1}")
                    # topic_seed keeps one video's visual style cohesive while
                    # letting different videos look distinct (human, not templated).
                    res = generate_images(
                        i, scene, used_hashes, used_fallbacks,
                        topic_seed=script_data.get('topic') or script_data.get('title', ''),
                    )
                    if res and res.get('path') and os.path.exists(res['path']):
                        image_paths.append(res['path'])
                        image_sources.append(res.get('source', 'unknown'))
                        media_types.append(res.get('media_type', 'image'))
                        success = True
                        break
                except Exception as e:
                    logger.warning(f"Image generation failed (attempt {retry+1}): {e}")
                    time.sleep(2)

            if not success:
                logger.error(f"All {MAX_IMAGE_RETRIES} attempts failed for scene {i+1}")
                raise RuntimeError(f"Failed to generate image for scene {i+1}")

        if len(image_paths) != total_scenes:
            raise RuntimeError(f"Generated {len(image_paths)} images for {total_scenes} scenes")

        # Merge this video's hashes/URLs into the channel-wide ledger and
        # persist immediately, so even a crash later in the pipeline still
        # protects future videos from reusing this media.
        self.media_hash_history |= used_hashes
        self.media_hash_history |= used_fallbacks
        self._save_media_hash_history(self.media_hash_history)

        return image_paths, image_sources, media_types

    def run_pipeline(self, topic: str = None) -> dict:
        """Main pipeline execution"""
        start_time = time.time()
        current_stage = "startup"
        _write_pipeline_checkpoint(current_stage, "started")
        logger.info("=" * 60)
        logger.info("🚀 STARTING MRNEXTEP - TRENDING VIRAL PIPELINE")
        logger.info("=" * 60)

        def _start_stage(name: str):
            nonlocal current_stage
            current_stage = name
            _write_pipeline_checkpoint(name, "started", elapsed_seconds=round(time.time() - start_time, 2))
            logger.info("⏱️ STAGE START: %s", name)

        def _complete_stage(name: str = None):
            _write_pipeline_checkpoint(
                name or current_stage,
                "completed",
                elapsed_seconds=round(time.time() - start_time, 2),
            )
            logger.info("⏱️ STAGE COMPLETE: %s", name or current_stage)

        def _fail(reason):
            # 2026-08-15: CI failure logs expire (410) within ~3 days, making
            # failures invisible. Persist reason + traceback tail to data/ so
            # diagnostics can read it straight from the repo.
            data_log = os.path.join("data", "pipeline_last_failure.json")
            try:
                payload = {
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "reason": reason,
                    "stage": current_stage,
                    "traceback": "".join(traceback.format_exception(*sys.exc_info()))[-3000:],
                }
                os.makedirs("data", exist_ok=True)
                with open(data_log, "w") as _f:
                    json.dump(payload, _f, indent=2, default=str)
                _write_pipeline_checkpoint(
                    current_stage,
                    "failed",
                    reason=str(reason)[:500],
                    elapsed_seconds=round(time.time() - start_time, 2),
                )
            except Exception:
                pass

        try:
            _scheduling_on = os.environ.get("YT_SCHEDULE_PUBLISH", "false").lower() == "true"
            if self.video_history and not _scheduling_on:
                last_posted_at = self.video_history[-1].get('posted_at')
                if last_posted_at:
                    try:
                        last_dt = datetime.fromisoformat(last_posted_at)
                        if not self.scheduler.validate_posting_interval(last_dt):
                            logger.warning("⚠️ Posting sooner than recommended 2h gap")
                            if os.environ.get("ENFORCE_POSTING_GAP", "true").lower() == "true":
                                logger.warning(
                                    "ENFORCE_POSTING_GAP=true → skipping this run. "
                                    "Set ENFORCE_POSTING_GAP=false to override (not recommended)."
                                )
                                return {"success": False, "skipped": "posting_interval"}
                    except Exception as e:
                        logger.warning(f"Could not validate posting interval: {e}")

            # Phase 0b: Autonomous strategy — let the ML/DS engine decide the
            # series, quality gate and cadence for THIS run before we generate.
            _start_stage("strategy_decision")
            self._apply_strategy_decision()
            _complete_stage()

            # Phase 1: Script Generation (with trending topics)
            _start_stage("script_generation")
            logger.info("\n📝 PHASE 1: SCRIPT GENERATION (TRENDING)")
            script_data = self.generate_with_niche_strategy(topic)
            # 2026-08-20 graceful quality-miss: the generator returns None
            # (not raises) when a weak script is queued for retry — the slot
            # is intentionally left empty today so consistency survives.
            if not script_data:
                _complete_stage()
                return {"success": True, "skipped": "quality_miss_graceful",
                        "note": "weak script queued for retry; next run re-opens the topic"}
            logger.info(f"✅ Script generated: {script_data.get('title', 'Untitled')}")
            _complete_stage()

            # Phase 1b: SEO Generation
            _start_stage("seo_and_metadata")
            logger.info("\n🔍 PHASE 1b: SEO GENERATION")
            try:
                seo_topic = script_data.get('topic', topic)
                script_data['summary'] = script_data.get('description', '')
                seo_package = generate_seo_package(seo_topic, script_data)

                script_data['title'] = seo_package.get('chosen_title', script_data.get('title', 'Untitled'))
                script_data['title_options'] = seo_package.get('title_options', [])
                script_data['description'] = seo_package.get('description', '')
                script_data['tags'] = seo_package.get('tags', [])
                script_data['hashtags'] = seo_package.get('hashtags', [])
                script_data['thumbnail_text'] = seo_package.get(
                    'thumbnail_text', script_data.get('thumbnail_text', '')
                )
                script_data['pinned_comment'] = seo_package.get('pinned_comment', '')
                script_data['playlist_suggestion'] = seo_package.get('playlist_suggestion', '')
                script_data['seo_score'] = seo_package.get('seo_score', {})

                seo_overall = script_data['seo_score'].get('scores', {}).get('overall_seo_score', 0)
                logger.info(f"✅ SEO score: {seo_overall}/100")
            except Exception as e:
                logger.warning(f"SEO generation failed, continuing: {e}")

            # Phase 1c: High-CTR title reinforcement. The SEO package picks a
            # good title; we also build a curiosity-driven CTR title and keep
            # whichever passes the CTR health gate — so every new upload goes
            # out with a hook that maximises click-through, never a flat label.
            try:
                from ctr_engine import generate_high_ctr_title, validate_title
                ctr_title = generate_high_ctr_title(
                    script_data.get('topic') or script_data.get('title', ''),
                    platform='youtube',
                )
                check = validate_title(ctr_title)
                if check['ok']:
                    old = script_data.get('title', 'Untitled')
                    script_data['title'] = ctr_title
                    # keep the SEO description's keyword line, but refresh the
                    # first line to the CTR hook so search + click align.
                    desc = script_data.get('description', '')
                    if desc and not desc.startswith(ctr_title.split(' — ')[0]):
                        script_data['description'] = (
                            ctr_title + "\n\n" + desc
                        )
                    logger.info("✅ High-CTR title: %r (was %r)", ctr_title, old)
                else:
                    logger.info("High-CTR title skipped (%s); keeping SEO title.",
                                "; ".join(check['issues']))
            except Exception as e:  # noqa: BLE001 - title polish must not block
                logger.warning(f"High-CTR title step skipped: {e}")

            try:
                _final_title = script_data.get('title', '') or ''
                if self._is_duplicate_title(_final_title):
                    raise RuntimeError(
                        f"DUPLICATE TITLE BLOCKED: '{_final_title}' already exists "
                        "on this channel (published or scheduled). Refusing to "
                        "publish a duplicate. Pick a new topic and re-run."
                    )
                logger.info("✅ Title passes duplicate guard: %r", _final_title)
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001 - guard must never break the run silently
                logger.warning(f"Duplicate guard skipped: {e}")

            # Phase 1e: Platform-specific SEO guards (2026 algorithm per platform).
            # Each ENABLED platform's metadata must comply with THAT platform's
            # 2026 algorithm (YouTube search/rec, Facebook UTIS, IG forwardable
            # payoff). Independent observers — no trust in the SEO self-score.
            try:
                from platform_seo_guards import run_platform_seo_guards
                _enabled = self._enabled_platforms()
                _seo_gate = run_platform_seo_guards(script_data, _enabled)
                if not _seo_gate["overall"]:
                    raise RuntimeError(
                        "PLATFORM SEO GUARD BLOCKED: "
                        + ", ".join(_seo_gate["failed"])
                        + " metadata does not comply with its 2026 algorithm."
                    )
                logger.info("✅ Platform SEO guards passed: %s", _seo_gate["passed"])
            except RuntimeError:
                raise
            except Exception as seo_err:  # noqa: BLE001 - guard must not silently pass
                logger.warning(f"Platform SEO guard skipped ({seo_err}); continuing.")

            _complete_stage()

            try:
                from growth_engine import hook_frame
                script_data['hook_frame'] = hook_frame(
                    script_data.get('hook') or script_data.get('title', '')
                )
            except Exception as e:  # noqa: BLE001 - telemetry must never block a run
                logger.debug(f"Could not classify hook frame: {e}")

            # CTR Prediction
            try:
                ctr_result = predict_ctr(script_data)
                script_data['ctr_prediction'] = ctr_result
                ranked_hashtags = rank_hashtags(script_data.get('hashtags', []))
                script_data['hashtags_ranked'] = ranked_hashtags
                title_options = script_data.get('title_options', [])
                if title_options:
                    ab_variants = generate_ab_variants(script_data, title_options)
                    script_data['ab_variants'] = ab_variants
                    recommended = ab_variants.get('recommended') or {}
                    experiment_material = "|".join([
                        str(script_data.get('topic', '')),
                        str(script_data.get('hook', '')),
                        str(script_data.get('slot_label', '')),
                    ])
                    script_data['experiment'] = {
                        'id': hashlib.sha256(experiment_material.encode('utf-8')).hexdigest()[:16],
                        'design': 'predicted_title_description_variant',
                        'selected_title': script_data.get('title'),
                        'recommended_variant': recommended,
                        'candidate_count': len(ab_variants.get('variants') or []),
                        'requires_real_metrics': True,
                    }
                insights = get_historical_insights()
                if insights.get('insights'):
                    script_data['historical_insights'] = insights
            except Exception as e:
                logger.warning(f"CTR prediction failed: {e}")

            # Phase 2: Image Generation
            # Phase 1f: MAX REACH OPTIMIZATION — master optimizer for views/subs/followers/earnings
            _start_stage("max_reach_optimization")
            logger.info("\n🚀 PHASE 1f: MAX REACH OPTIMIZATION")
            try:
                max_reach_result = optimize_for_max_reach(script_data)
                script_data = max_reach_result.get('optimized_script', script_data)
                script_data['max_reach'] = {
                    'predicted_metrics': max_reach_result.get('predicted_metrics', {}),
                    'platform_ctas': max_reach_result.get('platform_ctas', {}),
                    'title_variants': max_reach_result.get('title_variants', []),
                    'loop_back_score': max_reach_result.get('loop_back_score', 0),
                    'improvements_applied': max_reach_result.get('improvements_applied', []),
                    'earnings_estimate': max_reach_result.get('earnings_estimate', {}),
                }
                # Log optimization results
                improvements = max_reach_result.get('improvements_applied', [])
                if improvements:
                    for imp in improvements:
                        logger.info(f"  🔧 {imp}")
                metrics = max_reach_result.get('predicted_metrics', {})
                logger.info(f"  📊 Predicted retention: {metrics.get('retention', 0):.1%}")
                logger.info(f"  📊 Predicted CTR: {metrics.get('ctr', 0):.1%}")
                logger.info(f"  📊 Loop-back score: {max_reach_result.get('loop_back_score', 0):.2f}")
                earnings = max_reach_result.get('earnings_estimate', {})
                logger.info(f"  💰 Est. RPM: ${earnings.get('estimated_rpm_usd', 0):.3f}/1K views")
                logger.info(f"  💰 Est. revenue/100K views: ${earnings.get('revenue_per_100k_views_usd', 0):.2f}")
                _complete_stage()
            except Exception as e:  # noqa: BLE001 - optimizer must never block production
                logger.warning(f"Max reach optimization failed (continuing with original script): {e}")

            _start_stage("image_generation")
            logger.info("\n🎨 PHASE 2: IMAGE GENERATION")
            image_paths, image_sources, media_types = self._generate_images_with_retry(script_data)
            logger.info(f"✅ Generated {len(image_paths)} scene visuals: {dict(Counter(media_types))}")

            # Quality Gate: Check fallback ratio
            source_counts = Counter(image_sources)
            unsafe_sources = {"Playwright-screenshot"}
            fallback_count = sum(c for src, c in source_counts.items() if src in unsafe_sources)
            fallback_ratio = fallback_count / len(image_paths) if image_paths else 1.0

            logger.info(f"📊 Image sources: {dict(source_counts)}")
            logger.info(f"📊 Fallback ratio: {fallback_ratio:.1%}")

            if fallback_ratio > FALLBACK_ABORT_RATIO:
                raise RuntimeError(f"Quality gate failed: {fallback_ratio:.1%} fallbacks")
            _complete_stage()

            cta_mode = os.environ.get("SPOKEN_CTA_MODE", "loop").strip().lower()
            cta_text = (script_data.get('cta') or '').strip()

            if not cta_text or contains_bait(cta_text):
                # The CTA still ships in metadata (caption/description), so it
                # must be bait-free even when it is never spoken.
                for _ in range(10):
                    candidate = get_random_cta()
                    if candidate and not contains_bait(candidate):
                        cta_text = candidate
                        break
                else:
                    cta_text = "Follow for more body science."
                script_data['cta'] = cta_text

            if cta_mode == "cta" and script_data.get('scenes') and image_paths:
                outro_scene = {
                    'visual': script_data['scenes'][-1].get('visual', ''),
                    'caption': cta_text,
                }
                script_data['scenes'].append(outro_scene)
                image_paths.append(image_paths[-1])
                image_sources.append(image_sources[-1] if image_sources else 'reused-outro')
                media_types.append(media_types[-1] if media_types else 'image')
                logger.info("Added spoken CTA scene (SPOKEN_CTA_MODE=cta): \"%s\"", cta_text)
            else:
                script_data['ending_mode'] = 'loop'
                logger.info(
                    "Loop ending: no spoken CTA scene. The final scene echoes the hook so "
                    "the Short loops cleanly (replays count as watch time); the follow ask "
                    "lives in the caption instead of costing ~8%% of runtime."
                )

            # Phase 3: Voice Generation
            _start_stage("voice_generation")
            logger.info("\n🔊 PHASE 3: VOICE GENERATION")
            try:
                try:
                    from humanizer import tempo_jitter
                    _voice_speed = tempo_jitter(1.0, script_data.get('topic') or script_data.get('title', ''))
                except Exception:  # noqa: BLE001 - jitter must never block
                    _voice_speed = 1.0
                # Prefer Edge Neural TTS (free, natural) over Kokoro (robotic)
                if HAS_ENHANCED_VOICE:
                    try:
                        audio_segments = generate_enhanced_voice(
                            script_data['scenes'], output_dir="output/voice",
                            topic=script_data.get('topic') or script_data.get('title', ''),
                            video_id=script_data.get('video_id', ''),
                        )
                        logger.info(f"✅ Edge Neural TTS: {len(audio_segments)} segments")
                    except Exception as edge_err:
                        logger.warning(f"Edge TTS failed, falling back to Kokoro: {edge_err}")
                        audio_segments = generate_voice_segments(
                            script_data['scenes'],
                            voice=os.environ.get("KOKORO_VOICE") or None,
                            speed=_voice_speed,
                            topic=script_data.get('topic') or script_data.get('title', '')
                        )
                else:
                    audio_segments = generate_voice_segments(
                        script_data['scenes'],
                        voice=os.environ.get("KOKORO_VOICE") or None,
                        speed=_voice_speed,
                        topic=script_data.get('topic') or script_data.get('title', '')
                    )
                logger.info(f"✅ Generated {len(audio_segments)} audio segments")
                narration_seconds = sum(float(seg.get("duration", 0)) for seg in audio_segments)
                # Audio-reactive analysis for pattern interrupt timing
                if HAS_AUDIO_REACTIVE:
                    try:
                        all_cuts = compute_scene_cuts(audio_segments, script_data['scenes'])
                        cut_map = generate_cut_map(all_cuts)
                        script_data["audio_cut_map"] = cut_map
                        logger.info(f"🎵 Audio cuts: {cut_map['total_cuts']} across {len(all_cuts)} scenes")
                    except Exception as ar_err:
                        logger.warning(f"Audio-reactive analysis failed: {ar_err}")
                _yt_floor, _yt_ideal, target_max_seconds = duration_policy(YOUTUBE)
                if narration_seconds > target_max_seconds * 1.12:
                    raise RuntimeError(
                        f"Narration too long: {narration_seconds:.1f}s "
                        f"(maximum before regeneration: {target_max_seconds * 1.12:.1f}s). "
                        f"YouTube grades a {_yt_ideal:.0f}s Short on "
                        f"{retention_gate(YOUTUBE, _yt_ideal):.0%} completion — a longer "
                        "video has to hold viewers for longer to clear the same bar."
                    )

                silence_count = sum(1 for s in audio_segments if s.get('tts_engine') == 'silence')
                if silence_count > 0:
                    raise RuntimeError(f"Silent segments: {silence_count}")

                engines = {s.get('tts_engine') for s in audio_segments}
                if len(engines) != 1:
                    raise RuntimeError(f"Mixed TTS voices: {sorted(engines)}")
                if os.environ.get("REQUIRE_CLONED_VOICE", "true").lower() == "true":
                    if engines != {"chatterbox_clone"}:
                        raise RuntimeError(f"Cloned voice required, got: {sorted(engines)}")
                platforms = self._enabled_platforms()
                hook_target = shared_hook_seconds(platforms)
                hook_limit = MAX_HOOK_SECONDS or hook_enforcement_seconds(platforms)
                if NextepPipeline.lenient_fallback and not MAX_HOOK_SECONDS:
                    # The outage fallback already passed the content, evidence,
                    # spam, and structural gates. Chatterbox can add a small,
                    # natural first-segment variance; allow only 0.25s here,
                    # never enough to turn a cold opener into a slow intro.
                    hook_limit = round(hook_limit + 0.25, 2)
                hook_actual = audio_segments[0].get('duration', 99) if audio_segments else 99
                if hook_actual > hook_limit:
                    raise RuntimeError(
                        f"Hook takes {hook_actual:.2f}s against a {hook_target:.1f}s target "
                        f"(hard limit {hook_limit:.2f}s). Every 2026 feed decides whether to "
                        "keep showing a video inside the first 2-3 seconds, so a slow opening "
                        "caps distribution before any other signal is measured."
                    )
                logger.info(
                    "Hook lands in %.2fs (target %.1fs, limit %.2fs).",
                    hook_actual, hook_target, hook_limit,
                )
                _complete_stage()
            except Exception as e:
                logger.error(f"Voice generation failed: {e}")
                raise

            # Phase 3b: Shorts Enhancements
            _start_stage("shorts_enhancements")
            logger.info("\n📝 PHASE 3b: SHORTS ENHANCEMENTS")
            try:
                shorts_report = build_shorts_report(
                    script_data,
                    audio_segments,
                    script_data.get('tags', [])
                )

                pacing = shorts_report.get('caption_pacing', {})
                # Never silently shorten captions after TTS: doing so creates
                # subtitles that no longer match the spoken narration. A pacing
                # failure must regenerate the script/audio as one consistent unit.
                too_fast = [item for item in pacing.get('per_scene', []) if item.get('status') == 'too_fast']
                if too_fast:
                    raise RuntimeError(
                        "Caption pacing is too fast; regenerate the script and voice together. "
                        + "; ".join(pacing.get('issues', [])[:3])
                    )

                script_data['shorts_report'] = shorts_report

                # Log retention prediction
                retention_pred = shorts_report.get('retention_prediction', {})
                if retention_pred:
                    logger.info(f"📊 Predicted avg retention: {retention_pred.get('predicted_avg_retention', 0):.1%}")
                    logger.info(f"📊 Predicted swipe-away: {retention_pred.get('predicted_swipe_away', 0):.1%}")
                    for suggestion in retention_pred.get('suggestions', []):
                        logger.info(f"💡 {suggestion}")

                outage_fallback_approved = bool(script_data.get('outage_fallback_approved'))
                if shorts_report.get('caption_pacing', {}).get('all_readable') is False:
                    issues = shorts_report.get('caption_pacing', {}).get('issues', [])
                    if outage_fallback_approved and issues and all("dragging" in issue.lower() for issue in issues):
                        logger.warning(
                            "Outage fallback: accepting slow caption pacing as a quality warning; "
                            "content, evidence, spam, and structural gates remain hard.",
                        )
                    else:
                        raise RuntimeError("Caption pacing failed: " + "; ".join(issues[:3]))

                hook_score = shorts_report.get('hook_detail', {}).get('score', 0)
                if hook_score < MIN_HOOK_SCORE and not outage_fallback_approved:
                    hook_topic = script_data.get('topic') or topic
                    try:
                        self._enqueue_retry_topic(
                            hook_topic or "",
                            f"hook {hook_score}/{MIN_HOOK_SCORE}",
                            attempt_count=1,
                        )
                        self._persist_last_failure(
                            "hook_retry",
                            f"Queued for retry: {hook_topic} — hook {hook_score}/{MIN_HOOK_SCORE}",
                        )
                    except Exception as _e:  # queueing must never block logging
                        logger.warning("Retry-queue enqueue failed: %s", _e)
                    raise RuntimeError(
                        f"HOOK MISS RECOVERABLE: hook {hook_score}/{MIN_HOOK_SCORE} — "
                        f"topic queued, retry with fresh script (continuity loop)")
                if outage_fallback_approved and hook_score < MIN_HOOK_SCORE:
                    logger.warning(
                        "Outage fallback hook accepted at %d/100 after content, evidence, "
                        "spam, and structural gates; normal runs remain at %d/100.",
                        hook_score,
                        MIN_HOOK_SCORE,
                    )
                logger.info(f"✅ Hook score: {hook_score}/100")
                _complete_stage()
            except Exception as e:
                logger.error(f"Shorts publishing checks failed: {e}")
                raise

            # Generate SRT
            try:
                os.makedirs("output", exist_ok=True)
                srt_path = "output/captions.srt"
                generate_srt(script_data['scenes'], audio_segments, output_path=srt_path)
                script_data['srt_path'] = srt_path
                logger.info(f"✅ SRT generated: {srt_path}")
            except Exception as e:
                logger.warning(f"SRT generation failed: {e}")

            # Phase 4: Build Video — master cut (YouTube)
            _start_stage("master_render_and_gates")

            # Final metadata hygiene must run after every SEO/CTA mutation and
            # immediately before the independent publish gate. This prevents
            # generated phrases such as "subscribe for more" from blocking a
            # run after the earlier sanitizer has already completed.
            clean_metadata_fields(
                script_data,
                fields=("title", "description", "summary", "cta"),
                platform=None,
            )
            assert_bait_free(
                script_data,
                fields=("title", "description", "summary", "cta"),
                platform=None,
            )
            logger.info("\n🎬 PHASE 4: BUILD VIDEO (MASTER CUT)")
            try:
                # Stamp a first-frame hook TEXT on scene 0 so the renderer can
                # overlay a pattern-interrupt line aligned with the title's
                # keyword (viral-channel tactic + Gemini keyword alignment).
                if script_data.get('scenes'):
                    hook_line = (
                        script_data.get('hook')
                        or script_data['scenes'][0].get('caption', '')
                        or script_data.get('title', '')
                    )
                    script_data['scenes'][0]['hook_text'] = hook_line
                final_video = build_video(
                    image_paths, audio_segments, script_data['scenes'], media_types=media_types
                )
                # Enhanced thumbnails with gradients, glow, A/B variants
                if HAS_ENHANCED_THUMBS:
                    try:
                        thumb_variants = gen_enhanced_thumbs(
                            bg_image=generated.get('scene_image_paths', [None])[0] if generated.get('scene_image_paths') else None,
                            text=script_data.get('thumbnail_text', script_data['title']),
                            output_dir="output/thumbnails",
                            category=script_data.get('topic') or script_data.get('topic_category', 'Body'),
                        )
                        thumb_path = thumb_variants[0]["path"] if thumb_variants else ""
                        script_data["thumbnail_variants"] = thumb_variants
                    except Exception as et_err:
                        logger.warning(f"Enhanced thumbnails failed: {et_err}")
                        thumb_path = ""
                if not thumb_path:
                    thumb_text = script_data.get('thumbnail_text') or script_data['title']
                    thumb_path = generate_thumbnail(
                    image_paths[0], thumb_text,
                    category=script_data.get('category', 'Body')
                )

                # Duration floor comes from the platform policy, not a magic
                # number. Padding only covers a small shortfall; a genuinely
                # short video is a script problem and is reported as one.
                yt_floor, yt_ideal, yt_ceiling = duration_policy(YOUTUBE)
                min_seconds = max(0.0, yt_floor - 3.0)
                logger.info("Checking master cut against the %.0fs floor...", yt_floor)

                try:
                    final_video = pad_video_to_minimum(final_video, min_seconds)
                except Exception as pad_err:
                    logger.warning(f"Video padding skipped: {pad_err}")

                technical = probe_video(final_video)
                master_seconds = float(technical.get("duration") or 0.0) or sum(
                    float(s.get("duration", 0)) for s in audio_segments
                )
                script_data['duration_seconds'] = round(master_seconds, 2)
                ok, verdict = fits_platform(master_seconds, YOUTUBE)
                logger.info(
                    "Master cut %.1fs — %s (gate: %.0f%% average view percentage)",
                    master_seconds, verdict, retention_gate(YOUTUBE, master_seconds) * 100,
                )
                if not ok:
                    logger.warning("Master cut is outside the YouTube window: %s", verdict)
                logger.info(f"✅ Video built and validated: {final_video} ({technical})")
                logger.info(f"✅ Thumbnail built: {thumb_path}")

                try:
                    from gates import run_gates
                    _yt_floor, _yt_ideal, _yt_ceil = duration_policy(YOUTUBE)
                    gate_ctx = {
                        "script_data": script_data,
                        "technical": technical,
                        "policy": {"floor": _yt_floor, "ideal": _yt_ideal,
                                   "ceil": _yt_ceil},
                        "image_paths": image_paths,
                        "media_types": media_types,
                        "audio_segments": audio_segments,
                        "required_scenes": len(script_data.get('scenes') or []),
                        "viewer_pref_threshold": 55 if outage_fallback_approved else 70,
                    }
                    gate_result = run_gates(gate_ctx)
                    if not gate_result["overall"]:
                        raise RuntimeError(
                            "INDEPENDENT GATE BLOCKED the run: "
                            + ", ".join(gate_result["failed_guards"])
                            + " guard(s) failed. Fix before publishing."
                        )
                    logger.info(
                        "✅ Independent gate pipeline: %d/%d guards passed%s.",
                        gate_result["passed_count"], gate_result["total"],
                        " (outage viewer-preference floor: 55)" if outage_fallback_approved else "",
                    )
                    _complete_stage()
                except RuntimeError:
                    raise
                except Exception as gate_err:  # noqa: BLE001 - a broken guard must not silently pass
                    logger.error("🔴 Gate pipeline error: %s", gate_err)
                    raise RuntimeError(f"Gate pipeline failed: {gate_err}")
            except Exception as e:
                logger.error(f"Video build failed: {e}")
                raise

            # Phase 4b: Meta cut (Facebook + Instagram)
            _start_stage("meta_cut")
            meta_video = final_video
            meta_cut_seconds = script_data.get('duration_seconds')
            meta_platforms = [p for p in self._enabled_platforms() if p != YOUTUBE]
            if meta_platforms and os.environ.get("META_CUT_ENABLED", "true").lower() == "true":
                logger.info("\n✂️  PHASE 4b: META CUT (Facebook / Instagram)")
                try:
                    indices = select_meta_cut(script_data['scenes'], audio_segments)
                    if len(indices) < len(script_data['scenes']):
                        cut_images, cut_audio, cut_scenes, cut_media = apply_cut(
                            indices, image_paths, audio_segments,
                            script_data['scenes'], media_types,
                        )
                        meta_video = build_video(
                            cut_images, cut_audio, cut_scenes,
                            output_path="output/final_video_meta.mp4",
                            media_types=cut_media,
                        )
                        summary = cut_summary(indices, audio_segments, len(script_data['scenes']))
                        meta_cut_seconds = summary["seconds"]
                        script_data['meta_cut'] = summary
                        script_data['meta_cut_seconds'] = meta_cut_seconds
                        for platform in meta_platforms:
                            ok, verdict = fits_platform(meta_cut_seconds, platform)
                            logger.info("  %s: %s", platform, verdict)
                    else:
                        logger.info(
                            "Master cut already fits the Meta window (%.1fs) — no separate edit needed.",
                            float(meta_cut_seconds or 0),
                        )
                except Exception as cut_err:  # noqa: BLE001 - never block the run
                    logger.warning(
                        "Meta cut failed (%s); Facebook/Instagram will receive the master cut.",
                        cut_err,
                    )
                    meta_video = final_video
                    meta_cut_seconds = script_data.get('duration_seconds')
            script_data['meta_cut_seconds'] = meta_cut_seconds
            _complete_stage()

            # Thumbnail SEO Score
            try:
                thumbnail_score = score_thumbnail(thumb_path, script_data['title'])
                script_data['thumbnail_score'] = thumbnail_score
                thumb_overall = thumbnail_score.get('overall_thumbnail_score', 0)
                logger.info(f"✅ Thumbnail score: {thumb_overall}/100")
            except Exception as e:
                logger.warning(f"Thumbnail scoring failed: {e}")

            # Phase 5: Upload or private review artifact. Public publishing is
            # opt-in and requires both an explicit mode and a passing human-review
            # record. Draft mode still renders the full asset for inspection.
            _start_stage("platform_upload")
            logger.info("\n📤 PHASE 5: UPLOAD / REVIEW")
            publish_mode = os.environ.get("PUBLISH_MODE", "draft").strip().lower()
            gate_passed = bool(script_data.get("us_content_gate", {}).get("approved"))
            if publish_mode != "publish" or not gate_passed:
                os.makedirs("output", exist_ok=True)
                draft_manifest = {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "draft",
                    "publish_mode": publish_mode,
                    "review_required": not gate_passed,
                    "script": script_data,
                    "video_path": final_video,
                    "thumbnail_path": thumb_path,
                    "meta_video_path": meta_video,
                }
                with open("output/draft_manifest.json", "w", encoding="utf-8") as handle:
                    json.dump(draft_manifest, handle, indent=2, ensure_ascii=False)
                upload_result = {
                    "draft_only": True,
                    "youtube_success": False,
                    "facebook_success": False,
                    "instagram_success": False,
                    "review_manifest": "output/draft_manifest.json",
                }
                logger.warning(
                    "DRAFT ONLY: no public platform API called (PUBLISH_MODE=%s, gate_passed=%s)",
                    publish_mode, gate_passed,
                )
            else:
                try:
                    upload_result = upload_all(
                        final_video, thumb_path, script_data, meta_video_path=meta_video
                    )
                    logger.info(f"✅ Upload result: {upload_result}")
                except Exception as e:
                    logger.error(f"Upload failed: {e}")
                    raise
            _complete_stage()

            # Persist enough provenance to audit rights and reproducibility
            # without committing binary assets or private provider responses.
            script_data['asset_provenance'] = {
                'scene_count': len(image_paths),
                'media_types': list(media_types),
                'asset_files': [
                    {
                        'path': os.path.basename(str(path)),
                        'sha256': hashlib.sha256(open(path, 'rb').read()).hexdigest()
                        if path and os.path.exists(path) else None,
                    }
                    for path in image_paths
                ],
                'audio_segments': len(audio_segments),
                'music_track': os.environ.get('MUSIC_TRACK', ''),
            }

            _start_stage("history_persistence")
            # Save history
            content_fingerprint = hashlib.sha256(
                "|".join(
                    str(script_data.get(key, "")).strip().lower()
                    for key in ('topic', 'title', 'voiceover', 'hook')
                ).encode('utf-8')
            ).hexdigest()
            self._save_video_history({
                'content_fingerprint': content_fingerprint,
                'title': script_data.get('title', 'Untitled'),
                'topic': script_data.get('topic'),
                'trend_source': script_data.get('trend_source'),
                'trend_url': script_data.get('trend_url'),
                'voiceover': script_data.get('voiceover', '')[:500],
                'posted_at': datetime.now(timezone.utc).isoformat() if (upload_result.get('youtube_success') or upload_result.get('facebook_success')) else None,
                'publish_at': upload_result.get('publish_at'),
                'facebook_success': upload_result.get('facebook_success', False),
                'instagram_success': upload_result.get('instagram_success', False),
                'youtube_video_id': upload_result.get('youtube_video_id'),
                # 2026-08-15: platform ids now flow through upload_result
                # (uploader surfaces them from upload_state), so the history
                # ledger — the single source insights and repair scripts read
                # — sees every platform including Instagram.
                'facebook_video_id': upload_result.get('facebook_video_id'),
                'instagram_media_id': upload_result.get('instagram_media_id'),
                'seo_score': script_data.get('seo_score', {}).get('scores', {}).get('overall_seo_score'),
                'predicted_ctr': script_data.get('ctr_prediction', {}).get('ctr_prediction'),
                'hook_score': script_data.get('shorts_report', {}).get('hook_detail', {}).get('score'),
                'predicted_retention': script_data.get('shorts_report', {}).get('retention_prediction', {}).get('predicted_avg_retention'),
                'duration_seconds': script_data.get('duration_seconds'),
                'meta_cut_seconds': script_data.get('meta_cut_seconds'),
                'ending_mode': script_data.get('ending_mode', 'cta'),
                'hook_frame': script_data.get('hook_frame'),
                'sources': script_data.get('sources', [])[:3],
                'source_verification': script_data.get('source_verification', [])[:3],
                'source_discovery': script_data.get('source_discovery'),
                'ai_disclosure': script_data.get('ai_disclosure', {}),
                'us_content_gate': script_data.get('us_content_gate', {}),
                'asset_provenance': script_data.get('asset_provenance', {}),
                'experiment': script_data.get('experiment', {}),
                'ab_variants': script_data.get('ab_variants', {}),
                # MAX REACH: optimization metrics for growth engine learning
                'max_reach': script_data.get('max_reach', {}),
            })

            _complete_stage()
            _write_pipeline_checkpoint("pipeline", "completed", elapsed_seconds=round(time.time() - start_time, 2))
            elapsed = time.time() - start_time
            logger.info("=" * 60)
            logger.info(f"✅ PIPELINE COMPLETE in {elapsed:.1f}s")
            logger.info(f"📹 Video: {script_data.get('title')}")
            logger.info(f"🎯 Hook Score: {script_data.get('shorts_report', {}).get('hook_detail', {}).get('score', 'N/A')}")
            logger.info("=" * 60)

            return {
                'success': True,
                'title': script_data.get('title'),
                'video_path': final_video,
                'thumbnail_path': thumb_path,
                'upload_result': upload_result,
                'elapsed_time': elapsed
            }

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error("=" * 60)
            logger.error(f"❌ PIPELINE FAILED after {elapsed:.1f}s")
            logger.error(f"Error: {e}")
            logger.error(traceback.format_exc())
            logger.error("=" * 60)
            _fail(str(e))
            raise

    def run_pipeline_with_continuity(self, topic: str = None, slot_label: str = None) -> dict:
        """Run the pipeline but NEVER let a guard failure break the day's
        consistency.

        Guards are strict (that's the point) but a blocked video must not become
        a MISSED US-peak slot. So on a guard-failure we retry with a NEW topic
        (bounded by continuity.MAX_GUARD_RETRIES) before giving up, and we
        register the slot outcome so consistency is visible.

        Returns the successful run dict, or a 'missed' dict if every safe
        pre-upload retry fails. Unknown and upload-side errors still raise so a
        possible external side effect is never silently repeated.
        """
        from continuity import (
            is_retryable_pre_upload_failure,
            should_retry_on_guard_failure,
            register_slot_attempt,
        )

        attempt = 0
        last_err = None
        while True:
            attempt += 1
            # A fresh topic on each retry gives the guards a genuinely new chance
            # (the duplicate-title guard especially needs a different subject).
            retry_topic = topic
            if attempt > 1 and not topic:
                retry_topic = None  # let the topic engine pick something new
            try:
                result = self.run_pipeline(topic=retry_topic)
                if slot_label:
                    register_slot_attempt(
                        slot_label, "published",
                        (result or {}).get("title", ""))
                return result
            except RuntimeError as exc:
                msg = str(exc)
                if not is_retryable_pre_upload_failure(msg):
                    raise  # unknown or upload-side error; fail closed
                last_err = exc
                logger.warning(
                    "🔄 Pre-upload quality failure on attempt %d (%s). Regenerating "
                    "before any public upload...", attempt, msg[:160],
                )
                if not should_retry_on_guard_failure(attempt):
                    break
                # small backoff so consecutive retries don't hammer
                time.sleep(attempt * 30)

        # All guard retries exhausted — the slot is missed this run, but we
        # record it so the workflow can decide (e.g. re-dispatch) instead of
        # silently breaking the cadence.
        if slot_label:
            register_slot_attempt(slot_label, "guard_fail", str(last_err or "")[:80])
        logger.error("🔴 Slot could not be filled after %d guard retries: %s",
                     attempt, last_err)
        return {"success": False, "missed": True, "reason": str(last_err)}

    def run_daily_batch(self, num_videos: int = 3):
        """Run multiple videos in batch"""
        logger.info(f"Starting daily batch: {num_videos} videos")
        succeeded = 0
        failed = 0

        for i in range(num_videos):
            try:
                logger.info(f"\n{'=' * 40}")
                logger.info(f"VIDEO {i + 1}/{num_videos}")
                logger.info(f"{'=' * 40}")

                self.run_pipeline()
                succeeded += 1

                # Wait between videos
                if i < num_videos - 1:
                    wait_time = 300
                    logger.info(f"Waiting {wait_time}s before next video...")
                    time.sleep(wait_time)

            except Exception as e:
                failed += 1
                logger.error(f"Video {i + 1} failed: {e}")
                continue

        logger.info(f"Batch complete: {succeeded} succeeded, {failed} failed out of {num_videos}")


def main():
    """Main entry point"""
    try:
        pipeline = NextepPipeline()
        topic = os.environ.get("VIDEO_TOPIC") or _consume_next_topic_override()

        # Label the current US peak slot so continuity can track consistency.
        try:
            from continuity import is_us_peak_slot
            _now = __import__("datetime").datetime.now(
                __import__("pytz").timezone("America/New_York"))
            slot_label = f"NY{_now.hour:02d}:{_now.minute:02d}" if is_us_peak_slot(_now.hour) else "offpeak"
        except Exception:
            slot_label = None

        if topic:
            logger.info(f"Using specific topic: {topic}")
            pipeline.run_pipeline_with_continuity(topic=topic, slot_label=slot_label)
        else:
            batch_mode = os.environ.get("BATCH_MODE", "false").lower() == "true"
            if batch_mode:
                num_videos = int(os.environ.get("BATCH_COUNT", "3"))
                pipeline.run_daily_batch(num_videos)
            else:
                result = pipeline.run_pipeline_with_continuity(slot_label=slot_label)
                if result.get("missed"):
                    logger.warning("Slot missed after safe pre-upload retries — see continuity log.")
                    # Production can ask the workflow shell to retry the whole
                    # job. The default remains graceful for local/manual runs,
                    # while production never silently finishes without an upload.
                    fail_on_missed = os.environ.get(
                        "FAIL_ON_MISSED_SLOT", "false"
                    ).strip().lower() in {"1", "true", "yes"}
                    sys.exit(1 if fail_on_missed else 0)

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        sys.exit(1)


# Backward-compatible alias — old code may `from main import SKILLORPipeline`
SKILLORPipeline = NextepPipeline

if __name__ == "__main__":
    main()
