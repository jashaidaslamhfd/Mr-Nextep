"""Offline tests for the humanizer natural-variation layer (src/humanizer.py)."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from humanizer import (  # noqa: E402
    seed_for, pick, pick_n, style_suffix, rotate_hashtags, opener,
    tempo_jitter, natural_ellipsis,
)


class DeterminismTests(unittest.TestCase):
    def test_seed_is_stable_and_varies(self):
        self.assertEqual(seed_for("Sleep Paralysis"), seed_for("Sleep Paralysis"))
        self.assertNotEqual(seed_for("Sleep Paralysis"), seed_for("Deja Vu"))

    def test_pick_is_stable(self):
        pool = ["a", "b", "c", "d"]
        self.assertEqual(pick(pool, "topic x"), pick(pool, "topic x"))

    def test_pick_n_returns_deterministic_subset(self):
        pool = list("abcdefghij")
        r1 = pick_n(pool, "topic", 4)
        r2 = pick_n(pool, "topic", 4)
        self.assertEqual(r1, r2)
        self.assertEqual(len(r1), 4)
        self.assertEqual(len(set(r1)), 4, "no duplicates")


class StyleTests(unittest.TestCase):
    def test_style_suffix_varies_by_topic_but_stable_per_topic(self):
        s1 = style_suffix("Sleep Paralysis")
        s2 = style_suffix("Sleep Paralysis")
        self.assertEqual(s1, s2)
        self.assertIn("vertical composition", s1)
        self.assertTrue(len(s1) > 20)
        # With a 6-entry style pool, different topics should land on a few
        # different styles rather than one fixed string.
        distinct = {style_suffix(t) for t in ["a", "b", "c", "d", "e", "f", "g"]}
        self.assertGreaterEqual(len(distinct), 2)

    def test_style_suffix_handles_first_frame(self):
        s = style_suffix("topic", first_frame=True)
        self.assertIn("vertical composition", s)


class HashtagRotationTests(unittest.TestCase):
    def test_rotation_keeps_anchors_and_is_deterministic(self):
        tags = list("abcdefghijkl")
        r1 = rotate_hashtags(tags, "topic", keep_top=3, total=8)
        r2 = rotate_hashtags(tags, "topic", keep_top=3, total=8)
        self.assertEqual(r1, r2)
        self.assertEqual(len(r1), 8)
        self.assertEqual(r1[:3], tags[:3], "anchors preserved")

    def test_rotation_varies_across_topics(self):
        tags = list("abcdefghijklmno")
        a = rotate_hashtags(tags, "topic A", keep_top=3, total=8)
        b = rotate_hashtags(tags, "topic B", keep_top=3, total=8)
        # Different topics should usually produce different orderings/subsets.
        self.assertNotEqual(a, b)


class MicroVariationTests(unittest.TestCase):
    def test_opener_returns_nonempty(self):
        self.assertTrue(opener("topic").strip())

    def test_tempo_jitter_stays_in_band(self):
        for topic in ["a", "b", "c"]:
            t = tempo_jitter(1.0, topic)
            self.assertGreaterEqual(t, 0.85)
            self.assertLessEqual(t, 1.15)

    def test_ellipsis_never_double(self):
        # ellipsis is applied ~1/3 of the time; assert it is 0 or 1, never >1.
        s = natural_ellipsis("This is a fairly long caption line worth reading", "seed")
        self.assertIn(s.count("…"), (0, 1))


if __name__ == "__main__":
    unittest.main()
