"""Offline tests for reality calibration (src/calibration.py)."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from calibration import calibrate, reality_adjusted_ok  # noqa: E402


def _history(n=12, base=100, drift_ctr=False):
    """Synthetic history: hook_score positively correlates with views unless
    drift_ctr=True (then higher hook => lower views)."""
    rows = []
    for i in range(n):
        v = {
            "analytics_fetched_at": "2026-08-01T00:00:00+00:00",
            "views": base + i * 20,
            "hook_score": 50 + i * 3,
            "predicted_ctr": 5 + i * 0.2,
            "seo_score": 60 + i * 2,
            "predicted_retention": 0.5 + i * 0.01,
        }
        if drift_ctr:
            # make ctr negatively correlated
            v["predicted_ctr"] = 8 - i * 0.3
        rows.append(v)
    return rows


class CalibrationTests(unittest.TestCase):
    def test_healthy_levers_not_drifted(self):
        c = calibrate(_history())
        self.assertTrue(c["calibrated"])
        self.assertEqual(c["n"], 12)
        # hook_score is positively correlated -> not drifted
        self.assertNotIn("hook_score", c["drifted"])

    def test_drift_detected(self):
        c = calibrate(_history(drift_ctr=True))
        # predicted_ctr negatively correlated -> drifted
        self.assertIn("predicted_ctr", c["drifted"])

    def test_low_data_not_calibrated(self):
        c = calibrate(_history(3))
        self.assertFalse(c["calibrated"])

    def test_reality_adjusted_ok(self):
        r = reality_adjusted_ok(_history(drift_ctr=True),
                                {"predicted_ctr": 9, "hook_score": 85})
        self.assertIn("drifted_levers", r)
        self.assertIn("predicted_ctr", r["drifted_levers"])
        self.assertIn("affected_scores", r)


if __name__ == "__main__":
    unittest.main()
