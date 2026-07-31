#!/usr/bin/env python3
import os
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
THUMB_DIR = ROOT / "output" / "USA_Repair_2026_07_29" / "new_thumbnails"

def generate_mock_thumbnails():
    os.makedirs(THUMB_DIR, exist_ok=True)
    for i in range(1, 24):
        file_path = THUMB_DIR / f"vid_repair_{i}.jpg"
        if not file_path.exists():
            # Create a simple solid image
            img = Image.new("RGB", (1280, 720), color=(30, 30, 30))
            draw = ImageDraw.Draw(img)
            draw.text((100, 300), f"USA Repair #{i}", fill=(255, 0, 0))
            img.save(file_path, "JPEG")
    print(f"Mock thumbnails generated in {THUMB_DIR}")

if __name__ == "__main__":
    generate_mock_thumbnails()
