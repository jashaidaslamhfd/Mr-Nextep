"""Regression coverage for the Meta limited-distribution fixes."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import platform_captions as captions  # noqa: E402
import platform_metrics  # noqa: E402
import uploader  # noqa: E402
from hashtag_clusters import get_optimized_us_tags  # noqa: E402


class MetaCaptionTests(unittest.TestCase):
    def setUp(self):
        self.script = {
            "title": "Why Your Fingers Wrinkle in Water",
            "hook": "Pruney fingers are not simply soaking up water.",
            "summary": "Your nerves help trigger a temporary pattern that may improve wet grip.",
            "topic": "finger wrinkles in water",
            "scenes": [
                {"caption": "The visible change begins in the fingertips."},
                {"caption": "Blood flow and nerve signals are part of the response."},
                {"caption": "The pattern is not the same as a sponge absorbing water."},
                {"caption": "Wet objects create the useful test condition."},
                {"caption": "Smooth fingertips and wrinkled fingertips behave differently."},
                {"caption": "The effect is a studied possibility, not a universal rule."},
                {"caption": "The surprising fact is that the wrinkles may improve wet grip."},
                {"caption": "Look closely: your body is already switching modes."},
            ],
        }

    def test_instagram_caption_is_native(self):
        text = captions.build_instagram_caption(
            self.script, ["finger wrinkles", "body science", "shorts"]
        ).lower()
        self.assertNotIn("youtube", text)
        self.assertNotIn("@mrnextep", text)
        self.assertIn("finger", text)

    def test_meta_hashtags_keep_topic_anchors(self):
        tags = get_optimized_us_tags(
            "finger wrinkles in water",
            ["finger wrinkles", "body science", "shorts"],
        )
        self.assertEqual(tags[0], "fingerwrinkles")
        self.assertEqual(tags[1], "bodyscience")
        self.assertNotIn("learntiktok", tags)
        self.assertNotIn("reelsusa", tags)


class MetaAnalyticsReceiptTests(unittest.TestCase):
    def test_collection_uses_history_ids_when_upload_state_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path = root / "video_history.json"
            upload_state_path = root / "upload_state.json"
            metrics_path = root / "platform_metrics.json"
            posted_at = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            history_path.write_text(
                json.dumps(
                    [
                        {
                            "content_fingerprint": "fp-1",
                            "title": "Finger wrinkles",
                            "topic": "finger wrinkles",
                            "posted_at": posted_at,
                            "facebook_video_id": "fb-history-1",
                            "instagram_media_id": "ig-history-1",
                            "meta_cut_seconds": 14.0,
                            "duration_seconds": 30.0,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            upload_state_path.write_text("{}", encoding="utf-8")
            metrics_path.write_text("{}", encoding="utf-8")

            with patch.object(platform_metrics, "VIDEO_HISTORY_PATH", str(history_path)), \
                 patch.object(platform_metrics, "UPLOAD_STATE_PATH", str(upload_state_path)), \
                 patch.object(platform_metrics, "PLATFORM_METRICS_PATH", str(metrics_path)), \
                 patch.object(platform_metrics, "_meta_token", return_value="token"), \
                 patch.object(platform_metrics, "fetch_facebook", return_value={"views": 123}) as fb, \
                 patch.object(platform_metrics, "fetch_instagram", return_value={"views": 456}) as ig, \
                 patch.object(platform_metrics.time, "sleep"):
                result = platform_metrics.collect(min_hours_old=24, refresh_hours=0)

            self.assertEqual(result["stats"]["checked"], 1)
            fb.assert_called_once()
            ig.assert_called_once()
            self.assertEqual(fb.call_args.args[0], "fb-history-1")
            self.assertEqual(ig.call_args.args[0], "ig-history-1")


class MetaFacebookSchedulingTests(unittest.TestCase):
    def test_finish_payload_uses_six_hour_stagger(self):
        start = unittest.mock.Mock(status_code=200, content=b"{}", text="")
        start.json.return_value = {"video_id": "fb-1", "upload_url": "https://upload.example"}
        upload = unittest.mock.Mock(status_code=200, content=b"{}", text="")
        upload.json.return_value = {"success": True}
        finish = unittest.mock.Mock(status_code=200, content=b"{}", text="")
        finish.json.return_value = {"success": True}

        with tempfile.NamedTemporaryFile(suffix=".mp4") as video, \
             patch.dict(
                 uploader.os.environ,
                 {
                     "FB_UPLOAD_ENABLED": "true",
                     "FB_ACCESS_TOKEN": "token",
                     "FB_PAGE_ID": "page-1",
                     "FB_STAGGER_MINUTES": "360",
                 },
                 clear=False,
             ), \
             patch.object(uploader, "YT_SCHEDULE_PUBLISH", True), \
             patch.object(uploader, "_compute_publish_at", return_value="2026-08-23T16:30:00Z"), \
             patch.object(uploader, "_already_uploaded_to_facebook", return_value=False), \
             patch.object(uploader, "_load_upload_state", return_value={}), \
             patch.object(uploader, "_save_upload_state"), \
             patch.object(uploader, "_set_fb_reel_cover"), \
             patch.object(uploader.time, "time", return_value=1_000_000.0), \
             patch.object(uploader.requests, "post", side_effect=[start, upload, finish]) as post:
            result = uploader._upload_facebook_reels(
                video.name,
                {"title": "Finger wrinkles", "topic": "finger wrinkles", "hook": "The skin changes."},
                ["finger wrinkles", "body science"],
            )

        self.assertTrue(result)
        finish_payload = post.call_args_list[2].kwargs["data"]
        expected = int(
            uploader.datetime.strptime("2026-08-23T16:30:00Z", "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=uploader.pytz.UTC)
            .timestamp()
            + 360 * 60
        )
        self.assertEqual(finish_payload["scheduled_publish_time"], expected)
        self.assertEqual(finish_payload["video_state"], "SCHEDULED")


class PipelineCheckpointTests(unittest.TestCase):
    def test_checkpoint_is_atomic_and_contains_no_secret_values(self):
        import main

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "pipeline_checkpoint.json"
            with patch.object(main, "PIPELINE_CHECKPOINT_PATH", str(checkpoint)), \
                 patch.dict(os.environ, {"GITHUB_RUN_ID": "run-123", "REFRESH_TOKEN": "should-not-appear"}, clear=False):
                main._write_pipeline_checkpoint(
                    "image_generation", "started", elapsed_seconds=12.5,
                    reason="provider timeout",
                )

            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "image_generation")
            self.assertEqual(payload["status"], "started")
            self.assertEqual(payload["run_id"], "run-123")
            self.assertEqual(payload["reason"], "provider timeout")
            self.assertNotIn("REFRESH_TOKEN", checkpoint.read_text(encoding="utf-8"))
            self.assertFalse((Path(str(checkpoint) + ".tmp")).exists())


class YouTubeUploadTransportTests(unittest.TestCase):
    def test_resumable_transport_handles_308_without_httplib_redirects(self):
        source = Path(uploader.__file__).read_text(encoding="utf-8")
        self.assertIn("YT_HTTP_TIMEOUT", source)
        self.assertIn("AuthorizedHttp", source)
        self.assertIn("yt_transport.follow_redirects = False", source)
        self.assertIn("resumable protocol uses HTTP 308", source)


class PartialYouTubeRecoveryTests(unittest.TestCase):
    def test_recovery_metadata_matches_partial_meta_receipt(self):
        import hashlib
        import importlib.util

        script_path = ROOT / "scripts" / "recover_youtube_upload.py"
        spec = importlib.util.spec_from_file_location("recover_youtube_upload", script_path)
        recovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recovery)
        material = "|".join(
            value.strip().lower()
            for value in (
                recovery.DEFAULT_TOPIC,
                recovery.DEFAULT_TITLE,
                recovery.DEFAULT_VOICEOVER,
                recovery.DEFAULT_HOOK,
            )
        )
        self.assertEqual(hashlib.sha256(material.encode()).hexdigest(), recovery.FINGERPRINT)
        self.assertIn("_upload_youtube", script_path.read_text(encoding="utf-8"))
        self.assertNotIn("_upload_facebook_reels", script_path.read_text(encoding="utf-8"))
        self.assertNotIn("_upload_instagram_reel", script_path.read_text(encoding="utf-8"))


class MetaWorkflowContractTests(unittest.TestCase):
    def test_production_workflow_sets_native_meta_windows(self):
        workflow = Path(__file__).parents[1] / ".github" / "workflows" / "main.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertIn('FB_STAGGER_MINUTES: "10"', text)
        self.assertIn('QUALITY_GATE_MODE: "balanced"', text)
        self.assertIn('IG_WAIT_FOR_SLOT: "true"', text)
        self.assertIn('IG_MAX_WAIT_MINUTES: "150"', text)
        self.assertIn('MAX_GUARD_RETRIES: "2"', text)
        self.assertIn('for attempt in 1 2 3 4 5; do', text)
        self.assertIn('PIPELINE_ATTEMPT_TIMEOUT_MINUTES: "35"', text)
        self.assertIn('timeout --signal=TERM --kill-after=30s', text)
        self.assertIn('AI_VIDEO_SCENES: "1"', text)
        self.assertIn('AI_HORDE_MAX_WAIT: "60"', text)
        self.assertIn('POLLINATIONS_VIDEO_TIMEOUT: "45"', text)
        self.assertIn('PIPELINE_CHECKPOINT_PATH: "data/pipeline_checkpoint.json"', text)
        self.assertIn('Upload-stage failure has unknown external completion state', text)
        self.assertIn('FAIL_ON_MISSED_SLOT: "true"', text)
        self.assertIn('recover_run_id:', text)
        self.assertIn('Recover missing YouTube upload from a partial run', text)
        self.assertIn('github.token', text)
        self.assertIn('actions: read', text)


if __name__ == "__main__":
    unittest.main()
