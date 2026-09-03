from __future__ import annotations
import subprocess, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from config import Settings
W, H = 1080, 1920

def font(size: int):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
        if Path(path).exists(): return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def make_overlay(word: str, index: int, path: Path):
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0)); draw = ImageDraw.Draw(image)
    accent = (255, 86, 68) if index % 2 else (77, 210, 255)
    draw.text((72, 92), "MR NEXTEP · DARK SCIENCE", font=font(34), fill="white")
    draw.text((W // 2, H // 2), word, font=font(112), fill=accent, anchor="mm", stroke_width=4, stroke_fill=(5, 8, 18))
    image.save(path)

def render(script: dict, settings: Settings) -> Path:
    settings.ensure_dirs(); scene_dir = settings.output_dir / "scenes"; scene_dir.mkdir(exist_ok=True)
    segments, total = [], 0.0
    for i, scene in enumerate(script["scenes"], 1):
        words = scene["caption"].split() or [""]
        duration = max(1.4, min(3.2, 0.34 * len(words)))
        audio = settings.output_dir / f"audio_{i:02d}.wav"
        with wave.open(str(audio), "wb") as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000); out.writeframes(b"\0\0" * int(duration * 24000))
        frames = []
        for j, word in enumerate(words):
            overlay = scene_dir / f"overlay_{i:02d}_{j:03d}.png"; make_overlay(word, i, overlay); frames.append(overlay)
        listfile = scene_dir / f"frames_{i:02d}.txt"; listfile.write_text("\n".join(f"file '{p.resolve()}'\nduration {duration / len(frames):.4f}" for p in frames) + f"\nfile '{frames[-1].resolve()}'\n")
        segment = scene_dir / f"segment_{i:02d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile), "-i", str(audio), "-t", f"{duration:.3f}", "-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(segment)], check=True, capture_output=True)
        segments.append(segment); total += duration
    concat = settings.output_dir / "concat.txt"; concat.write_text("\n".join(f"file '{p.resolve()}'" for p in segments))
    video = settings.output_dir / "mr_nextep_short.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-t", f"{total:.3f}", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(video)], check=True, capture_output=True)
    return video

def validate(video: Path, settings: Settings) -> dict[str, object]:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", str(video)], check=True, capture_output=True, text=True)
    import json
    data = json.loads(result.stdout); streams = data["streams"]; duration = float(data["format"]["duration"])
    if not 15 <= duration <= 30: raise RuntimeError(f"Invalid duration: {duration:.2f}s")
    if not any(s.get("codec_type") == "audio" for s in streams): raise RuntimeError("Missing audio")
    return {"width": 1080, "height": 1920, "duration": duration, "audio": True}
