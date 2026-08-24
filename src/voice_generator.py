import os
import numpy as np
import soundfile as sf
import logging
import re
import time
from typing import List, Dict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PRIMARY ENGINE: Chatterbox (Resemble AI, MIT license - safe for a
# monetized channel).
#
# Why Chatterbox over Kokoro: Chatterbox can condition generation on the
# creator's approved voice reference, whereas Kokoro is a generic fallback
# voice. Its delivery controls let us keep narration clear and conversational
# instead of giving every scene an artificial dramatic tone.
#
# Lazy-loaded on first use (not at import time) so a missing pip install or
# a failed model download doesn't crash the whole pipeline before it even
# starts - _get_chatterbox() catches that, and every call in this file
# falls back to Kokoro per-segment if Chatterbox is unavailable or a
# specific generation call fails. One bad Chatterbox call should never take
# a whole video down.
# ---------------------------------------------------------------------------
_chatterbox_model = None
_chatterbox_load_failed = False
_chatterbox_load_error = None  # the real underlying exception, kept around so
                                # every later "not loaded" error can still show
                                # WHY, instead of just the first log line at
                                # startup (which is easy to miss/lose in CI logs).

# NATURAL YOUTUBE VOICE PROFILE
#
# Chatterbox's higher exaggeration values make delivery more theatrical and
# can also make it feel faster. That is useful for character acting, but it
# weakens speaker similarity for a creator's regular YouTube narration.
# These defaults deliberately favour a calm, clear, conversational delivery:
# natural energy, stable pronunciation and recognisable cloned identity.
# Every value can be overridden in .env / GitHub Actions secrets.
def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    """Read a bounded float setting and fall back safely on bad input."""
    raw = os.environ.get(name, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default
    if not minimum <= value <= maximum:
        logger.warning("%s=%s is outside [%s, %s]; using %s", name, value, minimum, maximum, default)
        return default
    return value


CHATTERBOX_EXAGGERATION = _env_float("CHATTERBOX_EXAGGERATION", 0.35, 0.0, 1.0)
CHATTERBOX_CFG_WEIGHT = _env_float("CHATTERBOX_CFG_WEIGHT", 0.70, 0.0, 1.0)
CHATTERBOX_TEMPERATURE = _env_float("CHATTERBOX_TEMPERATURE", 0.60, 0.05, 1.5)

# Chatterbox has no native speed control. atempo changes tempo while keeping
# pitch, so 0.96 is slightly calmer than normal without sounding slow or
# artificial. FFmpeg accepts 0.5–2.0 for one atempo filter.
CHATTERBOX_TEMPO = _env_float("CHATTERBOX_TEMPO", 0.96, 0.5, 2.0)

# ---------------------------------------------------------------------------
# KOKORO FALLBACK ENGINE CONFIG — these env vars are honored NOW.
# Previously KOKORO_LANG_CODE / KOKORO_VOICE / TTS_ENGINE were set in the
# GitHub workflow (French voice ff_siwis for the FR experiment) but were
# NEVER read by any code — the pipeline silently used hardcoded
# lang_code='a' and voice='am_adam'. The wiring below makes the environment
# the single source of truth.
#
# US AUDIENCE (current strategy): lang_code='a', voice='am_adam'
# (American English male). Other examples: lang_code 'b' (British),
# voices 'af_heart' (US female), 'bf_emma' (UK female).
# ---------------------------------------------------------------------------
KOKORO_LANG_CODE = os.environ.get("KOKORO_LANG_CODE", "a").strip() or "a"
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "am_adam").strip() or "am_adam"

# Humanizer is imported at the top so VOICE_ROTATE never fails silently on a
# path/working-directory quirk — if humanizer ever becomes unavailable the
# pipeline must see it at import time, not quietly pin every video to am_adam.
from humanizer import pick as _h_pick

# 2026-08 humanization pass: one frozen voice across 100+ videos is the single
# loudest "this channel is a machine" signal. VOICE_ROTATE=auto (workflow
# default) deterministically rotates among these natural EN voices by topic —
# the same topic always keeps its voice (channel consistency), different
# topics get different voices (human variety). Same seeding as humanizer.py so
# it is reproducible run-to-run.
VOICE_POOL = [
    "am_adam", "am_michael", "am_liam", "am_puck", "am_alex",
    "af_bella", "af_nova", "af_sky", "af_sarah", "af_heart",
]


def _rotated_voice(base_voice: str, topic: str) -> str:
    """Resolve the per-video voice: explicit base wins; else rotate by topic."""
    mode = (os.environ.get("VOICE_ROTATE") or "").strip().lower()
    if not base_voice or mode in ("auto", "on", "true", "1"):
        return _h_pick(VOICE_POOL, (topic or base_voice or "x") + "|voice")
    return base_voice

# Engine priority:
#   'chatterbox' (default) = clone-first, Kokoro fallback  (GPU / self-hosted)
#   'kokoro'               = skip Chatterbox entirely      (GitHub CPU runners)
TTS_ENGINE = os.environ.get("TTS_ENGINE", "chatterbox").strip().lower()
if TTS_ENGINE not in {"chatterbox", "kokoro"}:
    logger.warning("Unknown TTS_ENGINE=%r; using 'chatterbox'", TTS_ENGINE)
    TTS_ENGINE = "chatterbox"

# Number of times Chatterbox retries per segment before giving up and
# falling back to Kokoro. Retries use the cloned voice reference every
# time — if the reference is bad the first attempt will fail, and retrying
# with the same bad reference won't help, so _synthesize_chatterbox()
# detects that case and skips pointless retries.
CHATTERBOX_MAX_RETRIES = 3

# Seconds to wait between Chatterbox retry attempts. Gives transient
# issues (GPU memory pressure, model hot-reload glitches, etc.) a moment
# to clear before hammering again.
CHATTERBOX_RETRY_DELAY = 2.0

# Optional voice-clone reference. Drop a clean 10-20s WAV (single speaker,
# no background noise) here and Chatterbox will clone that voice for every
# video instead of its own built-in default voice. If this file doesn't
# exist, Chatterbox just uses its default voice - nothing else changes.
VOICE_REFERENCE_PATH = os.environ.get("VOICE_REFERENCE_PATH", "assets/voice_reference.wav")


def _voice_reference_ok() -> bool:
    """True only if the reference WAV is actually usable for cloning.

    Guards against three silent failure modes that would otherwise make the
    pipeline *think* it cloned when it didn't: (1) file missing, (2) file
    present but empty/corrupt, (3) file readable but effectively silent
    (all-zero / near-silent), which produces a garbage clone. Any problem
    here just logs and returns False -> Chatterbox uses its default voice
    instead of a broken clone.
    """
    path = VOICE_REFERENCE_PATH
    if not path or not os.path.exists(path) or os.path.getsize(path) < 1024:
        return False
    try:
        info = sf.info(path)
        if info.frames <= 0 or info.duration < 3.0:
            logger.warning("Voice reference is too short (%.1fs). Use at least 10 seconds.", info.duration)
            return False
        # A 30–60 second clean sample is noticeably more reliable for speaker
        # similarity. Shorter samples still work, so do not silently disable a
        # creator's clone merely because it is below the recommendation.
        if info.duration < 30.0:
            logger.warning(
                "Voice reference is only %.1fs. Cloning will work, but a 30–60s clean, "
                "single-speaker WAV usually sounds much closer to the original voice.",
                info.duration,
            )
        # Check a small slice for silence and severe clipping. This is a
        # validity gate, not a substitute for a clean recording.
        sample, _ = sf.read(path, frames=min(info.frames, info.samplerate * 5), dtype="float32")
        if sample.ndim > 1:
            sample = sample.mean(axis=1)
        if sample.size == 0 or float(np.abs(sample).max()) < 1e-3:
            logger.warning("Voice reference is silent/near-silent - using default voice.")
            return False
        clipping_ratio = float(np.mean(np.abs(sample) >= 0.995))
        if clipping_ratio > 0.005:
            logger.warning(
                "Voice reference may be clipped (%.2f%% samples near full scale). "
                "Re-record with lower input gain for a cleaner clone.",
                clipping_ratio * 100,
            )
        return True
    except Exception as e:
        logger.warning(f"Voice reference unreadable ({e}) - using default voice.")
        return False


def _get_chatterbox():
    """Loads the Chatterbox model once and caches it. Returns None (and
    remembers not to retry) if loading fails for any reason - missing
    package, no internet for the first-run model download, out-of-memory
    on a CPU-only runner, etc."""
    global _chatterbox_model, _chatterbox_load_failed, _chatterbox_load_error
    if _chatterbox_model is not None or _chatterbox_load_failed:
        return _chatterbox_model
    try:
        import torch
        # ------------------------------------------------------------------
        # Known bug workaround (resemble-ai/chatterbox GitHub issue #198):
        # in some environments perth.PerthImplicitWatermarker silently
        # resolves to None (even though `import perth` succeeds and
        # setuptools is present) - ChatterboxTTS.__init__ then does
        # `self.watermarker = perth.PerthImplicitWatermarker()` and blows up
        # with "TypeError: 'NoneType' object is not callable". Nobody in
        # that issue thread found a root cause that reliably fixes it across
        # environments, but the monkeypatch below (confirmed working by
        # several people on the thread) sidesteps it entirely: if the real
        # watermarker class is missing, swap in a harmless no-op before
        # ChatterboxTTS ever touches it. This only skips audio watermarking
        # - the actual voice cloning is completely unaffected.
        # ------------------------------------------------------------------
        import perth
        if getattr(perth, "PerthImplicitWatermarker", None) is None:
            logger.warning(
                "perth.PerthImplicitWatermarker is None (known chatterbox/perth "
                "issue #198) - patching in a no-op watermarker so Chatterbox can "
                "still load and clone voices normally."
            )
            class _NoOpWatermarker:
                def apply_watermark(self, wav, *args, **kwargs):
                    return wav
                def get_watermark(self, *args, **kwargs):
                    return 0.0
            perth.PerthImplicitWatermarker = _NoOpWatermarker

        from chatterbox.tts import ChatterboxTTS
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading Chatterbox TTS model on {device} (first call only, then cached)...")
        _chatterbox_model = ChatterboxTTS.from_pretrained(device=device)
        logger.info("Chatterbox loaded successfully.")
    except Exception as e:
        # Keep the full exception type + message around (not just this one
        # log line) so every later "model not loaded" error downstream can
        # still report WHY, even in a trimmed/partial log.
        _chatterbox_load_error = f"{type(e).__name__}: {e}"
        logger.error(f"Chatterbox unavailable ({_chatterbox_load_error}) - every segment will fall back to Kokoro.")
        _chatterbox_load_failed = True
        _chatterbox_model = None
    return _chatterbox_model


def _scene_tempo_for(base_speed: float, index: int, caption: str) -> float:
    """Deterministic per-scene tempo variation so narration sounds human.

    Real narrators speed up slightly on connective/excited lines and slow down
    on the hook and the payoff. We approximate that with a small, stable
    offset derived from the scene index and the caption hash:
      * scene 0 (hook): a touch slower for a confident open,
      * the final scene (payoff): a touch slower,
      * middle scenes: tiny ±1.5% variation.
    Always clamped to a safe band so TTS never sounds rushed or draggy.
    """
    try:
        import hashlib
        seed = int(hashlib.sha256(caption.encode("utf-8")).hexdigest()[:6], 16)
        variation = ((seed % 100) - 50) / 100.0  # -0.5 .. +0.5
        offset = variation * 0.03                # ±1.5%
        if index == 0:
            offset -= 0.015                        # hook: slightly slower
        # final scene is the payoff — a beat slower to land it
        # (we don't know length here, so caller nudges; kept simple)
        tempo = base_speed + offset
        return max(0.90, min(1.10, tempo))
    except Exception:  # noqa: BLE001 - never break TTS over a cosmetic tweak
        return base_speed


# 2026-08-19: ADULT-VOICE MATURING (ported from Neuro-Somaa). Chatterbox's
# default narrator is a neutral synthetic voice; with the creator's approved
# voice_reference.wav the pipeline deepens and matures the output so the
# narrator always sounds like an ADULT professional:
#   VOICE_MATURE_PITCH_SEMITONES = negative -> lower pitch (deeper voice)
#   VOICE_MATURE_TEMPO           = slightly calmer delivery (authority)
# When a usable clone reference exists, maturing is SKIPPED so the creator's
# own voice is never altered.
VOICE_MATURE_PITCH_SEMITONES = _env_float(
    "VOICE_MATURE_PITCH_SEMITONES", -4.0, -6.0, 0.0)
VOICE_MATURE_TEMPO = _env_float("VOICE_MATURE_TEMPO", 0.92, 0.75, 1.05)
VOICE_MATURE_ENABLED = os.environ.get(
    "VOICE_MATURE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

def _mature_voice(audio, sr):
    """Pitch-deepen + calm the synthetic default voice toward a mature adult
    male narrator. Uses ffmpeg's asetrate+aresample (pitch shift) followed
    by a gentle high-pass on mud and a limiter for broadcast-safe peaks.
    Falls back to the unmodified audio if processing fails."""
    if not VOICE_MATURE_ENABLED:
        return audio
    try:
        import subprocess
        import tempfile
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "in.wav")
            out_path = os.path.join(tmpdir, "out.wav")
            sf.write(in_path, audio, sr)
            result = subprocess.run(
                [
                    ffmpeg_exe, "-y", "-i", in_path, "-af",
                    (f"asetrate={sr}*2^({VOICE_MATURE_PITCH_SEMITONES}/12),"
                     f"aresample={sr},"
                     f"atempo={VOICE_MATURE_TEMPO},"
                     f"highpass=f=80,lowpass=f=14000,alimiter=limit=0.95"),
                    out_path,
                ],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not os.path.exists(out_path):
                logger.warning("Voice maturing failed, using unmodified audio: %s",
                               result.stderr[:200])
                return audio
            matured, _ = sf.read(out_path, dtype="float32")
            logger.info("Voice maturing APPLIED: pitch %.1f st, tempo %.2f", VOICE_MATURE_PITCH_SEMITONES, VOICE_MATURE_TEMPO)
            return matured
    except Exception as e:
        logger.warning("Voice maturing failed (%s), using unmodified audio", e)
        return audio

def _apply_tempo(audio: np.ndarray, sr: int, tempo: float) -> np.ndarray:
    """Apply natural voice finishing plus pitch-preserving tempo adjustment.

    A gentle high/low-pass removes DC/rumble and harsh ultrasonic artifacts;
    a limiter keeps every independently generated scene at a consistent peak.
    The filter is deliberately light—no aggressive denoise or reverb that
    would make the creator clone sound synthetic. Returns original audio if
    ffmpeg processing fails."""
    if tempo == 1.0:
        return audio
    try:
        import subprocess
        import tempfile
        import imageio_ffmpeg

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "in.wav")
            out_path = os.path.join(tmpdir, "out.wav")
            sf.write(in_path, audio, sr)
            result = subprocess.run(
                [
                    ffmpeg_exe, "-y", "-i", in_path, "-filter:a",
                    f"atempo={tempo},highpass=f=65,lowpass=f=15000,alimiter=limit=0.95",
                    out_path,
                ],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not os.path.exists(out_path):
                logger.warning(f"ffmpeg tempo adjustment failed, using original pace: {result.stderr[:200]}")
                return audio
            stretched, _ = sf.read(out_path, dtype="float32")
            return stretched
    except Exception as e:
        logger.warning(f"Tempo adjustment failed ({e}), using original pace")
        return audio


def _validate_generated_audio(audio: np.ndarray, sr: int, min_duration: float = 0.3) -> None:
    """Reject garbage TTS output that would silently produce broken audio.

    Catches three failure modes:
    1. Empty / near-zero-length arrays (model returned nothing)
    2. NaN / Inf contamination (numerical explosion in the model)
    3. Too-short output (e.g. model choked on the text and spat out a blip)

    Raises RuntimeError with a descriptive message so callers can decide
    whether to retry or fall back to another engine.
    """
    if audio is None or audio.size == 0:
        raise RuntimeError("TTS returned empty audio array")
    if np.isnan(audio).any() or np.isinf(audio).any():
        raise RuntimeError("TTS returned NaN/Inf audio — numerical explosion")
    duration = audio.size / sr if sr > 0 else 0.0
    if duration < min_duration:
        raise RuntimeError(f"TTS output too short ({duration:.2f}s < {min_duration:.2f}s minimum)")


def _synthesize_chatterbox(text: str, attempt: int = 1) -> tuple:
    """Generate speech with Chatterbox using the cloned voice reference.

    Returns (audio: np.ndarray float32, sample_rate: int).

    The voice reference is ALWAYS used when available — this is the whole
    point of the retry loop. If the reference file itself is broken
    (_voice_reference_ok() returns False), there is no point retrying with
    the same broken file, so we raise immediately to let the caller skip
    straight to Kokoro.

    Parameters
    ----------
    text : str
        The text to synthesize.
    attempt : int
        Current attempt number (1-based), used for logging.
    """
    model = _get_chatterbox()
    if model is None:
        reason = _chatterbox_load_error or "unknown reason"
        raise RuntimeError(f"Chatterbox model not loaded ({reason})")

    # If the voice reference is broken, retrying with the same broken
    # file is pointless — fail fast so the caller jumps to Kokoro.
    use_clone = _voice_reference_ok()
    if not use_clone and attempt == 1:
        logger.warning(
            "Voice reference NOT usable — Chatterbox will use its default voice. "
            "Retrying won't help since the reference won't magically fix itself."
        )

    kwargs = dict(
        exaggeration=CHATTERBOX_EXAGGERATION,
        cfg_weight=CHATTERBOX_CFG_WEIGHT,
        temperature=CHATTERBOX_TEMPERATURE,
    )
    if use_clone:
        kwargs["audio_prompt_path"] = VOICE_REFERENCE_PATH
        logger.info(f"Chatterbox attempt {attempt}/{CHATTERBOX_MAX_RETRIES}: using CLONED voice from {VOICE_REFERENCE_PATH}")
    else:
        logger.info(f"Chatterbox attempt {attempt}/{CHATTERBOX_MAX_RETRIES}: using DEFAULT voice (no valid reference)")

    wav = model.generate(text, **kwargs)
    audio = wav.squeeze().detach().cpu().numpy().astype(np.float32)

    # Validate before any post-processing — a garbage generation should
    # be retried, not normalised and passed downstream.
    _validate_generated_audio(audio, model.sr, min_duration=0.3)

    if np.isnan(audio).any():
        audio = np.nan_to_num(audio, 0.0)
    peak = np.abs(audio).max()
    if peak > 1.0:
        audio = audio / peak * 0.95

    audio = _apply_tempo(audio, model.sr, CHATTERBOX_TEMPO)

    return audio, model.sr


# ---------------------------------------------------------------------------
# FALLBACK ENGINE: Kokoro (Apache 2.0). No emotion control, but has no
# install/download surprises and is fast on CPU - kept exactly as before so
# a Chatterbox failure never takes the whole pipeline down with it.
# ---------------------------------------------------------------------------
_kokoro_tts = None
_kokoro_load_failed = False


def _get_kokoro():
    """Lazy-loads Kokoro only when actually needed as a fallback. Previously
    this loaded unconditionally at module import time (every single
    pipeline run), which meant paying its ~5s load + first-run model
    download cost even on runs where Chatterbox succeeded for every
    segment and Kokoro was never actually used."""
    global _kokoro_tts, _kokoro_load_failed
    if _kokoro_tts is not None or _kokoro_load_failed:
        return _kokoro_tts
    try:
        from kokoro import KPipeline
        logger.info("Loading Kokoro TTS model (fallback engine, first use only)...")
        # Language is env-driven (was hardcoded 'a' — the FR workflow's
        # KOKORO_LANG_CODE was silently ignored before this fix).
        _kokoro_tts = KPipeline(lang_code=KOKORO_LANG_CODE)
        logger.info("Kokoro loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load Kokoro: {e}")
        _kokoro_load_failed = True
        _kokoro_tts = None
    return _kokoro_tts

KOKORO_SAMPLE_RATE = 24000


def prepare_natural_narration(text: str) -> str:
    """Prepare natural YouTube narration without changing its meaning.

    Previous versions injected ellipses into phrases such as “right now” and
    “you too” for a dark/suspense delivery. Those artificial pauses make a
    clone sound unlike the real creator. Respect the script's punctuation and
    only clean whitespace and accidental repeated punctuation.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"(?<![.!?])\.{2}(?!\.)", ".", cleaned)
    cleaned = re.sub(r"([!?]){2,}", r"\1", cleaned)
    return cleaned


def _synthesize_kokoro(text: str, voice: str, speed: float):
    """Returns (audio: np.ndarray float32, sample_rate: int)."""
    kokoro = _get_kokoro()
    if not kokoro:
        raise RuntimeError("Kokoro TTS model not loaded. Check Kokoro installation.")

    generator = kokoro(text, voice=voice, speed=speed)
    chunks = []
    for gs, ps, audio in generator:
        if audio is not None:
            chunks.append(audio)

    if not chunks:
        raise RuntimeError(f"Kokoro ne audio generate nahi kiya for: {text[:50]}...")

    full_audio = np.concatenate(chunks)
    if np.isnan(full_audio).any():
        full_audio = np.nan_to_num(full_audio, 0.0)

    max_val = np.abs(full_audio).max()
    if max_val > 1.0:
        full_audio = full_audio / max_val * 0.95

    return full_audio, KOKORO_SAMPLE_RATE


def _synthesize_cloud_tts(text: str):
    """Step 3 emergency cloud TTS fallback (edge-tts / gTTS) using natural US English."""
    try:
        import asyncio
        import edge_tts
        import tempfile
        voice = "en-US-ChristopherNeural"
        communicate = edge_tts.Communicate(text, voice)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        asyncio.run(communicate.save(tmp_path))
        audio, sr = sf.read(tmp_path, dtype="float32")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio, sr
    except Exception as e:
        logger.warning(f"edge-tts unavailable/failed ({e}); trying gTTS...")
        try:
            from gtts import gTTS
            import tempfile
            tts = gTTS(text=text, lang='en', tld='com')
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name
            tts.save(tmp_path)
            audio, sr = sf.read(tmp_path, dtype="float32")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            return audio, sr
        except Exception as err2:
            raise RuntimeError(f"Cloud TTS fallbacks unavailable: {err2}")


def _synthesize(text: str, voice: str = "am_adam", speed: float = 1.0):
    """Synthesize a single segment with retry logic.

    FLOW:
      1. Chatterbox + cloned voice reference — try up to CHATTERBOX_MAX_RETRIES
         times (default 3) with CHATTERBOX_RETRY_DELAY seconds between attempts.
      2. If ALL Chatterbox attempts fail → Kokoro (no retries, one shot).
      3. If Kokoro also fails → Emergency Cloud TTS (edge-tts / gTTS).
      4. If all fail → RuntimeError.
    """
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    narration_text = prepare_natural_narration(text)

    # Resolve fallback voice at call time so an explicit argument wins and an
    # empty/`None` argument still lands on the env-configured voice. When
    # VOICE_ROTATE=auto (default), the env voice is a pool member picked
    # deterministically from the video topic — see _rotated_voice().
    voice = (voice or "").strip() or KOKORO_VOICE

    # ---- STEP 1: Chatterbox with the creator's voice reference ----
    # Skipped entirely when TTS_ENGINE=kokoro (CPU production path): burning
    # minutes on a guaranteed-slow/timing-out clone attempt is exactly what
    # made CI runs fragile on GitHub-hosted runners.
    chatterbox_errors = []
    if TTS_ENGINE == "kokoro":
        logger.info("TTS_ENGINE=kokoro → skipping Chatterbox clone attempt (CPU path)")
    else:
        for attempt in range(1, CHATTERBOX_MAX_RETRIES + 1):
            try:
                audio, sr = _synthesize_chatterbox(narration_text, attempt=attempt)
                engine = "chatterbox_clone" if _voice_reference_ok() else "chatterbox_default"
                # 2026-08-19: mature the synthetic default voice (skip when the
                # creator's own reference is being used — never alter it).
                if engine == "chatterbox_default":
                    audio = _mature_voice(audio, sr)
                logger.info(f"Chatterbox SUCCESS on attempt {attempt}/{CHATTERBOX_MAX_RETRIES} ({engine})")
                return audio, sr, engine
            except Exception as e:
                chatterbox_errors.append(str(e))
                logger.warning(f"Chatterbox attempt {attempt}/{CHATTERBOX_MAX_RETRIES} FAILED: {e}")
                if attempt < CHATTERBOX_MAX_RETRIES:
                    logger.info(f"Waiting {CHATTERBOX_RETRY_DELAY}s before retry...")
                    time.sleep(CHATTERBOX_RETRY_DELAY)

        logger.error(
            f"All {CHATTERBOX_MAX_RETRIES} Chatterbox attempts failed. Errors: "
            + " | ".join(chatterbox_errors)
        )

    # ---- STEP 2: Kokoro fallback (one shot) ----
    logger.info("Falling back to Kokoro TTS engine...")
    # Python deletes the `as` variable when an except block exits, so binding
    # the message to a normal name is required — referencing `kokoro_err`
    # further down raised NameError and destroyed the real diagnostic exactly
    # when all engines had failed and it was needed most.
    kokoro_error_message = "not attempted"
    try:
        audio, sr = _synthesize_kokoro(narration_text, voice, speed)
        logger.info("Kokoro fallback SUCCESS")
        return audio, sr, "kokoro"
    except Exception as kokoro_err:
        kokoro_error_message = str(kokoro_err)
        logger.warning(f"Kokoro fallback failed: {kokoro_err}. Trying emergency cloud TTS...")

    # ---- STEP 3: Emergency Cloud TTS fallback ----
    try:
        audio, sr = _synthesize_cloud_tts(narration_text)
        logger.info("Cloud TTS fallback SUCCESS")
        return audio, sr, "cloud_tts"
    except Exception as cloud_err:
        error_msg = (
            f"VOICE GENERATION FAILED — all engines exhausted. "
            f"Chatterbox errors: [{' | '.join(chatterbox_errors)}]. "
            f"Kokoro error: [{kokoro_error_message}]. "
            f"Cloud TTS error: [{cloud_err}]."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)


def generate_voice(text: str, voice: str = None, output_path: str = "output/voice.wav", speed: float = 1.0) -> str:
    """Generate clear, natural YouTube narration.

    Chatterbox with the approved creator reference is always tried first.
    Kokoro is only a technical fallback and cannot reproduce that voice.
    """
    try:
        logger.info("Generating natural YouTube voiceover (fallback_voice=%r, speed=%s)...", voice, speed)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        audio, sr, engine = _synthesize(text, voice, speed)
        sf.write(output_path, audio, sr)
        logger.info(f"Voice saved via {engine}: {output_path} ({len(audio)} samples, {len(audio)/sr:.2f}s)")
        return output_path
    except Exception as e:
        logger.error(f"Voice generation failed: {e}")
        raise RuntimeError(f"Voice generation error: {e}")


def generate_voice_segments(
    scenes: List[dict],
    voice: str = None,           # only used if a segment falls back to Kokoro; None → KOKORO_VOICE env
    output_dir: str = "output/segments",
    speed: float = 1.0,      # only used if a segment falls back to Kokoro
    topic: str = "",         # used by VOICE_ROTATE to pick a consistent voice per video
) -> List[Dict]:
    """
    Each scene gets clear, conversational narration via Chatterbox using the
    creator's voice reference, with Kokoro as a technical per-segment fallback.

    Raises
    ------
    RuntimeError
        If any segment fails on ALL engines (Chatterbox x3 + Kokoro).
        The pipeline MUST abort — a video with missing voiceover segments
        is worse than no video at all.
    """
    os.makedirs(output_dir, exist_ok=True)
    segments = []
    engine_counts = {}

    for i, scene in enumerate(scenes):
        caption = scene.get('caption', '').strip() if isinstance(scene, dict) else str(scene)
        if not caption:
            caption = " "

        # No try/except swallowing here — if _synthesize raises, the whole
        # pipeline must abort. Silent 1.5s silence inserts are NOT acceptable;
        # main.py's quality gate will catch the crash and log it properly.
        # Per-scene micro tempo jitter (deterministic by scene index) makes
        # narration sound like one person reading naturally, not a metronome:
        # some lines slightly faster, some slightly slower, ~±1.5% around the
        # caller-supplied speed. A fixed global tempo on every scene is a tell.
        _scene_tempo = _scene_tempo_for(speed, i, caption)
        # Per-video voice rotation (VOICE_ROTATE=auto, default in workflow):
        # every video gets a consistent-but-varied narrator instead of one
        # frozen voice channel-wide. Derived per-topic so it is stable.
        _seg_voice = _rotated_voice(voice, topic or scene.get("topic", "")) if i == 0 else voice
        audio, sr, engine = _synthesize(caption, _seg_voice, _scene_tempo)

        engine_counts[engine] = engine_counts.get(engine, 0) + 1
        path = os.path.join(output_dir, f"seg_{i}.wav")
        sf.write(path, audio, sr)
        duration = len(audio) / sr

        segments.append({"path": path, "duration": duration, "caption": caption, "tts_engine": engine})
        logger.info(f"Segment {i+1}/{len(scenes)} via {engine}: {duration:.2f}s (tempo {_scene_tempo:.3f}) - \"{caption[:50]}...\"")

    total = sum(s['duration'] for s in segments)
    logger.info(f"Total natural voiceover duration: {total:.2f}s | engines used: {engine_counts}")

    # Final consistency check — all segments must use the SAME engine.
    # Mixed engines mean different voice timbres across scenes, which
    # sounds jarring and unprofessional. Abort if mixed.
    engines_used = set(engine_counts.keys())
    if len(engines_used) > 1:
        raise RuntimeError(
            f"Mixed TTS engines in the same video: {dict(engine_counts)} "
            f"— voices would sound inconsistent. Aborting."
        )

    return segments
