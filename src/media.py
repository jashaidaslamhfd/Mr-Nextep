from __future__ import annotations
import json
import subprocess
import wave
import hashlib
import os
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from config import Settings
from visuals import download_clip, query_for_scene

W, H = 1080, 1920

def font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def make_overlay(word: str, index: int, path: Path) -> None:
    """Render high-contrast, stroke-bordered text overlay optimized for phone screens."""
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # 2026 Viral Caption Styling: Vibrant Yellow & Cyan with heavy dark outline
    accent = (255, 230, 0) if index % 2 == 0 else (0, 240, 255)
    f = font(108)

    # Position at 58% height (safe-zone: away from top channel header & bottom caption)
    x = W // 2
    y = int(H * 0.58)

    # Heavy dark stroke so captions pop against both bright and dark backgrounds
    draw.text(
        (x, y),
        word.upper(),
        font=f,
        fill=accent,
        anchor="mm",
        stroke_width=6,
        stroke_fill=(0, 0, 0, 240)
    )
    image.save(path)

def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)

def _make_audio(text: str, path: Path, duration_hint: float) -> float:
    """Generate cinematic narration with edge-tts and master to -14 LUFS standard."""
    mp3 = path.with_suffix(".mp3")
    # Upgrade voice from monotonous GuyNeural to deep authoritative ChristopherNeural
    voice = os.getenv("EDGE_US_VOICE", "en-US-ChristopherNeural")
    rate = os.getenv("EDGE_US_RATE", "-2%")
    pitch = os.getenv("EDGE_US_PITCH", "-3Hz")

    try:
        cmd = ["edge-tts", "--voice", voice, f"--rate={rate}", f"--pitch={pitch}", "--text", text, "--write-media", str(mp3)]
        try:
            _run(cmd)
        except Exception:
            _run(["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", str(mp3)])

        # Master audio: EBU R128 (-14 LUFS standard for YouTube Shorts & Reels) + 80Hz bass boost
        _run([
            "ffmpeg", "-y", "-i", str(mp3),
            "-af", "loudnorm=I=-14:LRA=7:TP=-1.5,equalizer=f=80:width_type=h:width=50:g=3",
            "-ar", "44100",
            "-ac", "2",
            str(path)
        ])
        mp3.unlink(missing_ok=True)

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            check=True, capture_output=True, text=True
        )
        return float(probe.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        mp3.unlink(missing_ok=True)
        raise RuntimeError(f"Audible narration failed: {exc}") from exc

def render(script: dict, settings: Settings) -> Path:
    settings.ensure_dirs()
    scene_dir = settings.output_dir / "scenes"
    shutil.rmtree(scene_dir, ignore_errors=True)
    scene_dir.mkdir(exist_ok=True)

    segments: list[Path] = []
    clip_hashes: list[str] = []
    total = 0.0

    for index, scene in enumerate(script["scenes"], 1):
        words = scene["caption"].split() or [""]
        duration = max(1.8, min(3.0, 0.32 * len(words)))
        audio = settings.output_dir / f"audio_{index:02d}.wav"

        if settings.dry_run:
            with wave.open(str(audio), "wb") as out:
                out.setnchannels(2)
                out.setsampwidth(2)
                out.setframerate(44100)
                out.writeframes(b"\0\0" * int(duration * 44100))
        else:
            duration = _make_audio(str(scene.get("narration") or scene["caption"]), audio, duration)
            duration = max(1.8, min(3.0, duration))

        clip = scene_dir / f"clip_{index:02d}.mp4"
        scene_query = query_for_scene({**scene, "caption": f"{scene.get('caption', 'dark science')} scene {index}"})
        download_clip(scene_query, clip, set(clip_hashes))
        clip_hash = hashlib.sha256(clip.read_bytes()).hexdigest()
        clip_hashes.append(clip_hash)

        frames: list[Path] = []
        for word_index, word in enumerate(words):
            overlay = scene_dir / f"overlay_{index:02d}_{word_index:03d}.png"
            make_overlay(word, index, overlay)
            frames.append(overlay)

        listfile = scene_dir / f"frames_{index:02d}.txt"
        listfile.write_text(
            "\n".join(f"file '{path.resolve()}'\nduration {duration / len(frames):.4f}" for path in frames) +
            f"\nfile '{frames[-1].resolve()}'\n",
            encoding="utf-8"
        )

        segment = scene_dir / f"segment_{index:02d}.mp4"
        _run([
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(clip),
            "-f", "concat", "-safe", "0", "-i", str(listfile),
            "-i", str(audio),
            "-filter_complex",
            "[0:v]trim=duration=30,setpts=PTS-STARTPTS[bg];"
            "[1:v]format=rgba,trim=duration=30,setpts=PTS-STARTPTS[fg];"
            "[bg][fg]overlay=0:0:shortest=1[v]",
            "-map", "[v]", "-map", "2:a",
            "-t", f"{duration:.3f}",
            "-r", "30",
            "-c:v", "libx264", "-b:v", "6500k", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(segment),
        ])
        segments.append(segment)
        total += duration

    concat = settings.output_dir / "concat.txt"
    concat.write_text("\n".join(f"file '{path.resolve()}'" for path in segments), encoding="utf-8")
    video = settings.output_dir / "mr_nextep_short.mp4"

    # Final Render with high-bitrate video stream and faststart
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-t", f"{total:.3f}",
        "-r", "30",
        "-c:v", "libx264", "-b:v", "7000k", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(video)
    ])
    (settings.output_dir / "clip_hashes.json").write_text(json.dumps(clip_hashes), encoding="utf-8")
    return video

def validate(video: Path, settings: Settings) -> dict[str, object]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", str(video)],
        check=True, capture_output=True, text=True
    )
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
