"""
src/audio_reactive.py

Detects energy peaks in narration audio to time visual pattern interrupts.
When the voice gets louder/more energetic, the video should CUT to a new
visual — resetting the viewer's "should I swipe?" timer.

This is 100% free — uses soundfile + numpy for energy analysis, no librosa needed.

Usage:
    from audio_reactive import detect_energy_peaks
    peaks = detect_energy_peaks("output/voice/scene_00.mp3")
    # Returns: [{'time': float, 'energy': float, 'suggested_cut': bool}, ...]
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def detect_energy_peaks(audio_path: str,
                         threshold_percentile: int = 75,
                         min_gap: float = 0.8) -> list:
    """Analyze audio energy to find natural cut points.

    Args:
        audio_path: Path to audio file (WAV, MP3 via soundfile)
        threshold_percentile: Energy level above which = "peak" (75 = top 25%)
        min_gap: Minimum seconds between peaks (prevents rapid cuts)

    Returns:
        [{'time': float, 'energy': float, 'relative_energy': float,
          'suggested_cut': bool, 'cut_type': str}, ...]
    """
    try:
        data, samplerate = sf.read(audio_path)
    except Exception as e:
        logger.warning("Could not read audio %s: %s", audio_path, e)
        return []

    # Convert to mono if stereo
    if len(data.shape) > 1:
        data = np.mean(data, axis=1)

    # Calculate short-time energy in 50ms windows
    window_size = int(samplerate * 0.05)  # 50ms
    hop_size = int(samplerate * 0.025)    # 25ms hop

    energies = []
    times = []
    for i in range(0, len(data) - window_size, hop_size):
        window = data[i:i + window_size]
        energy = float(np.sqrt(np.mean(window ** 2)))  # RMS energy
        energies.append(energy)
        times.append(i / samplerate)

    if not energies:
        return []

    energies = np.array(energies)
    times = np.array(times)

    # Normalize energies to 0-1
    max_energy = np.max(energies)
    if max_energy > 0:
        relative_energies = energies / max_energy
    else:
        relative_energies = energies

    # Find peaks above threshold
    threshold = np.percentile(energies, threshold_percentile)

    peaks = []
    last_peak_time = -min_gap  # allow first peak at t=0

    for i, (t, e, re) in enumerate(zip(times, energies, relative_energies)):
        if e >= threshold and (t - last_peak_time) >= min_gap:
            # Classify the cut type based on energy level
            if re > 0.9:
                cut_type = "hard"        # loud moment → hard cut
            elif re > 0.7:
                cut_type = "emphasis"    # emphasis → zoom/flash
            else:
                cut_type = "soft"        # subtle peak → gentle transition

            peaks.append({
                "time": round(t, 3),
                "energy": round(float(e), 4),
                "relative_energy": round(float(re), 4),
                "suggested_cut": True,
                "cut_type": cut_type,
            })
            last_peak_time = t

    # Always suggest a cut at the very beginning
    if peaks and peaks[0]["time"] > 0.5:
        peaks.insert(0, {
            "time": 0.0,
            "energy": round(float(energies[0]), 4),
            "relative_energy": round(float(relative_energies[0]), 4),
            "suggested_cut": True,
            "cut_type": "opening",
        })

    logger.info("Audio analysis: %d peaks found in %.1fs audio",
                len(peaks), times[-1] if len(times) else 0)

    return peaks


def compute_scene_cuts(segments: list, scenes: list) -> list:
    """Analyze all audio segments and compute optimal cut points per scene.

    Returns a list of cut instructions for video_editor.py:
    [{
        'scene_index': int,
        'cuts': [{'time_in_scene': float, 'cut_type': str, 'visual_direction': str}]
    }]
    """
    all_cuts = []

    for seg_idx, segment in enumerate(segments):
        audio_path = segment.get("path", "")
        duration = segment.get("duration", 3.0)

        if not audio_path or not os.path.exists(audio_path):
            # No audio file — generate cuts based on word count
            word_timings = segment.get("word_timings", [])
            if word_timings:
                # Cut every 3-4 words
                cuts = []
                word_group_size = 4
                for i in range(0, len(word_timings), word_group_size):
                    group = word_timings[i:i + word_group_size]
                    if group:
                        cuts.append({
                            "time_in_scene": round(group[0]["offset"], 3),
                            "cut_type": "word_group",
                            "visual_direction": _suggest_visual(i, seg_idx),
                        })
                all_cuts.append({
                    "scene_index": seg_idx,
                    "cuts": cuts,
                })
            continue

        # Analyze actual audio
        peaks = detect_energy_peaks(audio_path)
        cuts = []
        for peak in peaks:
            cuts.append({
                "time_in_scene": peak["time"],
                "cut_type": peak["cut_type"],
                "visual_direction": _suggest_visual(
                    len(cuts), seg_idx, peak["cut_type"]
                ),
            })

        all_cuts.append({
            "scene_index": seg_idx,
            "cuts": cuts,
        })

    return all_cuts


def _suggest_visual(cut_index: int, scene_index: int,
                     cut_type: str = "soft") -> str:
    """Suggest visual direction for a cut point."""
    directions = {
        "hard": ["zoom_in_close", "flash_white", "shake_horizontal"],
        "emphasis": ["zoom_in_slow", "color_shift", "vignette_pulse"],
        "soft": ["slight_zoom", "pan_left", "pan_right"],
        "word_group": ["zoom_in_slow", "slight_zoom", "pan_left"],
        "opening": ["zoom_out_reveal"],
    }

    options = directions.get(cut_type, directions["soft"])
    return options[cut_index % len(options)]


def generate_cut_map(all_cuts: list) -> dict:
    """Generate a summary cut map for the video editor.

    Returns timing instructions that video_editor.py can use to apply
    Ken Burns effects, zooms, and transitions at the right moments.
    """
    total_cuts = sum(len(c["cuts"]) for c in all_cuts)
    hard_cuts = sum(
        1 for c in all_cuts
        for cut in c["cuts"]
        if cut["cut_type"] in ("hard", "emphasis")
    )

    return {
        "total_cuts": total_cuts,
        "hard_cuts": hard_cuts,
        "soft_cuts": total_cuts - hard_cuts,
        "scenes": all_cuts,
        "avg_cuts_per_scene": round(total_cuts / max(len(all_cuts), 1), 1),
    }


if __name__ == "__main__":
    # Test with a synthetic signal
    import tempfile

    sr = 22050
    duration = 10.0
    t = np.linspace(0, duration, int(sr * duration))

    # Simulate speech with varying energy
    signal = np.sin(2 * np.pi * 200 * t) * 0.3
    # Add energy bursts at 2s, 5s, 8s
    for peak_time in [2.0, 5.0, 8.0]:
        mask = np.abs(t - peak_time) < 0.3
        signal[mask] *= 3.0

    # Add silence
    signal[int(sr * 6):int(sr * 7)] = 0

    tmp_path = "/tmp/test_audio_reactive.wav"
    sf.write(tmp_path, signal, sr)

    peaks = detect_energy_peaks(tmp_path)
    print(f"Found {len(peaks)} energy peaks:")
    for p in peaks:
        print(f"  t={p['time']:.2f}s  energy={p['relative_energy']:.2f}  "
              f"type={p['cut_type']}")

    os.remove(tmp_path)
