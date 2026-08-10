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


if __name__ == "__main__":
    unittest.main()
