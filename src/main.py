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
except ImportError as e:
    logger.error(f"Failed to import modules: {e}")
    logger.error("Make sure all required modules are in the same directory")
    sys.exit(1)

# Constants
MAX_SCRIPT_ATTEMPTS = 3
MAX_IMAGE_RETRIES = 3
FALLBACK_ABORT_RATIO = float(os.environ.get("FALLBACK_ABORT_RATIO", "0.5"))
# 70 accepts a clear, specific natural hook while still rejecting vague or
# manipulative openings. The scorer and generator use the same 6–9 word policy.
MIN_HOOK_SCORE = int(os.environ.get("MIN_HOOK_SCORE", "70"))
# Natural cloned delivery varies by speaker/reference. Five seconds preserves
# a concise hook without throwing away an otherwise healthy 30-second Short.
MAX_HOOK_SECONDS = float(os.environ.get("MAX_HOOK_SECONDS", "5.0"))
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
        """Get recent topics to avoid repetition"""
        return [v.get('topic') for v in self.video_history[-n:] if v.get('topic')]

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
                    res = generate_images(i, scene, used_hashes, used_fallbacks)
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
            # Phase 0: Check posting interval
            if self.video_history:
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

            # Phase 2b: Outro / CTA scene
            # `cta` was previously stored only as metadata and used in the
            # YouTube description (uploader.py) - it was never spoken or
            # shown on screen, so viewers never actually saw/heard a
            # "like / follow / share" prompt at the end of the video.
            # Turning it into one more real scene means it goes through the
            # normal voice + caption + build_video pipeline like every other
            # scene, so it is both spoken and displayed at the end.
            cta_text = (script_data.get('cta') or '').strip()
            _cta_action_words = ('follow', 'share', 'subscribe', 'comment', 'like')
            # Facebook's engagement-bait policy demotes Reels whose CTA begs
            # for likes/shares/comments. When FB upload is enabled the SAME
            # audio goes to both platforms, so the spoken CTA must be the
            # FB-safe variant (follow-based). YouTube-only runs may use the
            # full action-word pool.
            _fb_bait_words = ('like', 'share', 'comment', 'tag', 'subscribe')
            _fb_uploads = os.environ.get("FB_UPLOAD_ENABLED", "false").lower() == "true"

            def _has_action_word(text: str) -> bool:
                return any(w in text.lower() for w in _cta_action_words)

            def _is_fb_safe_cta(text: str) -> bool:
                lowered = text.lower()
                return 'follow' in lowered and not any(b in lowered for b in _fb_bait_words)

            def _cta_ok(text: str) -> bool:
                return _is_fb_safe_cta(text) if _fb_uploads else _has_action_word(text)

            if not cta_text or not _cta_ok(cta_text):
                for _ in range(10):
                    candidate = get_random_cta()
                    if _cta_ok(candidate):
                        cta_text = candidate
                        break
                else:
                    cta_text = "Follow for more facts like this."
                script_data['cta'] = cta_text
                logger.info("No usable CTA in script; using fallback: %s", cta_text)

            if cta_text and script_data.get('scenes') and image_paths:
                outro_scene = {
                    'visual': script_data['scenes'][-1].get('visual', ''),
                    'caption': cta_text,
                }
                script_data['scenes'].append(outro_scene)
                image_paths.append(image_paths[-1])
                image_sources.append(image_sources[-1] if image_sources else 'reused-outro')
                media_types.append(media_types[-1] if media_types else 'image')
                logger.info("✅ Added outro CTA scene: \"%s\"", cta_text)

            # Phase 3: Voice Generation
            logger.info("\n🔊 PHASE 3: VOICE GENERATION")
            try:
                # Voice/lang are env-driven now (KOKORO_VOICE / KOKORO_LANG_CODE
                # / TTS_ENGINE). Previously hardcoded "am_adam" here overrode
                # the workflow's voice config without anyone noticing.
                audio_segments = generate_voice_segments(
                    script_data['scenes'],
                    voice=os.environ.get("KOKORO_VOICE") or None,
                    speed=1.0
                )
                logger.info(f"✅ Generated {len(audio_segments)} audio segments")
                narration_seconds = sum(float(seg.get("duration", 0)) for seg in audio_segments)
                target_max_seconds = float(os.environ.get("TARGET_MAX_SECONDS", "55"))
                # video_editor may make a small (<=12%) transparent speed
                # correction. Anything beyond that must be regenerated instead
                # of producing rushed, low-retention narration.
                if narration_seconds > target_max_seconds * 1.12:
                    raise RuntimeError(
                        f"Narration too long: {narration_seconds:.1f}s "
                        f"(maximum before regeneration: {target_max_seconds * 1.12:.1f}s)"
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
                if audio_segments and audio_segments[0].get('duration', 99) > MAX_HOOK_SECONDS:
                    raise RuntimeError(
                        f"First scene exceeds {MAX_HOOK_SECONDS:.1f} seconds"
                    )
                if audio_segments and audio_segments[0].get('duration', 0) > 4.0:
                    logger.info(
                        "Hook is %.2fs; accepted within the natural cloned-voice limit of %.1fs.",
                        audio_segments[0]['duration'], MAX_HOOK_SECONDS,
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

            # Phase 4: Build Video (with visual effects)
            logger.info("\n🎬 PHASE 4: BUILD VIDEO (WITH EFFECTS)")
            try:
                final_video = build_video(
                    image_paths, audio_segments, script_data['scenes'], media_types=media_types
                )
                thumb_text = script_data.get('thumbnail_text') or script_data['title']
                thumb_path = generate_thumbnail(
                    image_paths[0], thumb_text,
                    category=script_data.get('category', 'Body')
                )
                
                # Pad video if slightly too short
                target_min = float(os.environ.get("TARGET_MIN_SECONDS", "40"))
                min_seconds = max(0.0, target_min - 5.0)
                logger.info(f"Checking video duration against minimum {min_seconds:.2f}s...")
                
                try:
                    final_video = pad_video_to_minimum(final_video, min_seconds)
                except Exception as pad_err:
                    logger.warning(f"Video padding skipped: {pad_err}")
                
                technical = probe_video(final_video)
                logger.info(f"✅ Video built and validated: {final_video} ({technical})")
                logger.info(f"✅ Thumbnail built: {thumb_path}")
            except Exception as e:
                logger.error(f"Video build failed: {e}")
                raise

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
                upload_result = upload_all(final_video, thumb_path, script_data)
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
                'facebook_success': upload_result.get('facebook_success', False),
                'instagram_success': upload_result.get('instagram_success', False),
                'youtube_video_id': upload_result.get('youtube_video_id'),
                'seo_score': script_data.get('seo_score', {}).get('scores', {}).get('overall_seo_score'),
                'predicted_ctr': script_data.get('ctr_prediction', {}).get('ctr_prediction'),
                'hook_score': script_data.get('shorts_report', {}).get('hook_detail', {}).get('score'),
                'predicted_retention': script_data.get('shorts_report', {}).get('retention_prediction', {}).get('predicted_avg_retention'),
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
