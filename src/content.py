from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any
from urllib.request import Request, urlopen

from .config import Settings
from .utils import SHORTS_TITLE_MAX_CHARS, TitleRejected, validate_short_title

log = logging.getLogger(__name__)

# How many times to ask the model for a publishable script before giving up. Each retry
# carries the rejection reason back to the model so it can correct rather than re-roll.
GENERATION_ATTEMPTS = int(os.getenv("CONTENT_GENERATION_ATTEMPTS", "3"))

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "for", "to", "with",
    "from", "by", "as", "is", "are", "was", "were", "be", "been", "do", "does", "did",
    "why", "how", "what", "when", "where", "who", "which", "your", "you", "we", "our",
    "this", "that", "these", "those", "so", "it", "its", "can", "could", "would",
    "should", "will", "feel", "feels", "seem", "seems", "really", "very", "some",
})


class ContentGenerationError(RuntimeError):
    """No publishable script could be generated.

    Raised instead of falling back to the built-in template. The template emits the same
    seven scenes for every topic, so publishing it is how the channel accumulated
    duplicate uploads — failing the run is the cheaper outcome.
    """


TOPICS = [
    "Why do déjà vu moments feel so real?",
    "Why does a smell unlock an old memory?",
    "Why does your body jolt as you fall asleep?",
    "Why do nightmares wake you up?",
    "Why can silence feel physically loud?",
    "Why do dim mirrors melt your face?",
    "Why do you see shadows in the dark?"
]


def salient_words(topic: str) -> list[str]:
    """Content words from a topic, longest first — used to vary template text by topic."""
    words = [
        w.strip(".,;:!?\"'()[]").lower()
        for w in str(topic or "").replace("-", " ").split()
    ]
    keep = [w for w in words if len(w) > 3 and w not in _STOPWORDS and w.isalpha()]
    return sorted(dict.fromkeys(keep), key=len, reverse=True)


def _fallback_title(topic: str, max_chars: int = SHORTS_TITLE_MAX_CHARS) -> str:
    """A validated title derived from the topic, without ever truncating it."""
    candidate = " ".join(str(topic or "").split()).rstrip(".!")
    for attempt in (candidate, f"{candidate}?" if not candidate.endswith("?") else candidate):
        try:
            return validate_short_title(attempt, max_chars=max_chars)
        except TitleRejected:
            continue
    words = salient_words(topic)
    for count in (3, 2, 1):
        if len(words) >= count:
            focus = " ".join(words[:count])
            for shape in (
                f"The dark truth about {focus}",
                f"What {focus} hides from you",
                f"The hidden science of {focus}",
            ):
                try:
                    return validate_short_title(shape, max_chars=max_chars)
                except TitleRejected:
                    continue
    raise TitleRejected(f"could not derive a valid title from topic {topic!r}")


def fallback(topic: str) -> dict[str, Any]:
    """Topic-derived template script. NOT publishable — dry runs and tests only.

    Every line that can vary is derived from the topic and rotated by a topic-seeded
    index, so two different topics no longer produce the identical body that the old
    hardcoded template did. It still must not reach an upload: generate_script raises
    rather than returning this when the run is going to publish.
    """
    seed = int(hashlib.sha256(str(topic).encode()).hexdigest()[:8], 16)
    focus = str(topic).rstrip("?.!").strip()
    words = salient_words(topic)
    subject = words[0] if words else "this reflex"
    detail = words[1] if len(words) > 1 else "your nervous system"

    hooks = [
        f"Your brain hides this {subject} secret.",
        f"This {subject} glitch is terrifyingly real.",
        f"Nobody explains this {subject} reflex.",
        f"Never ignore this {subject} signal.",
        f"Science finally explains {subject} here.",
    ]
    second = [
        f"Your neurons fire before {detail} reacts.",
        f"{detail.capitalize()} lags behind your awareness.",
        f"Signals reach {detail} milliseconds early.",
    ]
    third = [
        f"An ancient pathway hijacks {detail}.",
        f"A survival circuit overrides {detail}.",
        f"Your oldest wiring seizes {detail}.",
    ]
    fourth = [
        f"Researchers call this {subject} drift.",
        f"Neuroscientists named this {subject} desync.",
        f"Labs call it {subject} misfiring.",
    ]
    fifth = [
        "Your brain manufactures a false memory.",
        "Your mind invents an instant explanation.",
        "Your brain patches the gap silently.",
    ]
    sixth = [
        f"The {subject} feeling is purely biological.",
        f"Nothing about {subject} is imagined.",
        f"{subject.capitalize()} is machinery, not magic.",
    ]
    seventh = [
        "You just caught your mind glitching.",
        "You watched your subconscious stall.",
        "You felt a processing loop close.",
    ]

    def pick(options: list[str], offset: int) -> str:
        return options[(seed + offset) % len(options)]

    scenes = [
        {"caption": pick(hooks, 0), "narration": f"{focus}... and your brain is hiding the real cause."},
        {"caption": pick(second, 1), "narration": f"Your sensory neurons fire milliseconds before {detail} can react."},
        {"caption": pick(third, 2), "narration": f"When {focus.lower()} happens, an ancient survival pathway takes over."},
        {"caption": pick(fourth, 3), "narration": f"Researchers describe it as a split-second desynchronization in {detail}."},
        {"caption": pick(fifth, 4), "narration": "To prevent overload, your brain manufactures an instant logical explanation."},
        {"caption": pick(sixth, 5), "narration": f"The sensation is not imagination. {detail.capitalize()} is simply lagging behind."},
        {"caption": pick(seventh, 6), "narration": "You literally caught your subconscious mind inside a processing loop."},
        {"caption": "Which is why you felt that.", "narration": f"Which is why {subject} hit you the exact moment it started."},
    ]

    return {
        "title": _fallback_title(topic),
        "description": f"The dark neuroscience behind {focus.lower()} explained in 20 seconds. #shorts #science #psychology #mystery",
        "tags": ["dark science", "psychology facts", "brain glitch", "mystery", "shorts"],
        "scenes": scenes,
    }

def choose_topic(settings: Settings) -> str:
    if settings.topic:
        return settings.topic
    queue_path = settings.data_dir / "search_demand_queue_us.json"
    queue_index_path = settings.data_dir / "trend_topic_index.json"
    if queue_path.exists():
        try:
            queue = json.loads(queue_path.read_text(encoding="utf-8")).get("topics", [])
            if queue:
                index = 0
                if queue_index_path.exists():
                    try:
                        index = int(json.loads(queue_index_path.read_text(encoding="utf-8")))
                    except (ValueError, TypeError, json.JSONDecodeError):
                        index = 0
                queue_index_path.write_text(json.dumps(index + 1), encoding="utf-8")
                item = queue[index % len(queue)]
                # Prefer the raw headline. `question_phrase` is the trend scraper's old
                # mechanical "Why does <headline>?" splice, which is what produced titles
                # like "Why does apple acquires brain imaging firm". Queue files written
                # before that fix still carry it, so it is only a last resort.
                return str(item.get("topic") or item.get("question_phrase") or "")
        except Exception as exc:
            log.warning("Could not parse trend topic queue: %s", exc)
    path = settings.data_dir / "topic_index.json"
    index = 0
    if path.exists():
        try:
            index = int(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError, json.JSONDecodeError):
            index = 0
    path.write_text(json.dumps(index + 1), encoding="utf-8")
    return TOPICS[index % len(TOPICS)]

SYSTEM_PROMPT = f"""You write US-English dark-science YouTube Shorts for Mr-Nextep.
Return JSON only with title, description, tags, and exactly 8 scenes.

Title rules (the title is the channel's only click surface — treat it as the hardest part):
- Write the title yourself in the channel's dark-science voice. The input is raw source
  material, often a news headline. NEVER reuse the headline as the title, and NEVER
  prepend "Why does" or "Why do" to it — that produces ungrammatical titles.
- Maximum {SHORTS_TITLE_MAX_CHARS} characters, including spaces. A short title is always better than a
  long one. It will be rejected, not trimmed, if it runs over — so count the characters.
- One sentence, 4 to 12 words. End with "?" if it asks a question.
- Open a curiosity gap: name the strange effect, withhold the cause.
- No hashtags, no emojis, no colons, no dashes, no source or brand names, no ellipsis.

Script rules:
- Target 18-22 seconds total duration.
- Scene 1 caption MUST be 4-7 words and create an immediate psychological curiosity gap.
- Every scene caption MUST be brief (1 to 8 words maximum).
- Each scene must contain "caption" and "narration" strings.
- Scene 8 narration must provide a curiosity loop-back ending that connects into Scene 1.
- Never use clickbait medical promises, emojis, or greetings like "Did you know".
- The eight scenes must be written for THIS topic specifically. Do not reuse a generic
  skeleton about neurons and survival pathways that would fit any topic.
"""


def _validate_script(result: Any) -> dict[str, Any]:
    """Raise ValueError/TitleRejected unless this is a publishable script."""
    if not isinstance(result, dict):
        raise ValueError(f"expected a JSON object, got {type(result).__name__}")
    scenes = result.get("scenes", [])
    if len(scenes) != 8:
        raise ValueError(f"expected exactly 8 scenes, got {len(scenes)}")
    if any(not isinstance(s, dict) or not s.get("caption") or not s.get("narration") for s in scenes):
        raise ValueError("every scene needs a non-empty caption and narration")
    if not 4 <= len(str(scenes[0]["caption"]).split()) <= 7:
        raise ValueError("scene 1 caption must be 4-7 words")
    if any(len(str(s.get("caption", "")).split()) > 8 for s in scenes):
        raise ValueError("scene captions must be 8 words or fewer")
    # Raises TitleRejected with the reason, which is fed back to the model on retry.
    result["title"] = validate_short_title(result.get("title", ""))
    return result


def _request_script(topic: str, key: str, feedback: str | None = None) -> dict[str, Any]:
    instruction = f"Create one original Short about: {topic}"
    if feedback:
        instruction += (
            f"\n\nYour previous attempt was rejected because: {feedback}\n"
            "Fix exactly that and return the corrected JSON."
        )
    payload = {
        "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "temperature": 0.75,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": instruction}
        ],
        "response_format": {"type": "json_object"}
    }
    request = Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST"
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode())
    return json.loads(data["choices"][0]["message"]["content"])


def generate_script(topic: str, settings: Settings) -> dict[str, Any]:
    """Generate a publishable script, or raise ContentGenerationError.

    There is deliberately no fallback-to-template path for a publishing run. The template
    produced near-identical scripts for every topic, which is how duplicate uploads got
    published under different headlines; a failed run is recoverable, a duplicate upload
    on the channel is not. The template is returned only for a dry run, which never
    reaches an upload.
    """
    key = os.getenv("GROQ_API_KEY")
    dry_run = bool(getattr(settings, "dry_run", False))

    if not key:
        if dry_run:
            log.warning("GROQ_API_KEY is not set; dry run continues on the topic-derived template.")
            return fallback(topic)
        raise ContentGenerationError(
            "GROQ_API_KEY is not set, so no original script can be written. Refusing to "
            "publish the built-in template because it is near-identical for every topic."
        )

    last_error: Exception | None = None
    feedback: str | None = None
    for attempt in range(1, GENERATION_ATTEMPTS + 1):
        try:
            return _validate_script(_request_script(topic, key, feedback))
        except Exception as exc:
            last_error = exc
            feedback = str(exc)
            log.warning(
                "Script generation attempt %d/%d rejected: %s", attempt, GENERATION_ATTEMPTS, exc
            )

    if dry_run:
        log.warning("All %d generation attempts failed; dry run continues on the template.", GENERATION_ATTEMPTS)
        return fallback(topic)
    raise ContentGenerationError(
        f"No publishable script after {GENERATION_ATTEMPTS} attempts. Last rejection: {last_error}"
    ) from last_error
