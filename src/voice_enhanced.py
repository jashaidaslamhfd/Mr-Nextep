"""
src/voice_enhanced.py

Premium-quality TTS using Microsoft Edge Neural voices (100% free, no API key).
These are the same voices used by Edge browser's Read Aloud — neural, natural,
American English. A massive upgrade from Kokoro's synthetic output.

Voice selection for dark-mystery body-science niche:
  - Primary: en-US-BrianNeural (male, conversational, slightly deep)
  - Alt 1: en-US-AndrewNeural (male, warm, authoritative)
  - Alt 2: en-US-GuyNeural (male, news/narration style)
  - Alt 3: en-US-ChristopherNeural (male, deep, storytelling)

Usage:
    from voice_enhanced import generate_enhanced_voice
    segments = generate_enhanced_voice(scenes, output_dir="output/voice")
    # Returns: [{'path': str, 'duration': float, 'word_timings': [...]}]
"""

import asyncio
import json
import logging
import os
import random
import re
import struct
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


VOICE_POOL = [
    {
        "id": "en-US-BrianNeural",
        "name": "Brian",
        "style": "conversational",
        "gender": "male",
        "mood": "calm authoritative",
        "speed": "-5%",       # slightly slower = more gravitas
        "pitch": "-2Hz",      # slightly deeper
    },
    {
        "id": "en-US-AndrewNeural",
        "name": "Andrew",
        "style": "conversational",
        "gender": "male",
        "mood": "warm storyteller",
        "speed": "-3%",
        "pitch": "+0Hz",
    },
    {
        "id": "en-US-GuyNeural",
        "name": "Guy",
        "style": "news",
        "gender": "male",
        "mood": "serious narrator",
        "speed": "-8%",       # slower for gravitas
        "pitch": "-3Hz",
    },
    {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher",
        "style": "news",
        "gender": "male",
        "mood": "deep mysterious",
        "speed": "-6%",
        "pitch": "-4Hz",      # deepest voice
    },
    {
        "id": "en-US-EricNeural",
        "name": "Eric",
        "style": "news",
        "gender": "male",
        "mood": "matter-of-fact",
        "speed": "-4%",
        "pitch": "-1Hz",
    },
    {
        "id": "en-US-RogerNeural",
        "name": "Roger",
        "style": "news",
        "gender": "male",
        "mood": "confident direct",
        "speed": "-2%",
        "pitch": "-2Hz",
    },
]


def _get_voice(topic: str = "other", video_id: str = "") -> dict:
    """Select a voice based on topic. Rotate to avoid repetition."""
    # Map topics to voice moods for best pairing
    topic_voice_map = {
        "brain": ["deep mysterious", "serious narrator"],    # brain = mysterious
        "muscle": ["calm authoritative", "confident direct"],  # muscle = strong
        "ear": ["warm storyteller", "matter-of-fact"],        # ear = gentle
        "health": ["confident direct", "calm authoritative"],  # health = trustworthy
        "other": ["calm authoritative", "warm storyteller"],
    }

    preferred_moods = topic_voice_map.get(topic, topic_voice_map["other"])

    # Try preferred mood first
    for mood in preferred_moods:
        matches = [v for v in VOICE_POOL if v["mood"] == mood]
        if matches:
            # Use video_id hash for deterministic rotation within the mood
            if video_id:
                idx = hash(video_id) % len(matches)
                return matches[idx]
            return random.choice(matches)

    return random.choice(VOICE_POOL)


async def _generate_segment(text: str, voice: dict, output_path: str) -> dict:
    """Generate a single voice segment with edge-tts.

    Returns: {'path': str, 'duration': float, 'word_timings': list}
    """
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice["id"],
        rate=voice.get("speed", "-5%"),
        pitch=voice.get("pitch", "-2Hz"),
    )

    # Collect audio data and word timings
    audio_data = b""
    word_timings = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            word_timings.append({
                "text": chunk["text"],
                "offset": chunk["offset"] / 10_000_000,   # ticks to seconds
                "duration": chunk["duration"] / 10_000_000,
            })

    # Write MP3
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(audio_data)

    # Get duration via soundfile (need to convert mp3→wav first or use ffprobe)
    duration = _get_audio_duration(output_path)

    return {
        "path": output_path,
        "duration": duration,
        "word_timings": word_timings,
        "voice_id": voice["id"],
        "voice_name": voice["name"],
    }


def _get_audio_duration(path: str) -> float:
    """Get audio duration in seconds. Works with MP3 via ffprobe."""
    try:
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        # Fallback: estimate from file size (MP3 ~128kbps)
        try:
            size = os.path.getsize(path)
            return size / (128 * 1024 / 8)  # bytes / bytes_per_second
        except Exception:
            return 3.0  # safe default


async def _generate_all_segments(scenes: list, voice: dict,
                                   output_dir: str, prefix: str = "scene"
                                   ) -> list:
    """Generate TTS for all scenes."""
    tasks = []
    for i, scene in enumerate(scenes):
        caption = scene.get("caption", "")
        if not caption:
            continue
        output_path = os.path.join(output_dir, f"{prefix}_{i:02d}.mp3")
        tasks.append(_generate_segment(caption, voice, output_path))

    results = []
    for task in tasks:
        result = await task
        results.append(result)
        logger.info("Generated: %s (%.1fs, %d words)",
                     os.path.basename(result['path']),
                     result['duration'],
                     len(result['word_timings']))

    return results


def generate_enhanced_voice(scenes: list, output_dir: str = "output/voice",
                             topic: str = "other", video_id: str = "",
                             force_voice: str = None) -> list:
    """Generate premium TTS for all scenes using Edge Neural voices.

    This is a drop-in replacement for the Kokoro-based generate_voice_segments.

    Args:
        scenes: [{'caption': str, 'visual': str, ...}, ...]
        output_dir: Where to save MP3 files
        topic: Topic category for voice selection
        video_id: For deterministic voice rotation
        force_voice: Override voice selection (voice ID string)

    Returns:
        [{'path': str, 'duration': float, 'word_timings': [...], ...}, ...]
    """
    # Select voice
    if force_voice:
        voice = next((v for v in VOICE_POOL if v["id"] == force_voice), VOICE_POOL[0])
    else:
        voice = _get_voice(topic, video_id)

    logger.info("Using voice: %s (%s) for topic: %s", voice["name"], voice["mood"], topic)

    # Generate all segments
    results = asyncio.run(
        _generate_all_segments(scenes, voice, output_dir)
    )

    # Summary
    total_duration = sum(r["duration"] for r in results)
    total_words = sum(len(r["word_timings"]) for r in results)
    logger.info("Voice generation complete: %.1fs total, %d words, %d segments",
                 total_duration, total_words, len(results))

    return results


def generate_srt_with_timings(segments: list, scenes: list) -> str:
    """Generate SRT subtitle file with precise word-level timings from Edge TTS.

    Much more accurate than the Kokoro-based timing because Edge TTS
    provides actual word boundary timestamps.

    Returns SRT content as string.
    """
    srt_lines = []
    index = 1
    cumulative_offset = 0.0

    for seg_idx, segment in enumerate(segments):
        word_timings = segment.get("word_timings", [])
        duration = segment.get("duration", 3.0)

        if not word_timings:
            # Fallback: split evenly across duration
            caption = scenes[seg_idx].get("caption", "") if seg_idx < len(scenes) else ""
            words = caption.split()
            if words:
                word_dur = duration / len(words)
                for w_idx, word in enumerate(words):
                    start = cumulative_offset + w_idx * word_dur
                    end = start + word_dur
                    srt_lines.append(f"{index}")
                    srt_lines.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
                    srt_lines.append(word)
                    srt_lines.append("")
                    index += 1
        else:
            for wt in word_timings:
                start = cumulative_offset + wt["offset"]
                end = start + wt["duration"]
                # Capitalize for emphasis
                text = wt["text"]
                if text.upper() == text and len(text) > 1:
                    text = text  # keep ALL CAPS for emphasis words
                srt_lines.append(f"{index}")
                srt_lines.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
                srt_lines.append(text)
                srt_lines.append("")
                index += 1

        cumulative_offset += duration

    return "\n".join(srt_lines)


def _format_srt_time(seconds: float) -> str:
    """Format seconds to SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def list_available_voices():
    """List all available US English voices (for debugging/selection)."""
    async def _list():
        import edge_tts
        voices = await edge_tts.list_voices()
        return [v for v in voices if v["Locale"].startswith("en-US")]

    voices = asyncio.run(_list())
    for v in voices:
        print(f"  {v['ShortName']:40s} {v['Gender']:8s}")
    return voices


if __name__ == "__main__":
    print("Available US English voices:")
    list_available_voices()

    # Quick test
    test_scenes = [
        {"caption": "Your body freezes before you hear the scary sound."},
        {"caption": "The moment your brain detects danger, it locks your muscles in place."},
        {"caption": "This happens in less than two hundred milliseconds."},
    ]
    print("\nGenerating test audio...")
    results = generate_enhanced_voice(test_scenes, output_dir="/tmp/test_voice", topic="muscle")
    for r in results:
        print(f"  {r['path']}: {r['duration']:.1f}s, {len(r['word_timings'])} words")
