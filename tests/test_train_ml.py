"""Offline test for the training pipeline (scripts/train_ml.py)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


class TrainMLTests(unittest.TestCase):
    def test_train_builds_full_state(self):
        import train_ml
        state = train_ml.train()
        self.assertIn("views_ensemble", state)
        self.assertIn("ctr_model", state)
        self.assertIn("retention_model", state)
        self.assertIn("calibration", state)
        self.assertIn("channel_score", state)
        self.assertIn("n_training_samples", state)

    def test_train_persists_to_state_file(self):
        import train_ml
        with tempfile.TemporaryDirectory() as tmp:
            old = train_ml.MODEL_STATE_PATH
            train_ml.MODEL_STATE_PATH = os.path.join(tmp, "model_state.json")
            try:
                state = train_ml.train()
                train_ml.persist(state)
                p = Path(train_ml.MODEL_STATE_PATH)
                self.assertTrue(p.exists())
                import json
                d = json.load(open(p))
                self.assertIn("ctr_model", d)
            finally:
                train_ml.MODEL_STATE_PATH = old


if __name__ == "__main__":
    unittest.main()
