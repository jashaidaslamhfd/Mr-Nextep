from __future__ import annotations
import json, os
from typing import Any
from config import Settings

TOPICS = ["Why do déjà vu moments feel so real?", "Why does a smell unlock an old memory?", "Why does your body jolt as you fall asleep?", "Why do nightmares wake you up?", "Why can silence feel physically loud?"]

def fallback(topic: str) -> dict[str, Any]:
    return {"title": topic[:70], "description": f"A dark science explanation in under 30 seconds. #shorts #science #mystery", "tags": ["dark science", "mystery", "psychology", "shorts"], "scenes": [
        {"caption": topic, "narration": topic}, {"caption": "Your brain spots a pattern before you notice it.", "narration": "Your brain spots a pattern before you notice it."},
        {"caption": "Then it links that signal to an older memory.", "narration": "Then it links that signal to an older memory."}, {"caption": "The emotion arrives before the explanation.", "narration": "The emotion arrives before the explanation."},
        {"caption": "That is why the moment feels impossible to ignore.", "narration": "That is why the moment feels impossible to ignore."}, {"caption": "Your mind is predicting the next detail.", "narration": "Your mind is predicting the next detail."},
        {"caption": "But prediction is not proof.", "narration": "But prediction is not proof."}, {"caption": "The mystery is your brain filling in the gap.", "narration": "The mystery is your brain filling in the gap."},
    ]}

def choose_topic(settings: Settings) -> str:
    if settings.topic: return settings.topic
    path = settings.data_dir / "topic_index.json"
    try: index = int(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError, json.JSONDecodeError): index = 0
    path.write_text(json.dumps(index + 1))
    return TOPICS[index % len(TOPICS)]

def generate_script(topic: str, settings: Settings) -> dict[str, Any]:
    # Deterministic fallback keeps production available when an LLM provider is unavailable.
    return fallback(topic)
