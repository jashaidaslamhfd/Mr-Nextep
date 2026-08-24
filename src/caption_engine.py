"""
src/caption_engine.py

Hormozi-style animated word-by-word captions — 100% free, PIL + moviepy.

This is the single biggest retention driver after hook quality. Viewers who
can READ along with the narration stay engaged. The engine:

  1. Reads SRT word timings from Edge TTS
  2. Renders each word as a PIL image frame
  3. Applies emphasis effects: scale, color, shadow for key words
  4. Composes into moviepy clips that overlay on the video

Style: large bold white text, centered bottom-third, key words flash yellow/orange
with a subtle scale punch. No external fonts needed (uses default PIL font).

Usage:
    from caption_engine import CaptionRenderer
    renderer = CaptionRenderer(width=1080, height=1920)
    caption_clips = renderer.render_word_by_word(segments, scenes, total_duration)
    # Returns list of moviepy TextClip/ImageClip ready to composit
"""

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Style constants — Hormozi-inspired
# ---------------------------------------------------------------------------
CANVAS_W = 1080
CANVAS_H = 1920

# Caption position: bottom 25% of screen (where viewers expect it)
CAPTION_Y_START = int(CANVAS_H * 0.72)
CAPTION_Y_END = int(CANVAS_H * 0.82)

# Font sizes
FONT_SIZE_DEFAULT = 62
FONT_SIZE_EMPHASIS = 78     # key words are bigger
FONT_SIZE_MAX = 90          # absolute max for single important word

# Colors — high contrast for mobile
COLOR_DEFAULT = (255, 255, 255)       # white
COLOR_EMPHASIS = (255, 200, 0)        # yellow-gold (attention grabber)
COLOR_SHADOW = (0, 0, 0)              # black shadow for readability
COLOR_OUTLINE = (0, 0, 0)             # black outline

# Emphasis words that get the highlight treatment
_EMPHASIS_WORDS = frozenset([
    'body', 'brain', 'heart', 'muscle', 'nerve', 'bone', 'eye', 'ear',
    'skin', 'blood', 'lung', 'stomach', 'sleep', 'death', 'fear',
    'danger', 'freeze', 'locks', 'fires', 'explodes', 'stops',
    'never', 'always', 'every', 'first', 'last', 'only',
    'millisecond', 'seconds', 'minutes', 'hours',
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
    'thousand', 'million', 'billion',
    'actually', 'literally', 'really',
])


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a bold font. Falls back to default if no bold available."""
    # Try common bold font paths
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)

    # Fallback: PIL default
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except (IOError, OSError):
        return ImageFont.load_default()


class CaptionRenderer:
    """Renders word-by-word animated captions as moviepy-compatible clips."""

    def __init__(self, width: int = CANVAS_W, height: int = CANVAS_H):
        self.width = width
        self.height = height
        self.font_default = _get_font(FONT_SIZE_DEFAULT)
        self.font_emphasis = _get_font(FONT_SIZE_EMPHASIS)

    def render_word_by_word(self, segments: list, scenes: list,
                             total_duration: float,
                             output_dir: str = "output/captions") -> list:
        """Render word-by-word captions and return clip data.

        Instead of returning moviepy clips (which would require moviepy import
        at module level), we return a list of frame dicts that video_editor.py
        can compose into clips. This keeps the module lightweight.

        Returns:
            [{
                'word': str,
                'start': float,      # seconds
                'end': float,        # seconds
                'is_emphasis': bool,
                'frame_path': str,   # path to rendered PIL image
            }, ...]
        """
        os.makedirs(output_dir, exist_ok=True)

        words_data = self._extract_word_timings(segments, scenes, total_duration)

        rendered = []
        for i, wd in enumerate(words_data):
            frame_path = os.path.join(output_dir, f"word_{i:04d}.png")
            self._render_word_frame(
                word=wd["word"],
                is_emphasis=wd["is_emphasis"],
                is_first_in_group=wd.get("is_first", False),
                output_path=frame_path,
            )
            wd["frame_path"] = frame_path
            rendered.append(wd)

            if (i + 1) % 20 == 0:
                logger.info("Rendered %d/%d caption frames", i + 1, len(words_data))

        logger.info("Caption rendering complete: %d frames", len(rendered))
        return rendered

    def _extract_word_timings(self, segments: list, scenes: list,
                               total_duration: float) -> list:
        """Extract individual word timings with start/end times."""
        words = []
        cumulative = 0.0

        for seg_idx, segment in enumerate(segments):
            word_timings = segment.get("word_timings", [])
            duration = segment.get("duration", 3.0)

            if word_timings:
                for wt in word_timings:
                    start = cumulative + wt["offset"]
                    end = start + wt["duration"]
                    word = wt["text"]
                    words.append({
                        "word": word,
                        "start": start,
                        "end": end,
                        "is_emphasis": self._is_emphasis(word),
                        "is_first": False,
                    })
                if words:
                    words[-len(word_timings)]["is_first"] = True
            else:
                # Fallback: split by spaces with even timing
                caption = scenes[seg_idx].get("caption", "") if seg_idx < len(scenes) else ""
                scene_words = caption.split()
                if scene_words:
                    word_dur = duration / len(scene_words)
                    for w_idx, w in enumerate(scene_words):
                        start = cumulative + w_idx * word_dur
                        end = start + word_dur
                        words.append({
                            "word": w,
                            "start": start,
                            "end": end,
                            "is_emphasis": self._is_emphasis(w),
                            "is_first": w_idx == 0,
                        })

            cumulative += duration

        return words

    def _is_emphasis(self, word: str) -> bool:
        """Determine if a word gets emphasis styling."""
        clean = re.sub(r'[^a-zA-Z0-9]', '', word).lower()
        if clean in _EMPHASIS_WORDS:
            return True
        if clean.isdigit():
            return True
        if clean.isupper() and len(clean) > 1:
            return True
        return False

    def _render_word_frame(self, word: str, is_emphasis: bool = False,
                            is_first_in_group: bool = False,
                            output_path: str = ""):
        """Render a single word as a transparent PNG frame.

        The frame has a transparent background so it can be composited
        over the video in moviepy.
        """
        font = self.font_emphasis if is_emphasis else self.font_default
        color = COLOR_EMPHASIS if is_emphasis else COLOR_DEFAULT
        text = word.upper() if is_emphasis else word

        # Measure text
        dummy = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        # Create frame
        frame_w = text_w + 40   # padding
        frame_h = text_h + 20
        img = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw shadow (offset by 2px)
        shadow_offset = 3
        draw.text(
            (20 + shadow_offset, 10 + shadow_offset),
            text, font=font, fill=(*COLOR_SHADOW, 180),
            anchor="mt",
        )

        # Draw outline (8 directions)
        outline_range = 2
        for dx in range(-outline_range, outline_range + 1):
            for dy in range(-outline_range, outline_range + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text(
                    (20 + dx, 10 + dy),
                    text, font=font, fill=(*COLOR_OUTLINE, 200),
                    anchor="mt",
                )

        # Draw main text
        draw.text(
            (20, 10),
            text, font=font, fill=(*color, 255),
            anchor="mt",
        )

        # For emphasis words: add a subtle glow effect
        if is_emphasis:
            glow = img.copy()
            glow = glow.filter(ImageFilter.GaussianBlur(radius=4))
            glow = Image.blend(img, glow, alpha=0.3)
            img = glow

        if output_path:
            img.save(output_path, "PNG")

        return img

    def build_composite_data(self, rendered_words: list) -> dict:
        """Build a summary dict for video_editor to use.

        Returns data needed to overlay captions without importing moviepy here.
        """
        return {
            "word_count": len(rendered_words),
            "total_duration": rendered_words[-1]["end"] if rendered_words else 0,
            "emphasis_count": sum(1 for w in rendered_words if w["is_emphasis"]),
            "frames_dir": os.path.dirname(rendered_words[0]["frame_path"]) if rendered_words else "",
            "words": rendered_words,
        }


def render_caption_overlay(video_path: str, segments: list, scenes: list,
                            output_path: str = "output/captioned_video.mp4") -> str:
    """Full pipeline: render captions and overlay on video using moviepy.

    This is the high-level entry point called by main.py.
    """
    from moviepy.editor import ImageClip, CompositeVideoClip

    renderer = CaptionRenderer()
    rendered = renderer.render_word_by_word(
        segments, scenes,
        total_duration=sum(s.get("duration", 3.0) for s in segments),
    )

    if not rendered:
        logger.warning("No captions to render")
        return video_path

    # Load the base video
    from moviepy.editor import VideoFileClip
    video = VideoFileClip(video_path)

    # Build caption clips
    caption_clips = []
    for wd in rendered:
        if not os.path.exists(wd["frame_path"]):
            continue
        # Load the word frame
        frame_img = Image.open(wd["frame_path"])

        # Create a clip from the PIL image
        clip = ImageClip(list(frame_img.getdata()), ismask=False)
        clip = clip.set_duration(wd["end"] - wd["start"])
        clip = clip.set_start(wd["start"])

        # Position: centered horizontally, bottom 25% vertically
        x = (CANVAS_W - frame_img.width) // 2
        y = CAPTION_Y_START + (CAPTION_Y_END - CAPTION_Y_START) // 2 - frame_img.height // 2
        clip = clip.set_position((x, y))

        caption_clips.append(clip)

    # Composite
    all_clips = [video] + caption_clips
    final = CompositeVideoClip(all_clips, size=(CANVAS_W, CANVAS_H))
    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        fps=30,
        preset="fast",
        threads=4,
    )

    logger.info("Captioned video saved: %s", output_path)
    return output_path


if __name__ == "__main__":
    # Test: render a single word frame
    renderer = CaptionRenderer()
    test_words = [
        ("Your", False), ("BODY", True), ("freezes", False),
        ("before", False), ("you", False), ("HEAR", True), ("the sound.", False),
    ]
    os.makedirs("/tmp/test_captions", exist_ok=True)
    for word, emphasis in test_words:
        path = f"/tmp/test_captions/{word.lower()}.png"
        renderer._render_word_frame(word, is_emphasis=emphasis, output_path=path)
        img = Image.open(path)
        print(f"  {word:12s} emphasis={emphasis} size={img.size}")
    print("Caption frames rendered to /tmp/test_captions/")
