"""Offline tests for the independent guard pipeline (src/gates.py)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from gates import (  # noqa: E402
    check_script, check_hook, check_seo, check_captions,
    check_video_quality, check_video_generation, check_voice, run_gates,
)


def _good_script():
    return {
        "title": "Why Your Hours Feel Like Minutes",
        "hook": "Why does time fly when you are having fun?",
        "cta": "Follow for more.",
        "description": "A full description with enough words about body science "
                       "and why things happen the way they do every single day.",
        "voiceover": " ".join(["word"] * 95),
        "scenes": [{"caption": f"Why does time fly scene {i} has enough text here"}
                   for i in range(8)],
        "tags": ["science", "body", "facts"],
        "hashtags": ["#science", "#body", "#facts"],
    }


class IndependentGuardTests(unittest.TestCase):
    def test_script_guard_good(self):
        r = check_script(_good_script())
        self.assertTrue(r["pass"])

    def test_script_guard_bad(self):
        r = check_script({"scenes": [], "title": ""})
        self.assertFalse(r["pass"])
        self.assertTrue(r["issues"])

    def test_hook_guard_requires_curiosity(self):
        good = check_hook({"hook": "Why does time fly when you have fun?",
                           "scenes": [{"caption": "Why does time fly"}]})
        self.assertTrue(good["pass"])
        bad = check_hook({"hook": "Time passes.", "scenes": [{"caption": "x"}]})
        self.assertFalse(bad["pass"])

    def test_video_quality_checks_canvas_duration(self):
        ok = check_video_quality({"width": 1080, "height": 1920, "duration": 33},
                                 {"floor": 27, "ceil": 40})
        self.assertTrue(ok["pass"])
        bad = check_video_quality({"width": 720, "height": 1280, "duration": 60},
                                  {"floor": 27, "ceil": 40})
        self.assertFalse(bad["pass"])

    def test_video_generation_needs_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for i in range(8):
                f = Path(tmp) / f"a{i}.jpg"
                f.write_bytes(b"x" * 2000)
                files.append(str(f))
            ok = check_video_generation(files, ["image"] * 8, 8)
            self.assertTrue(ok["pass"])
            # missing file
            bad = check_video_generation([os.path.join(tmp, "nope.jpg")], ["image"], 1)
            self.assertFalse(bad["pass"])

    def test_voice_guard_checks_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "v.wav"
            f.write_bytes(b"x" * 2000)
            segs = [{"path": str(f), "duration": 4.0, "tts_engine": "kokoro"}] * 8
            ok = check_voice(segs, 8)
            self.assertTrue(ok["pass"])
            bad = check_voice([{"path": str(f), "duration": 4.0, "tts_engine": "a"},
                               {"path": str(f), "duration": 4.0, "tts_engine": "b"}], 2)
            self.assertFalse(bad["pass"])  # mixed engines

    def test_seo_guard(self):
        self.assertTrue(check_seo(_good_script())["pass"])
        self.assertFalse(check_seo({"title": "", "description": "", "tags": [], "hashtags": []})["pass"])

    def test_caption_guard(self):
        good = check_captions({"scenes": [{"caption": "Hello there world"}, {"caption": "More text here"}]})
        self.assertTrue(good["pass"])
        bad = check_captions({"scenes": [{"caption": "Hello there world"}, {"caption": "Bad punct., here"}]})
        self.assertFalse(bad["pass"])

    def test_gate_pipeline_blocks_on_any_failure(self):
        ctx = {
            "script_data": {"scenes": [], "title": "", "hook": "",
                            "description": "", "voiceover": "", "tags": [], "hashtags": []},
            "technical": {"width": 720, "height": 1280, "duration": 60},
            "policy": {"floor": 27, "ceil": 40},
            "image_paths": [], "media_types": [], "audio_segments": [],
            "required_scenes": 8,
        }
        r = run_gates(ctx)
        self.assertFalse(r["overall"])
        self.assertGreaterEqual(r["failed_count"], 3)


if __name__ == "__main__":
    unittest.main()
