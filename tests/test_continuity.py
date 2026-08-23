"""Offline tests for the continuity / slot-consistency layer."""
import os
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from continuity import (  # noqa: E402
    should_retry_on_guard_failure,
    clamp_cadence_3,
    is_us_peak_slot,
    register_slot_attempt,
    slot_consistency_status,
)


class ContinuityTests(unittest.TestCase):
    def test_guard_failure_is_retryable(self):
        self.assertTrue(should_retry_on_guard_failure(1))
        self.assertTrue(should_retry_on_guard_failure(2))
        self.assertFalse(should_retry_on_guard_failure(3))  # bounded

    def test_cadence_reaches_3_only_when_retention_earns_it(self):
        """Two healthy platforms = the 3/day production cadence is earned."""
        healthy = {
            "youtube_shorts": {"status": "healthy"},
            "facebook_reels": {"status": "healthy"},
        }
        self.assertEqual(clamp_cadence_3(1, healthy), 3)
        self.assertEqual(clamp_cadence_3(3, healthy), 3)

    def test_critical_retention_forces_one_video_per_day(self):
        """The bug this replaces: 3/day was forced while Meta sat at 19%
        completion against a ~70% gate, which teaches the feed to stop showing
        the channel."""
        critical = {
            "youtube_shorts": {"status": "below_gate"},
            "facebook_reels": {"status": "critical"},
            "instagram_reels": {"status": "critical"},
        }
        self.assertEqual(clamp_cadence_3(3, critical), 1)

    def test_below_gate_retention_caps_at_two(self):
        below = {"youtube_shorts": {"status": "below_gate"}}
        self.assertEqual(clamp_cadence_3(3, below), 2)

    def test_no_data_holds_conservative_two(self):
        self.assertEqual(clamp_cadence_3(3, {}), 2)
        self.assertEqual(
            clamp_cadence_3(3, {"youtube_shorts": {"status": "no_data"}}), 2
        )

    def test_cadence_never_exceeds_production_ceiling(self):
        healthy = {
            "youtube_shorts": {"status": "healthy"},
            "instagram_reels": {"status": "healthy"},
        }
        self.assertEqual(clamp_cadence_3(99, healthy), 3)

    def test_ceiling_derives_ratio_when_only_completion_is_present(self):
        """A health dict without an explicit status must still be understood."""
        from continuity import retention_cadence_ceiling

        ceiling, reason = retention_cadence_ceiling(
            {"facebook_reels": {"status": "critical", "avg_completion": 0.19, "gate": 0.72}}
        )
        self.assertEqual(ceiling, 1)
        self.assertIn("critical", reason)

    def test_cadence_3_can_be_disabled(self):
        os.environ["DISABLE_CADENCE_3"] = "true"
        try:
            self.assertEqual(clamp_cadence_3(1), 1)
        finally:
            os.environ.pop("DISABLE_CADENCE_3", None)

    def test_us_peak_slot(self):
        self.assertTrue(is_us_peak_slot(12))
        self.assertFalse(is_us_peak_slot(18))
        self.assertFalse(is_us_peak_slot(20))
        self.assertFalse(is_us_peak_slot(9))

    def test_slot_status(self):
        # fresh state so repeated runs don't accumulate
        from continuity import _state_path
        p = _state_path()
        if p.exists():
            p.unlink()
        register_slot_attempt("NY12:30", "published", "topic a")
        register_slot_attempt("NY18:30", "published", "topic b")
        register_slot_attempt("NY20:00", "guard_fail", "topic c")
        s = slot_consistency_status()
        self.assertEqual(s["published"], 2)
        self.assertEqual(s["missed"], 1)
        self.assertGreater(s["consistency_pct"], 0)


if __name__ == "__main__":
    unittest.main()
