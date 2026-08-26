"""Tests for the advanced ML brain (src/ml_brain.py)."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from ml_brain import (
    _extract_features,
    _curiosity_gap_score,
    _has_body_word,
    _duration_bucket,
    _build_model_candidates,
    _calibrated_confidence,
    build_training_data,
    train_views_model,
    train_retention_model,
    predict_views,
    predict_retention,
    save_model,
    load_model,
    needs_retrain,
    train_all,
    steer_generation,
    log_prediction,
    evaluate_predictions,
    check_drift,
)


def _sample_video(i: int = 0) -> dict:
    """Generate a synthetic video record for testing."""
    return {
        "content_fingerprint": f"fp_{i:04d}",
        "title": f"Your Body Freezes at 3AM #{i}",
        "topic": f"brain dream #{i % 5}",
        "trend_source": "youtube_trending",
        "hook_score": 70 + (i % 30),
        "seo_score": 60 + (i % 40),
        "duration_seconds": 25 + (i % 15),
        "predicted_ctr": 5.0 + (i % 5),
        "predicted_retention": 0.5 + (i % 10) * 0.02,
        "posted_at": f"2026-08-{10 + (i % 15):02d}T{12 + (i % 12):02d}:00:00+00:00",
        "views": 50 + i * 30,
        "average_view_percentage": 20.0 + (i % 8) * 5.0,
        "hook_frame": ["second_person", "statement", "question"][i % 3],
        "ending_mode": ["loop", "cta", "cliffhanger"][i % 3],
        "voiceover": f"This is a voiceover script about body #{i}",
    }


def _feats_list(n: int = 20) -> list:
    """Generate a list of synthetic features with training data."""
    videos = [_sample_video(i) for i in range(n)]
    features_list = []
    for v in videos:
        f = _extract_features(v, videos)
        if f is not None:
            features_list.append(f)
    return features_list


class FeatureExtractionTests(unittest.TestCase):
    def test_extracts_basic_features(self):
        v = _sample_video(0)
        feats = _extract_features(v, [_sample_video(i) for i in range(20)])
        self.assertIsNotNone(feats)
        self.assertIn("hook_score", feats)
        self.assertIn("seo_score", feats)
        self.assertIn("title_length", feats)
        self.assertIn("duration_seconds", feats)

    def test_returns_none_without_hook_score(self):
        v = _sample_video(0)
        v["hook_score"] = None
        self.assertIsNone(_extract_features(v))

    def test_curiosity_gap_words(self):
        self.assertGreater(_curiosity_gap_score("Your Body Is Wrong at Night"), 0)
        self.assertEqual(_curiosity_gap_score(""), 0.0)

    def test_body_word_detection(self):
        self.assertTrue(_has_body_word("Why Your Brain Freezes at 3AM"))
        self.assertFalse(_has_body_word("Something Random"))

    def test_duration_bucket(self):
        self.assertEqual(_duration_bucket(20), 0.0)
        self.assertEqual(_duration_bucket(30), 1.0)
        self.assertEqual(_duration_bucket(40), 2.0)


class ConfidenceTests(unittest.TestCase):
    def test_insufficient(self):
        self.assertEqual(_calibrated_confidence(0.5, 5), "insufficient")

    def test_low_samples(self):
        self.assertEqual(_calibrated_confidence(0.5, 20), "low")

    def test_high(self):
        self.assertEqual(_calibrated_confidence(0.7, 45), "high")

    def test_medium(self):
        self.assertEqual(_calibrated_confidence(0.4, 35), "medium")


class ModelCandidateTests(unittest.TestCase):
    def test_small_sample_fewer_models(self):
        candidates = _build_model_candidates(10)
        self.assertIn("random_forest", candidates)
        self.assertNotIn("gradient_boosting_deep", candidates)

    def test_large_sample_more_models(self):
        candidates = _build_model_candidates(30)
        self.assertIn("gradient_boosting_deep", candidates)
        self.assertIn("ridge", candidates)

    def test_factories_create_different_instances(self):
        candidates = _build_model_candidates(20)
        m1 = candidates["random_forest"]()
        m2 = candidates["random_forest"]()
        self.assertIsNot(m1, m2)


class TrainingTests(unittest.TestCase):
    def test_views_model_trains(self):
        feats = _feats_list(20)
        feature_names = sorted(feats[0].keys())
        views = [50.0 + i * 30 for i in range(len(feats))]
        result = train_views_model(feats, feature_names, views)
        self.assertTrue(result["trained"])
        self.assertGreater(result["r2_cv"], 0)
        self.assertIn("feature_importance", result)
        self.assertIn("confidence", result)

    def test_views_model_falls_back_on_few(self):
        result = train_views_model(_feats_list(3)[:3], ["hook_score"], [1.0, 2.0, 3.0])
        self.assertFalse(result["trained"])

    def test_retention_model_trains(self):
        feats = _feats_list(20)
        feature_names = sorted(feats[0].keys())
        retention = [0.3 + i * 0.02 for i in range(len(feats))]
        result = train_retention_model(feats, feature_names, retention)
        self.assertTrue(result["trained"])

    def test_retention_model_falls_back_with_zeroes(self):
        feats = _feats_list(20)
        feature_names = sorted(feats[0].keys())
        retention = [0.0] * len(feats)
        result = train_retention_model(feats, feature_names, retention)
        self.assertFalse(result["trained"])


class ModelPersistenceTests(unittest.TestCase):
    def test_save_and_load(self):
        import tempfile, os
        old_dir = os.environ.get("ML_MODEL_DIR")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["ML_MODEL_DIR"] = tmp
                feats = _feats_list(20)
                feature_names = sorted(feats[0].keys())
                views = [50.0 + i * 30 for i in range(len(feats))]
                result = train_views_model(feats, feature_names, views)
                save_model("test_model", result)
                loaded = load_model("test_model")
                self.assertIsNotNone(loaded)
                self.assertTrue(loaded["trained"])
                self.assertEqual(loaded["n"], result["n"])
        finally:
            if old_dir is not None:
                os.environ["ML_MODEL_DIR"] = old_dir
            else:
                os.environ.pop("ML_MODEL_DIR", None)

    def test_load_nonexistent(self):
        self.assertIsNone(load_model("nonexistent_model_xyz"))


class SteeringTests(unittest.TestCase):
    def test_steering_returns_decisions(self):
        import tempfile, os
        old_dir = os.environ.get("ML_MODEL_DIR")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["ML_MODEL_DIR"] = tmp
                # Train first
                train_all(force=True)
                # Load features for steering
                features_list, feature_names, targets, vids = build_training_data()
                result = steer_generation(features_list, feature_names, targets)
                self.assertIn("decisions", result)
                self.assertIn("optimization_rules", result)
                self.assertIn("experiment_budget", result)
        finally:
            if old_dir is not None:
                os.environ["ML_MODEL_DIR"] = old_dir
            else:
                os.environ.pop("ML_MODEL_DIR", None)


class TrainAllTests(unittest.TestCase):
    def test_train_all(self):
        import tempfile, os
        old_dir = os.environ.get("ML_MODEL_DIR")
        old_state = os.environ.get("ML_BRAIN_STATE_PATH")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["ML_MODEL_DIR"] = tmp
                os.environ["ML_BRAIN_STATE_PATH"] = os.path.join(tmp, "brain.json")
                report = train_all(force=True)
                self.assertEqual(report["status"], "trained")
                self.assertIn("views", report["models"])
                self.assertIn("retention", report["models"])
                self.assertTrue(report["models"]["views"]["trained"])
        finally:
            for key, val in [("ML_MODEL_DIR", old_dir), ("ML_BRAIN_STATE_PATH", old_state)]:
                if val is not None:
                    os.environ[key] = val
                else:
                    os.environ.pop(key, None)


class PredictionTests(unittest.TestCase):
    def test_predict_views_no_model(self):
        v = _sample_video(0)
        result = predict_views(v)
        self.assertIn("predicted_views", result)

    def test_predict_retention_no_model(self):
        v = _sample_video(0)
        result = predict_retention(v)
        self.assertIn("predicted_retention", result)


class DriftTests(unittest.TestCase):
    def test_no_drift_without_data(self):
        import tempfile, os
        old_log = os.environ.get("ML_PREDICTION_LOG")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["ML_PREDICTION_LOG"] = os.path.join(tmp, "pred_log.json")
                result = check_drift()
                self.assertFalse(result["drift_detected"])
        finally:
            if old_log is not None:
                os.environ["ML_PREDICTION_LOG"] = old_log
            else:
                os.environ.pop("ML_PREDICTION_LOG", None)

    def test_evaluate_empty_log(self):
        import tempfile, os
        old_log = os.environ.get("ML_PREDICTION_LOG")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["ML_PREDICTION_LOG"] = os.path.join(tmp, "pred_log.json")
                result = evaluate_predictions()
                self.assertFalse(result["evaluated"])
        finally:
            if old_log is not None:
                os.environ["ML_PREDICTION_LOG"] = old_log
            else:
                os.environ.pop("ML_PREDICTION_LOG", None)


class BuildTrainingDataTests(unittest.TestCase):
    def test_builds_data(self):
        features, names, targets, vids = build_training_data()
        self.assertEqual(len(features), len(vids))
        if features:
            self.assertIn("hook_score", names)
            self.assertIn("views", targets)


if __name__ == "__main__":
    unittest.main()
