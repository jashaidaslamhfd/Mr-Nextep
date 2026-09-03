from __future__ import annotations
import json
from datetime import UTC, datetime
from config import SETTINGS
from content import choose_topic, generate_script
from media import render, validate
from youtube import upload

def run() -> dict:
    errors = SETTINGS.validate()
    if errors: raise RuntimeError("Configuration invalid: " + "; ".join(errors))
    topic = choose_topic(SETTINGS); script = generate_script(topic, SETTINGS); video = render(script, SETTINGS); technical = validate(video, SETTINGS)
    result = {"created_at": datetime.now(UTC).isoformat(), "topic": topic, "title": script["title"], "video_path": str(video), **technical}
    result.update(upload(video, script, SETTINGS)); SETTINGS.ensure_dirs(); (SETTINGS.data_dir / "video_history.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2)); return result
if __name__ == "__main__": run()
