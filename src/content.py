from __future__ import annotations
import json
import os
import hashlib
import logging
from urllib.request import Request, urlopen
from typing import Any
from config import Settings

log = logging.getLogger(__name__)

TOPICS = [
    "Why do déjà vu moments feel so real?",
    "Why does a smell unlock an old memory?",
    "Why does your body jolt as you fall asleep?",
    "Why do nightmares wake you up?",
    "Why can silence feel physically loud?",
    "Why do dim mirrors melt your face?",
    "Why do you see shadows in the dark?"
]

def fallback(topic: str) -> dict[str, Any]:
    """High-retention dark science fallback adhering to strict guard & similarity rules."""
    seed = int(hashlib.sha256(topic.encode()).hexdigest()[:8], 16)
    focus = topic.rstrip("?.!").strip()

    # Pattern-Interrupt Hook for Scene 1 (strictly 4-7 words)
    hooks = [
        "Your brain is hiding this secret.",
        "This mind glitch is terrifyingly real.",
        "The truth about this will shock you.",
        "Never ignore this strange brain signal.",
        "Science explains this uncanny human reflex."
    ]
    hook = hooks[seed % len(hooks)]

    # 8 scenes strictly 1 to 8 words per caption, targeted for 18-22s duration
    scenes = [
        {"caption": hook, "narration": f"{focus}... and your brain is hiding the real cause."},
        {"caption": "Your sensory neurons fire before awareness.", "narration": "Your sensory neurons fire signals milliseconds before your conscious awareness reacts."},
        {"caption": "A hidden neural pathway takes over.", "narration": f"When {focus.lower()} happens, an ancient survival pathway takes over your nervous system."},
        {"caption": "Neuroscientists call this spontaneous cognitive drift.", "narration": "Neuroscientists call this spontaneous cognitive drift—a split-second desynchronization."},
        {"caption": "Your brain manufactures a false memory.", "narration": "To prevent mental overload, your brain manufactures an instant logical explanation."},
        {"caption": "The eerie feeling is completely biological.", "narration": "The eerie sensation is not imagination. It is pure biological machinery lagging behind."},
        {"caption": "You just caught your mind glitching.", "narration": "You literally caught your subconscious mind in a processing loop."},
        {"caption": "Which is why you felt that...", "narration": "Which is why you felt that exact sensation the moment it started."},
    ]

    return {
        "title": topic[:70],
        "description": f"The dark neuroscience behind {focus.lower()} explained in 20 seconds. #shorts #science #psychology #mystery",
        "tags": ["dark science", "psychology facts", "brain glitch", "mystery", "shorts"],
        "scenes": scenes
    }

def choose_topic(settings: Settings) -> str:
    if settings.topic:
        return settings.topic
    queue_path = settings.data_dir / "search_demand_queue_us.json"
    queue_index_path = settings.data_dir / "trend_topic_index.json"
    try:
        queue = json.loads(queue_path.read_text(encoding="utf-8")).get("topics", [])
        index = int(json.loads(queue_index_path.read_text(encoding="utf-8")))
        if queue:
            queue_index_path.write_text(json.dumps(index + 1))
            return str(queue[index % len(queue)].get("question_phrase") or queue[index % len(queue)].get("topic"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    path = settings.data_dir / "topic_index.json"
    try:
        index = int(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        index = 0
    path.write_text(json.dumps(index + 1))
    return TOPICS[index % len(TOPICS)]

SYSTEM_PROMPT = """You write US-English dark-science YouTube Shorts for Mr-Nextep.
Return JSON only with title, description, tags, and exactly 8 scenes.
Rules:
- Target 18-22 seconds total duration.
- Scene 1 caption MUST be 4-7 words and create an immediate psychological curiosity gap.
- Every scene caption MUST be brief (1 to 8 words maximum).
- Each scene must contain "caption" and "narration" strings.
- Scene 8 narration must provide a curiosity loop-back ending that connects into Scene 1.
- Never use clickbait medical promises, emojis, or greetings like "Did you know".
"""

def generate_script(topic: str, settings: Settings) -> dict[str, Any]:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return fallback(topic)
    payload = {
        "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "temperature": 0.75,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Create one original Short about: {topic}"}
        ],
        "response_format": {"type": "json_object"}
    }
    try:
        request = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST"
        )
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
        result = json.loads(data["choices"][0]["message"]["content"])
        scenes = result.get("scenes", [])
        if (
            not result.get("title") or len(scenes) != 8 or
            any(not s.get("caption") or not s.get("narration") for s in scenes) or
            not 4 <= len(str(scenes[0]["caption"]).split()) <= 12 or
            any(len(str(s.get("caption", "")).split()) > 8 for s in scenes)
        ):
            raise ValueError("LLM output failed the eight-scene schema")
        return result
    except Exception as exc:
        log.warning("LLM generation failed; using enhanced fallback: %s", exc)
        return fallback(topic)
