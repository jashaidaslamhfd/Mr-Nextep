"""Offline tests for the human-feel video/voice features.

These verify the deterministic-but-varied helpers WITHOUT importing the heavy
moviepy/tts stack (we test the pure logic functions).
"""
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# Import only the pure helpers via importlib to avoid pulling moviepy.
import importlib.util as _ilu


def _load(name, file):
    spec = _ilu.spec_from_file_location(name, file)
    mod = _ilu.module_from_spec(spec)
    # stub heavy deps before exec so the module can at least load its defs
    import types
    for dep in ("moviepy", "numpy", "PIL"):
        if dep not in sys.modules:
            sys.modules[dep] = types.ModuleType(dep)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass  # may need deps; we still can read source for logic tests below
    return mod


class VoiceTempoTests(unittest.TestCase):
    def test_tempo_is_deterministic(self):
        from voice_generator import _scene_tempo_for
        self.assertEqual(_scene_tempo_for(1.0, 0, "Why does your body shake?"),
                         _scene_tempo_for(1.0, 0, "Why does your body shake?"))
        self.assertNotEqual(_scene_tempo_for(1.0, 0, "Why does your body shake?"),
                            _scene_tempo_for(1.0, 1, "It is a reflex."))

    def test_tempo_stays_in_safe_band(self):
        from voice_generator import _scene_tempo_for
        for i in range(12):
            t = _scene_tempo_for(1.0, i, f"line {i} with some content")
            self.assertGreaterEqual(t, 0.9)
            self.assertLessEqual(t, 1.1)

    def test_hook_scene_slightly_slower(self):
        from voice_generator import _scene_tempo_for
        # scene 0 (hook) has an extra -0.015 offset; should not be faster than
        # a comparable middle scene of the same caption base.
        t0 = _scene_tempo_for(1.0, 0, "hello world this is a test line")
        t1 = _scene_tempo_for(1.0, 1, "hello world this is a test line")
        self.assertLessEqual(t0, t1 + 0.02)


class VideoThemeTests(unittest.TestCase):
    def test_theme_accents_are_finite_and_varied(self):
        # Accent pool is 5 colors; the theme selection uses hash of caption.
        src = (SRC / "video_editor.py").read_text()
        self.assertIn("_accents", src)
        self.assertIn("color_theme", src)
        # There should be >1 accent so videos aren't all identical.
        import re
        m = re.search(r"_accents\s*=\s*\[(.*?)\]", src, re.DOTALL)
        self.assertTrue(m, "accent pool present")
        # count RGB tuples
        self.assertGreaterEqual(len(re.findall(r"\(\d+,\s*\d+,\s*\d+\)", m.group(1))), 3)

    def test_seeded_ken_burns_direction(self):
        src = (SRC / "video_editor.py").read_text()
        self.assertIn("_dir_seed", src)
        self.assertIn("caption_text", src)


if __name__ == "__main__":
    unittest.main()


class ViralHookOverlayTests(unittest.TestCase):
    def test_hook_overlay_uses_keywords_not_stopwords(self):
        # Verify _hook_overlay_clip produces a short punchy phrase by reading
        # the source (avoids importing moviepy). The function strips stopwords
        # and takes <=2 meaningful words.
        src = (SRC / "video_editor.py").read_text()
        self.assertIn("def _hook_overlay_clip", src)
        self.assertIn("pattern-interrupt", src)
        self.assertIn("hook_text", src)
        # stopwords stripped
        self.assertIn("stop = {\"the\", \"a\", \"an\",", src)
        self.assertIn("meaningful[:2]", src)

    def test_first_frame_hook_text_stamped_in_main(self):
        src = (SRC / "main.py").read_text()
        self.assertIn("hook_text", src)
        self.assertIn("script_data['scenes'][0]['hook_text']", src)

    def test_overlay_only_on_first_scene(self):
        src = (SRC / "video_editor.py").read_text()
        self.assertIn("if i == 0:", src)
        self.assertIn("overlays.append(_hook_overlay_clip", src)


class HookOverlayPillowCompatTests(unittest.TestCase):
    def test_hook_overlay_uses_textbbox_not_textlength_for_stroke(self):
        """Pillow's textlength() rejects stroke_width (a real runtime crash).
        The hook overlay must measure width via textbbox."""
        src = (SRC / "video_editor.py").read_text()
        # textbbox is used for the stroke-width measure in the overlay
        self.assertIn("textbbox((0, 0), phrase, font=font, stroke_width=6)", src)
        # no real call textlength( ... stroke_width= ...) (would crash Pillow 10+)
        for line in src.splitlines():
            code = line.lstrip()
            if code.startswith("#"):
                continue  # skip comments
            if "textlength(" in code and "stroke_width" in code:
                self.fail(f"textlength with stroke_width would crash Pillow: {code.strip()}")
