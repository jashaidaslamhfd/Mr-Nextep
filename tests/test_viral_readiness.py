"""Offline tests for the viral-readiness scorecard (src/viral_readiness.py)."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from viral_readiness import readiness_scorecard, summary  # noqa: E402


class ReadinessTests(unittest.TestCase):
    def test_returns_score_and_rating(self):
        c = readiness_scorecard()
        self.assertIn("score", c)
        self.assertIn("rating", c)
        self.assertGreaterEqual(c["score"], 0)
        self.assertLessEqual(c["score"], 100)
        self.assertIn(c["rating"], ("EXCELLENT", "STRONG", "MODERATE", "WEAK"))

    def test_has_all_levers(self):
        c = readiness_scorecard()
        names = [lv["name"] for lv in c["checks"]]
        self.assertIn("First-frame hook TEXT overlay", names)
        self.assertIn("Duplicate prevention", names)
        self.assertIn("CTR & Retention ML training", names)

    def test_summary_returns_string(self):
        s = summary()
        self.assertIsInstance(s, str)
        self.assertIn("Viral readiness", s)


if __name__ == "__main__":
    unittest.main()
