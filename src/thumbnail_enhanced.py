"""
src/thumbnail_enhanced.py

Premium-quality thumbnails using only PIL — 100% free. Creates YouTube Shorts
thumbnails that stop the scroll: dramatic gradients, bold text with glow,
vignette effects, and face-composition analysis.

Style: dark background + gradient overlay + large bold text + subtle glow.
Matches the dark-mystery body-science brand.

Usage:
    from thumbnail_enhanced import generate_enhanced_thumbnail
    path = generate_enhanced_thumbnail(
        bg_image="output/images/scene_00.jpg",
        text="YOUR BODY FREEZES",
        output_path="output/thumbnail.jpg",
        category="Body",
    )
"""

import logging
import os
import random
import re
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canvas dimensions (YouTube Shorts / IG Reels / FB Reels)
# ---------------------------------------------------------------------------
THUMB_W = 1080
THUMB_H = 1920

# ---------------------------------------------------------------------------
# Color themes per category
# ---------------------------------------------------------------------------
CATEGORY_THEMES = {
    "Brain": {
        "gradient": [(20, 0, 40), (60, 0, 120)],      # deep purple
        "text": (255, 200, 50),                          # gold
        "glow": (120, 60, 200),                          # purple glow
        "accent": (0, 200, 255),                         # cyan accent
    },
    "Body": {
        "gradient": [(40, 0, 0), (120, 10, 10)],        # dark red
        "text": (255, 60, 60),                           # red
        "glow": (255, 100, 50),                          # orange glow
        "accent": (255, 200, 0),                         # gold accent
    },
    "Ear": {
        "gradient": [(0, 20, 40), (10, 60, 100)],       # dark blue
        "text": (0, 200, 255),                           # cyan
        "glow": (0, 120, 200),                           # blue glow
        "accent": (255, 255, 100),                       # yellow accent
    },
    "Health": {
        "gradient": [(0, 30, 10), (10, 80, 30)],        # dark green
        "text": (100, 255, 100),                         # green
        "glow": (50, 200, 80),                           # green glow
        "accent": (255, 255, 255),                       # white accent
    },
    "Mystery": {
        "gradient": [(10, 0, 20), (30, 10, 50)],        # near-black purple
        "text": (200, 150, 255),                         # lavender
        "glow": (100, 50, 200),                          # purple glow
        "accent": (255, 50, 50),                         # red accent
    },
}
DEFAULT_THEME = CATEGORY_THEMES["Body"]

# Font paths
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    for fp in _FONT_PATHS:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except (IOError, OSError):
        return ImageFont.load_default()


def _create_gradient_bg(width: int, height: int,
                         color_top: tuple, color_bottom: tuple) -> Image.Image:
    """Create a vertical gradient background."""
    img = Image.new("RGB", (width, height))
    for y in range(height):
        ratio = y / height
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * ratio)
        for x in range(width):
            img.putpixel((x, y), (r, g, b))
    return img


def _create_gradient_bg_fast(width: int, height: int,
                              color_top: tuple, color_bottom: tuple) -> Image.Image:
    """Fast gradient using numpy (much faster than putpixel)."""
    import numpy as np
    top = np.array(color_top, dtype=np.float32)
    bot = np.array(color_bottom, dtype=np.float32)
    ratios = np.linspace(0, 1, height).reshape(-1, 1, 1)
    gradient = top + (bot - top) * ratios
    gradient = np.clip(gradient, 0, 255).astype(np.uint8)
    gradient = np.broadcast_to(gradient, (height, width, 3))
    return Image.fromarray(gradient.copy(), "RGB")


def _add_vignette(img: Image.Image, strength: float = 0.6) -> Image.Image:
    """Add a dark vignette around the edges."""
    import numpy as np
    w, h = img.size
    # Create radial gradient
    Y, X = np.ogrid[:h, :w]
    cx, cy = w / 2, h / 2
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    max_dist = np.sqrt(cx ** 2 + cy ** 2)
    vignette = 1.0 - strength * (dist / max_dist) ** 2
    vignette = np.clip(vignette, 0, 1)

    arr = np.array(img, dtype=np.float32)
    for c in range(3):
        arr[:, :, c] *= vignette
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def _draw_text_with_glow(draw: ImageDraw.Draw, position: tuple, text: str,
                          font: ImageFont.FreeTypeFont, text_color: tuple,
                          glow_color: tuple, glow_radius: int = 6):
    """Draw text with a glow effect."""
    x, y = position

    # Draw glow (multiple offset copies with low opacity)
    for dx in range(-glow_radius, glow_radius + 1, 2):
        for dy in range(-glow_radius, glow_radius + 1, 2):
            alpha = max(0, 255 - int(255 * (dx ** 2 + dy ** 2) / glow_radius ** 2))
            glow_with_alpha = (*glow_color, alpha // 3)
            draw.text((x + dx, y + dy), text, font=font, fill=glow_with_alpha)

    # Draw outline
    outline_range = 3
    for dx in range(-outline_range, outline_range + 1):
        for dy in range(-outline_range, outline_range + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 220))

    # Draw main text
    draw.text((x, y), text, font=font, fill=(*text_color, 255))


def _wrap_text_bold(text: str, font: ImageFont.FreeTypeFont,
                     max_width: int) -> list:
    """Wrap text to fit within max_width, returning list of lines."""
    words = text.split()
    lines = []
    current_line = ""

    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def generate_enhanced_thumbnail(
    bg_image: str = None,
    text: str = "",
    output_path: str = "output/thumbnail.jpg",
    category: str = "Body",
    variant: int = 0,
) -> str:
    """Generate a premium thumbnail with gradient, glow, and text effects.

    Args:
        bg_image: Path to background image (optional — gradient used if None)
        text: Main text overlay (large, bold, centered)
        output_path: Where to save the thumbnail
        category: Brain/Body/Ear/Health/Mystery for color theme
        variant: 0-2 for A/B testing variants

    Returns:
        Path to saved thumbnail
    """
    theme = CATEGORY_THEMES.get(category, DEFAULT_THEME)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # --- Step 1: Background ---
    if bg_image and os.path.exists(bg_image):
        try:
            bg = Image.open(bg_image).convert("RGB")
            bg = bg.resize((THUMB_W, THUMB_H), Image.LANCZOS)
        except Exception:
            bg = _create_gradient_bg_fast(THUMB_W, THUMB_H,
                                           theme["gradient"][0], theme["gradient"][1])
    else:
        bg = _create_gradient_bg_fast(THUMB_W, THUMB_H,
                                       theme["gradient"][0], theme["gradient"][1])

    # --- Step 2: Darken the background ---
    enhancer = ImageEnhance.Brightness(bg)
    bg = enhancer.enhance(0.4)  # darken to 40%

    # --- Step 3: Add gradient overlay ---
    gradient = _create_gradient_bg_fast(THUMB_W, THUMB_H,
                                         (0, 0, 0), theme["gradient"][1])
    gradient_arr = __import__('numpy').array(gradient, dtype=__import__('numpy').float32)
    bg_arr = __import__('numpy').array(bg, dtype=__import__('numpy').float32)
    # Blend: 60% background + 40% gradient
    blended = bg_arr * 0.6 + gradient_arr * 0.4
    blended = __import__('numpy').clip(blended, 0, 255).astype(__import__('numpy').uint8)
    bg = Image.fromarray(blended, "RGB")

    # --- Step 4: Vignette ---
    bg = _add_vignette(bg, strength=0.7)

    # --- Step 5: Text overlay ---
    if text:
        # Variant-specific text transformations
        display_text = text.upper()
        if variant == 1:
            # Variant 1: Question mark
            if not display_text.endswith("?"):
                display_text = f"WHY {display_text}?"
        elif variant == 2:
            # Variant 2: Exclamation
            display_text = display_text.rstrip("?.!") + "!"

        # Font size based on text length
        words = display_text.split()
        if len(words) <= 3:
            font_size = 96
        elif len(words) <= 5:
            font_size = 78
        else:
            font_size = 62

        font = _get_font(font_size)

        # Wrap text
        max_text_width = int(THUMB_W * 0.85)
        lines = _wrap_text_bold(display_text, font, max_text_width)

        # Calculate total text height
        line_height = font_size + 10
        total_height = len(lines) * line_height

        # Center vertically (slightly above center for visual balance)
        y_start = (THUMB_H - total_height) // 2 - 50

        # Create overlay for text
        overlay = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            x = (THUMB_W - text_w) // 2
            y = y_start + i * line_height

            # Alternate colors for emphasis lines
            if i % 2 == 0:
                _draw_text_with_glow(draw, (x, y), line, font,
                                      theme["text"], theme["glow"])
            else:
                _draw_text_with_glow(draw, (x, y), line, font,
                                      theme["accent"], theme["glow"])

        # Composite text onto background
        bg_rgba = bg.convert("RGBA")
        bg_rgba = Image.alpha_composite(bg_rgba, overlay)
        bg = bg_rgba.convert("RGB")

    # --- Step 6: Add accent line at top ---
    draw_final = ImageDraw.Draw(bg)
    accent_color = theme["accent"]
    # Thin accent line
    for y in range(3):
        draw_final.line([(0, 20 + y), (THUMB_W, 20 + y)],
                        fill=accent_color, width=1)

    # --- Step 7: Category badge in corner ---
    badge_font = _get_font(28)
    badge_text = f"#{category.upper()}"
    draw_final.text((40, 40), badge_text, font=badge_font, fill=theme["accent"])

    # --- Step 8: Save ---
    bg.save(output_path, "JPEG", quality=95)
    logger.info("Thumbnail saved: %s (%s theme, variant %d)",
                output_path, category, variant)

    return output_path


def generate_thumbnail_variants(bg_image: str = None,
                                 text: str = "",
                                 output_dir: str = "output/thumbnails",
                                 category: str = "Body") -> list:
    """Generate 3 A/B testing thumbnail variants.

    Returns list of {'path': str, 'variant': int, 'strategy': str}
    """
    os.makedirs(output_dir, exist_ok=True)

    variants = []
    strategies = [
        (0, "original", "Bold statement — straightforward"),
        (1, "question", "Curiosity gap — 'WHY does your BODY...?'"),
        (2, "exclamation", "Urgency — 'YOUR BODY FREEZES!'"),
    ]

    for variant_id, strategy, desc in strategies:
        path = os.path.join(output_dir, f"thumb_v{variant_id}.jpg")
        generate_enhanced_thumbnail(
            bg_image=bg_image, text=text,
            output_path=path, category=category,
            variant=variant_id,
        )
        variants.append({
            "path": path,
            "variant": variant_id,
            "strategy": strategy,
            "description": desc,
        })

    logger.info("Generated %d thumbnail variants in %s", len(variants), output_dir)
    return variants


if __name__ == "__main__":
    # Test: generate 3 variants
    variants = generate_thumbnail_variants(
        text="Your Body Freezes Before You Hear The Sound",
        output_dir="/tmp/test_thumbnails",
        category="Body",
    )
    for v in variants:
        print(f"  Variant {v['variant']}: {v['strategy']} → {v['path']}")
