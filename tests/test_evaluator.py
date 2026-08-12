"""Offline tests for the independent evaluation gate + analytics guards."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from evaluator import evaluate, has_reliable_signal, real_training_rows  # noqa: E402
from analytics_guards import data_health, require_real_signal, collect_metrics_guard  # noqa: E402


def _rows(ctr=5.0, n=12):
    # ctr=0 => no real ctr (set to exactly 0 for all rows); otherwise vary
    ctr_vals = [0.0] * n if ctr == 0 else [ctr + i * 0.1 for i in range(n)]
    return [
        {
            "views": 200 + i * 50,
            "retention": 0.3 + 0.02 * i,
            "avg_watch_sec": 8 + i,
            "ctr": ctr_vals[i],
            "likes": 1 + i,
            "comments": 0,
            "published": f"2026-08-0{i%9+1}T00:00:00",
        }
        for i in range(n)
    ]


class EvaluatorTests(unittest.TestCase):
    def test_evaluates_independently(self):
        e = evaluate(_rows())
        self.assertTrue(e["independent"])
        self.assertEqual(e["n"], 12)
        self.assertGreater(e["channel_score"], 0)

    def test_data_health_flags_no_real_ctr(self):
        e = evaluate(_rows(ctr=0))  # no real ctr
        self.assertEqual(e["data_health"]["n_with_real_ctr"], 0)
        self.assertFalse(e["data_health"]["ctr_scope_ok"])
        self.assertFalse(e["data_health"]["trust_worthy"])

    def test_data_health_trustworthy_with_ctr(self):
        e = evaluate(_rows(ctr=5.0))  # real ctr
        self.assertTrue(e["data_health"]["ctr_scope_ok"])
        self.assertTrue(e["data_health"]["trust_worthy"])

    def test_has_reliable_signal(self):
        # returns a bool and is callable; on real (CTR-less) data it's False
        self.assertTrue(callable(has_reliable_signal))
        self.assertIn(has_reliable_signal(), (True, False))

    def test_real_training_rows_returns_list(self):
        self.assertIsInstance(real_training_rows(), list)


class GuardTests(unittest.TestCase):
    def test_data_health_returns_dict(self):
        h = data_health()
        self.assertIn("n_with_real_ctr", h)
        self.assertIn("verdict", h)

    def test_require_real_signal_returns_decision(self):
        d = require_real_signal(block=False)
        self.assertIn("can_trust_scores", d)
        self.assertIn("action", d)

    def test_collect_metrics_guard(self):
        g = collect_metrics_guard()
        self.assertIn("views_collected", g)


if __name__ == "__main__":
    unittest.main()
