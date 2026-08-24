"""Recover a missing YouTube upload from a partial multi-platform run.

This command is intentionally narrow: it requires one exact partial-upload
fingerprint whose Facebook and Instagram receipts are completed and whose
YouTube receipt is absent. It reuses the original rendered video and captions,
then merges the new YouTube receipt back with the existing Meta receipts.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uploader  # noqa: E402

FINGERPRINT = "1db197dd85cafe1436777479b4c249f20b0bc9ddd4c78c22c9cfa21579868d5b"
DEFAULT_TITLE = "Your Nightmare Fuel: Vampire Squid's Glowing Goo"
DEFAULT_TOPIC = "the vampire squid"
DEFAULT_HOOK = "Why does this creature bleed light?"
DEFAULT_VOICEOVER = " ".join(
    [
        DEFAULT_HOOK,
        "Living two thousand feet down means avoiding predators without any sunlight to hide you.",
        "It cannot squirt black ink like shallow water cousins when a big fish attacks.",
        "Instead of ink, special glands squirt sticky clouds of glowing blue mucus directly out.",
        "Thousands of microscopic points of light blind and confuse whatever is chasing it.",
        "Then it pulls its webbed arms over its head to hide its body completely.",
        "It dumps glowing liquid from its arm tips instead of ink to survive the deep.",
        DEFAULT_HOOK,
    ]
)
DEFAULT_TAGS = ["vampire squid", "deep sea animals", "ocean science", "marine biology"]


def _load_json(path: Path, fallback):
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data
    except (OSError, json.JSONDecodeError):
        return fallback


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
    temporary.replace(path)


def _find_partial_record(state: dict, fingerprint: str, title: str) -> tuple[str, dict]:
    if fingerprint and fingerprint in state:
        candidates = [(fingerprint, state[fingerprint])]
    else:
        candidates = [(key, value) for key, value in state.items() if value.get("title") == title]
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected exactly one partial record for title/fingerprint; found {len(candidates)}"
        )
    key, record = candidates[0]
    if record.get("status") != "started":
        raise RuntimeError("Recovery requires a top-level started receipt")
    if record.get("youtube_video_id") or record.get("youtube", {}).get("video_id"):
        raise RuntimeError("YouTube already has a receipt; refusing a duplicate recovery")
    for platform in ("facebook", "instagram"):
        if record.get(platform, {}).get("status") != "completed":
            raise RuntimeError(f"Recovery requires a completed {platform} receipt")
    return key, record


def _append_history(history_path: Path, fingerprint: str, script_data: dict, record: dict) -> None:
    history = _load_json(history_path, [])
    if not isinstance(history, list):
        history = []
    if any(item.get("content_fingerprint") == fingerprint for item in history):
        return
    history.append(
        {
            "content_fingerprint": fingerprint,
            "title": script_data["title"],
            "topic": script_data["topic"],
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "publish_at": record.get("publish_at") or uploader._RUN_PUBLISH_AT,
            "youtube_video_id": record.get("youtube_video_id"),
            "facebook_video_id": record.get("facebook", {}).get("video_id"),
            "instagram_media_id": record.get("instagram", {}).get("media_id"),
            "facebook_success": record.get("facebook", {}).get("status") == "completed",
            "instagram_success": record.get("instagram", {}).get("status") == "completed",
            "duration_seconds": 41.03,
            "meta_cut_seconds": 14.0,
            "ending_mode": "loop",
            "sources": [],
            "source_verification": [],
            "recovered_from_partial_run": True,
        }
    )
    _save_json(history_path, history)


def recover(args: argparse.Namespace) -> str:
    artifact = Path(args.artifact_dir).resolve()
    data_dir = artifact / "data"
    output_dir = artifact / "output"
    state_path = data_dir / "upload_state.json"
    history_path = data_dir / "video_history.json"
    video_path = output_dir / "final_video.mp4"
    thumb_path = output_dir / "thumbnail.jpg"
    srt_path = output_dir / "captions.srt"
    for path in (state_path, history_path, video_path, srt_path):
        if not path.exists():
            raise FileNotFoundError(path)

    state = _load_json(state_path, {})
    if not isinstance(state, dict):
        raise RuntimeError("Artifact upload state is not an object")
    checkpoint = _load_json(data_dir / "pipeline_checkpoint.json", {})
    if args.expected_run_id and str(checkpoint.get("run_id")) != str(args.expected_run_id):
        raise RuntimeError(
            f"Artifact checkpoint run ID {checkpoint.get('run_id')} does not match "
            f"requested run {args.expected_run_id}"
        )
    fingerprint, partial = _find_partial_record(state, args.fingerprint, args.title)

    script_data = {
        "title": args.title,
        "topic": args.topic,
        "hook": DEFAULT_HOOK,
        "voiceover": DEFAULT_VOICEOVER,
        "summary": "The vampire squid uses glowing mucus instead of black ink in the deep sea.",
        "description": "A calm, evidence-backed explanation of how vampire squid use bioluminescent mucus in the deep sea.",
        "tags": DEFAULT_TAGS,
        "hashtags": ["#vampiresquid", "#deepscience", "#oceanscience"],
        "pinned_comment": "The deep ocean has some remarkably practical defenses.",
        "srt_path": str(srt_path),
    }
    computed = uploader._content_fingerprint(script_data)
    if computed != fingerprint:
        raise RuntimeError(
            f"Recovery metadata fingerprint mismatch: expected {fingerprint}, computed {computed}"
        )

    uploader.UPLOAD_STATE_PATH = str(state_path)
    uploader.VIDEO_HISTORY_PATH = str(history_path)
    tags = list(script_data["tags"])
    # _upload_youtube deliberately blocks a top-level started record. Remove
    # only this exact record while it runs, then restore the completed Meta
    # receipts immediately if the YouTube attempt fails.
    working_state = dict(state)
    working_state.pop(fingerprint, None)
    _save_json(state_path, working_state)
    try:
        success, video_id = uploader._upload_youtube(str(video_path), str(thumb_path), script_data, tags)
    except Exception:
        _save_json(state_path, {**working_state, fingerprint: partial})
        raise
    if not success or not video_id:
        _save_json(state_path, {**working_state, fingerprint: partial})
        raise RuntimeError("YouTube-only recovery did not return a video ID")

    latest = _load_json(state_path, {}).get(fingerprint, {})
    for platform in ("facebook", "instagram"):
        latest[platform] = partial[platform]
    latest["status"] = "completed"
    latest["youtube_video_id"] = str(video_id)
    latest["publish_at"] = uploader._RUN_PUBLISH_AT
    latest["recovered_at"] = datetime.now(timezone.utc).isoformat()
    _save_json(state_path, {**_load_json(state_path, {}), fingerprint: latest})
    _append_history(history_path, fingerprint, script_data, latest)
    print(f"Recovered YouTube video {video_id} for fingerprint {fingerprint}")
    print("Existing Facebook and Instagram receipts were preserved; no Meta API was called.")
    return str(video_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--fingerprint", default=FINGERPRINT)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--expected-run-id", default="")
    args = parser.parse_args()
    try:
        recover(args)
    except Exception as exc:  # noqa: BLE001 - CLI must return a clear fail-closed error
        print(f"Recovery refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
