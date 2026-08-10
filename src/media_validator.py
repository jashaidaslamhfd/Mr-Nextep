"""Strict media checks used before rendering and uploading."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Dict

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def _ffprobe_exe() -> str:
    """Return a usable ffprobe path, or "" when none exists.

    Prefer a system 'ffprobe'; otherwise try next to the imageio-ffmpeg
    binary. Returning "" instead of the literal string "ffprobe" matters:
    the caller can then fall back to parsing ffmpeg's own output rather than
    raising, because imageio-ffmpeg ships ffmpeg WITHOUT an ffprobe beside it
    — so the old "last resort" guess always produced FileNotFoundError on any
    machine that had the pip package but not the system tool.
    """
    system = shutil.which("ffprobe")
    if system:
        return system
    try:
        import imageio_ffmpeg
    except Exception as exc:  # noqa: BLE001 - probe fallback must never crash
        logger.debug("ffprobe discovery failed (no imageio_ffmpeg): %s", exc)
        return ""
    candidate = imageio_ffmpeg.get_ffmpeg_exe().replace("ffmpeg", "ffprobe")
    if os.path.isfile(candidate):
        return candidate

    return ""


def _ffmpeg_exe() -> str:
    """A usable ffmpeg path (system first, then the bundled imageio binary)."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _inspect_with_ffmpeg(path: str) -> Dict:
    """Probe a file using ffmpeg's stderr banner when ffprobe is unavailable.

    ffmpeg prints the same container/stream facts we need before it complains
    about having no output file, so this recovers duration, resolution and the
    presence of an audio track without a second binary.

    This exists because a missing ffprobe used to abort the pipeline AFTER the
    video had already been rendered — throwing away ~40 minutes of generation
    over a tool that was never required to produce the file in the first place.
    """
    import re

    result = subprocess.run(
        [_ffmpeg_exe(), "-hide_banner", "-i", path],
        capture_output=True, text=True, timeout=60,
    )
    text = result.stderr or ""

    duration_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    if not duration_match:
        raise MediaValidationError(
            f"Neither ffprobe nor ffmpeg could read {path}. Install ffmpeg."
        )
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    size_match = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", text)
    width, height = (int(size_match.group(1)), int(size_match.group(2))) if size_match else (0, 0)

    streams = []
    if size_match:
        streams.append({"codec_type": "video", "width": width, "height": height})
    if re.search(r"Stream #\d+:\d+.*?: Audio:", text):
        streams.append({"codec_type": "audio"})
    return {"streams": streams, "format": {"duration": f"{duration}"}}


def _probe_media(path: str) -> Dict:
    """ffprobe JSON if available, otherwise the ffmpeg-derived equivalent."""
    exe = _ffprobe_exe()
    if exe:
        try:
            result = subprocess.run(
                [exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                capture_output=True, text=True, timeout=30, check=True,
            )
            return json.loads(result.stdout)
        except Exception:
            # Fall through to ffmpeg rather than failing: a broken ffprobe must
            # not cost us a finished render.
            pass
    return _inspect_with_ffmpeg(path)


class MediaValidationError(RuntimeError):
    pass


# The vertical canvas every platform expects for Shorts/Reels. Kept as a
# module-level constant (rather than a literal inside the check) so tests and
# low-memory environments can render a smaller proxy without disabling the
# validation itself.
_EXPECTED_CANVAS = (1080, 1920)


def validate_scene_image(path: str, min_side: int = 512) -> Dict:
    """Decode an image and reject error pages, corrupt, tiny or black assets."""
    if not path or not os.path.isfile(path):
        raise MediaValidationError(f"Image does not exist: {path}")
    try:
        with Image.open(path) as probe:
            probe.verify()
        with Image.open(path) as image:
            image = image.convert("RGB")
            width, height = image.size
            if min(width, height) < min_side:
                raise MediaValidationError(f"Image too small: {width}x{height}")
            sample = np.asarray(image.resize((64, 64)), dtype=np.float32)
            brightness = float(sample.mean())
            variation = float(sample.std())
            if brightness < 12.0:
                raise MediaValidationError(f"Near-black image: brightness={brightness:.1f}")
            if variation < 2.0:
                raise MediaValidationError(f"Almost blank image: variation={variation:.1f}")
            return {"width": width, "height": height, "brightness": brightness, "variation": variation}
    except MediaValidationError:
        raise
    except Exception as exc:
        raise MediaValidationError(f"Invalid image {path}: {exc}") from exc


def pad_video_to_minimum(path: str, min_seconds: float) -> str:
    """If video is slightly too short, pad it with a freeze frame at the end.
    
    Returns the path to the padded video (or original if no padding needed).
    """
    # First probe the current video (ffprobe, or ffmpeg as a fallback)
    try:
        data = _probe_media(path)
    except Exception as exc:
        raise MediaValidationError(f"Could not measure video before padding: {exc}") from exc

    duration = float(data.get("format", {}).get("duration") or 0)
    
    # If video is already long enough, return original
    if duration >= min_seconds:
        return path
    
    # Calculate how much padding we need
    padding_needed = min_seconds - duration + 0.5  # Add 0.5s buffer
    
    # Create padded video using ffmpeg - freeze last frame
    output_path = path.replace(".mp4", "_padded.mp4")
    
    # Use ffmpeg to pad with freeze frame
    # tpad filter: duplicate last frame to extend video
    # tpad.stop is a frame count, not milliseconds. The renderer outputs 30fps.
    pad_frames = max(1, min(int(round(padding_needed * 30)), 30 * 20))
    filter_complex = f"tpad=stop={pad_frames}:stop_mode=clone"
    
    command = [
        _ffmpeg_exe(), "-y", "-i", path,
        "-vf", filter_complex,
        "-af", "apad",
        "-t", f"{min_seconds + 0.5:.3f}",
        "-c:v", "libx264", "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 100000:
            # Replace original with padded version
            os.replace(output_path, path)
            return path
    except Exception:
        # If padding fails, clean up and return original
        if os.path.isfile(output_path):
            os.remove(output_path)
    
    return path


def probe_video(path: str) -> Dict:
    """Use ffprobe to enforce a playable 9:16 Short with audio."""
    if not os.path.isfile(path) or os.path.getsize(path) < 100_000:
        raise MediaValidationError(f"Video missing or too small: {path}")
    try:
        data = _probe_media(path)
    except MediaValidationError:
        raise
    except Exception as exc:
        raise MediaValidationError(f"Could not inspect rendered video: {exc}") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise MediaValidationError("Rendered file must contain video and audio streams")
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if (width, height) != _EXPECTED_CANVAS:
        raise MediaValidationError(
            f"Wrong canvas {width}x{height}; expected "
            f"{_EXPECTED_CANVAS[0]}x{_EXPECTED_CANVAS[1]}"
        )
    # Duration bounds come from algorithm_policy so the renderer, the writer
    # and this gate can never disagree about what a valid Short is. The gate
    # deliberately allows a wider band than the policy ideal: its job is to
    # catch a BROKEN render (truncated file, runaway narration), not to
    # second-guess an editorial choice that already passed the earlier checks.
    try:
        from algorithm_policy import YOUTUBE, duration_policy, env_float
        policy_floor, _ideal, policy_ceiling = duration_policy(YOUTUBE)
    except Exception:  # pragma: no cover - keeps validation usable standalone
        policy_floor, policy_ceiling = 30.0, 42.0
        def env_float(name, fallback):
            return float(os.environ.get(name) or fallback)

    # env_float ignores retired overrides, so a stale workflow pinning the old
    # 40-55s window cannot widen this gate back open.
    max_seconds = env_float("TARGET_MAX_SECONDS", policy_ceiling) + 0.25
    # A Short far below the floor (e.g. a truncated render) must not publish.
    # The grace below the floor covers normal TTS variance.
    min_seconds = max(0.0, env_float("TARGET_MIN_SECONDS", policy_floor) - 5.0)
    if duration <= 0 or duration > max_seconds:
        raise MediaValidationError(f"Wrong duration {duration:.2f}s; maximum {max_seconds:.2f}s")
    if duration < min_seconds:
        raise MediaValidationError(f"Video too short {duration:.2f}s; minimum {min_seconds:.2f}s")
    return {"width": width, "height": height, "duration": duration}
