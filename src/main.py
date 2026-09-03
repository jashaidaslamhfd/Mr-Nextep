from __future__ import annotations
import json
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
        try:
            video = render(script, SETTINGS); technical = validate(video, SETTINGS)
            guard = enforce(script, technical["duration"], history)
            break
        except RuntimeError as exc:
            if "Duplicate" not in str(exc): raise
    else:
        raise RuntimeError("Could not find a non-duplicate topic after 10 attempts")
    result = {"created_at": datetime.now(UTC).isoformat(), "topic": topic, "title": script["title"], "video_path": str(video), **technical, **guard}
    result.update(upload(video, script, SETTINGS))
    if not SETTINGS.dry_run:
        result["meta"] = publish_meta(video, script, result)
    SETTINGS.ensure_dirs(); (SETTINGS.data_dir / "video_history.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    history.append(guard); save_history(history_path, history)
    print(json.dumps(result, indent=2)); return result
if __name__ == "__main__": run()
