from __future__ import annotations

import json
import subprocess
import wave
import hashlib
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import Settings
from visuals import download_clip, query_for_scene

W, H = 1080, 1920


def font(size: int):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_overlay(word: str, index: int, path: Path) -> None:
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    accent = (255, 86, 68) if index % 2 else (77, 210, 255)
    # Keep the first frame visually immediate: no logo bar, box, or caption border.
    draw.text((W // 2, H // 2), word, font=font(112), fill=accent, anchor="mm")
    image.save(path)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


def _make_audio(text: str, path: Path, duration_hint: float) -> float:
    """Generate audible narration; silence is not an acceptable production fallback."""
    mp3 = path.with_suffix(".mp3")
    voice = os.getenv("EDGE_US_VOICE", "en-US-GuyNeural")
    rate = os.getenv("EDGE_US_RATE", "+8%")
    try:
        _run(["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", str(mp3)])
        _run(["ffmpeg", "-y", "-i", str(mp3), "-ar", "24000", "-ac", "1", str(path)])
        mp3.unlink(missing_ok=True)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], check=True, capture_output=True, text=True)
        return float(probe.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        mp3.unlink(missing_ok=True)
        raise RuntimeError(f"Audible narration failed: {exc}") from exc


def render(script: dict, settings: Settings) -> Path:
    settings.ensure_dirs()
    scene_dir = settings.output_dir / "scenes"
    scene_dir.mkdir(exist_ok=True)
    segments: list[Path] = []
    clip_hashes: list[str] = []
    total = 0.0
    for index, scene in enumerate(script["scenes"], 1):
        words = scene["caption"].split() or [""]
        duration = max(1.4, min(3.2, 0.30 * len(words)))
        audio = settings.output_dir / f"audio_{index:02d}.wav"
        if settings.dry_run:
            with wave.open(str(audio), "wb") as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
                out.writeframes(b"\0\0" * int(duration * 24000))
        else:
            duration = _make_audio(str(scene.get("narration") or scene["caption"]), audio, duration)
            duration = max(1.1, min(3.8, duration))
        clip = scene_dir / f"clip_{index:02d}.mp4"
        download_clip(query_for_scene(scene), clip)
        clip_hash = hashlib.sha256(clip.read_bytes()).hexdigest()
        if clip_hash in clip_hashes:
            raise RuntimeError(f"Duplicate moving clip detected in scene {index}")
        clip_hashes.append(clip_hash)
        frames: list[Path] = []
        for word_index, word in enumerate(words):
            overlay = scene_dir / f"overlay_{index:02d}_{word_index:03d}.png"
            make_overlay(word, index, overlay)
            frames.append(overlay)
        listfile = scene_dir / f"frames_{index:02d}.txt"
        listfile.write_text("\n".join(f"file '{path.resolve()}'\nduration {duration / len(frames):.4f}" for path in frames) + f"\nfile '{frames[-1].resolve()}'\n", encoding="utf-8")
        segment = scene_dir / f"segment_{index:02d}.mp4"
        _run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(clip), "-f", "concat", "-safe", "0", "-i", str(listfile), "-i", str(audio),
            "-filter_complex", "[0:v]trim=duration=30,setpts=PTS-STARTPTS[bg];[1:v]format=rgba,trim=duration=30,setpts=PTS-STARTPTS[fg];[bg][fg]overlay=0:0:shortest=1[v]",
            "-map", "[v]", "-map", "2:a", "-t", f"{duration:.3f}", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(segment),
        ])
        segments.append(segment)
        total += duration
    concat = settings.output_dir / "concat.txt"
    concat.write_text("\n".join(f"file '{path.resolve()}'" for path in segments), encoding="utf-8")
    video = settings.output_dir / "mr_nextep_short.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-t", f"{total:.3f}", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(video)])
    (settings.output_dir / "clip_hashes.json").write_text(json.dumps(clip_hashes), encoding="utf-8")
    return video


def validate(video: Path, settings: Settings) -> dict[str, object]:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", str(video)], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    streams = data["streams"]
    duration = float(data["format"]["duration"])
    if not settings.min_seconds <= duration <= settings.max_seconds:
        raise RuntimeError(f"Invalid duration: {duration:.2f}s")
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise RuntimeError("Missing audio")
    if not any(stream.get("codec_type") == "video" and stream.get("width") == W and stream.get("height") == H for stream in streams):
        raise RuntimeError("Video must be 1080x1920")
    return {"width": W, "height": H, "duration": duration, "audio": True, "moving_clips": True}
