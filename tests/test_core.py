"""Fast, offline regression tests for the production-critical content rules."""
import sys
import unittest
from pathlib import Path

# Tests are run from the repository root in GitHub Actions; source modules
# live in src/ rather than the root package.
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from script_generator import _normalize_scenes, validate_script  # noqa: E402
from seo_generator import generate_seo_package  # noqa: E402
from shorts_enhancer import check_caption_pacing, score_hook  # noqa: E402
from trend_fetcher import (  # noqa: E402
    _deduplicate, _is_relevant, get_body_glitch_topics, get_dark_mystery_topics,
)


class ScriptPolicyTests(unittest.TestCase):
    def setUp(self):
        self.script = _normalize_scenes({
            "title": "Why Sleep Helps Your Brain",
            "thumbnail_text": "Memory Reset",
            "hook": "Your brain saves memories while sleeping.",
            "cta": "Follow for more science made simple.",
            "description": "Sleep helps your brain strengthen important memories.",
            "scenes": [
                {"visual": "glowing brain during deep sleep", "caption": "Your brain saves memories while sleeping."},
                {"visual": "memory signals moving through neurons", "caption": "How does it choose which moments stay?"},
                {"visual": "student studying in a quiet room", "caption": "Without sleep, facts feel clear now but vanish tomorrow."},
                {"visual": "brain pathways strengthening overnight", "caption": "Deep sleep replays the day and keeps what matters."},
                {"visual": "calm sleeper with brain overlay", "caption": "It links ideas, making recall easier later."},
                {"visual": "memory pathway becoming brighter", "caption": "That is why rest steadies your learning."},
                {"visual": "organized notes beside sleeping person", "caption": "Sleep gives the brain time to organize."},
                {"visual": "morning light over focused person", "caption": "Which is why your brain saves memories while sleeping."},
            ],
        })

    def test_script_matches_the_unified_short_policy(self):
        # UPDATED 2026-08-14: YT master ideal moved 33s -> 24s (million-views
        # pass), so the valid script ceiling is now ~79 words at 2.62 w/s and
        # non-hook scenes cap at 10 words. The fixture was trimmed in setUp to
        # match; it guards the CURRENT policy, not the retired 33s one.
        valid, issues = validate_script(self.script)
        self.assertTrue(valid, issues)
        words = len(self.script["voiceover"].split())
        self.assertGreaterEqual(words, 55)
        self.assertLessEqual(words, 79)
        self.assertEqual(len(self.script["scenes"]), 8)

    def test_hook_passes_natural_hook_gate(self):
        self.assertGreaterEqual(score_hook(self.script)["score"], 70)

    def test_body_glitch_series_does_not_reject_temporary_six_word_title(self):
        import os
        old_series = os.environ.get("CONTENT_SERIES")
        os.environ["CONTENT_SERIES"] = "body_glitches"
        try:
            altered = dict(self.script)
            altered["title"] = "Why Your Eye Twitches At Night"
            valid, issues = validate_script(altered)
            self.assertTrue(valid, issues)
        finally:
            if old_series is None:
                os.environ.pop("CONTENT_SERIES", None)
            else:
                os.environ["CONTENT_SERIES"] = old_series

    def test_natural_caption_delivery_is_not_rejected_at_3_point_5_wps(self):
        scenes = [{"caption": "Your brain saves important memories while you sleep every single night without conscious effort."}]
        segments = [{"duration": 3.5}]
        report = check_caption_pacing(scenes, segments)
        self.assertTrue(report["all_readable"], report["issues"])


class SeoPolicyTests(unittest.TestCase):
    def test_titles_tags_and_thumbnail_are_topic_specific(self):
        script = {
            "title": "Why Sleep Helps Your Brain",
            "thumbnail_text": "Memory Reset",
            "hook": "Your brain saves memories while sleeping.",
            "cta": "Follow for more science made simple.",
            "description": "Sleep helps your brain strengthen important memories.",
            "summary": "Sleep helps your brain strengthen important memories.",
        }
        package = generate_seo_package("How sleep helps your brain make memories", script)
        self.assertTrue(all(len(title.split()) <= 8 for title in package["title_options"]))
        self.assertEqual(package["thumbnail_text"], "MEMORY RESET")
        self.assertNotIn("helps", [tag.lower() for tag in package["tags"]])
        self.assertEqual(
            [tag.lower() for tag in package["hashtags"]],
            ["#sleepscience", "#sleepandmemory", "#memoryformation"],
        )


class TrendSafetyTests(unittest.TestCase):
    def test_irrelevant_football_hearts_title_is_not_body_science(self):
        self.assertFalse(_is_relevant("Hearts - Rayo Vallecano"))
        self.assertTrue(_is_relevant("NASA releases a new space image"))

    def test_topic_deduplication_ignores_case_and_punctuation(self):
        records = _deduplicate([
            {"topic": "Brain Science"},
            {"topic": "brain-science"},
        ])
        self.assertEqual(len(records), 1)

    def test_body_glitch_catalogue_has_500_branded_topics(self):
        records = get_body_glitch_topics()
        self.assertGreaterEqual(len(records), 500)
        self.assertEqual(records[0]["series_title"], "Eye Twitch 👁️")
        self.assertTrue(all(record["source"] == "body_glitch_series" for record in records))

    def test_dark_mystery_catalogue_has_500_branded_topics(self):
        """The pivot series must be launch-ready at 500 unique topics, all
        tagged as dark_mystery, and every topic must be a valid curiosity hook
        the medical-accuracy gate will accept (real phenomena, no invented
        cures or panic)."""
        records = get_dark_mystery_topics()
        self.assertGreaterEqual(len(records), 500)
        topics = {r["topic"] for r in records}
        self.assertEqual(len(topics), len(records), "topics must be unique")
        self.assertTrue(all(r["source"] == "dark_mystery_series" for r in records))
        self.assertTrue(all(r["pillar"] == "dark_mystery" for r in records))
        # Every record must carry the hook metadata the pipeline consumes.
        for r in records:
            self.assertTrue(r.get("angle"))
            self.assertTrue(r.get("series_title"))
            self.assertTrue(r.get("thumbnail_text"))
        # Series numbers must be a clean 1..N sequence for episode labelling.
        self.assertEqual([r["series_number"] for r in records],
                         list(range(1, len(records) + 1)))

    def test_dark_mystery_prompt_mode_is_live(self):
        """When CONTENT_SERIES=dark_mystery the writer must emit the dark
        mystery ruleset (curiosity/tension framing, no gore, no fake cures)."""
        import script_generator
        src = __import__("inspect").getsource(script_generator._default_prompt)
        self.assertIn("dark_mystery_mode", src)
        self.assertIn("DARK MYSTERY & MIND-BENDING FACTS SERIES RULES", src)


if __name__ == "__main__":
    unittest.main()


class LLMFallbackTests(unittest.TestCase):
    def test_openrouter_fallback_graceful_without_key(self):
        import script_generator, os
        old = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            r = script_generator._openrouter_generate(
                [{"role": "user", "content": "hi"}])
            self.assertIsNone(r)  # no key -> None, never raises
        finally:
            if old is not None:
                os.environ["OPENROUTER_API_KEY"] = old

    def test_openrouter_fallback_is_wired_in_generate(self):
        import script_generator
        src = script_generator.__file__
        code = open(src, encoding="utf-8").read()
        self.assertIn("_openrouter_generate", code)
        self.assertIn("OPENROUTER_API_KEY", code)
