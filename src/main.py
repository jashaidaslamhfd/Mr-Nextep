from __future__ import annotations
import json
import logging
import subprocess
from datetime import UTC, datetime
from config import SETTINGS
from content import choose_topic, generate_script
from media import render, validate
from youtube import upload
from meta import publish as publish_meta
from guards import enforce, load_history, save_history

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _git_persist(paths: list[str], message: str) -> None:
    """Best-effort state commit with rebase; never hide the production result."""
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=False)
    subprocess.run(["git", "add", *paths], check=False)
    commit = subprocess.run(["git", "commit", "-m", message], check=False, capture_output=True, text=True)
    if commit.returncode == 0:
        pull = subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False, capture_output=True, text=True)
        if pull.returncode == 0:
            pushed = subprocess.run(["git", "push", "origin", "HEAD:main"], check=False, capture_output=True, text=True)
            if pushed.returncode != 0: log.warning("State push failed: %s", pushed.stderr[-500:])
        else:
            log.warning("State rebase failed: %s", pull.stderr[-500:])


def run() -> dict:
    errors = SETTINGS.validate()
    if errors: raise RuntimeError("Configuration invalid: " + "; ".join(errors))
    history_path = SETTINGS.data_dir / "content_history.json"
    history = load_history(history_path)
    last_error: Exception | None = None
    for attempt in range(SETTINGS.max_attempts):
        topic = choose_topic(SETTINGS)
        if SETTINGS.topic and attempt:
            topic = f"{SETTINGS.topic} — fresh angle {attempt + 1}"
        script = generate_script(topic, SETTINGS)
        if SETTINGS.topic:
            script["title"] = topic[:70]
            if script.get("scenes"):
                script["scenes"][0]["narration"] = topic
        try:
            video = render(script, SETTINGS)
            technical = validate(video, SETTINGS)
            guard = enforce(script, float(technical["duration"]), history)
            break
        except RuntimeError as exc:
            last_error = exc
            log.warning("Attempt %d/%d rejected: %s", attempt + 1, SETTINGS.max_attempts, exc)
            continue
    else:
        raise RuntimeError(f"Could not produce a valid unique video after {SETTINGS.max_attempts} attempts: {last_error}")

    SETTINGS.ensure_dirs()
    clip_manifest = SETTINGS.output_dir / "clip_hashes.json"
    clip_hashes = json.loads(clip_manifest.read_text(encoding="utf-8")) if clip_manifest.exists() else []
    source_urls = [p.read_text(encoding="utf-8") for p in sorted((SETTINGS.output_dir / "scenes").glob("*.source_url"))]
    created_at = datetime.now(UTC).isoformat()
    result = {"created_at": created_at, "status": "pending", "topic": topic, "title": script["title"], "video_path": str(video), "clip_hashes": clip_hashes, **technical, **guard}

    # Persist the reservation before any external upload. A later run can reject it.
    history.append(guard)
    save_history(history_path, history)
    clip_history_path = SETTINGS.data_dir / "clip_history.json"
    clip_history = load_history(clip_history_path)
    clip_history.extend({"hash": h, "source_url": source_urls[i] if i < len(source_urls) else "", "title": result["title"], "created_at": created_at} for i, h in enumerate(clip_hashes))
    clip_history_path.write_text(json.dumps(clip_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    video_history_path = SETTINGS.data_dir / "video_history.json"
    video_history = load_history(video_history_path)
    video_history.append(result)
    video_history_path.write_text(json.dumps(video_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    topic_index_path = SETTINGS.data_dir / "topic_index.json"
    _git_persist([str(history_path), str(clip_history_path), str(video_history_path), str(topic_index_path)], "chore: reserve generated video state")

    try:
        result.update(upload(video, script, SETTINGS))
        if not SETTINGS.dry_run:
            try:
                result["meta"] = publish_meta(video, script, result)
            except Exception as exc:
                log.exception("Meta publishing failed after YouTube upload; preserving YouTube result")
                result["meta"] = {"status": "error", "reason": str(exc)}
        result["status"] = "uploaded"
    except Exception:
        log.exception("Upload failed; pending state remains committed for duplicate protection")
        raise

    video_history[-1] = result
    video_history_path.write_text(json.dumps(video_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    _git_persist([str(video_history_path)], "chore: finalize generated video state")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run()
