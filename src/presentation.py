"""Post-render polish: subtle original ambient audio and platform-specific cover art."""
from __future__ import annotations

import logging
import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

log = logging.getLogger("mrnextep.presentation")


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _make_original_ambient(path: Path, duration: float, sample_rate: int = 44100) -> None:
    """Synthesize a low-volume ambient bed locally; no third-party track or music license."""
    frames = max(1, int(duration * sample_rate))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        chunk_size = 8192
        for start in range(0, frames, chunk_size):
            data = bytearray()
            for i in range(start, min(frames, start + chunk_size)):
                t = i / sample_rate
                envelope = min(1.0, t / 1.2, max(0.0, (duration - t) / 1.5))
                chord = (
                    0.48 * math.sin(2 * math.pi * 110.0 * t)
                    + 0.29 * math.sin(2 * math.pi * 164.81 * t)
                    + 0.18 * math.sin(2 * math.pi * 220.0 * t)
                    + 0.08 * math.sin(2 * math.pi * 329.63 * t)
                )
                sample = int(max(-1.0, min(1.0, chord * envelope * 0.10)) * 32767)
                data.extend(struct.pack("<hh", sample, sample))
            out.writeframesraw(data)


def add_subtle_background_music(video: Path) -> Path:
    """Mix a gentle ambient bed under narration, keeping speech at the foreground."""
    if os.getenv("BACKGROUND_MUSIC_ENABLED", "true").strip().lower() in {"0", "false", "no"}:
        return video
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        check=True, capture_output=True, text=True,
    )
    duration = float(probe.stdout.strip())
    if duration <= 0:
        raise RuntimeError("Cannot add background music to a zero-duration video")
    bed = video.with_name("ambient_bed.wav")
    temp_video = video.with_name(video.stem + "_mixed.mp4")
    _make_original_ambient(bed, duration)
    fade_out_start = max(0.0, duration - 1.5)
    try:
        _run([
            "ffmpeg", "-y", "-i", str(video), "-i", str(bed),
            "-filter_complex",
            f"[0:a]volume=1.0[voice];[1:a]volume=0.12,afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out_start:.3f}:d=1.5[bed];[voice][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(temp_video),
        ])
        temp_video.replace(video)
        log.info("Added subtle original ambient bed beneath narration (music mix level 12%%).")
        return video
    finally:
        bed.unlink(missing_ok=True)
        temp_video.unlink(missing_ok=True)


def generate_platform_thumbnails(video: Path, title: str, output_dir: Path) -> dict[str, Path]:
    """Generate YouTube 16:9 and Facebook/Instagram Reels 9:16 covers from a video frame."""
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_path = output_dir / "thumbnail_source_frame.jpg"
    paths = {
        "youtube": output_dir / "mr_nextep_thumb_youtube.jpg",
        "instagram": output_dir / "mr_nextep_thumb_instagram.jpg",
        "facebook": output_dir / "mr_nextep_thumb_facebook.jpg",
    }
    try:
        _run(["ffmpeg", "-y", "-ss", "00:00:01.000", "-i", str(video),
              "-frames:v", "1", "-q:v", "2", str(frame_path)])
        if not frame_path.exists():
            raise RuntimeError("Thumbnail frame extraction returned no image")
        with Image.open(frame_path) as raw:
            frame = ImageOps.exif_transpose(raw).convert("RGB")
        words = " ".join(str(title or "DARK SCIENCE").upper().split()).split()[:7]
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > 15:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        lines = lines[:4] or ["DARK SCIENCE"]

        # YouTube landscape layout: soft cinematic backdrop, sharp portrait frame, clear title.
        landscape = ImageOps.fit(frame, (1280, 720), method=Image.Resampling.LANCZOS)
        landscape = ImageEnhance.Brightness(landscape.filter(ImageFilter.GaussianBlur(22))).enhance(0.38).convert("RGBA")
        portrait = ImageOps.fit(frame, (405, 720), method=Image.Resampling.LANCZOS)
        landscape.alpha_composite(portrait.convert("RGBA"), (0, 0))
        draw = ImageDraw.Draw(landscape)
        draw.rectangle((405, 0, 1280, 720), fill=(5, 10, 20, 185))
        font = _font(62)
        y = 185 if len(lines) <= 3 else 125
        for line in lines:
            draw.text((455, y + 4), line, font=font, fill=(0, 0, 0, 255),
                      stroke_width=3, stroke_fill=(0, 0, 0, 255))
            draw.text((450, y), line, font=font, fill=(255, 236, 150, 255),
                      stroke_width=2, stroke_fill=(20, 25, 35, 255))
            y += 82
        landscape.convert("RGB").save(paths["youtube"], "JPEG", quality=93, optimize=True)

        # Reels cover text is placed in the central safe area, away from app controls.
        for platform in ("instagram", "facebook"):
            canvas = ImageOps.fit(frame, (1080, 1920), method=Image.Resampling.LANCZOS).convert("RGBA")
            shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(shade).rectangle((0, 560, 1080, 1380), fill=(0, 0, 0, 110))
            canvas = Image.alpha_composite(canvas, shade)
            draw = ImageDraw.Draw(canvas)
            size = 82 if max((len(line) for line in lines), default=0) < 14 else 68
            font = _font(size)
            y = max(690, min(1040, 960 - (len(lines) * (size + 24)) // 2))
            for line in lines:
                draw.text((544, y + 6), line, font=font, fill=(0, 0, 0, 240),
                          anchor="mm", stroke_width=6, stroke_fill=(0, 0, 0, 255))
                draw.text((540, y), line, font=font, fill=(255, 236, 150, 255),
                          anchor="mm", stroke_width=4, stroke_fill=(5, 10, 20, 255))
                y += size + 24
            canvas.convert("RGB").save(paths[platform], "JPEG", quality=93, optimize=True)
        return paths
    except Exception as exc:
        log.warning("Platform cover generation failed (%s)", type(exc).__name__)
        return {}
    finally:
        frame_path.unlink(missing_ok=True)


def prepare_published_assets(video: Path, title: str, output_dir: Path) -> dict[str, str]:
    """Apply audio polish and return only cover assets successfully generated."""
    add_subtle_background_music(video)
    covers = generate_platform_thumbnails(video, title, output_dir)
    return {name: str(path) for name, path in covers.items() if path.exists()}
