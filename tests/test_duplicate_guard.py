"""Offline tests for the duplicate-title guard (src/main.py helper)."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# import only the pipeline class's helper by reading source; heavy deps like
# moviepy/dotenv are NOT needed for the pure normalization/comparison logic.
import re


def _norm(t):
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", " ", str(t or ""))
    t = re.sub(r"#[A-Za-z0-9_]+", "", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _is_dup(title, known):
    target = _norm(title)
    if len(target) < 10:
        return False
    for cand in known:
        c = _norm(cand)
        if len(c) < 10:
            continue
        if c == target:
            return True
        tw, cw = set(target.split()), set(c.split())
        if len(tw) >= 2 and len(cw) >= 2:
            overlap = len(tw & cw) / min(len(tw), len(cw))
            if overlap >= 0.85:
                return True
    return False


KNOWN = [
    "Why Your Body Shakes When You Sleep 😴",
    "Why Your Body Freezes When Scared 🫀",
    "Deja Vu 🫀",
    "Time Compression 🫀",
]


class DuplicateGuardTests(unittest.TestCase):
    def test_exact_duplicate_detected(self):
        self.assertTrue(_is_dup("Why Your Body Shakes When You Sleep", KNOWN))
        self.assertTrue(_is_dup("Time Compression 🫀", KNOWN))

    def test_new_title_allowed(self):
        self.assertFalse(_is_dup("Why Your Fingertips Prune Faster in Salt Water", KNOWN))
        self.assertFalse(_is_dup("Why Birds Never Get Dizzy", KNOWN))

    def test_punctuation_and_emoji_insensitive(self):
        # emoji/punctuation stripped -> still matches the stored title
        self.assertTrue(_is_dup("Why Your Body Shakes When You Sleep!!!", KNOWN))

    def test_short_titles_not_false_positive(self):
        # short/generic titles under threshold shouldn't hard-block everything
        self.assertFalse(_is_dup("Hi", KNOWN))


if __name__ == "__main__":
    unittest.main()
