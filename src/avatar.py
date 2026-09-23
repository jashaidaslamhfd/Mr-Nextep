"""Talking-avatar pipeline: clones the channel owner's voice (OpenVoice V2) and
animates their face photo to speak the script (SadTalker), both fully open-source
and CPU-only (no GPU on GitHub-hosted runners, so this is slow — expect several
minutes per video, not seconds).

This module is intentionally isolated from the existing stock-footage pipeline
(media.py) so the current, working production flow is untouched while this is
tested. It is invoked directly by scripts/test_avatar_pipeline.py for now.

Both third-party tools are cloned (not pip-installed) by scripts/setup_avatar_models.sh
into third_party/OpenVoice and third_party/SadTalker before this module is imported.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY = REPO_ROOT / "third_party"
OPENVOICE_DIR = THIRD_PARTY / "OpenVoice"
SADTALKER_DIR = THIRD_PARTY / "SadTalker"


class AvatarPipelineError(RuntimeError):
    """Raised when voice cloning or avatar generation fails."""


def clone_voice(text: str, reference_audio: Path, output_path: Path, language: str = "EN_NEWEST") -> Path:
    """Synthesize `text` in the voice of `reference_audio` using OpenVoice V2.

    Two stages, matching OpenVoice V2's own demo_part3 pattern:
    1. MeloTTS speaks the text in a generic base voice.
    2. OpenVoice's tone-color converter re-colors that audio to match the
       reference speaker's tone, using a "source" embedding for the base
       speaker and a "target" embedding extracted from the reference clip.
    """
    if str(OPENVOICE_DIR) not in sys.path:
        sys.path.insert(0, str(OPENVOICE_DIR))

    import torch
    from melo.api import TTS
    from openvoice import se_extractor
    from openvoice.api import ToneColorConverter

    device = "cpu"
    ckpt_converter = OPENVOICE_DIR / "checkpoints_v2" / "converter"
    tone_color_converter = ToneColorConverter(str(ckpt_converter / "config.json"), device=device)
    tone_color_converter.load_ckpt(str(ckpt_converter / "checkpoint.pth"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_base_audio = output_path.with_name(output_path.stem + "_base_tts.wav")

    try:
        target_se, _ = se_extractor.get_se(str(reference_audio), tone_color_converter, vad=True)
    except Exception as exc:  # noqa: BLE001 - surfaced as a clear pipeline error
        raise AvatarPipelineError(f"Could not extract a voice profile from {reference_audio}: {exc}") from exc

    model = TTS(language=language, device=device)
    speaker_ids = model.hps.data.spk2id
    speaker_key = next(iter(speaker_ids.keys()))
    speaker_id = speaker_ids[speaker_key]
    model.tts_to_file(text, speaker_id, str(tmp_base_audio), speed=1.0)

    source_se_path = OPENVOICE_DIR / "checkpoints_v2" / "base_speakers" / "ses" / f"{speaker_key.lower().replace('_', '-')}.pth"
    source_se = torch.load(source_se_path, map_location=device)

    tone_color_converter.convert(
        audio_src_path=str(tmp_base_audio),
        src_se=source_se,
        tgt_se=target_se,
        output_path=str(output_path),
        message="@MrNextep",
    )
    tmp_base_audio.unlink(missing_ok=True)
    return output_path


def generate_avatar_video(face_image: Path, audio_path: Path, output_dir: Path) -> Path:
    """Animate `face_image` lip-synced to `audio_path` using SadTalker.

    Runs SadTalker's own inference.py as a subprocess (its own code is not a
    clean importable API), then locates the .mp4 it wrote into output_dir.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(SADTALKER_DIR / "inference.py"),
        "--driven_audio", str(audio_path),
        "--source_image", str(face_image),
        "--result_dir", str(output_dir),
        "--still",  # keep head mostly static — more natural for a talking-head Short than full-body motion
        "--preprocess", "full",
        "--cpu",
    ]
    result = subprocess.run(cmd, cwd=str(SADTALKER_DIR), capture_output=True, text=True)
    if result.returncode != 0:
        raise AvatarPipelineError(
            f"SadTalker inference failed (exit {result.returncode}).\n"
            f"stdout(tail): {result.stdout[-2000:]}\nstderr(tail): {result.stderr[-2000:]}"
        )

    produced = sorted(output_dir.glob("**/*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not produced:
        raise AvatarPipelineError(f"SadTalker reported success but no .mp4 was found in {output_dir}")
    return produced[0]
