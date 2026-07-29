"""Regression tests for the runtime-config bugs fixed in the US-audience
refactor. Every test here maps to a bug that once shipped to production."""

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
sys.path.insert(0, str(SRC_DIR))


class GitignoreSafetyTests(unittest.TestCase):
    """A `git add .` must never be able to commit credentials or the private
    voice reference (this trap existed: oauth_backup.json was written into
    the repo root with no ignore pattern)."""

    def setUp(self):
        self.gitignore = (ROOT / ".gitignore").read_text()

    def test_token_artifacts_are_ignored(self):
        for pattern in ("oauth_backup.json", "client_secrets*.json", "token*.json"):
            self.assertIn(pattern, self.gitignore, f".gitignore missing {pattern}")

    def test_voice_reference_is_ignored_and_untracked(self):
        self.assertIn("assets/voice_reference.wav", self.gitignore)
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "assets/voice_reference.wav"],
            cwd=ROOT, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0, "voice reference must not be git-tracked")


class RequirementsTests(unittest.TestCase):
    """Every third-party top-level import must be declared somewhere."""

    @staticmethod
    def _declared_packages(text: str) -> str:
        """Only real requirement lines — comments must not count (the core
        file's footer NOTES mention removed packages by name)."""
        lines = [ln.split("#", 1)[0].strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln)

    def setUp(self):
        self.core = self._declared_packages((ROOT / "requirements.txt").read_text().lower())
        self.optional = self._declared_packages((ROOT / "requirements-optional.txt").read_text().lower())

    def test_previously_missing_imports_are_declared(self):
        self.assertIn("feedparser", self.core)   # scripts/fetch_trending_now.py crashed without it
        self.assertIn("edge-tts", self.core)     # emergency cloud TTS was undeclared

    def test_unused_google_genai_removed_from_core(self):
        self.assertNotIn("google-genai", self.core)

    def test_voice_clone_stack_is_optional_only(self):
        for pkg in ("chatterbox-tts", "torchaudio", "transformers"):
            self.assertNotIn(pkg, self.core)
            self.assertIn(pkg, self.optional)


class EnvWiringTests(unittest.TestCase):
    """The workflow's env vars must actually be read by code (the old
    KOKORO_VOICE/KOKORO_LANG_CODE/TTS_ENGINE/CHANNEL_LANGUAGE block was
    completely decorative — French config silently produced US audio)."""

    def test_kokoro_envs_are_honored(self):
        voice_generator = pytestless_import("voice_generator")
        old = {k: os.environ.get(k) for k in ("KOKORO_VOICE", "KOKORO_LANG_CODE", "TTS_ENGINE")}
        try:
            os.environ["KOKORO_VOICE"] = "af_heart"
            os.environ["KOKORO_LANG_CODE"] = "b"
            os.environ["TTS_ENGINE"] = "kokoro"
            import importlib
            importlib.reload(voice_generator)
            self.assertEqual(voice_generator.KOKORO_VOICE, "af_heart")
            self.assertEqual(voice_generator.KOKORO_LANG_CODE, "b")
            self.assertEqual(voice_generator.TTS_ENGINE, "kokoro")
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            import importlib
            importlib.reload(voice_generator)

    def test_invalid_tts_engine_falls_back(self):
        voice_generator = pytestless_import("voice_generator")
        old = os.environ.get("TTS_ENGINE")
        try:
            os.environ["TTS_ENGINE"] = "banana"
            import importlib
            importlib.reload(voice_generator)
            self.assertEqual(voice_generator.TTS_ENGINE, "chatterbox")
        finally:
            if old is None:
                os.environ.pop("TTS_ENGINE", None)
            else:
                os.environ["TTS_ENGINE"] = old
            import importlib
            importlib.reload(voice_generator)


def pytestless_import(name):
    """Import a src module, skipping cleanly when its heavy deps are absent."""
    try:
        import importlib
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        raise unittest.SkipTest(f"{name} deps not installed here: {exc}")


class PublishAtTests(unittest.TestCase):
    """YT_SCHEDULE_PUBLISH was a dead env var with no publishAt logic; the
    helper must now always return a future US-peak slot in UTC."""

    def test_publish_at_is_future_peak_slot(self):
        uploader = pytestless_import("uploader")
        old = os.environ.get("YT_SCHEDULE_PUBLISH")
        try:
            from datetime import datetime, timedelta
            import pytz
            os.environ["YT_SCHEDULE_PUBLISH"] = "true"
            publish_at = uploader._compute_publish_at()
            parsed = datetime.strptime(publish_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            self.assertGreaterEqual(parsed, datetime.now(pytz.UTC) + timedelta(minutes=25))
            slot_ny = parsed.astimezone(pytz.timezone("America/New_York"))
            self.assertIn((slot_ny.hour, slot_ny.minute), [(12, 30), (20, 0), (21, 30)])
        finally:
            if old is None:
                os.environ.pop("YT_SCHEDULE_PUBLISH", None)
            else:
                os.environ["YT_SCHEDULE_PUBLISH"] = old


class PublicApiTests(unittest.TestCase):
    """src/__init__.py once declared __all__ with zero resolvable names."""

    def test_every_advertised_name_is_lazy_mapped(self):
        import src
        self.assertGreater(len(src.__all__), 10)
        for name in src.__all__:
            self.assertIn(name, src._LAZY_EXPORTS, f"{name} in __all__ but has no lazy mapping")

    def test_unknown_attribute_still_raises(self):
        import src
        with self.assertRaises(AttributeError):
            src.DEFINITELY_NOT_A_REAL_EXPORT_123


def _arc_fixture():
    """Valid 8-scene script that follows Hook→Suspense→…→Loop-back."""
    return {
        "title": "Why Sleep Helps Your Brain",
        "hook": "Your brain saves memories while sleeping.",
        "cta": "Follow for more science made simple.",
        "scenes": [
            {"visual": "glowing brain during deep sleep", "caption": "Your brain saves memories while sleeping."},
            {"visual": "memory signals moving through neurons", "caption": "But how does your brain choose which moments stay important after a long day?"},
            {"visual": "student studying in a quiet room", "caption": "Without enough sleep, new information can feel clear now but disappear much sooner tomorrow."},
            {"visual": "brain pathways strengthening overnight", "caption": "During deep sleep, your brain replays recent experiences and strengthens the connections worth keeping."},
            {"visual": "calm sleeper with brain overlay", "caption": "It also links related ideas together, making recall easier when you need those details."},
            {"visual": "memory pathway becoming brighter", "caption": "This process is why rest can help learning feel stable after a full day."},
            {"visual": "organized notes beside sleeping person", "caption": "The memory is not perfect, but sleep gives your brain time to organize it."},
            {"visual": "morning light over focused person", "caption": "So sleep quietly saves the memories your waking brain might otherwise lose completely tomorrow."},
        ],
    }


class StoryArcTests(unittest.TestCase):
    """2026 feed reality: first-3s suspense question + closing loop-back are
    the two cheapest retention levers. Scripts missing them must fail
    validation (and be retried), not ship."""

    def setUp(self):
        self.sg = pytestless_import("script_generator")

    def _validated(self, data):
        return self.sg.validate_script(self.sg._normalize_scenes(data))

    def test_complete_arc_passes(self):
        valid, issues = self._validated(_arc_fixture())
        self.assertTrue(valid, issues)

    def test_scene_two_without_open_question_is_rejected(self):
        data = _arc_fixture()
        data["scenes"][1]["caption"] = "Your brain simply keeps doing this every single day."
        valid, issues = self._validated(data)
        self.assertFalse(valid)
        self.assertTrue(any("SUSPENSE" in issue for issue in issues), issues)

    def test_final_scene_without_loopback_is_rejected(self):
        data = _arc_fixture()
        data["scenes"][-1]["caption"] = "Cities glow brighter during quiet winter festivals worldwide."
        valid, issues = self._validated(data)
        self.assertFalse(valid)
        self.assertTrue(any("LOOP-BACK" in issue for issue in issues), issues)

    def test_content_concepts_fold_plurals_and_drop_stopwords(self):
        concepts = self.sg._content_concepts("Your brain saves the memories")
        self.assertIn("brain", concepts)
        self.assertIn("memorie", concepts)
        self.assertNotIn("your", concepts)


class FacebookSafetyTests(unittest.TestCase):
    """Meta demotes engagement-bait captions — a YouTube-style
    'like/share/subscribe' CTA must never reach the Facebook caption."""

    def test_bait_cta_is_replaced(self):
        uploader = pytestless_import("uploader")
        caption = uploader._build_facebook_description(
            {"hook": "Your knee cracks loudly.",
             "summary": "Why joints pop, explained simply.",
             "cta": "Like, share and subscribe!"},
            ["kneecracking", "bodyscience"],
        )
        lowered = caption.lower()
        self.assertNotIn("subscribe", lowered)
        self.assertNotIn("share", lowered)
        self.assertNotIn("like,", lowered)
        self.assertIn("follow", lowered)


if __name__ == "__main__":
    unittest.main()


class DescriptionSeoTests(unittest.TestCase):
    """Live audit of the MrNextep channel (2026-07-27) found two SEO faults
    in every published description."""

    def setUp(self):
        try:
            from seo_generator import generate_description, _normalise_tags
        except ModuleNotFoundError as exc:
            self.skipTest(f"deps not installed here: {exc}")
        self.build = generate_description
        self.normalise = _normalise_tags

    def _desc(self, tags):
        return self.build(
            {"hook": "Your calf locks up.",
             "summary": "Learn what causes sudden calf cramps at night.",
             "topic": "why calf muscles cramp at night", "category": "Body"},
            tags,
        )

    def test_hashtags_never_contain_spaces(self):
        """'#brain facts' is parsed by YouTube as '#brain' plus a loose word,
        so the intended hashtag never existed."""

        desc = self._desc(["brain facts", "body science", "neuroscience"])
        block = [ln for ln in desc.splitlines() if ln.strip().startswith("#")]
        self.assertTrue(block, desc)
        for line in block:
            for token in line.split():
                self.assertTrue(token.startswith("#"), f"loose word in {line!r}")
                self.assertNotIn(" ", token)

    def test_multiword_tags_become_single_hashtags(self):
        desc = self._desc(["brain facts", "body science"])
        self.assertIn("#BrainFacts", desc)
        self.assertIn("#BodyScience", desc)

    def test_filler_words_never_reach_the_description(self):
        """Published live: '...neuroscience, having.' and '...sudden, charley.'"""
        for junk in ("having", "charley", "sudden"):
            desc = self._desc(["human body", "body science", junk])
            context = [ln for ln in desc.splitlines()
                       if ln.startswith("Learn the science behind")]
            self.assertTrue(context)
            self.assertNotIn(junk, context[0].lower(), context[0])

    def test_normalise_tags_drops_short_and_stop_words(self):
        self.assertEqual(self.normalise(["ok", "having", "brain facts"], 4),
                         ["brain facts"])


class HashtagIdempotencyTests(unittest.TestCase):
    """as_hashtag() used .title(), which lowercases everything after the
    first letter — so an already-correct '#BrainFacts' became '#Brainfacts'
    on the next pass. The sweep then rewrote all 83 videos on every run,
    burning quota and never converging."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import us_seo_sweep
        self.sweep = us_seo_sweep

    def test_as_hashtag_is_stable(self):
        for word in ("brain facts", "BrainFacts", "human body", "HumanBody"):
            once = self.sweep.as_hashtag(word)
            twice = self.sweep.as_hashtag(once)
            self.assertEqual(once, twice, word)

    def test_multiword_capitalisation_is_preserved(self):
        self.assertEqual(self.sweep.as_hashtag("brain facts"), "BrainFacts")
        self.assertEqual(self.sweep.as_hashtag("BrainFacts"), "BrainFacts")

    def test_clean_description_is_left_untouched(self):
        """Feed the sweep its OWN output; a second pass must be a no-op.
        (Built by running the sweep once rather than hand-writing the
        expected closing line, which now rotates by topic hash.)"""
        raw = ("Hook.\n\nSummary line.\n\n"
               "Learn the science behind brain facts, brain science. Old CTA.\n\n"
               "#Shorts #BrainFacts #BrainScience")
        once, _ = self.sweep.fix_description(raw)
        twice, _ = self.sweep.fix_description(once)
        self.assertEqual(once, twice)


class AnalyticsLoopTests(unittest.TestCase):
    """The analytics workflow reported SUCCESS for four consecutive days
    while every single video failed with invalid_scope, leaving
    data/video_history.json with 0 real view counts out of 17 entries."""

    def test_credentials_do_not_pin_scopes_on_refresh(self):
        """google-auth sends a `scope` field when scopes= is set, and Google
        rejects any refresh that alters a token's scopes."""
        import re
        source = (ROOT / "src" / "seo_analytics.py").read_text()
        block = re.search(r"google\.oauth2\.credentials\.Credentials\((.*?)\n    \)",
                          source, re.S)
        self.assertIsNotNone(block, "Credentials(...) call not found")
        self.assertNotIn("scopes=", block.group(1))

    def test_unsupported_metrics_are_dropped_not_fatal(self):
        source = (ROOT / "src" / "seo_analytics.py").read_text()
        self.assertIn("Unknown identifier", source)

    def test_disabled_api_is_reported_distinctly(self):
        """403 'API has not been used in project N' is a Google Cloud console
        setting, not a scope or token problem. Blaming the scope sent the
        previous debugging round down the wrong path."""
        source = (ROOT / "src" / "seo_analytics.py").read_text()
        self.assertIn("analytics_api_disabled", source)
        self.assertIn("has not been used in project", source)

    def test_entries_are_not_frozen_by_a_null_ctr(self):
        """Refresh must key off analytics_fetched_at, not the mere presence
        of an 'actual_ctr' key (which is written as None on channels that do
        not serve CTR)."""
        source = (ROOT / "src" / "seo_analytics.py").read_text()
        self.assertNotIn('"actual_ctr" in entry', source)
        self.assertIn("analytics_fetched_at", source)

    def test_runner_exits_nonzero_when_nothing_was_written(self):
        """A broken feedback loop must be visible in the Actions tab.

        Every per-video error is caught and logged as a warning, so this
        runner once exited 0 while all 17 videos failed with invalid_scope —
        four consecutive green ticks over an empty history file.

        This asserts the actual exit codes by running the module, rather than
        grepping for the string "sys.exit(1)". The grep version broke on a
        refactor that kept the behaviour identical (the code now assigns an
        exit_code and exits once at the end), which is a test reporting on
        source layout instead of on what the program does.
        """
        import subprocess
        import tempfile

        script = ROOT / "src" / "analytics_updater.py"

        def run(history_payload: str, extra_env: dict) -> int:
            with tempfile.TemporaryDirectory() as tmp:
                history = Path(tmp) / "history.json"
                history.write_text(history_payload, encoding="utf-8")
                env = {
                    **os.environ,
                    "VIDEO_HISTORY_PATH": str(history),
                    "PLATFORM_METRICS_PATH": str(Path(tmp) / "metrics.json"),
                    "GROWTH_STATE_PATH": str(Path(tmp) / "growth.json"),
                    **extra_env,
                }
                # Strip credentials so the fetch fails deterministically.
                for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "REFRESH_TOKEN"):
                    env.pop(key, None)
                return subprocess.run(
                    [sys.executable, str(script)], env=env,
                    capture_output=True, text=True, timeout=120,
                ).returncode

        # One mature video whose fetch cannot succeed -> failed, nothing
        # written -> must exit non-zero.
        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        payload = json.dumps([{
            "content_fingerprint": "abc", "title": "t", "topic": "eye twitch",
            "youtube_video_id": "vid123", "posted_at": old,
        }])
        self.assertNotEqual(run(payload, {}), 0,
                            "a totally failed sync reported success")

        # Nothing to sync at all is not a failure — an empty channel must not
        # produce a red workflow every morning.
        self.assertEqual(run("[]", {}), 0,
                         "an empty history should not fail the run")

    def test_history_write_is_atomic(self):
        source = (ROOT / "src" / "seo_analytics.py").read_text()
        self.assertIn("os.replace(tmp, HISTORY_FILE)", source)


class DescriptionVarietyTests(unittest.TestCase):
    """All 83 published videos carried the identical closing sentence
    "Follow for clear science and brain facts explained simply." — byte for
    byte. Identical boilerplate across a whole channel is a templated-content
    signal and wastes the one line a viewer may actually read."""

    def setUp(self):
        try:
            from seo_generator import generate_description
        except ModuleNotFoundError as exc:
            self.skipTest(f"deps not installed here: {exc}")
        self.build = generate_description

    def _closing(self, tags):
        desc = self.build({"hook": "H.", "summary": "S.", "topic": "t",
                           "category": "Brain"}, tags)
        line = [l for l in desc.split("\n")
                if l.startswith("Learn the science behind")]
        return line[0] if line else ""

    def test_closing_line_varies_across_topics(self):
        seen = {self._closing(t) for t in (
            ["brain facts", "neuroscience"],
            ["human body", "muscle"],
            ["sleep science", "dreams"],
            ["gut health", "digestion"],
        )}
        self.assertGreater(len(seen), 1, "every video would share one CTA")

    def test_closing_line_is_stable_for_the_same_topic(self):
        """Must be deterministic or the repair sweep rewrites forever."""
        first = self._closing(["brain facts", "neuroscience"])
        second = self._closing(["brain facts", "neuroscience"])
        self.assertEqual(first, second)

    def test_old_hardcoded_cta_is_gone(self):
        source = (ROOT / "src" / "seo_generator.py").read_text()
        self.assertNotIn(
            '"Follow for clear science and brain facts explained simply."',
            source)


class SweepIdempotencyTests(unittest.TestCase):
    """The sweep must converge — a non-idempotent sweep rewrites all 83
    videos on every run, burning quota and republishing for nothing."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import us_seo_sweep
        self.sweep = us_seo_sweep

    def test_second_pass_changes_nothing(self):
        raw = ("You're stuck on it.\n\nSummary.\n\n"
               "Learn the science behind brain facts, brain science, having. "
               "Follow for clear science and brain facts explained simply.\n\n"
               "#Shorts #brain facts #brain science")
        once, _ = self.sweep.fix_description(raw)
        twice, _ = self.sweep.fix_description(once)
        self.assertEqual(once, twice)

    def test_closing_line_rotates_but_is_deterministic(self):
        raw = ("H.\n\nS.\n\nLearn the science behind human body, muscle. Old.\n\n"
               "#Shorts #HumanBody")
        first, _ = self.sweep.fix_description(raw)
        second, _ = self.sweep.fix_description(raw)
        self.assertEqual(first, second)


class FacebookPaginationTests(unittest.TestCase):
    """The Page has 80 Reels but every tune-up pass fetched with a bare
    limit=50, so the 30 oldest were never seen. Combined with the 34 entries
    already in fb_thumbs_done.json, the cover pass had 16 candidates left and
    reported "no reel matched a cover" — while the audit taken seven minutes
    later still found 46 Reels with no cover and 58 with no title. Re-running
    could never have reached them."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        os.environ.setdefault("FB_ACCESS_TOKEN", "test")
        os.environ.setdefault("FB_PAGE_ID", "test")
        import fb_page_tuneup
        self.fb = fb_page_tuneup

    def test_all_reel_passes_use_the_paginating_fetch(self):
        source = (ROOT / "scripts" / "fb_page_tuneup.py").read_text()
        # captions, titles and thumbnails must all page
        self.assertEqual(source.count('gget_all(f"{PAGE}/video_reels"'), 3)
        self.assertNotIn('gget(f"{PAGE}/video_reels"', source)

    def test_pagination_follows_next_cursor(self):
        import json as _json
        import urllib.request
        pages = [
            {"data": [{"id": str(i)} for i in range(50)],
             "paging": {"next": "http://example/2"}},
            {"data": [{"id": str(i)} for i in range(50, 80)]},
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = _json.dumps(payload).encode()

            def read(self):
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        original_get, original_open, original_pace = (
            self.fb.gget, urllib.request.urlopen, self.fb.PACE)
        try:
            self.fb.gget = lambda path, **kw: pages[0]
            urllib.request.urlopen = lambda url, timeout=45: FakeResponse(pages[1])
            self.fb.PACE = 0
            result = self.fb.gget_all("page/video_reels", limit=50)
        finally:
            self.fb.gget, urllib.request.urlopen, self.fb.PACE = (
                original_get, original_open, original_pace)
        self.assertEqual(len(result["data"]), 80)

    def test_first_page_error_is_returned_not_swallowed(self):
        original = self.fb.gget
        try:
            self.fb.gget = lambda path, **kw: {"error": 400, "body": "bad"}
            result = self.fb.gget_all("page/video_reels", limit=50)
        finally:
            self.fb.gget = original
        self.assertIsNone(result.get("data"))


class FacebookCoverMatchTests(unittest.TestCase):
    """Date-order cover matching accepted overlap>=3 / score>=0.25. Checked
    against the live Page: all 24 proposed covers scored 0.25-0.37, and reel
    "Attachment Theory in 60 Seconds" was paired with the YouTube video
    "The Brain Hack hiding in your Dizziness" — unrelated topics that shared
    filler words and sat near each other in time. A wrong cover misrepresents
    the video to every viewer, so it is worse than no cover."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        os.environ.setdefault("FB_ACCESS_TOKEN", "test")
        os.environ.setdefault("FB_PAGE_ID", "test")
        import fb_page_tuneup
        self.fb = fb_page_tuneup

    def _match(self, reel_words, video_words, hours_apart=1):
        reel = {"created_time": "2026-07-20T12:00:00+0000",
                "description": " ".join(reel_words)}
        base = self.fb._iso_ts("2026-07-20T12:00:00+0000") - hours_apart * 3600
        vids = [(base, "vid123", {"words": set(video_words)})]
        return self.fb._ordered_match(reel, vids, 0)

    def test_weak_overlap_is_rejected(self):
        # 3 shared filler-ish words — the shape that produced the bad pairing
        ytid, _, score = self._match(
            ["attachment", "theory", "your", "brain", "wires", "itself"],
            {"your", "brain", "the"})
        self.assertIsNone(ytid, f"weak match accepted at score {score}")

    def test_strong_topical_overlap_is_accepted(self):
        ytid, _, score = self._match(
            ["your", "brain", "starts", "shrinking", "right", "now", "slowly"],
            {"your", "brain", "starts", "shrinking", "now", "slowly"})
        self.assertEqual(ytid, "vid123")
        self.assertGreaterEqual(score, 0.45)

    def test_threshold_is_documented_in_source(self):
        source = (ROOT / "scripts" / "fb_page_tuneup.py").read_text()
        self.assertIn("overlap >= 5 and score >= 0.45", source)


class PostingScheduleTests(unittest.TestCase):
    """Three videos a day at US peaks, on all three platforms.

    YouTube uses status.publishAt and Facebook uses scheduled_publish_time,
    but the Instagram Graph API has NO scheduling parameter on media_publish
    — so every Reel went live the moment generation finished (~10:38 / 18:08
    / 19:38 NY), never at a peak. This channel's own 15 videos show 12:00 NY
    averaging 833 views and 20:00 averaging 730, against 50-79 for the
    06:00-09:00 band."""

    def setUp(self):
        try:
            from scheduler import USAPeakTimeScheduler
        except ModuleNotFoundError as exc:
            self.skipTest(f"deps not installed here: {exc}")
        self.sched = USAPeakTimeScheduler()

    def test_exactly_three_daily_peak_slots(self):
        self.assertEqual(len(self.sched.PEAK_TIMES), 3)

    def test_slots_match_the_measured_winners(self):
        slots = {(s["hour"], s["minute"]) for s in self.sched.PEAK_TIMES}
        self.assertIn((12, 30), slots)   # channel avg 719 [830, 988, 339]
        self.assertIn((20, 0), slots)    # channel avg 519 [664, 795, 98]

    def test_every_slot_sits_in_a_consensus_window(self):
        """Five independent 2026 studies of US Shorts (iqfluence n=325,
        miraflow, socialrails, mediamister, sellerpic) all name 12-2 PM and
        6-9 PM ET. The retired 21:30 slot sat outside both."""
        for slot in self.sched.PEAK_TIMES:
            minutes = slot["hour"] * 60 + slot["minute"]
            in_lunch = 12 * 60 <= minutes <= 14 * 60
            in_evening = 18 * 60 <= minutes <= 21 * 60
            self.assertTrue(
                in_lunch or in_evening,
                f"{slot['hour']:02d}:{slot['minute']:02d} is outside 12-2 PM and 6-9 PM ET",
            )

    def test_retired_weak_slot_is_gone(self):
        """21:30 averaged 117 views on this channel [107, 127] and competed
        with the 20:00 upload 90 minutes earlier."""
        slots = {(s["hour"], s["minute"]) for s in self.sched.PEAK_TIMES}
        self.assertNotIn((21, 30), slots)

    def test_crons_match_the_slot_count(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text()
        self.assertEqual(workflow.count("- cron:"), len(self.sched.PEAK_TIMES))

    def test_slots_are_at_least_90_minutes_apart(self):
        mins = sorted(s["hour"] * 60 + s["minute"] for s in self.sched.PEAK_TIMES)
        for earlier, later in zip(mins, mins[1:]):
            self.assertGreaterEqual(later - earlier, 90)

    def test_instagram_waits_for_the_slot(self):
        source = (ROOT / "src" / "uploader.py").read_text()
        self.assertIn("_wait_for_instagram_slot", source)
        self.assertIn("IG_MAX_WAIT_MINUTES", source)

    def test_instagram_wait_is_bounded(self):
        """An unbounded wait would hang the runner."""
        import uploader
        slept = []
        original = uploader.time.sleep
        try:
            uploader.time.sleep = lambda s: slept.append(s)
            os.environ["IG_WAIT_FOR_SLOT"] = "true"
            os.environ["IG_MAX_WAIT_MINUTES"] = "1"
            uploader._wait_for_instagram_slot()
        finally:
            uploader.time.sleep = original
            os.environ.pop("IG_MAX_WAIT_MINUTES", None)
        self.assertEqual(slept, [], "wait exceeded its own cap")

    def test_job_timeout_covers_the_instagram_hold(self):
        """8 min generation + a 112 min hold sat exactly on the old 120 limit."""
        import re
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text()
        timeout = int(re.search(r"timeout-minutes:\s*(\d+)", workflow).group(1))
        cap = int(re.search(r'IG_MAX_WAIT_MINUTES:\s*"(\d+)"', workflow).group(1))
        self.assertGreater(timeout, cap + 30,
                           "job would be killed mid-hold")

    def test_three_crons_scheduled(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text()
        self.assertEqual(workflow.count("- cron:"), 3)


class FacebookCoverMapTests(unittest.TestCase):
    """32 Reels had no cover. The date-order guesser could not fill them
    safely (it once paired "Attachment Theory" with "Dizziness"), so 9 were
    matched exactly by comparing each Reel's opening line to the pipeline's
    own recorded voiceover, and stored as a verified map."""

    def setUp(self):
        self.map_path = ROOT / "data" / "fb_cover_map.json"
        if not self.map_path.exists():
            self.skipTest("cover map not present")
        self.cover_map = json.loads(self.map_path.read_text())

    def test_every_mapped_reel_has_its_cover_file(self):
        for reel_id, youtube_id in self.cover_map.items():
            cover = ROOT / "assets" / "thumbnails_us" / f"{youtube_id}.jpg"
            self.assertTrue(cover.is_file(), f"{reel_id} -> {youtube_id}.jpg missing")

    def test_covers_are_valid_jpeg_under_the_api_limit(self):
        for youtube_id in set(self.cover_map.values()):
            cover = ROOT / "assets" / "thumbnails_us" / f"{youtube_id}.jpg"
            data = cover.read_bytes()
            self.assertEqual(data[:3], b"\xff\xd8\xff", f"{youtube_id} not JPEG")
            self.assertLess(len(data), 2 * 1024 * 1024, f"{youtube_id} over 2MB")

    def test_no_youtube_id_is_reused_for_two_reels(self):
        values = list(self.cover_map.values())
        self.assertEqual(len(values), len(set(values)),
                         "one cover assigned to multiple Reels")

    def test_tuneup_prefers_the_verified_map(self):
        source = (ROOT / "scripts" / "fb_page_tuneup.py").read_text()
        self.assertIn("fb_cover_map.json", source)
        self.assertIn("verified-map", source)
        # the map must be consulted BEFORE the guesser
        self.assertLess(source.index('cover_map.get(reel["id"])'),
                        source.index('via = f"date-order'))


class FacebookTitleVerificationTests(unittest.TestCase):
    """The tune-up reported 63 Reel titles "ok". Reading the Reels straight
    back from Graph showed only 3 actually carrying a title — the 3 newest,
    posted by the current pipeline, which sets the title at upload time.
    Graph returns {"success": true} while silently discarding a retro-fitted
    title on older Reels, so the report was confidently wrong."""

    def setUp(self):
        self.source = (ROOT / "scripts" / "fb_page_tuneup.py").read_text()

    def test_title_write_is_verified_by_read_back(self):
        self.assertIn('check = gget(reel["id"], fields="title")', self.source)

    def test_silently_dropped_titles_are_reported_distinctly(self):
        self.assertIn("ignored-by-api", self.source)

    def test_success_is_not_assumed_from_the_response_alone(self):
        # the old shape trusted the absence of an error key
        self.assertNotIn('note("reel titles", "ok" if "error" not in res',
                         self.source)
