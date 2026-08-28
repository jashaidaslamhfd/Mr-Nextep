import os
import re
import random
import logging
from typing import Dict
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    ImageClip, VideoFileClip, ColorClip, CompositeVideoClip,
    AudioFileClip, AudioClip, concatenate_videoclips, concatenate_audioclips,
    CompositeAudioClip,
)
import moviepy.video.fx.all as vfx
import moviepy.audio.fx.all as afx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================
# CONSTANTS
# ============================================
CANVAS_W, CANVAS_H = 1080, 1920
# 10 ms prevents clicks without creating audible gaps between separately
# generated cloned-voice scenes.
AUDIO_EDGE_FADE = 0.01
# 2026-08-20 PROFESSIONAL MOTION (owner: "pics zoom unprofessionally"):
# Old 0.18 base + 0.18 hook extra = 36% zooms that read huge and jerky on
# phone screens. New range is deliberate and hard-capped like a real editor:
# gentle base, S-curve easing so motion starts/ends softly, subtle pan.
ZOOM_AMOUNT = 0.06
ZOOM_MAX = 0.12          # absolute ceiling on any single motion beat
PAN_PX = 25
# Render targets follow the platform policy rather than a local constant, so
# changing the strategy in one file updates the writer, the renderer and the
# validator together. Env vars still win for one-off experiments.
try:
    from algorithm_policy import (
        YOUTUBE as _YT_PLATFORM,
        duration_policy as _duration_policy,
        env_float as _env_float,
    )
    _POLICY_MIN, _POLICY_IDEAL, _POLICY_MAX = _duration_policy(_YT_PLATFORM)
except Exception:  # pragma: no cover - editor must stay importable standalone
    _POLICY_MIN, _POLICY_IDEAL, _POLICY_MAX = 30.0, 36.0, 42.0
    def _env_float(name, fallback):
        return float(os.environ.get(name) or fallback)

# env_float ignores values retired with the old strategy (e.g. the workflow's
# legacy TARGET_MAX_SECONDS="55"), so a stale deployment cannot silently
# override the policy this module is built on.
TARGET_MIN_SEC = _env_float("TARGET_MIN_SECONDS", _POLICY_MIN)
TARGET_MAX_SEC = _env_float("TARGET_MAX_SECONDS", _POLICY_MAX)

# RETENTION OPTIMIZATIONS
CAPTION_Y_FRACTION = 0.52
WORD_MIN_DURATION = 0.12
# 2026-08-15: 7% made the music effectively inaudible on most playback
# devices (users reported 'no background music at all'). 18% lands in the
# professional Shorts band (15-20% of full scale after ducking): clearly
# present, never competes with the narration. Override via MUSIC_VOLUME env.
MUSIC_VOLUME = float(os.environ.get("MUSIC_VOLUME", "0.18"))
MUSIC_SAMPLE_RATE = 24000
MUSIC_DIR = "assets/music"

SFX_ENABLED = os.environ.get("SCENE_CUT_SFX", "true").strip().lower() in (
    "true", "1", "yes", "on",
)
SFX_VOLUME = float(os.environ.get("SCENE_CUT_SFX_VOLUME", "0.08"))
SFX_MAX_FREQ = 440.0   # upper edge of the blip sweep - pleasant, not sharp


def _make_pop_sfx(sr: int = MUSIC_SAMPLE_RATE, freq: float = SFX_MAX_FREQ,
                  dur: float = 0.08, volume: float = SFX_VOLUME) -> AudioClip:
    """One broadcast-safe pop blip (sine sweep + quick decay)."""
    n = max(int(sr * dur), 1)
    t = np.linspace(0, dur, n, endpoint=False)
    sweep = freq * (1.0 - (t / dur) ** 2)          # 440 Hz down to ~0
    wave = np.sin(2.0 * np.pi * np.cumsum(sweep) / sr)
    env = np.exp(-6.0 * t / max(dur, 1e-9))        # fast natural decay
    samples = (wave * env * volume).astype(np.float32)
    def _frame(tt):
        arr = np.asarray(tt)
        values = np.interp(arr, t, samples)
        if arr.ndim == 0:
            # MoviePy uses the scalar probe to infer nchannels.
            value = float(values)
            return np.array([value, value], dtype=np.float32)
        # CompositeAudioClip expects (samples, channels) for vectorized audio.
        return np.column_stack((values, values)).astype(np.float32)

    clip = AudioClip(_frame, duration=dur, fps=sr)
    return clip.set_duration(dur)

# CAPTION STYLING
CAPTION_FONT_PATH = os.environ.get("CAPTION_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
CAPTION_FONT_SIZE = 72
CAPTION_STROKE_W = 4
CAPTION_MAX_WORDS_PER_LINE = 2
CAPTION_MIN_FONT_SIZE = 40

def _get_caption_font(font_size: int):
    """Safely resolve bold sans-serif font across Linux, macOS, and Windows."""
    candidates = [
        CAPTION_FONT_PATH,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, font_size)
            except Exception:
                continue
    return ImageFont.load_default()

# ✅ NEW: Priority improvements (safe additions)
# 2026-08-21: extended with US power words that hold viewers (banned,
# illegal, free, money, dark) - kept lowercase-ASCII-matched in _is_important_word.
IMPORTANT_WORDS = ['dangerous', 'secret', 'never', 'shocking', 'impossible',
                   'truth', 'hidden', 'actually', 'why', 'what', 'how',
                   'when', 'always', 'every', 'mind', 'brain', 'heart',
                   'real', 'finally', 'explained', 'proven', 'banned',
                   'illegal', 'free', 'money', 'dark', 'scary', 'insane',
                   'bizarre', 'unknown', 'mystery', 'warning', 'shock']

# Color themes
COLOR_THEMES = [
    {'primary': (255, 200, 50), 'secondary': (255, 100, 50), 'bg': (20, 20, 40)},   # Gold/Orange
    {'primary': (50, 200, 255), 'secondary': (50, 100, 255), 'bg': (20, 30, 50)},   # Blue
    {'primary': (255, 80, 80), 'secondary': (255, 50, 50), 'bg': (40, 20, 20)},     # Red
    {'primary': (50, 255, 150), 'secondary': (50, 200, 100), 'bg': (20, 40, 30)},   # Green
    {'primary': (200, 100, 255), 'secondary': (150, 50, 255), 'bg': (30, 20, 40)},  # Purple
]

# ============================================
# 1. IMAGE PROCESSING FUNCTIONS
# ============================================

def _cover_fit(img_path: str, out_path: str, size=(CANVAS_W, CANVAS_H)):
    """Resize+crop an image to exactly fill `size` (cover-fit)."""
    with Image.open(img_path) as _src:
        img = _src.convert("RGB")
    target_w, target_h = size
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        new_h = target_h
        new_w = int(new_h * src_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / src_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))
    img.save(out_path)
    return out_path


def _ease_in_out(frac: float) -> float:
    """Smooth S-curve so the motion starts and ends gently — the #1 cue
    separating 'professional cinematic' from 'amateur flat zoom'."""
    f = max(0.0, min(1.0, frac))
    return f * f * (3 - 2 * f)


def _ken_burns_clip(img_path: str, duration: float, direction: str, zoom_extra: float = 0.0,
                  hook_snap: bool = False) -> CompositeVideoClip:
    """Professional Ken Burns beat: HARD-CAPPED eased zoom + gentle pan.
    1.25x overscan base image prevents black border leakage on edges.
    Hook snap (scene 1): punch-in finishes inside the first ~2.4s so the
    retention-critical first 3 seconds read as a live camera move."""
    overscan_w, overscan_h = int(CANVAS_W * 1.25), int(CANVAS_H * 1.25)
    prepped = img_path.replace(".png", "_fit.png").replace(".jpg", "_fit.jpg")
    _cover_fit(img_path, prepped, size=(overscan_w, overscan_h))

    # Cap every beat — big jerky zooms are now structurally impossible
    # even when extras stack (hook scene: 0.06 base + 0.12 extra capped).
    zoom_amount = min(ZOOM_MAX, ZOOM_AMOUNT + zoom_extra)
    zoom_start, zoom_end = (1.0, 1.0 + zoom_amount) if direction == "in" else (1.0 + zoom_amount, 1.0)
    pan_dir = 1 if direction == "in" else -1

    base_clip = ImageClip(prepped).set_duration(duration)

    def scale_fn(t):
        frac = _ease_in_out(min(t / duration, 1.0)) if duration > 0 else 0
        return zoom_start + (zoom_end - zoom_start) * frac

    def pos_fn(t):
        frac = _ease_in_out(min(t / duration, 1.0)) if duration > 0 else 0
        s = scale_fn(t)
        w, h = overscan_w * s, overscan_h * s
        dx = pan_dir * PAN_PX * (frac - 0.5) * 2
        x = (CANVAS_W - w) / 2 + dx
        y = (CANVAS_H - h) / 2
        return (x, y)

    zoomed = base_clip.resize(scale_fn).set_position(pos_fn)
    bg = ColorClip(size=(CANVAS_W, CANVAS_H), color=(0, 0, 0)).set_duration(duration)
    return CompositeVideoClip([bg, zoomed], size=(CANVAS_W, CANVAS_H)).set_duration(duration)


# ============================================
# 2. CAPTION RENDERING (PRIORITY: HIGHLIGHTED WORDS)
# ============================================

def _wrap_text(draw, text, font, max_width, max_words_per_line=CAPTION_MAX_WORDS_PER_LINE):
    """Groups words into short punchy lines (max N words each)."""
    words = text.split()
    lines, current = [], []
    for w in words:
        candidate = current + [w]
        test = " ".join(candidate)
        bbox = draw.textbbox((0, 0), test, font=font, stroke_width=CAPTION_STROKE_W)
        too_wide = (bbox[2] - bbox[0]) > max_width
        too_many = len(candidate) > max_words_per_line
        if (too_wide or too_many) and current:
            lines.append(" ".join(current))
            current = [w]
        else:
            current = candidate
    if current:
        lines.append(" ".join(current))
    return lines


def _is_important_word(word: str) -> bool:
    """Check if word is important for highlighting"""
    word_clean = re.sub(r'[^a-zA-Z]', '', word.lower())
    return word_clean in IMPORTANT_WORDS


def _caption_clip(text: str, duration: float, is_important: bool = False, color_theme: Dict = None,
                    is_hook: bool = False) -> ImageClip:
    """
    Renders caption with RETENTION OPTIMIZATIONS:
    - Large, readable text
    - Short punchy lines (2-3 words)
    - High contrast (white text with black stroke)
    - ✅ Priority: Important words highlighted (yellow/red)
    - Centered on screen in vertical safe zone (Y=0.52)
    """
    if color_theme is None:
        color_theme = {'primary': (255, 255, 255), 'secondary': (255, 200, 50)}
    
    max_width = int(CANVAS_W * 0.82)
    try:
        from safe_zones import caption_baseline, safe_text_width
        baseline = caption_baseline(CANVAS_H)
        max_width = min(max_width, safe_text_width(CANVAS_W))
    except Exception:  # pragma: no cover - rendering must never depend on this
        baseline = int(CANVAS_H * 0.75)
    available_height = max(int(CANVAS_H * 0.12), baseline - int(CANVAS_H * CAPTION_Y_FRACTION))

    font_size = int(CAPTION_FONT_SIZE * 1.25) if is_hook else CAPTION_FONT_SIZE
    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    dummy_draw = ImageDraw.Draw(dummy)

    while True:
        font = _get_caption_font(font_size)

        lines = _wrap_text(dummy_draw, text, font, max_width)
        line_height = int(font_size * 1.3)
        block_height = line_height * len(lines) + 20

        widest_line = max(
            (dummy_draw.textbbox((0, 0), ln, font=font, stroke_width=CAPTION_STROKE_W)[2] for ln in lines),
            default=0,
        )

        fits_vertically = block_height <= available_height
        fits_horizontally = widest_line <= max_width

        if (fits_vertically and fits_horizontally) or font_size <= CAPTION_MIN_FONT_SIZE:
            break
        font_size -= 4

    line_height = int(font_size * 1.3)
    img_h = max(line_height * len(lines) + 20, line_height)
    widest_line = max(
        (dummy_draw.textbbox((0, 0), ln, font=font, stroke_width=CAPTION_STROKE_W)[2] for ln in lines),
        default=max_width,
    )
    canvas_w = min(max(widest_line, 1), max_width) + 40
    canvas = Image.new("RGBA", (canvas_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    y = 10
    for line in lines:
        # ✅ Priority: Check if this line has important words
        words_in_line = line.split()
        line_has_important = any(_is_important_word(w) for w in words_in_line)
        
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=CAPTION_STROKE_W)
        line_w = bbox[2] - bbox[0]
        x = max((canvas.width - line_w) / 2, 0)
        
        # ✅ Priority: Highlight important words
        if line_has_important and is_important:
            # Draw each word separately with colors
            current_x = x
            for idx, word in enumerate(words_in_line):
                word_clean = re.sub(r'[^a-zA-Z]', '', word.lower())
                display_word = word + (" " if idx < len(words_in_line) - 1 else "")
                if word_clean in IMPORTANT_WORDS:
                    color = color_theme.get('secondary', (255, 200, 50))
                    draw.text((current_x, y), display_word, font=font, fill=color,
                              stroke_width=CAPTION_STROKE_W, stroke_fill="black")
                else:
                    draw.text((current_x, y), display_word, font=font, fill=(255, 255, 255),
                              stroke_width=CAPTION_STROKE_W, stroke_fill="black")
                current_x += draw.textlength(display_word, font=font)
        else:
            # Normal rendering (all white)
            draw.text((x, y), line, font=font, fill="white",
                      stroke_width=CAPTION_STROKE_W, stroke_fill="black")
        y += line_height

    frame = np.array(canvas)
    txt = ImageClip(frame).set_duration(duration)
    return txt.set_position(('center', CAPTION_Y_FRACTION), relative=True)


def _word_by_word_clips(text: str, total_duration: float, color_theme: Dict = None,
                        scene_index: int = 0):
    """Show short, punchy 1-2 word phrases instead of dense multi-word blocks.

    Timing is punctuation/word-length weighted. This is still lightweight and
    works without another model; a future Whisper alignment can feed exact
    timestamps through the same clip interface.
    """
    words = text.split()
    if not words:
        return []
    groups, current = [], []
    for word in words:
        current.append(word)
        closes_phrase = word.rstrip().endswith((",", ".", "?", "!", ";", ":"))
        if len(current) >= 2 or closes_phrase:
            groups.append(" ".join(current))
            current = []
    if current:
        groups.append(" ".join(current))

    weights = [max(len(g.replace(" ", "")), 6) for g in groups]
    total_weight = sum(weights)
    durations = [total_duration * w / total_weight for w in weights]
    clips, cursor = [], 0.0
    for phrase, duration in zip(groups, durations):
        important = any(_is_important_word(w) for w in phrase.split())
        clip = _caption_clip(phrase, duration, important, color_theme, is_hook=(scene_index == 0)).set_start(cursor)
        clips.append(clip)
        cursor += duration
    return clips


def _hook_overlay_clip(text: str, duration: float, color_theme: Dict = None) -> ImageClip:
    """A big, bold pattern-interrupt hook line shown in the FIRST frame.

    Viral Shorts win or lose in the first ~2 seconds. Beyond a strong hook
    image, successful channels overlay a short, high-contrast text line that
    mirrors the title's keyword — this is the "sound effect + overlay within
    a second" pattern that stops the swipe, and it also aligns on-screen text
    with the title keyword that YouTube's semantic (Gemini) layer now reads.
    """
    if color_theme is None:
        color_theme = {'primary': (255, 255, 255), 'secondary': (255, 205, 40)}
    # Short, punchy, upper-case. Use only the most important few words of the
    # hook line so it is instantly scannable at thumbnail size.
    words = [re.sub(r"[^A-Za-z0-9' ]", "", w) for w in text.split()]
    stop = {"the", "a", "an", "of", "to", "is", "are", "it", "in", "your", "why", "you", "do", "does"}
    meaningful = [w for w in words if w and w.lower() not in stop]
    # keep the first meaningful word + one more for a 1-2 word hook line
    phrase = " ".join(meaningful[:2]).upper() or "WHY?"
    if not phrase:
        phrase = "WHY?"

    max_width = int(CANVAS_W * 0.9)
    font_size = 110
    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    dummy_draw = ImageDraw.Draw(dummy)
    while font_size > 60:
        font = _get_caption_font(font_size)
        # textlength() does NOT accept stroke_width; measure via textbbox.
        bb = dummy_draw.textbbox((0, 0), phrase, font=font, stroke_width=6)
        if (bb[2] - bb[0]) <= max_width:
            break
        font_size -= 6

    line_height = int(font_size * 1.15)
    img_h = line_height + 24
    bbox = dummy_draw.textbbox((0, 0), phrase, font=font, stroke_width=6)
    canvas_w = min(max(bbox[2] - bbox[0], 1), max_width) + 60
    canvas = Image.new("RGBA", (canvas_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # dark translucent band behind the text for legibility on any frame
    draw.rounded_rectangle([0, 0, canvas_w - 1, img_h - 1], radius=18,
                           fill=(0, 0, 0, 150))

    bbox2 = draw.textbbox((0, 0), phrase, font=font, stroke_width=6)
    x = max((canvas_w - (bbox2[2] - bbox2[0])) / 2, 10)
    y = 12
    accent = color_theme.get('secondary', (255, 205, 40))
    draw.text((x, y), phrase, font=font, fill=accent,
              stroke_width=6, stroke_fill="black")

    frame = np.array(canvas)
    clip = ImageClip(frame).set_duration(duration)
    # place hook line in the upper third (below the top chrome, above captions)
    return clip.set_position(('center', int(CANVAS_H * 0.16)))


# ============================================
# 3. AUDIO PROCESSING (PRIORITY: MUSIC DUCKING)
# ============================================

# FIXED 2026-07-31: Duck level 0.15 -> 0.10 for clearer voice (retention).
# Channel data showed viewers leaving early partly due to muddy voice/music mix.
# Lower duck = music quieter when narrating = higher comprehension = longer watch.
DUCK_LEVEL = float(os.environ.get("DUCK_LEVEL", "0.10"))
UNDUCK_LEVEL = float(os.environ.get("UNDUCK_LEVEL", "1.0"))
DUCK_THRESHOLD = float(os.environ.get("DUCK_THRESHOLD", "0.015"))
DUCK_SMOOTH_SEC = float(os.environ.get("DUCK_SMOOTH_SEC", "0.08"))


def _build_ducking_envelope(audio_segments: list, total_duration: float,
                            sample_rate: int = 24000,
                            window_ms: int = 50) -> np.ndarray:
    """Build a time-varying gain envelope from real voice activity.

    Reads every voice segment WAV, computes per-window RMS energy, and
    produces a smooth 1-D float32 array where:
      - value ≈ DUCK_LEVEL   when the narrator is speaking
      - value ≈ UNDUCK_LEVEL during pauses / silence between words

    Parameters
    ----------
    audio_segments : list of dict
        Each dict must have 'path' (WAV path) and 'duration' (seconds).
        The segments are laid out sequentially starting at t=0.
    total_duration : float
        Total voiceover duration in seconds (sum of all segment durations).
    sample_rate : int
        Target sample rate for the envelope (matches music clip).
    window_ms : int
        Analysis window size in milliseconds.  50 ms is a good trade-off
        between time resolution and stability.

    Returns
    -------
    np.ndarray
        1-D float32 array of length ``int(total_duration * sample_rate)``
        with values in [DUCK_LEVEL, UNDUCK_LEVEL], smoothed to avoid clicks.
    """
    n_samples = max(int(total_duration * sample_rate), 1)
    envelope = np.full(n_samples, UNDUCK_LEVEL, dtype=np.float32)

    window_samples = max(int(sample_rate * window_ms / 1000), 1)
    cursor = 0  # running sample offset into the global envelope

    for seg in audio_segments:
        seg_path = seg.get("path", "")
        seg_dur = float(seg.get("duration", 0))
        if seg_dur <= 0 or not seg_path or not os.path.isfile(seg_path):
            cursor += max(int(seg_dur * sample_rate), 0)
            continue

        try:
            audio_data, sr = sf.read(seg_path, dtype="float32")
        except Exception as e:
            logger.warning(f"Ducking: could not read {seg_path}: {e}")
            cursor += max(int(seg_dur * sample_rate), 0)
            continue

        # Mono mix-down for energy analysis
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)

        # Resample to target sample_rate if needed
        if sr != sample_rate and sr > 0:
            # Simple resample via linear interpolation (good enough for
            # envelope detection — we don't need audiophile quality here).
            duration_s = len(audio_data) / sr
            target_len = int(duration_s * sample_rate)
            if target_len > 0:
                src_idx = np.linspace(0, len(audio_data) - 1, target_len)
                audio_data = np.interp(src_idx, np.arange(len(audio_data)), audio_data)

        n_seg = len(audio_data)
        # Walk through the segment in windows and compute RMS per window
        for win_start in range(0, n_seg, window_samples):
            win_end = min(win_start + window_samples, n_seg)
            chunk = audio_data[win_start:win_end]
            if chunk.size == 0:
                continue
            rms = float(np.sqrt(np.mean(chunk ** 2)))

            # Map RMS to gain: loud → duck, quiet → unduck
            gain = DUCK_LEVEL if rms >= DUCK_THRESHOLD else UNDUCK_LEVEL

            # Write into the global envelope at the correct offset
            env_start = cursor + int(win_start * sample_rate / sr) if sr != sample_rate else cursor + win_start
            env_end = cursor + int(win_end * sample_rate / sr) if sr != sample_rate else cursor + win_end
            env_start = min(env_start, n_samples)
            env_end = min(env_end, n_samples)
            if env_start < env_end:
                envelope[env_start:env_end] = gain

        cursor += max(int(seg_dur * sample_rate), 0)

    # --- Smooth the envelope to avoid clicks ---
    # Convert smooth duration to samples and build a moving-average kernel.
    smooth_n = max(int(DUCK_SMOOTH_SEC * sample_rate), 1)
    if smooth_n > 1 and n_samples > smooth_n:
        kernel = np.ones(smooth_n, dtype=np.float32) / smooth_n
        # 'same' keeps the array length identical; edge artefacts are
        # negligible because the video has fade-in/fade-out anyway.
        envelope = np.convolve(envelope, kernel, mode="same")

    return envelope


def _synthesize_ambient_bed(duration: float, seed: int = None) -> np.ndarray:
    """Procedural dark-ambient drone for background."""
    rng = np.random.default_rng(seed)
    sr = MUSIC_SAMPLE_RATE
    n = max(int(sr * duration), sr)
    t = np.linspace(0, duration, n, endpoint=False)

    root = 48 + rng.uniform(-4, 4)
    freqs = [root, root * 1.5, root * 2.006]
    wave = np.zeros_like(t)
    for f in freqs:
        wave += 0.30 * np.sin(2 * np.pi * f * t)

    lfo = 0.7 + 0.3 * np.sin(2 * np.pi * 0.04 * t + rng.uniform(0, 2 * np.pi))
    wave *= lfo

    noise = rng.normal(0, 1, size=t.shape)
    kernel = np.ones(300) / 300
    noise = np.convolve(noise, kernel, mode="same")
    wave += 0.04 * noise

    peak = np.abs(wave).max()
    if peak > 0:
        wave = wave / peak * 0.9
    return wave.astype(np.float32)


def _get_music_track(duration: float, output_dir: str) -> str:
    """Select a mystery/science background track.

    Priority:
    1. Generated mystery tracks ('brain_tension.wav', etc.)
    2. Environment-configured track
    3. Random licensed track from assets/music
    """
    # 2026-08-21 US viewer-experience fix: unique viral dark-
    # mystery BGM per video (matches the script topic, no stock repetition,
    # no Content ID). Full failure is swallowed - a music drop must never
    # stop a video, so any exception simply falls through to legacy tiers.
    if os.environ.get("MR_VIRAL_BGM", "true").strip().lower() in (
        "true", "1", "yes", "on",
    ):
        try:
            from music_generator import pick_track
            gen = pick_track(
                theme=os.environ.get("VIDEO_TOPIC", "").strip(),
                target_duration=duration,
            )
            if gen:
                logger.info("Using AI-generated viral BGM: %s", gen)
                return gen
        except Exception as exc:  # noqa: BLE001 - never block on music
            logger.warning("Viral BGM tier failed (%s) - using legacy tiers", exc)
    configured_track = os.environ.get("MUSIC_TRACK", "").strip()
    supported_extensions = (".wav", ".mp3", ".m4a", ".ogg", ".aac", ".flac")

    # 🚀 MYSTERY PRIORITY: Use synthetic high-tension tracks if available
    mystery_tracks = ["brain_tension.wav", "cosmic_mystery.wav"]
    for mt in mystery_tracks:
        mpath = os.path.join(MUSIC_DIR, mt)
        if not configured_track and os.path.isfile(mpath):
            logger.info("Using SYNTHETIC MYSTERY track: %s", mt)
            return mpath

    if configured_track:
        # Accept only a filename, not an arbitrary path outside the approved
        # music directory.
        candidate = os.path.join(MUSIC_DIR, os.path.basename(configured_track))
        if not os.path.isfile(candidate):
            raise FileNotFoundError(
                f"MUSIC_TRACK={configured_track!r} was requested but does not exist in {MUSIC_DIR}"
            )
        if not candidate.lower().endswith(supported_extensions):
            raise ValueError(f"MUSIC_TRACK has an unsupported audio type: {configured_track}")
        logger.info("Using configured asset music: %s", candidate)
        return candidate

    if os.path.isdir(MUSIC_DIR):
        real_tracks = sorted(
            os.path.join(MUSIC_DIR, filename)
            for filename in os.listdir(MUSIC_DIR)
            if filename.lower().endswith(supported_extensions)
            and os.path.getsize(os.path.join(MUSIC_DIR, filename)) > 10_000
        )
        if real_tracks:
            selected = random.choice(real_tracks)
            logger.info("Using asset music: %s", selected)
            return selected

    logger.warning("No playable track found in %s; using generated ambient fallback.", MUSIC_DIR)
    os.makedirs(output_dir, exist_ok=True)
    music_path = os.path.join(output_dir, "bg_music.wav")
    bed = _synthesize_ambient_bed(duration, seed=random.randint(1, 999999))
    sf.write(music_path, bed, MUSIC_SAMPLE_RATE)
    return music_path


# ============================================
# 4. MAIN BUILD FUNCTION (PRIORITY IMPROVEMENTS)
# ============================================

def _cover_video_clip(path: str, duration: float) -> VideoFileClip:
    """Fit a downloaded Pexels/Pixabay B-roll clip to the vertical canvas.

    The stock clip's own audio is discarded—voiceover and licensed music are
    mixed later. Short source clips loop cleanly to cover one narration scene.
    """
    source = VideoFileClip(path, audio=False)
    if source.duration <= 0:
        source.close()
        raise RuntimeError(f"Stock video has no duration: {path}")
    loops = max(1, int(np.ceil(duration / source.duration)))
    clip = concatenate_videoclips([source] * loops, method="compose").subclip(0, duration)
    if clip.w / clip.h < CANVAS_W / CANVAS_H:
        clip = clip.resize(width=CANVAS_W)
    else:
        clip = clip.resize(height=CANVAS_H)
    x1 = max((clip.w - CANVAS_W) / 2, 0)
    y1 = max((clip.h - CANVAS_H) / 2, 0)
    return clip.fx(
        vfx.crop, x1=x1, y1=y1, width=CANVAS_W, height=CANVAS_H
    ).set_duration(duration)


def build_video(image_paths, audio_segments, scenes, output_path="output/final_video.mp4", media_types=None):
    """
    RETENTION OPTIMIZED:
    - Ken Burns effect (alternating zoom in/out)
    - Word-by-word captions (karaoke style)
    - Background music (dark ambient)
    - Pop SFX on scene cuts
    - Automatic speed adjustment for target duration
    - ✅ Priority: Highlighted important words
    - ✅ Priority: Better first 3-second hook
    - ✅ Priority: Dynamic zoom on important words
    - ✅ Priority: Flash/zoom transitions
    - ✅ Priority: Automatic overlays
    - ✅ Priority: Music ducking
    """
    if not len(image_paths) == len(audio_segments) == len(scenes):
        raise ValueError("image_paths, audio_segments and scenes must have the same length")
    media_types = media_types or ["image"] * len(image_paths)
    if len(media_types) != len(image_paths):
        raise ValueError("media_types must match image_paths length")

    # Brand palette with a per-video accent that keeps the channel recognizable
    # but stops every Short looking byte-identical (a machine tell). The accent
    # is seeded from the first scene's caption so the same video stays
    # consistent run-to-run while different videos differ slightly.
    _accents = [
        (255, 205, 40),   # brand gold
        (90, 220, 200),   # teal
        (255, 150, 60),   # warm orange
        (140, 120, 255),  # soft violet
        (255, 120, 150),  # rose
    ]
    _seed_txt = " ".join(str(scenes[i].get("caption", "")) for i in range(min(2, len(scenes))))
    _acc_idx = abs(hash(_seed_txt)) % len(_accents)
    color_theme = {'primary': (255, 255, 255), 'secondary': _accents[_acc_idx], 'bg': (18, 20, 28)}
    logger.info(f"Using Nextep theme with accent #{_acc_idx}: {color_theme['secondary']}")

    video_clips = []
    audio_clips = []
    t_cursor = 0.0

    for i, (img_path, seg, media_type) in enumerate(zip(image_paths, audio_segments, media_types)):
        duration = max(seg['duration'], 0.6)

        # ✅ Priority: Check if caption has important words
        caption_text = scenes[i].get('caption', seg.get('caption', ''))
        has_important = any(_is_important_word(w) for w in caption_text.split())
        # ✅ Priority: Dynamic zoom for important words
        zoom_extra = 0.06 if has_important else 0.0
        # ✅ Priority: First scene special (controlled hook punch)
        # FIXED 2026-08-20: 0.18+0.18 = 36% zooms looked huge/jerky on phones.
        # The hook now uses a CAPPED 0.12 beat that lands inside the first
        # ~2.4s — pattern interrupt that stops the thumb, but professional.
        if i == 0:
            zoom_extra += 0.12
            first_beat_frac = 0.40
        else:
            first_beat_frac = 0.50

        # RETENTION: Alternate zoom direction every scene, but seed the start
        # phase from the caption so different videos don't all open with the
        # same direction (a human editor varies their shot rhythm).
        _dir_seed = (abs(hash(caption_text or "x")) >> 4) & 1
        direction = ("in" if (_dir_seed + i) % 2 == 0 else "out")

        if media_type == "video":
            # Real licensed B-roll: preserve natural movement rather than
            # applying the static-image Ken Burns treatment.
            scene_visual = _cover_video_clip(img_path, duration)
        else:
            # AI/static image: two motion beats make the scene feel alive.
            first_duration = duration * first_beat_frac
            second_duration = duration - first_duration
            first_beat = _ken_burns_clip(img_path, first_duration, direction, zoom_extra, hook_snap=(i == 0))
            second_direction = "out" if direction == "in" else "in"
            second_beat = _ken_burns_clip(
                img_path, second_duration, second_direction, zoom_extra + 0.04,
                # second beat of the hook scene also gets the punch-in so the
                # opening frame reads as a live camera move for its full first 3s.
                hook_snap=(i == 0),
            )
            scene_visual = concatenate_videoclips(
                [first_beat, second_beat], method="compose"
            ).set_duration(duration)

        # ✅ Priority: Word-by-word captions with highlighting
        word_clips = _word_by_word_clips(caption_text, duration, color_theme,
                                         scene_index=i)

        overlays = []
        if i == 0:
            hook_src = (scenes[i].get('hook_text')
                        or (scenes[i].get('caption') or ''))
            if hook_src:
                overlays.append(_hook_overlay_clip(hook_src, duration, color_theme))

        # Combine visual + captions (+ optional hook overlay on frame one)
        combined = CompositeVideoClip(
            [scene_visual] + word_clips + overlays,
            size=(CANVAS_W, CANVAS_H)
        ).set_duration(duration)

        # ✅ Priority: Overlays (arrows, circles, glow effects)
        # Note: Complex overlays require additional processing
        # This is a placeholder for future implementation

        # Deliberately no synthetic flash overlay here. The previous overlay used
        # a global timestamp inside a scene-local composition and caused blank/
        # black frames on later scenes. Motion is provided by Ken Burns instead.

        video_clips.append(combined)
        # Audio segment
        seg_audio = AudioFileClip(seg['path']).fx(
            afx.audio_fadein, AUDIO_EDGE_FADE
        ).fx(
            afx.audio_fadeout, AUDIO_EDGE_FADE
        )
        audio_clips.append(seg_audio)
        t_cursor += duration
        if i < len(scenes) - 1:
            _gap = seg.get('gap_after')
            if _gap in (None, ''):
                try:
                    from humanizer import breath_pause
                    _gap = breath_pause(i, caption_text or "")
                except Exception:  # noqa: BLE001 — gaps never block
                    _gap = 0.0
            _gap = float(_gap or 0.0)
            if 0.15 <= _gap <= 1.5:
                # moviepy 1.x (pinned in requirements.txt) ships AudioClip
                # but not AudioArrayClip — a zero-valued getframe is the
                # portable silent-clip constructor.
                def _silent(_t):
                    # MoviePy probes an AudioClip with scalar t=0 during
                    # construction to infer nchannels. Returning (1, 2) there
                    # incorrectly declares one channel and later broadcasts a
                    # vectorized silent frame into an (N, N) matrix.
                    _arr = np.asarray(_t)
                    if _arr.ndim == 0:
                        return np.zeros(2, dtype=float)
                    return np.zeros((len(_arr), 2), dtype=float)
                silent = AudioClip(_silent, duration=_gap)
                silent.fps = 44100
                audio_clips.append(silent)
                # still-beat visual hold: freeze the scene's final frame
                # (re-using the already-composited clip, so size/style match
                # the surrounding timeline exactly and no extra renders run).
                try:
                    video_clips.append(
                        combined.copy().subclip(
                            max(0.0, duration - 0.001), duration
                        ).set_duration(_gap)
                    )
                except Exception:  # noqa: BLE001 — visual beat never blocks
                    pass

    logger.info("Concatenating video clips...")
    final_video = concatenate_videoclips(video_clips, method="compose")

    logger.info("Concatenating audio segments...")
    voice_audio = concatenate_audioclips(audio_clips)

    logger.info("Adding background music bed...")
    music_path = _get_music_track(
        voice_audio.duration,
        os.path.dirname(output_path) or "output"
    )
    music_clip = AudioFileClip(music_path)

    if music_clip.duration < voice_audio.duration:
        loops_needed = int(voice_audio.duration // music_clip.duration) + 1
        music_clip = concatenate_audioclips([music_clip] * loops_needed)
    music_clip = music_clip.subclip(0, voice_audio.duration).fx(
        afx.audio_fadein, 1.0
    ).fx(
        afx.audio_fadeout, 1.0
    )

    logger.info("Building voice-activity ducking envelope...")
    duck_env = _build_ducking_envelope(audio_segments, voice_audio.duration)
    logger.info(
        f"Ducking envelope: {len(duck_env)} samples, "
        f"duck coverage ≈ {np.mean(duck_env < (DUCK_LEVEL + 0.01)) * 100:.0f}%"
    )

    def _apply_ducking(gf, t):
        """Time-varying gain applied to the music track at render time.

        ``t`` arrives as a float OR a numpy array (moviepy reads audio in
        chunks), so everything is vectorised with np operations.
        """
        frame = gf(t)
        t_arr = np.atleast_1d(np.asarray(t, dtype=np.float64))
        indices = np.clip(
            (t_arr * MUSIC_SAMPLE_RATE).astype(np.int64),
            0,
            len(duck_env) - 1,
        )
        gain = duck_env[indices] * MUSIC_VOLUME
        # MoviePy normally returns audio as (samples, channels), but some
        # reader/effect combinations return (channels, samples). Choose the
        # matching axis explicitly; blindly using gain[:, None] turns a
        # channel-first (2, N) frame into the observed (N, N) matrix.
        frame = np.asarray(frame)
        if frame.ndim == 2 and gain.ndim == 1:
            sample_count = len(t_arr)
            if frame.shape[0] == sample_count:
                gain = gain[:, np.newaxis]
            elif frame.shape[1] == sample_count:
                gain = gain[np.newaxis, :]
        return gain * frame

    ducked_music = music_clip.fl(_apply_ducking)

    # 2026-08-21: subtle pop at every scene boundary (except the very start)
    # - never on top of the narration's first word of a new scene because the
    # blip is mixed under the voice at -22 dB below ducked music; it reads as
    # an editorial beat, not a glitch.
    sfx_clips = []
    if SFX_ENABLED:
        try:
            _t = 0.0
            for seg in audio_segments:
                _t += max(seg.get("duration", 0.0), 0.6)
                if 0.0 < _t < voice_audio.duration - 0.1:
                    sfx_clips.append(_make_pop_sfx().set_start(_t))
        except Exception as exc:  # noqa: BLE001 - SFX never blocks a run
            logger.warning("Scene-cut SFX skipped (%s)", exc)

    logger.info("Mixing voice + ducked background music...")
    final_audio = CompositeAudioClip([ducked_music, voice_audio] + sfx_clips)
    final_video = final_video.set_audio(final_audio)

    # ---- Strict Shorts duration gate ----
    duration = final_video.duration
    if duration > TARGET_MAX_SEC:
        required_speed = duration / TARGET_MAX_SEC
        # A bounded correction is preferable to aborting after all assets are
        # generated. Anything larger must still be fixed at script level;
        # crushing a long narration into a Short sounds bad.
        if required_speed <= 1.25:
            logger.warning("Applying small %.3fx correction to meet %.1fs limit", required_speed, TARGET_MAX_SEC)
            final_video = final_video.fx(vfx.speedx, required_speed)
        else:
            raise RuntimeError(
                f"Narration is {duration:.1f}s; refusing destructive speed-up. "
                f"Regenerate a script that fits the {TARGET_MAX_SEC:.0f}s target."
            )
    elif duration < TARGET_MIN_SEC:
        logger.warning("Short is %.1fs (target starts at %.1fs); keeping natural speed", duration, TARGET_MIN_SEC)
    else:
        logger.info("Video duration %.1fs is within Shorts target", duration)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    logger.info(f"Writing video to {output_path}...")
    final_video.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        # YouTube's own guidance recommends ~8 Mbps for 1080p/30fps SDR
        # uploads; 6 Mbps was leaving quality on the table before YouTube's
        # own re-compression even runs. 10 Mbps gives it more to work with.
        bitrate="10000k",
        audio_bitrate="192k",
        preset="slow",
        ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-aspect", "9:16"]
    )
    logger.info(f"Video created: {output_path} ({final_video.duration:.1f}s)")

    return output_path


# ============================================
# 5. THUMBNAIL GENERATION (PRIORITY: BETTER THUMBNAILS)
# ============================================

def generate_thumbnail(image_path: str, title: str, output_path: str = "output/thumbnail.jpg", category: str = "Body") -> str:
    """
    Creates RETENTION-OPTIMIZED YouTube thumbnail:
    - High contrast
    - Large readable text (3-5 words max)
    - Dark gradient overlay for text legibility
    - Category-specific colors for visual diversity
    - ✅ Priority: Glow effect
    - ✅ Priority: Face zoom
    - ✅ Priority: Object outline
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Strip emoji for font compatibility (kept in sync with niche_strategy.py's
    # _EMOJI_PATTERN - stars/arrows/media-control glyphs outside 2600-27BF
    # were previously left behind, printing as a missing-glyph box on the
    # thumbnail).
    title = re.sub(
        r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF"
        r"\u25A0-\u25FF\U0001F1E6-\U0001F1FF\uFE0F]+\s*",
        "",
        title,
    ).strip()

    # ✅ Priority: Category-specific background color
    CATEGORY_BG_COLORS = {
        "Brain": (20, 30, 60),
        "Body": (60, 20, 20),
        "Mystery": (40, 20, 60),
        "Health": (20, 60, 20),
    }
    CATEGORY_TEXT_COLORS = {
        "Brain": (255, 215, 0),
        "Body": (255, 100, 100),
        "Mystery": (255, 200, 100),
        "Health": (100, 255, 100),
    }

    bg_color = CATEGORY_BG_COLORS.get(category, (0, 0, 0))
    THUMB_W, THUMB_H = 1080, 1920
    canvas = Image.new("RGB", (THUMB_W, THUMB_H), bg_color)
    
    # First scene may be an actual Pexels/Pixabay MP4 B-roll clip. Extract a
    # clean early frame for the upload thumbnail instead of trying to decode
    # an MP4 with Pillow (which would crash after an otherwise good render).
    if str(image_path).lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
        preview = VideoFileClip(image_path, audio=False)
        try:
            frame_time = min(max(preview.duration * 0.2, 0.05), max(preview.duration - 0.05, 0.05))
            src = Image.fromarray(preview.get_frame(frame_time)).convert("RGB")
        finally:
            preview.close()
    else:
        with Image.open(image_path) as _src:
            src = _src.convert("RGB")

    # ✅ Priority: Face zoom (focus on center 70% of image)
    src_ratio = src.width / src.height
    target_ratio = THUMB_W / THUMB_H
    
    # Zoom in more on center for face/object focus
    zoom_factor = 1.15  # 15% zoom
    if src_ratio > target_ratio:
        new_h = int(THUMB_H * zoom_factor)
        new_w = int(new_h * src_ratio)
    else:
        new_w = int(THUMB_W * zoom_factor)
        new_h = int(new_w / src_ratio)
    
    src = src.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - THUMB_W) // 2
    top = (new_h - THUMB_H) // 2
    src = src.crop((left, top, left + THUMB_W, top + THUMB_H))
    
    # ✅ Priority: Glow effect (add radial gradient overlay)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    
    # Dark gradient from bottom
    strip_top = THUMB_H - 340
    for y in range(strip_top, THUMB_H):
        alpha = int(200 * (y - strip_top) / 340)
        draw_overlay.line([(0, y), (THUMB_W, y)], fill=(0, 0, 0, alpha))
    
    # ✅ Priority: Glow effect (center radial)
    for i in range(100):
        x = random.randint(250, 830)
        y = random.randint(150, 700)
        radius = random.randint(150, 300)
        alpha = random.randint(5, 15)
        draw_overlay.ellipse(
            [(x - radius, y - radius), (x + radius, y + radius)],
            fill=(255, 255, 255, alpha)
        )
    
    canvas = Image.alpha_composite(canvas.convert("RGBA"), src.convert("RGBA"))
    canvas = Image.alpha_composite(canvas, overlay).convert("RGB")

    draw = ImageDraw.Draw(canvas)
    font = _get_caption_font(90)

    # Keep only 3-4 meaningful words. Taking the first five words produced
    # vague phrases such as "SECRET RHYTHMS OF YOUR BODY" on mobile.
    all_words = [re.sub(r"[^A-Z0-9']", "", w) for w in title.upper().split()]
    stop = {"THE", "A", "AN", "OF", "TO", "IS", "ARE", "THIS", "THAT", "ABOUT", "BEHIND"}
    meaningful = [w for w in all_words if w and w not in stop]
    words = (meaningful or all_words)[:4]
    title = " ".join(words)

    _THUMB_STROKE_W = 5
    _THUMB_OUTLINE_OFFSET = 3
    _ink_margin = 2 * (_THUMB_STROKE_W + _THUMB_OUTLINE_OFFSET)
    try:
        from safe_zones import safe_box as _safe_box
        safe_left, _sy0, safe_right, _sy1 = _safe_box(THUMB_W, THUMB_H)
    except Exception:  # pragma: no cover
        safe_left, safe_right = int(THUMB_W * 0.04), int(THUMB_W * 0.87)
    wrap_width = (safe_right - safe_left) - _ink_margin

    # Shrink the font before truncating: a four-word title that needs three
    # lines is still better than one with a word chopped off.
    while len(words) > 1:
        longest = max(draw.textlength(w, font=font) for w in words)
        if longest <= wrap_width or font.size <= 48:
            break
        font = _get_caption_font(max(48, font.size - 6))

    lines, current = [], ""
    for w in words:
        test = (current + " " + w).strip()
        if current and draw.textlength(test, font=font) > wrap_width:
            lines.append(current)
            current = w
        else:
            current = test
    if current:
        lines.append(current)

    # ✅ Priority: Text color
    text_color = CATEGORY_TEXT_COLORS.get(category, (255, 255, 255))

    try:
        from safe_zones import thumbnail_text_band
        band_top, band_bottom = thumbnail_text_band(THUMB_W, THUMB_H)
    except Exception:  # pragma: no cover - thumbnails must never fail to render
        band_top, band_bottom = int(THUMB_H * 0.55), int(THUMB_H * 0.80)

    line_height = int(font.size * 1.15)
    block_height = len(lines) * line_height
    # Centre the block in the band, then clamp so a three-line title cannot
    # push its last line back down into the chrome.
    y = band_top + max(0, (band_bottom - band_top - block_height) // 2)
    y = min(y, band_bottom - block_height)
    y = max(y, band_top)

    # Centre on the SAFE box, not the raw frame. The safe area is asymmetric
    # (every platform draws its action column on the right), so centring on
    # the frame pushes text ~80px too far right and the last characters of a
    # long line end up behind the like/share buttons even after wrapping.
    safe_centre = (safe_left + safe_right) / 2

    for line in lines:
        w = draw.textlength(line, font=font)
        x = safe_centre - w / 2
        # Never let the ink cross either safe edge, whatever the wrap produced.
        x = max(safe_left + _ink_margin / 2, min(x, safe_right - w - _ink_margin / 2))

        
        # Draw outline (glow effect)
        for dx in range(-_THUMB_OUTLINE_OFFSET, _THUMB_OUTLINE_OFFSET + 1):
            for dy in range(-_THUMB_OUTLINE_OFFSET, _THUMB_OUTLINE_OFFSET + 1):
                if abs(dx) == _THUMB_OUTLINE_OFFSET or abs(dy) == _THUMB_OUTLINE_OFFSET:
                    draw.text((x + dx, y + dy), line, font=font, 
                              fill=(0, 0, 0, 100), stroke_width=0)
        
        # Main text
        draw.text(
            (x, y),
            line,
            font=font,
            fill=text_color,
            stroke_width=_THUMB_STROKE_W,
            stroke_fill="black"
        )
        y += line_height

    canvas.save(output_path, quality=95)
    logger.info(f"Thumbnail saved: {output_path}")
    return output_path


# ============================================
# 6. RETENTION ANALYSIS FUNCTION
# ============================================

def analyze_video_retention_potential(video_path: str) -> Dict:
    """
    Analyzes video for retention potential.
    Checks: duration, scene count, caption pacing, etc.
    """
    from moviepy.editor import VideoFileClip

    clip = VideoFileClip(video_path)
    duration = clip.duration

    # Scene detection (approximate)
    scenes = int(duration / 5)

    analysis = {
        'duration': duration,
        'duration_optimal': TARGET_MIN_SEC <= duration <= TARGET_MAX_SEC,
        'estimated_scenes': scenes,
        'scene_count_optimal': 7 <= scenes <= 12,
        'retention_score': 0,
        'suggestions': []
    }

    score = 50

    if analysis['duration_optimal']:
        score += 20
    else:
        analysis['suggestions'].append(
            f"Duration {duration:.1f}s - aim for {TARGET_MIN_SEC}-{TARGET_MAX_SEC}s"
        )

    if analysis['scene_count_optimal']:
        score += 20
    else:
        analysis['suggestions'].append(
            f"Estimated {scenes} scenes - aim for 7-12 scenes"
        )

    if scenes > 5 and duration > 30:
        score += 10

    analysis['retention_score'] = min(100, score)

    clip.close()
    return analysis


# ============================================
# 7. MAIN EXECUTION
# ============================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("="*60)
    print("RETENTION-OPTIMIZED VIDEO EDITOR")
    print("="*60)
    print()

    print("✅ Features enabled:")
    print("   - Ken Burns effect (alternating zoom in/out)")
    print("   - Word-by-word captions (karaoke style)")
    print("   - Highlighted important words (yellow/red)")
    print("   - Dynamic zoom on important words")
    print("   - Flash/zoom transitions between scenes")
    print("   - Random color themes per video")
    print("   - Music ducking (real voice-activity detection, not fake modulo)")
    print("   - Better first 3-second hook")
    print("   - Dark ambient background music")
    print("   - High-contrast thumbnails with glow effect")
    print("   - Automatic speed adjustment (40-55s target)")
    print()
    print("📊 Retention optimizations:")
    print("   - Visual variety per scene")
    print("   - Caption pacing for engagement")
    print("   - Audio transitions for flow")
    print("   - Thumbnail contrast for CTR")
    print()
    print("="*60)
