#!/usr/bin/env python3
"""
MrNextep Thumbnail A/B Testing Engine
-------------------------------------
Generates 3-5 thumbnail variants per video with different:
- Text placement (top/middle/bottom)
- Color schemes (dark mystery, bright medical, neutral science)
- Hook text variations

After 4-6 hours, reads back YouTube CTR and auto-selects the winner.
Integrates with the existing generate_thumbnail() in video_editor.py.

Usage (standalone):
    python scripts/generate_ab_thumbnails.py --topic "Why Your Heart Skips a Beat"
    
Usage (integrated):
    from scripts.generate_ab_thumbnails import ThumbnailABGenerator
    gen = ThumbnailABGenerator()
    variants = gen.generate_variants(image_base, topic, hook_text)
"""

import json
import os
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Style presets per niche
# ---------------------------------------------------------------------------
STYLES: Dict[str, Dict] = {
    "body_glitches": {
        "primary": ("#1a1a2e", "#e94560"),   # Dark navy + neon red
        "secondary": ("#0f3460", "#16c79a"),  # Deep blue + teal
        "accent": ("#16213e", "#f5f5f5"),     # Midnight + white
        "font_bold": "Impact, Arial Black, sans-serif",
        "font_regular": "Arial, Helvetica, sans-serif",
        "overlay_opacity": 0.55,
    },
    "dark_mystery": {
        "primary": ("#0a0a0a", "#ff4444"),
        "secondary": ("#1a1a1a", "#cc0000"),
        "accent": ("#000000", "#ffffff"),
        "font_bold": "Impact, Arial Black, sans-serif",
        "font_regular": "Arial, Helvetica, sans-serif",
        "overlay_opacity": 0.65,
    },
}

OUTPUT_DIR = Path(os.environ.get("THUMBNAIL_OUTPUT_DIR", "output/thumbnails"))
AB_STATE_PATH = Path(os.environ.get("AB_STATE_PATH", "data/ab_thumbnail_state.json"))

# ---------------------------------------------------------------------------
# Text placement strategies
# ---------------------------------------------------------------------------
PLACEMENTS = [
    {"name": "top", "y_pct": 0.10, "align": "center"},
    {"name": "middle", "y_pct": 0.50, "align": "center"},
    {"name": "bottom", "y_pct": 0.82, "align": "center"},
    {"name": "top-left", "y_pct": 0.15, "align": "left", "x_pct": 0.05},
    {"name": "top-split", "y_pct": 0.08, "align": "center"},
]

# ---------------------------------------------------------------------------
# Hook text variations
# ---------------------------------------------------------------------------
HOOK_FORMATS = [
    "{hook}",                              # plain hook
    "{hook} 🤯",                           # with emoji
    "⚠️ {hook}",                           # warning prefix
    "{hook_short}",                        # shortened (max 5 words)
    "\"{hook_short}\"",                    # quoted
]


class ThumbnailABGenerator:
    """Generate A/B test thumbnails for faceless body-science Shorts."""

    def __init__(self, style: str = "body_glitches"):
        self.style = STYLES.get(style, STYLES["body_glitches"])
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self._font_cache: Dict[Tuple[str, int], Optional[ImageFont.FreeTypeFont]] = {}

    def _get_font(self, size: int, bold: bool = True) -> Optional[ImageFont.FreeTypeFont]:
        """Get a font, falling back to default."""
        key = ("bold" if bold else "regular", size)
        if key in self._font_cache:
            return self._font_cache[key]

        font = None
        try:
            # Try system fonts first
            for path in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]:
                if os.path.exists(path):
                    font = ImageFont.truetype(path, size)
                    break
        except Exception:
            pass

        if font is None:
            font = ImageFont.load_default()

        self._font_cache[key] = font
        return font

    def _shorten_hook(self, hook: str, max_words: int = 5) -> str:
        """Shorten hook to max_words while keeping impact."""
        words = hook.strip().split()
        if len(words) <= max_words:
            return hook
        return " ".join(words[:max_words]) + "…"

    def _wrap_text(
        self, text: str, font: ImageFont.FreeTypeFont, max_width: int
    ) -> List[str]:
        """Wrap text to fit within max_width pixels."""
        words = text.split()
        lines = []
        current = []
        for word in words:
            test = " ".join(current + [word])
            try:
                bbox = font.getbbox(test)
                w = bbox[2] - bbox[0]
            except Exception:
                w = len(test) * (font.size // 2)
            if w <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
        return lines

    def _draw_text_with_outline(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        position: Tuple[int, int],
        font: ImageFont.FreeTypeFont,
        fill: str,
        outline: str = "#000000",
        outline_width: int = 3,
    ):
        """Draw text with a dark outline for readability."""
        x, y = position
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
        draw.text((x, y), text, font=font, fill=fill)

    def generate_variants(
        self,
        base_image: Image.Image,
        topic: str,
        hook_text: str,
        num_variants: int = 5,
    ) -> List[Dict]:
        """
        Generate A/B thumbnail variants.

        Returns list of dicts:
        [
            {
                "path": "output/thumbnails/variant_1.jpg",
                "placement": "top",
                "hook_variant": "...",
                "color_scheme": "primary",
                "fingerprint": "abc123",
            },
            ...
        ]
        """
        variants = []
        hook_short = self._shorten_hook(hook_text)
        fingerprint_base = hashlib.sha256(
            (topic + hook_text).encode()
        ).hexdigest()[:8]

        for i in range(min(num_variants, 5)):
            # Cycle through placement × color scheme × hook format
            placement = PLACEMENTS[i % len(PLACEMENTS)]
            color_key = ["primary", "secondary", "accent"][i % 3]
            bg_color, text_color = self.style[color_key]
            hook_fmt = HOOK_FORMATS[i % len(HOOK_FORMATS)]

            # Format the hook text
            display_text = hook_fmt.format(
                hook=hook_text,
                hook_short=hook_short,
            )

            # Create variant
            variant = base_image.copy().convert("RGBA")
            variant = variant.resize((1080, 1920), Image.LANCZOS)

            # Dark overlay
            overlay = Image.new("RGBA", variant.size, bg_color + "cc")
            variant = Image.alpha_composite(variant, overlay)
            variant = variant.convert("RGB")

            draw = ImageDraw.Draw(variant)
            font_bold = self._get_font(72, bold=True)
            font_small = self._get_font(36, bold=False)

            img_w, img_h = variant.size
            margin = int(img_w * 0.08)
            max_text_w = img_w - 2 * margin

            # Wrap text
            lines = self._wrap_text(display_text, font_bold, max_text_w)

            # Calculate y position
            line_height = font_bold.size + 12
            total_height = len(lines) * line_height
            base_y = int(img_h * placement["y_pct"])

            # Adjust for multi-line
            if placement["y_pct"] > 0.5:
                base_y -= total_height
            elif placement["y_pct"] < 0.3:
                base_y = base_y
            else:
                base_y -= total_height // 2

            # Draw background pill for readability
            if lines:
                try:
                    text_bboxes = []
                    for line in lines:
                        bbox = font_bold.getbbox(line)
                        text_bboxes.append((bbox[2] - bbox[0]))

                    max_line_w = max(text_bboxes)
                    pill_pad = 20
                    pill_x0 = (img_w - max_line_w) // 2 - pill_pad
                    pill_x1 = pill_x0 + max_line_w + 2 * pill_pad
                    pill_y0 = base_y - 15
                    pill_y1 = base_y + total_height + 5

                    pill = Image.new("RGBA", variant.size, (0, 0, 0, 0))
                    pill_draw = ImageDraw.Draw(pill)
                    pill_draw.rounded_rectangle(
                        [pill_x0, pill_y0, pill_x1, pill_y1],
                        radius=16,
                        fill=(0, 0, 0, 140),
                    )
                    variant = Image.alpha_composite(
                        variant.convert("RGBA"), pill
                    ).convert("RGB")
                    draw = ImageDraw.Draw(variant)
                except Exception:
                    pass  # Pill is cosmetic; skip if it fails

            # Draw each line
            y = base_y
            for line in lines:
                try:
                    bbox = font_bold.getbbox(line)
                    text_w = bbox[2] - bbox[0]
                except Exception:
                    text_w = len(line) * (font_bold.size // 2)

                x = (img_w - text_w) // 2
                if placement.get("x_pct"):
                    x = int(img_w * placement["x_pct"])

                self._draw_text_with_outline(draw, line, (x, y), font_bold, text_color)
                y += line_height

            # Add small topic label at the very bottom
            topic_label = topic[:40]
            try:
                tbbox = font_small.getbbox(topic_label)
                tx = (img_w - (tbbox[2] - tbbox[0])) // 2
            except Exception:
                tx = img_w // 4
            self._draw_text_with_outline(
                draw, topic_label, (tx, img_h - 80), font_small,
                "#cccccc", outline_width=2,
            )

            # Save
            fingerprint = hashlib.sha256(
                f"{fingerprint_base}-{i}-{placement['name']}".encode()
            ).hexdigest()[:8]
            output_path = OUTPUT_DIR / f"thumb_ab_{fingerprint}.jpg"
            variant.save(output_path, "JPEG", quality=92)

            variants.append({
                "path": str(output_path),
                "placement": placement["name"],
                "hook_variant": hook_fmt,
                "color_scheme": color_key,
                "fingerprint": fingerprint,
                "topic": topic,
                "display_text": display_text,
            })

            logger.info(
                "Variant %d: %s | placement=%s | colors=%s",
                i + 1, fingerprint, placement["name"], color_key,
            )

        return variants

    def save_ab_state(
        self,
        variants: List[Dict],
        video_topic: str,
        youtube_id: str = "",
    ) -> str:
        """Save A/B state for later CTR-based selection."""
        state = {
            "topic": video_topic,
            "youtube_id": youtube_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "variants": variants,
            "winner": None,
            "ctr_data": {},
        }

        os.makedirs(AB_STATE_PATH.parent, exist_ok=True)
        tmp = str(AB_STATE_PATH) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, AB_STATE_PATH)

        return str(AB_STATE_PATH)

    @staticmethod
    def select_winner(
        ab_state_path: str = "",
        ctr_threshold: float = 0.04,
    ) -> Optional[Dict]:
        """Select the winning thumbnail based on CTR data.

        Reads data/ab_thumbnail_state.json, picks the variant with highest
        CTR above the threshold. Call this 4-6 hours after upload.

        Returns the winning variant dict or None.
        """
        path = Path(ab_state_path or str(AB_STATE_PATH))
        if not path.exists():
            logger.warning("No A/B state file found.")
            return None

        with open(path) as f:
            state = json.load(f)

        variants = state.get("variants", [])
        ctr_data = state.get("ctr_data", {})

        if not ctr_data:
            logger.info("No CTR data yet — wait 4-6h after upload.")
            return None

        best = None
        best_ctr = 0
        for v in variants:
            fp = v.get("fingerprint", "")
            ctr = ctr_data.get(fp, 0)
            if ctr > best_ctr:
                best_ctr = ctr
                best = v

        if best and best_ctr >= ctr_threshold:
            state["winner"] = best
            state["winner_ctr"] = best_ctr
            tmp = str(path) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, path)
            logger.info("Winner: %s (CTR: %.2f%%)", best["fingerprint"], best_ctr * 100)
            return best

        logger.info("No variant above %.1f%% CTR threshold.", ctr_threshold * 100)
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scripts/generate_ab_thumbnails.py --topic \"Your topic here\"")
        print("       python scripts/generate_ab_thumbnails.py --select-winner")
        sys.exit(1)

    if sys.argv[1] == "--select-winner":
        winner = ThumbnailABGenerator.select_winner()
        if winner:
            print(f"Winner: {winner['fingerprint']} — {winner['display_text'][:60]}")
            print(f"File: {winner['path']}")
        else:
            print("No winner yet.")
        sys.exit(0)

    # Parse --topic
    topic = ""
    for i, arg in enumerate(sys.argv):
        if arg == "--topic" and i + 1 < len(sys.argv):
            topic = sys.argv[i + 1]
            break

    if not topic:
        topic = "Why Your Body Does This"

    hook = topic  # Use topic as hook if no separate hook provided

    # Create a placeholder base image
    base = Image.new("RGB", (1080, 1920), "#1a1a2e")

    gen = ThumbnailABGenerator(style="body_glitches")
    variants = gen.generate_variants(base, topic, hook, num_variants=5)

    print(f"\n✅ Generated {len(variants)} thumbnail variants:")
    for v in variants:
        print(f"  📸 {v['fingerprint']} | {v['placement']:12s} | {v['color_scheme']:10s} | {v['display_text'][:50]}")
    print(f"\n📁 Output: {OUTPUT_DIR}/")
