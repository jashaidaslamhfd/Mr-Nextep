from __future__ import annotations
import json
import subprocess
from datetime import UTC, datetime
from config import SETTINGS
from content import choose_topic, generate_script
from media import render, validate
from youtube import upload
from meta import publish as publish_meta
from guards import enforce, load_history, save_history

def run() -> dict:
    errors = SETTINGS.validate()
    if errors: raise RuntimeError("Configuration invalid: " + "; ".join(errors))
    history_path = SETTINGS.data_dir / "content_history.json"
    history = load_history(history_path)
    for _ in range(10):
        topic = choose_topic(SETTINGS); script = generate_script(topic, SETTINGS)
        if SETTINGS.topic:
            script["title"] = topic[:70]
            if script.get("scenes"):
                script["scenes"][0]["narration"] = topic
        try:
            video = render(script, SETTINGS); technical = validate(video, SETTINGS)
            guard = enforce(script, technical["duration"], history)
            break
        except RuntimeError as exc:
            if "Duplicate" not in str(exc): raise
    else:
        raise RuntimeError("Could not find a non-duplicate topic after 10 attempts")
    clip_manifest = SETTINGS.output_dir / "clip_hashes.json"
    clip_hashes = json.loads(clip_manifest.read_text(encoding="utf-8")) if clip_manifest.exists() else []
    source_urls = [p.read_text(encoding="utf-8") for p in SETTINGS.output_dir.glob("scenes/*.source_url")]
    result = {"created_at": datetime.now(UTC).isoformat(), "topic": topic, "title": script["title"], "video_path": str(video), "clip_hashes": clip_hashes, **technical, **guard}
    result.update(upload(video, script, SETTINGS))
    if not SETTINGS.dry_run:
        result["meta"] = publish_meta(video, script, result)
    SETTINGS.ensure_dirs(); (SETTINGS.data_dir / "video_history.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    history.append(guard); save_history(history_path, history)
    clip_history_path = SETTINGS.data_dir / "clip_history.json"
    try:
        clip_history = json.loads(clip_history_path.read_text(encoding="utf-8")) if clip_history_path.exists() else []
    except (OSError, json.JSONDecodeError):
        clip_history = []
    clip_history.extend({"hash": h, "source_url": source_urls[i] if i < len(source_urls) else "", "title": result["title"], "created_at": result["created_at"]} for i, h in enumerate(clip_hashes))
    clip_history_path.write_text(json.dumps(clip_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=False)
    subprocess.run(["git", "add", str(history_path), str(clip_history_path)], check=False)
    subprocess.run(["git", "commit", "-m", "chore: record generated clip fingerprints"], check=False, capture_output=True)
    subprocess.run(["git", "push"], check=False, capture_output=True)
    print(json.dumps(result, indent=2)); return result
if __name__ == "__main__": run()
