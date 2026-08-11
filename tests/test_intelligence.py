"""Offline tests for the advanced intelligence layer (src/intelligence.py)."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from intelligence import (  # noqa: E402
    ensemble_predict,
    viral_outliers,
    topic_segments,
    synthesize_intelligence,
    stacking_meta_learner,
    train_ctr_model,
    train_retention_model,
)


def _feats(n=16, base_views=200):
    """Synthetic features with a real views signal tied to hook + ctr."""
    return [
        {
            "views": base_views + i * 40 + (60 + i * 2),   # grows with i
            "completion": 0.3 + 0.01 * i,
            "hook_score": 50 + i * 2,
            "predicted_ctr": 2 + i * 0.3,
            "seo_score": 60 + i,
            "duration_seconds": 30,
            "predicted_retention": 0.3 + 0.02 * i,
            "word_count": 80 + i,
        }
        for i in range(n)
    ]


class EnsembleTests(unittest.TestCase):
    def test_trains_and_returns_weights(self):
        r = ensemble_predict(_feats(), target="views")
        self.assertTrue(r["trained"])
        self.assertIn("random_forest", r["weights"])
        self.assertIn("ridge", r["weights"])
        self.assertIn("r2_cv", r)
        # weights should sum to ~1
        self.assertAlmostEqual(sum(r["weights"].values()), 1.0, places=2)

    def test_falls_back_on_too_few_samples(self):
        r = ensemble_predict(_feats(3), target="views")
        self.assertFalse(r["trained"])
        self.assertIn("note", r)

    def test_returns_feature_importance(self):
        r = ensemble_predict(_feats(), target="views")
        self.assertTrue(r.get("feature_importance"))

    def test_never_raises_on_empty(self):
        r = ensemble_predict([], target="views")
        self.assertFalse(r["trained"])


class OutlierTests(unittest.TestCase):
    def test_detects_outliers_when_present(self):
        feats = _feats(14)
        feats[0]["views"] = 99999  # inject an anomaly
        r = viral_outliers(feats)
        self.assertTrue(r["detected"])
        self.assertIn(0, r["outlier_indices"])

    def test_falls_back_on_too_few(self):
        self.assertFalse(viral_outliers(_feats(2))["detected"])


class SegmentTests(unittest.TestCase):
    def test_clusters_into_segments(self):
        r = topic_segments(_feats(12), n_clusters=3)
        self.assertTrue(r["clustered"])
        self.assertGreaterEqual(len(r["segments"]), 2)

    def test_falls_back_on_too_few(self):
        self.assertFalse(topic_segments(_feats(3))["clustered"])


class StackingTests(unittest.TestCase):
    def test_meta_learner_trains(self):
        r = stacking_meta_learner(_feats(16), target="views")
        self.assertTrue(r["trained"])
        self.assertIn("meta_coefficients", r)
        self.assertIn("random_forest", r["meta_coefficients"])

    def test_meta_learner_falls_back(self):
        self.assertFalse(stacking_meta_learner(_feats(3))["trained"])

    def test_synthesize_includes_stacking(self):
        r = synthesize_intelligence(_feats(16))
        self.assertIn("stacking_meta", r)


class CtrRetentionTests(unittest.TestCase):
    def test_ctr_model_trains(self):
        feats = _feats(16)
        for i, f in enumerate(feats):
            f["real_ctr"] = 2 + i * 0.3   # real CTR grows with features
        r = train_ctr_model(feats)
        self.assertTrue(r["trained"])
        self.assertEqual(r["target"], "ctr")
        self.assertIn("drivers", r)
        self.assertIn("advice", r)

    def test_ctr_model_falls_back_to_heuristic(self):
        feats = _feats(16)  # no real_ctr -> heuristic target
        r = train_ctr_model(feats)
        self.assertTrue(r["trained"])
        self.assertIn("target_source", r)
        self.assertEqual(r["target_source"], "predicted_ctr")

    def test_ctr_model_low_data(self):
        r = train_ctr_model(_feats(3))
        self.assertFalse(r["trained"])

    def test_retention_model_trains(self):
        feats = _feats(16)
        for i, f in enumerate(feats):
            f["real_retention"] = 0.3 + 0.01 * i
        r = train_retention_model(feats)
        self.assertTrue(r["trained"])
        self.assertEqual(r["target"], "retention")
        self.assertIn("advice", r)

    def test_retention_model_low_data(self):
        r = train_retention_model(_feats(3))
        self.assertFalse(r["trained"])

    def test_synthesize_includes_ctr_and_retention(self):
        r = synthesize_intelligence(_feats(16))
        self.assertIn("ctr_model", r)
        self.assertIn("retention_model", r)


class SynthesizeTests(unittest.TestCase):
    def test_returns_full_report(self):
        r = synthesize_intelligence(_feats(16))
        self.assertIn("views_ensemble", r)
        self.assertIn("viral_outliers", r)
        self.assertIn("topic_segments", r)
        self.assertIn("advice", r)
        self.assertIn("confidence", r)


if __name__ == "__main__":
    unittest.main()
