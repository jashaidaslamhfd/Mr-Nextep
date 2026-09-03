from __future__ import annotations
import json, os
from urllib.request import Request, urlopen
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

SYSTEM_PROMPT = """You write US-English dark-science YouTube Shorts for Mr-Nextep.
Return JSON only with title, description, tags, and exactly 8 scenes.
Rules: target 15-24 seconds; hook viewers in the first 2 seconds; one surprising,
credible idea per video; every scene must advance the explanation; use short spoken
sentences; make each caption readable as one-word-at-a-time animation; create a
strong curiosity loop-back ending; never use clickbait claims, medical promises,
engagement bait, emojis, filler intros, logos, or repeated wording. Avoid any topic
or angle that is a duplicate of the supplied topic. Do not invent citations.
Each scene must contain caption and narration strings. Caption text should be brief.
"""

def generate_script(topic: str, settings: Settings) -> dict[str, Any]:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return fallback(topic)
    payload = {"model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"), "temperature": 0.75, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": f"Create one original Short about: {topic}"}], "response_format": {"type": "json_object"}}
    try:
        request = Request("https://api.groq.com/openai/v1/chat/completions", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
        result = json.loads(data["choices"][0]["message"]["content"])
        scenes = result.get("scenes", [])
        if not result.get("title") or len(scenes) != 8 or any(not s.get("caption") or not s.get("narration") for s in scenes):
            raise ValueError("LLM output failed the eight-scene schema")
        return result
    except Exception:
        # Provider failure never blocks a safe run; the deterministic script still passes local gates.
        return fallback(topic)
