"""TEMPORARY test entrypoint for the avatar pipeline (voice clone + talking avatar).

Not part of production yet. Run after scripts/setup_avatar_models.sh. Produces:
  data/_avatar_test/cloned_voice.wav   - the voice-cloned audio
  data/_avatar_test/avatar_preview.jpg - a middle frame of the generated video (for visual inspection)
  data/_avatar_test/result.json        - timings + status, since this environment can't
                                          download raw video artifacts to inspect directly

Commits these results back to the branch so they can be pulled and reviewed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from avatar import AvatarPipelineError, clone_voice, generate_avatar_video  # noqa: E402

TEST_TEXT = (
    "Did you know your brain can trick you into remembering things that never happened? "
    "Here's the wild part."
)


def extract_preview_frame(video_path: Path, out_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vf", "select=eq(n\\,15)", "-vframes", "1", str(out_path)],
        capture_output=True,
    )


def main() -> None:
    out_dir = REPO_ROOT / "data" / "_avatar_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"text": TEST_TEXT}
    t0 = time.time()

    try:
        cloned_audio = clone_voice(
            TEST_TEXT,
            REPO_ROOT / "assets" / "avatar" / "voice_sample.m4a",
            out_dir / "cloned_voice.wav",
        )
        result["voice_clone_seconds"] = round(time.time() - t0, 1)
        result["voice_clone_status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        result["voice_clone_status"] = f"FAILED: {exc}"
        Path("data/_avatar_test/result.json").write_text(json.dumps(result, indent=2))
        raise

    t1 = time.time()
    try:
        video_path = generate_avatar_video(
            REPO_ROOT / "assets" / "avatar" / "face.png",
            cloned_audio,
            out_dir / "sadtalker_output",
        )
        result["avatar_generation_seconds"] = round(time.time() - t1, 1)
        result["avatar_generation_status"] = "ok"
        result["video_path"] = str(video_path.relative_to(REPO_ROOT))
        extract_preview_frame(video_path, out_dir / "avatar_preview.jpg")
        result["preview_extracted"] = (out_dir / "avatar_preview.jpg").exists()
    except AvatarPipelineError as exc:
        result["avatar_generation_status"] = f"FAILED: {exc}"

    result["total_seconds"] = round(time.time() - t0, 1)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    subprocess.run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        check=False,
    )
    subprocess.run(["git", "add", "-f", "data/_avatar_test/result.json"], check=False)
    if (out_dir / "avatar_preview.jpg").exists():
        subprocess.run(["git", "add", "-f", "data/_avatar_test/avatar_preview.jpg"], check=False)
    subprocess.run(["git", "commit", "-m", "chore: avatar pipeline test result"], check=False)
    subprocess.run(["git", "push", "origin", "HEAD"], check=False)


if __name__ == "__main__":
    main()
