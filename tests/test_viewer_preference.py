"""Offline tests for the FREE viewer-preference guard (src/viewer_preference.py)."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from viewer_preference import (  # noqa: E402
    score_viewer_preference, viewer_preference_guard, extract_features,
    recalibrate,
)


def _good():
    return {
        "title": "Why Your Eye Twitches at Night",
        "hook": "Why does your eye twitch right before you sleep?",
        "voiceover": " ".join(["word"] * 80),
        "description": "A full description about body science and why things "
                       "happen the way they do every single day.",
        "scenes": [{"caption": f"Why does your eye twitch scene {i} enough text"}
                   for i in range(8)],
    }


def _weak():
    return {"title": "Facts", "hook": "Time passes.", "voiceover": " ".join(["w"]*30),
            "description": "short", "scenes": [{"caption": "x"}]*3}


class ViewerPreferenceTests(unittest.TestCase):
    def test_good_script_scores_strong(self):
        s = score_viewer_preference(_good())
        self.assertGreaterEqual(s["score"], 70)
        self.assertEqual(s["verdict"], "strong")
        self.assertTrue(s["free"])

    def test_weak_script_fails_guard(self):
        s = score_viewer_preference(_weak())
        self.assertLess(s["score"], 55)
        self.assertFalse(viewer_preference_guard(_weak(), 70)["pass"])

    def test_guard_passes_good(self):
        self.assertTrue(viewer_preference_guard(_good(), 70)["pass"])

    def test_extract_features_returns_dict(self):
        f = extract_features(_good())
        self.assertIn("hook_strength", f)
        self.assertIn("story_completeness", f)
        self.assertIn("pacing", f)

    def test_recalibrate_needs_labels(self):
        """Empty history -> not calibrated.

        This used to read the repo's real data/viewer_preference_history.json,
        so the assertion silently depended on how many labels happened to be
        committed: once the pipeline recorded 8+ of them the test failed for a
        reason that had nothing to do with the code under test. Isolate it.
        """
        import importlib
        import os
        import tempfile

        import viewer_preference

        with tempfile.TemporaryDirectory() as tmp:
            saved = os.environ.get("VIEWER_PREF_HISTORY")
            os.environ["VIEWER_PREF_HISTORY"] = os.path.join(tmp, "history.json")
            try:
                module = importlib.reload(viewer_preference)
                r = module.recalibrate()
                self.assertFalse(r["calibrated"])
                self.assertEqual(r["n_labels"], 0)
            finally:
                if saved is None:
                    os.environ.pop("VIEWER_PREF_HISTORY", None)
                else:
                    os.environ["VIEWER_PREF_HISTORY"] = saved
                importlib.reload(viewer_preference)


if __name__ == "__main__":
    unittest.main()
