"""Offline tests for the 2026 per-platform SEO guards."""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from platform_seo_guards import (  # noqa: E402
    check_youtube_seo, check_facebook_seo, check_instagram_seo,
    run_platform_seo_guards,
)


def _good():
    return {
        "title": "Why Your Hours Feel Like Minutes",
        "hook": "Why does time fly when you have fun?",
        "description": "A full description about body science with keywords and "
                       "why things happen the way they do every single day.",
        "tags": ["science", "body", "facts", "why"],
        "hashtags": ["#shorts", "#science", "#body"],
        "facebook_caption": "Your sense of time warps under stress. The science "
                            "is clear.\n\n#bodyfacts #science",
        "instagram_caption": "Here's why time feels slower when you are stressed: "
                             "your brain records more. DM-worthy fact. "
                             "#bodyfacts #science #didyouknow",
    }


class PlatformSeoTests(unittest.TestCase):
    def test_youtube_good(self):
        self.assertTrue(check_youtube_seo(_good())["pass"])

    def test_youtube_bad(self):
        r = check_youtube_seo({"title": "Time", "hook": "", "description": "short",
                               "tags": [], "hashtags": ["#shorts"]})
        self.assertFalse(r["pass"])
        self.assertTrue(r["issues"])

    def test_facebook_good(self):
        self.assertTrue(check_facebook_seo(_good())["pass"])

    def test_facebook_rejects_crosspost_and_bait(self):
        r = check_facebook_seo({"facebook_caption": "Subscribe for more! "
                               "#shorts #youtube #viral"})
        self.assertFalse(r["pass"])
        joined = " ".join(r["issues"]).lower()
        self.assertIn("shorts", joined)
        self.assertIn("bait", joined)

    def test_instagram_good(self):
        self.assertTrue(check_instagram_seo(_good())["pass"])

    def test_instagram_rejects_missing_payoff_and_bait(self):
        r = check_instagram_seo({"instagram_caption": "Smash that like #shorts"})
        self.assertFalse(r["pass"])
        joined = " ".join(r["issues"]).lower()
        self.assertIn("payoff", joined)
        self.assertIn("bait", joined)

    def test_combined_all_platforms_pass(self):
        r = run_platform_seo_guards(_good(), ["youtube", "facebook", "instagram"])
        self.assertTrue(r["overall"])
        self.assertEqual(r["passed"], ["youtube", "facebook", "instagram"])

    def test_combined_blocks_bad(self):
        bad = {"facebook_caption": "Subscribe #shorts #youtube",
               "instagram_caption": "Smash that like #shorts",
               "description": "x", "title": "x", "tags": [], "hashtags": []}
        r = run_platform_seo_guards(bad, ["youtube", "facebook", "instagram"])
        self.assertFalse(r["overall"])
        self.assertEqual(r["failed"], ["youtube", "facebook", "instagram"])


if __name__ == "__main__":
    unittest.main()
