"""Offline tests for the high-CTR title engine (src/ctr_engine.py)."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from ctr_engine import (  # noqa: E402
    generate_high_ctr_title,
    generate_ctr_hook_line,
    strip_bait,
    validate_title,
)


class TitleGenerationTests(unittest.TestCase):
    def test_returns_nonempty_under_budget(self):
        for topic in [
            "feeling like hours passed in minutes",
            "Why Your Body Does This: Memory Boost",
            "Sleep Paralysis",
            "your eyes twitching out of nowhere",
        ]:
            title = generate_high_ctr_title(topic, platform="youtube")
            self.assertTrue(title.strip())
            self.assertLessEqual(len(title), 58)

    def test_contains_curiosity_power_word(self):
        title = generate_high_ctr_title("Sleep Paralysis")
        lowered = title.lower()
        self.assertTrue(
            any(w in lowered for w in ("why", "real", "truth", "secret", "hidden")),
            f"title lacks a CTR power word: {title}",
        )

    def test_no_engagement_bait(self):
        for topic in [
            "why your body twitches", "the reason you blush",
            "your eyes twitching out of nowhere",
        ]:
            title = generate_high_ctr_title(topic)
            lowered = title.lower()
            for bait in ("subscribe", "smash like", "tag someone", "hit the bell"):
                self.assertNotIn(bait, lowered)

    def test_no_duplicate_your_why(self):
        for topic in [
            "why your body freezes when scared",
            "your eyes twitching out of nowhere",
            "Why Your Body Does This: Memory Boost",
        ]:
            title = generate_high_ctr_title(topic).lower()
            self.assertNotIn("your your", title)
            self.assertNotIn("why why", title)

    def test_platform_budget_differs(self):
        yt = generate_high_ctr_title("Sleep Paralysis", platform="youtube")
        self.assertLessEqual(len(yt), 58)


class HookAndValidationTests(unittest.TestCase):
    def test_hook_line_is_nonempty_and_bait_free(self):
        hook = generate_ctr_hook_line("Sleep Paralysis")
        self.assertTrue(hook.strip())
        self.assertNotIn("subscribe", hook.lower())

    def test_strip_bait_removes_engagement_phrases(self):
        cleaned = strip_bait("Watch now and subscribe for more body science!")
        self.assertNotIn("subscribe", cleaned.lower())

    def test_validate_flags_weak_title(self):
        bad = validate_title("Fun facts", max_chars=60)
        self.assertFalse(bad["ok"])
        self.assertTrue(bad["issues"])

    def test_validate_passes_strong_title(self):
        good = validate_title("Why Your Hours Feel Like Minutes", max_chars=60)
        self.assertTrue(good["ok"])

    def test_gibberish_head_is_rejected(self):
        # 2026-08-15 title-quality fix: malformed topic inputs that reduce to
        # junk subjects must never validate, even when a category word like
        # "science"/"brain" appears in them.
        for junk in [
            "Why Your Funny Video Science — The Surprising Truth",
            "Why Your Regression Mean Brain — The Real Reason",
            "Why Get Funny Videos From Happens — The Real Reason",
        ]:
            result = validate_title(junk)
            self.assertFalse(result["ok"], f"gibberish title passed: {junk}")
            self.assertTrue(any("gibberish" in i for i in result["issues"]),
                            f"expected gibberish guard issue: {result}")

    def test_valid_titles_with_real_anchors_pass(self):
        for title in [
            "Why Your Cold Hands — The Real Reason",
            "Why Your Brain Rewrites Bad Day — What Your Brain Is Doing",
            "Why Your Body Jerks Sleep — Why It Actually Happens",
        ]:
            result = validate_title(title)
            self.assertTrue(result["ok"],
                            f"valid title rejected: {title} {result['issues']}")

    def test_malformed_topic_falls_back_to_grammatical_title(self):
        # A malformed topic must never surface as a "Why Your {junk}" title.
        for junk_topic in [
            "Funny Video Science",
            "Regression Mean Brain",
            "Why a 'Funny' Video Is Science",
        ]:
            title = generate_high_ctr_title(junk_topic).lower()
            for junk in ("why your funny", "regression mean", "funny video",
                         "why your regression"):
                self.assertNotIn(junk, title)
            # The fallback stays under the platform budget.
            self.assertLessEqual(len(generate_high_ctr_title(junk_topic)), 58)


if __name__ == "__main__":
    unittest.main()
