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

    def test_cadence_clamped_to_3(self):
        self.assertEqual(clamp_cadence_3(1), 3)
        self.assertEqual(clamp_cadence_3(2), 3)
        self.assertEqual(clamp_cadence_3(3), 3)

    def test_cadence_3_can_be_disabled(self):
        os.environ["DISABLE_CADENCE_3"] = "true"
        try:
            self.assertEqual(clamp_cadence_3(1), 1)
        finally:
            os.environ.pop("DISABLE_CADENCE_3", None)

    def test_us_peak_slots(self):
        for h in (12, 18, 20):
            self.assertTrue(is_us_peak_slot(h))
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
