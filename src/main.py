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
    from algorithm_policy import (
        FACEBOOK, INSTAGRAM, YOUTUBE,
        MIN_HOOK_SCORE as _POLICY_MIN_HOOK_SCORE,
        contains_bait, duration_policy, env_float, env_int,
        hook_enforcement_seconds, retention_gate, shared_hook_seconds,
    )
    from platform_cuts import apply_cut, cut_summary, fits_platform, select_meta_cut
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
# The hook budget is a RANKING constraint, not a stylistic one: every 2026
# feed decides whether to keep showing a video within the first 2-3 seconds,
# so an opening that takes 5 seconds to land its promise has already lost the
# cohort it was testing on. Default comes from algorithm_policy (2.8s for
# YouTube) and can still be overridden per-run for experiments.
MAX_HOOK_SECONDS = env_float("MAX_HOOK_SECONDS", 0.0) or None
# Tracked repository state is durable across Actions runs; generated media
# remains in output/ and is intentionally not committed.
VIDEO_HISTORY_PATH = os.environ.get("VIDEO_HISTORY_PATH", "data/video_history.json")
# Cross-video image/clip hash ledger. Without this, image_generator.py only
# dedupes scenes WITHIN a single video (used_hashes/used_fallbacks are fresh
# sets per run) — the exact same fallback image or stock clip could then
# reappear in video #1 and video #200 with nothing to stop it. This file
# persists every hash/URL ever used so reuse is blocked channel-wide.
MEDIA_HASH_HISTORY_PATH = os.environ.get("MEDIA_HASH_HISTORY_PATH", "data/media_hash_history.json")
# Cap on how many hashes/URLs we remember, so the ledger doesn't grow forever.
MAX_MEDIA_HASH_HISTORY = int(os.environ.get("MAX_MEDIA_HASH_HISTORY", "20000"))


class SKILLORPipeline:
    def __init__(self):
        """Initialize pipeline with all components"""
        logger.info("Initializing SKILLOR Pipeline...")

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

            lever = decision.get("lever_analysis", {})
            if lever and lever.get("lever_importance"):
                top = lever["lever_importance"][0]
                logger.info(
                    "🤖 ML lever insight: %s drives views most (%s%%).",
                    top.get("label"), int(round(top.get("share", 0) * 100)),
                )

            # CTR / retention steering: log what the dedicated models say so the
            # operator sees exactly what to protect (these two gates decide
            # whether the channel keeps being distributed).
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

            # Medical accuracy check
            med_check = validate_script_for_medical_accuracy(script_data)
            if not med_check.get('valid', False):
                logger.warning("Medical accuracy check failed, adding disclaimer")
                script_data = auto_add_disclaimer(script_data)

            # Quality check
            quality_result = self.quality_checker.check_script_quality(script_data)
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
        """Generate script with retry logic - uses trending topics if no topic provided"""
        fixed_topic = topic
        recent_topics = self._get_recent_topics()
        best_attempt = None
        last_error = None

        for attempt in range(1, MAX_SCRIPT_ATTEMPTS + 1):
            try:
                # Use trending topic if no fixed topic
                if fixed_topic:
                    current_topic = fixed_topic
                else:
                    # Production requires a real same-day external trend; the
                    # selected source/URL is retained with the generated video.
                    trend_record = get_trending_topic(
                        exclude=recent_topics, return_metadata=True
                    )
                    current_topic = trend_record['topic']

                logger.info(f"Attempt {attempt}/{MAX_SCRIPT_ATTEMPTS} for topic: {current_topic}")

                result = self._generate_and_check_once(current_topic)
                if not fixed_topic:
                    generated = result['script_data']
                    generated['trend_source'] = trend_record.get('source')
                    generated['trend_url'] = trend_record.get('source_url')
                    generated['series_number'] = trend_record.get('series_number')
                    generated['series_title'] = trend_record.get('series_title')
                    generated['thumbnail_text'] = trend_record.get('thumbnail_text', '')
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
            last_error = "best candidate rejected: " + ", ".join(failures)

        raise RuntimeError(
            f"All {MAX_SCRIPT_ATTEMPTS} script-generation attempts failed mandatory gates. "
            f"Last error: {last_error}"
        )

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
        logger.info("=" * 60)
        logger.info("🚀 STARTING SKILLOR - TRENDING VIRAL PIPELINE")
        logger.info("=" * 60)

        try:
            # Phase 0: Check posting interval. When scheduled publishing is
            # on, the one-video-per-slot lock in uploader.py already spaces
            # publishes >=90 min apart via publishAt — the upload-TIME gap
            # check here would only skip legitimate same-evening runs, so it
            # stays active for instant-publish mode only.
            _scheduling_on = os.environ.get("YT_SCHEDULE_PUBLISH", "false").lower() == "true"
            if self.video_history and not _scheduling_on:
                last_posted_at = self.video_history[-1].get('posted_at')
                if last_posted_at:
                    try:
                        last_dt = datetime.fromisoformat(last_posted_at)
                        if not self.scheduler.validate_posting_interval(last_dt):
                            # Was a toothless warning before: a back-to-back
                            # manual dispatch could hammer the channel with
                            # uploads minutes apart despite our anti-spam
                            # policy. ENFORCE_POSTING_GAP=true (default) now
                            # SKIPS the run instead of just logging.
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
            self._apply_strategy_decision()

            # Phase 1: Script Generation (with trending topics)
            logger.info("\n📝 PHASE 1: SCRIPT GENERATION (TRENDING)")
            script_data = self.generate_with_niche_strategy(topic)
            logger.info(f"✅ Script generated: {script_data.get('title', 'Untitled')}")

            # Phase 1b: SEO Generation
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

            # Phase 1d: Duplicate-title guard. NEVER publish a title that
            # already exists on this channel (published or scheduled) — a
            # duplicate Short tanks retention AND is an inauthentic-content
            # risk. If the final title is a duplicate, abort the run so the
            # operator/system can pick a fresh topic rather than upload a copy.
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

            # Record which opening frame this video used, so the growth engine
            # can learn which frames survive the first three seconds. Without
            # this the classifier would have to re-derive the frame from the
            # published title later — and the title gets rewritten by SEO, so
            # it would be classifying the wrong string.
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
                insights = get_historical_insights()
                if insights.get('insights'):
                    script_data['historical_insights'] = insights
            except Exception as e:
                logger.warning(f"CTR prediction failed: {e}")

            # Phase 2: Image Generation
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

            # Phase 2b: Ending mode — loop-back (default) or a short spoken CTA
            #
            # WHY THE SPOKEN CTA IS OFF BY DEFAULT NOW
            # A "follow for more" outro used to be appended as a real 9th
            # scene, so every video spent 2-4 seconds of its runtime asking
            # for something instead of delivering. On a 36-second Short those
            # seconds are ~8% of the video, and they land exactly where the
            # completion percentage is decided. All three 2026 ranking systems
            # grade on completion (YouTube's watch-time-per-impression gate,
            # Meta's watch-through), and Meta additionally demotes captions
            # and audio that beg for engagement.
            #
            # Loop mode ends on the script's LOOP-BACK line instead, so the
            # last frame flows back into the first. A clean loop earns replays,
            # and replays count as watch time on every platform. The follow
            # ask still exists — it just lives in the caption, where it costs
            # zero seconds of retention.
            #
            # SPOKEN_CTA_MODE=cta restores the old behaviour with a hard 2s
            # budget if the channel ever wants to test it again.
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
            logger.info("\n🔊 PHASE 3: VOICE GENERATION")
            try:
                # Voice/lang are env-driven now (KOKORO_VOICE / KOKORO_LANG_CODE
                # / TTS_ENGINE). Previously hardcoded "am_adam" here overrode
                # the workflow's voice config without anyone noticing.
                # A tiny per-video tempo jitter (humanizer) stops every video
                # being exactly on-beat, which is a machine tell.
                try:
                    from humanizer import tempo_jitter
                    _voice_speed = tempo_jitter(1.0, script_data.get('topic') or script_data.get('title', ''))
                except Exception:  # noqa: BLE001 - jitter must never block
                    _voice_speed = 1.0
                audio_segments = generate_voice_segments(
                    script_data['scenes'],
                    voice=os.environ.get("KOKORO_VOICE") or None,
                    speed=_voice_speed
                )
                logger.info(f"✅ Generated {len(audio_segments)} audio segments")
                narration_seconds = sum(float(seg.get("duration", 0)) for seg in audio_segments)
                # The master cut's ceiling comes from algorithm_policy, which
                # derives it from YouTube's retention gate rather than from a
                # hand-picked number. video_editor may still make a small
                # (<=12%) inaudible speed correction; anything beyond that
                # gets regenerated, because rushed narration is exactly the
                # "machine-made" quality the 2026 inauthentic-content policy
                # penalises.
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
                # Hook budget: the tightest ENABLED platform wins, because one
                # audio track serves all of them and Instagram decides fastest
                # (~2s). The enforcement threshold carries a delivery
                # tolerance — the writer aims at the true budget, and the gate
                # rejects genuinely slow openings rather than punishing a
                # strong hook for a natural dramatic beat. Both numbers come
                # from algorithm_policy so they can never drift apart again.
                platforms = self._enabled_platforms()
                hook_target = shared_hook_seconds(platforms)
                hook_limit = MAX_HOOK_SECONDS or hook_enforcement_seconds(platforms)
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
            except Exception as e:
                logger.error(f"Voice generation failed: {e}")
                raise

            # Phase 3b: Shorts Enhancements
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

                if shorts_report.get('caption_pacing', {}).get('all_readable') is False:
                    issues = shorts_report.get('caption_pacing', {}).get('issues', [])
                    raise RuntimeError("Caption pacing failed: " + "; ".join(issues[:3]))

                hook_score = shorts_report.get('hook_detail', {}).get('score', 0)
                if hook_score < MIN_HOOK_SCORE:
                    raise RuntimeError(f"Hook failed: {hook_score}/{MIN_HOOK_SCORE}")
                
                logger.info(f"✅ Hook score: {hook_score}/100")
                
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
            except Exception as e:
                logger.error(f"Video build failed: {e}")
                raise

            # Phase 4b: Meta cut (Facebook + Instagram)
            #
            # Facebook widens distribution around ~72% watch-through and
            # Instagram decides in the first seconds; both sit well below
            # YouTube's window. Publishing the 36s master to Meta was asking a
            # 27s-shaped audience to finish a 36s video, and this channel's own
            # Instagram insights showed the result: 2.6-7.5s average watch time.
            #
            # The Meta cut reuses the SAME rendered scenes and audio, so it
            # costs one extra encode and zero extra generation. If anything
            # fails, Meta simply receives the master cut — a slightly-too-long
            # Reel beats no Reel.
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

            # Thumbnail SEO Score
            try:
                thumbnail_score = score_thumbnail(thumb_path, script_data['title'])
                script_data['thumbnail_score'] = thumbnail_score
                thumb_overall = thumbnail_score.get('overall_thumbnail_score', 0)
                logger.info(f"✅ Thumbnail score: {thumb_overall}/100")
            except Exception as e:
                logger.warning(f"Thumbnail scoring failed: {e}")

            # Phase 5: Upload
            logger.info("\n📤 PHASE 5: UPLOAD")
            try:
                upload_result = upload_all(
                    final_video, thumb_path, script_data, meta_video_path=meta_video
                )
                logger.info(f"✅ Upload result: {upload_result}")
            except Exception as e:
                logger.error(f"Upload failed: {e}")
                raise

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
                'seo_score': script_data.get('seo_score', {}).get('scores', {}).get('overall_seo_score'),
                'predicted_ctr': script_data.get('ctr_prediction', {}).get('ctr_prediction'),
                'hook_score': script_data.get('shorts_report', {}).get('hook_detail', {}).get('score'),
                'predicted_retention': script_data.get('shorts_report', {}).get('retention_prediction', {}).get('predicted_avg_retention'),
                # Real rendered lengths. platform_metrics divides each
                # platform's average watch time by the length of the cut THAT
                # platform actually received — without these two fields every
                # completion rate would be computed against the wrong
                # denominator and the learning loop would draw the wrong
                # conclusion about which platform is working.
                'duration_seconds': script_data.get('duration_seconds'),
                'meta_cut_seconds': script_data.get('meta_cut_seconds'),
                'ending_mode': script_data.get('ending_mode', 'cta'),
                'hook_frame': script_data.get('hook_frame'),
            })

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
            raise

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
        pipeline = SKILLORPipeline()
        topic = os.environ.get("VIDEO_TOPIC")

        if topic:
            logger.info(f"Using specific topic: {topic}")
            pipeline.run_pipeline(topic=topic)
        else:
            batch_mode = os.environ.get("BATCH_MODE", "false").lower() == "true"
            if batch_mode:
                num_videos = int(os.environ.get("BATCH_COUNT", "3"))
                pipeline.run_daily_batch(num_videos)
            else:
                pipeline.run_pipeline()

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
