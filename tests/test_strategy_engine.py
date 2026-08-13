"""Offline tests for the Autonomous Strategy Engine (src/strategy_engine.py).

These feed the pure decision core synthetic state so they are fully offline,
fast and deterministic — no network, no real data files.
"""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from strategy_engine import (  # noqa: E402
    decide_from_state,
    ml_lever_analysis,
    SERIES_STRATEGY,
    SUPPORTED_SERIES,
)


def _features(avg_comp=0.4, n=12):
    """Synthetic per-video features with a positive views signal."""
    return [
        {
            "views": 100 + i * 50,
            "completion": avg_comp + 0.01 * (i % 3),
            "hook_score": 60 + (i % 5) * 5,
            "predicted_ctr": 3 + (i % 4),
            "seo_score": 60 + (i % 3) * 10,
            "duration_seconds": 36,
            "predicted_retention": avg_comp,
        }
        for i in range(n)
    ]


class DecideCoreTests(unittest.TestCase):
    def test_completion_barrier_is_detected_and_sets_cadence_to_1(self):
        decision = decide_from_state(
            platform_health={"youtube_shorts": {"gate": 0.5, "gate_ratio": 0.3}},
            video_features=_features(avg_comp=0.2),
            slot_weights={"20:00": 1.2, "12:30": 0.8},
        )
        self.assertEqual(decision["barrier"], "completion")
        self.assertEqual(decision["cadence"], 1)  # quality over volume

    def test_healthy_volume_increases_cadence_to_3(self):
        decision = decide_from_state(
            platform_health={"youtube_shorts": {"gate": 0.5, "gate_ratio": 0.9}},
            video_features=_features(avg_comp=0.6),
        )
        self.assertEqual(decision["barrier"], "volume")
        self.assertEqual(decision["cadence"], 3)

    def test_best_slot_is_the_highest_weight(self):
        decision = decide_from_state(
            platform_health={},
            video_features=_features(),
            slot_weights={"20:00": 1.5, "12:30": 0.9, "18:30": 1.1},
        )
        self.assertEqual(decision["best_slot"], "20:00")

    def test_no_data_returns_sane_defaults_without_raising(self):
        decision = decide_from_state(platform_health={}, video_features=[])
        self.assertIn(decision["recommended_series"], SUPPORTED_SERIES)
        self.assertIn(decision["topic_strategy"], SERIES_STRATEGY.values())
        self.assertIn(decision["quality_threshold"], (60, 55, 65, 70))

    def test_series_weights_respect_learned_history(self):
        decision = decide_from_state(
            platform_health={},
            video_features=_features(),
            series_history={
                "dark_mystery": {"avg_completion": 0.8, "samples": 10},
                "body_glitches": {"avg_completion": 0.3, "samples": 10},
            },
        )
        self.assertEqual(decision["recommended_series"], "dark_mystery")
        self.assertGreater(
            decision["series_weights"]["dark_mystery"],
            decision["series_weights"]["body_glitches"],
        )


class MLLeverTests(unittest.TestCase):
    def test_neutral_fallback_when_too_few_samples(self):
        result = ml_lever_analysis(_features(n=3))
        self.assertFalse(result["trained"])
        self.assertEqual(len(result["lever_importance"]), 3)

    def test_trains_and_returns_ranked_levers(self):
        result = ml_lever_analysis(_features(n=20))
        self.assertTrue(result["trained"])
        self.assertGreaterEqual(result["sample_size"], 8)
        self.assertGreaterEqual(len(result["lever_importance"]), 5)
        # Importance values are normalised shares that sum to ~1.
        shares = [item["share"] for item in result["lever_importance"]]
        self.assertAlmostEqual(sum(shares), 1.0, places=2)

    def test_never_raises_on_empty_input(self):
        result = ml_lever_analysis([])
        self.assertFalse(result["trained"])
        self.assertEqual(result["sample_size"], 0)


if __name__ == "__main__":
    unittest.main()
