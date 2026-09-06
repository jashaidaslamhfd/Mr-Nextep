from __future__ import annotations
import json
import os
import hashlib
import logging
from urllib.request import Request, urlopen
from typing import Any
from config import Settings

log = logging.getLogger(__name__)

# 10 High-Retention Viral Dark Science Script Templates
# Each template is engineered for:
# 1. 3-7 word Pattern-Interrupt Hook (First 2 seconds)
# 2. Scene captions strictly 1-8 words
# 3. 8 scenes targeting 18-22s duration
# 4. Infinite replay loop connector (Scene 8 connects back to Scene 1)
VIRAL_DARK_TEMPLATES = [
    {
        "title": "Why Your Brain Hallucinates In Total Silence",
        "description": "The terrifying sensory deprivation paradox explained in 20 seconds. #shorts #darkscience #psychology",
        "tags": ["dark science", "sensory deprivation", "brain tricks", "psychology", "mystery", "shorts"],
        "scenes": [
            {"caption": "Your brain panics in total silence.", "narration": "Your brain panics in total silence... and begins manufacturing sound."},
            {"caption": "Inside an anechoic chamber, hearing amplifies.", "narration": "Inside an anechoic chamber, your hearing sensitivity spikes by four hundred percent."},
            {"caption": "First, you hear your own blood.", "narration": "First, you hear your own blood roaring through your carotid artery."},
            {"caption": "Then, your brain invents phantom sounds.", "narration": "Within five minutes, the starved auditory cortex invents phantom footsteps."},
            {"caption": "Neuroscientists call this spontaneous neural firing.", "narration": "Neuroscientists call it spontaneous neural firing—a desperate search for input."},
            {"caption": "Without acoustic feedback, sensory reality fractures.", "narration": "Without acoustic anchor points, your internal reality fractures."},
            {"caption": "Your mind would rather hear monsters.", "narration": "Your mind would literally rather hear monsters than hear nothing at all."},
            {"caption": "And that is exactly why...", "narration": "And that is exactly why..."},
        ]
    },
    {
        "title": "Why Dim Mirrors Melt Your Face At Night",
        "description": "The Troxler Effect: Why staring into a dark mirror distorts your face. #shorts #psychology #science",
        "tags": ["troxler effect", "optical illusion", "dark psychology", "brain glitch", "shorts"],
        "scenes": [
            {"caption": "Never stare into a dim mirror.", "narration": "Never stare into a dim mirror for more than sixty seconds."},
            {"caption": "Your facial features will begin melting.", "narration": "Within one minute, your facial features will appear to melt into a stranger."},
            {"caption": "This optical terror is Troxler Effect.", "narration": "This terrifying psychological glitch is called the Troxler Effect."},
            {"caption": "Unchanging sensory neurons stop firing signals.", "narration": "When retinal neurons stare at one point, unchanged neurons stop firing."},
            {"caption": "Your brain fills in blank gaps.", "narration": "Your brain frantically fills the blank spots with subconscious fears."},
            {"caption": "You are not hallucinating a demon.", "narration": "You are not hallucinating a demon in the glass."},
            {"caption": "You are watching visual cortex crash.", "narration": "You are watching your visual cortex crash in real-time."},
            {"caption": "Which is why you should never...", "narration": "Which is why you should never..."},
        ]
    },
    {
        "title": "The Hypnic Jerk: Why You Fall Asleep",
        "description": "Why does your body violently jerk awake right as you fall asleep? #shorts #sleepscience #facts",
        "tags": ["hypnic jerk", "sleep paralysis", "brain facts", "science", "shorts"],
        "scenes": [
            {"caption": "That sudden jolt as you sleep?", "narration": "That violent body jolt as you fall asleep is not an accident."},
            {"caption": "Your brain believes you are dying.", "narration": "Your motor cortex briefly believes you are falling to your death."},
            {"caption": "Muscles relax before brain activity slows.", "narration": "As your heart rate drops, your voluntary muscles relax too quickly."},
            {"caption": "A primal survival reflex misfires.", "narration": "Your brain stem misinterprets the sudden drop in muscle tone."},
            {"caption": "It shocks you with adrenaline.", "narration": "In panic, it shocks your nervous system with pure adrenaline."},
            {"caption": "Evolutionary biologists trace this to trees.", "narration": "Biologists trace this to our ancestors sleeping in high canopy trees."},
            {"caption": "One reflex error saved our species.", "narration": "One miscalculated reflex literally kept early humans alive."},
            {"caption": "And that is why you feel...", "narration": "And that is why you feel..."},
        ]
    },
    {
        "title": "The Call of the Void Phenomenon",
        "description": "Why does your brain urge you to jump from high places? #shorts #darkpsychology #science",
        "tags": ["call of the void", "psychology", "brain secrets", "facts", "shorts"],
        "scenes": [
            {"caption": "Ever stood on a high ledge?", "narration": "Ever stood on a high ledge and felt an urge to jump?"},
            {"caption": "The French call it high place.", "narration": "The French call it l'appel du vide—the call of the void."},
            {"caption": "It is not a death wish.", "narration": "Surprisingly, psychologists proved this is not a death wish."},
            {"caption": "It is an ultra-fast survival reflex.", "narration": "It is actually an ultra-fast subconscious survival reflex."},
            {"caption": "Your brain detected danger and recoiled.", "narration": "Your amygdala detected lethal danger and forced you to step back."},
            {"caption": "Your conscious mind misread the hesitation.", "narration": "Your slower conscious mind misread that sudden hesitation as an urge."},
            {"caption": "The thought proved you want survival.", "narration": "The terrifying urge proved your survival instincts are functioning."},
            {"caption": "The next time you stand high...", "narration": "The next time you stand high..."},
        ]
    },
    {
        "title": "Why Deja Vu Feels So Terrifying",
        "description": "What is really happening during an uncanny deja vu episode? #shorts #neuroscience #mystery",
        "tags": ["deja vu", "neuroscience", "mind blown", "dark science", "shorts"],
        "scenes": [
            {"caption": "Deja vu is a neurological misfire.", "narration": "Deja vu is not a glimpse of the past. It is a neurological misfire."},
            {"caption": "Two brain pathways process sensory input.", "narration": "Your sensory information travels along two distinct neural pathways."},
            {"caption": "One pathway suffers a microsecond delay.", "narration": "When one pathway suffers a millisecond delay, data arrives twice."},
            {"caption": "Your temporal lobe catalogs present memory.", "narration": "Your temporal lobe mistakenly flags current reality as an old memory."},
            {"caption": "You feel like you predicted future.", "narration": "You feel like you predicted the future, but your brain is lagging."},
            {"caption": "It is a temporary neural desynchronization.", "narration": "It is a temporary desynchronization between perception and storage."},
            {"caption": "Your mind caught itself lagging behind.", "narration": "Your conscious mind literally caught itself lagging behind reality."},
            {"caption": "And that is why deja vu...", "narration": "And that is why deja vu..."},
        ]
    }
]

def fallback(topic: str) -> dict[str, Any]:
    """Enhanced viral fallback: selects from high-tension structured psychology scripts."""
    seed = int(hashlib.sha256(topic.encode()).hexdigest()[:8], 16)
    template = VIRAL_DARK_TEMPLATES[seed % len(VIRAL_DARK_TEMPLATES)]
    # Ensure title fits and scenes meet strict guard criteria (caption 1-8 words, 8 scenes)
    scenes = [
        {"caption": s["caption"], "narration": s["narration"]}
        for s in template["scenes"]
    ]
    return {
        "title": template["title"][:70],
        "description": template["description"],
        "tags": template["tags"],
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
    return VIRAL_DARK_TEMPLATES[index % len(VIRAL_DARK_TEMPLATES)]["title"]

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
        log.warning("LLM generation failed; using enhanced viral fallback: %s", exc)
        return fallback(topic)
