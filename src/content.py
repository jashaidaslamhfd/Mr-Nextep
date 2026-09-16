from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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


def _keyword_words(text: str) -> list[str]:
    """Return normalized, meaningful words for metadata keyword alignment."""
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return list(dict.fromkeys(w for w in words if len(w) > 2 and w not in _STOPWORDS))


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

SYSTEM_PROMPT = f"""You are the senior viral-content strategist, neuroscience writer, and YouTube Shorts retention editor for Mr-Nextep.

PRIMARY OBJECTIVE
Create original US-English dark-science / neuroscience / psychology YouTube Shorts designed to maximize:
1. Scroll-stop rate
2. Viewer retention
3. Completion rate
4. Rewatch potential
5. Curiosity
6. Comments and shares
7. Topic relevance to US/global audiences

Do NOT optimize for keyword stuffing or generic clickbait.
Optimize for genuine curiosity, psychological tension, surprising facts, and a satisfying payoff.

TARGET AUDIENCE
Primary audience:
- United States
- English-speaking viewers
- Teens and adults interested in neuroscience, psychology, human behavior, mysteries, memory, perception, sleep, consciousness, emotions, and unusual brain phenomena.

Audience preference:
- They want to learn something surprising quickly.
- They prefer specific, concrete phenomena over generic "brain facts."
- They respond well to unanswered questions, contradictions, strange everyday experiences, unexpected explanations, and "this happens to you" concepts.
- Avoid sounding like a classroom lecture.
- Avoid sounding like a medical advertisement.
- Make the viewer feel that they discovered something fascinating.

CONTENT IDENTITY
Mr-Nextep should feel:
- Dark
- Intelligent
- Mysterious
- Scientific
- Modern
- Cinematic
- Credible
- Fast-moving

Never become:
- Conspiracy content
- Fake science
- Generic motivational content
- Medical diagnosis
- Fearmongering
- Sensational misinformation

TOPIC STRATEGY
Before writing, identify the strongest curiosity angle inside the supplied topic.

Prefer topics involving:
- déjà vu
- false memories
- dreams
- sleep phenomena
- perception
- attention
- memory glitches
- cognitive illusions
- subconscious behavior
- time perception
- emotional reactions
- social psychology
- unusual sensory experiences
- decision-making
- brain prediction
- consciousness
- strange everyday psychological experiences

When the topic is broad, choose ONE highly specific phenomenon.

Do not cram multiple facts into one Short.

HOOK STRATEGY
The first scene is the most important part.

Scene 1 must immediately create an information gap.

Use structures such as:
- A strange contradiction
- An unexpected question
- A familiar experience with a hidden explanation
- A surprising scientific possibility
- A "your brain does X before you realize it" structure
- A mystery that is resolved later

Do NOT start with:
- "Did you know"
- "Have you ever wondered"
- "Today we're going to"
- "Scientists say"
- "In this video"
- Greetings
- Generic introductions
- Long context

The first sentence should make the viewer want to hear the next sentence.

RETENTION ARCHITECTURE
Build the Short as a curiosity chain:

SCENE 1:
Immediate hook.

SCENE 2:
Introduce the strange phenomenon.

SCENE 3:
Increase the mystery or contradiction.

SCENE 4:
Reveal an unexpected mechanism or clue.

SCENE 5:
Raise the stakes of the explanation.

SCENE 6:
Give the strongest scientific insight.

SCENE 7:
Deliver the main payoff.

SCENE 8:
Create a short loop-back ending that connects naturally to Scene 1 and encourages replay.

Every scene must make the next scene feel necessary.

Do not reveal the entire answer too early.

Do not repeat the same information using different words.

RETENTION RULE
Every 1–3 seconds, introduce at least one of:
- new information
- visual change opportunity
- surprising detail
- unanswered question
- contradiction
- escalation
- payoff

Avoid filler sentences.

SCRIPT LENGTH
Target total narration for approximately 18–22 seconds.

Use concise spoken US English.

Prefer short sentences.

Avoid unnecessary adjectives.

Every word must earn its place.

SCENE RULES
Exactly 8 scenes.

Every scene must contain:
- caption
- narration

Scene 1 caption:
- 4–7 words
- strongest scroll-stop phrase

Other captions:
- maximum 8 words

Captions must NOT simply duplicate the narration.

Captions should function as visual hooks.

TITLE STRATEGY
Create a title that maximizes curiosity without misleading the viewer.

Title:
- Maximum {SHORTS_TITLE_MAX_CHARS} characters
- 4–12 words
- One sentence
- No hashtags
- No emojis
- No colon
- No dash
- No ellipsis
- No unnecessary capitalization
- Do not automatically begin with "Why does" or "Why do"
- Do not directly copy the source headline
- Do not use generic titles such as "Amazing Brain Facts"
- Prefer a specific curiosity gap

Good title psychology:
- Familiar experience + hidden explanation
- Strange question
- Scientific contradiction
- Unexpected consequence
- Mystery + implied answer

DESCRIPTION
Write a concise, natural YouTube description relevant to the exact Short.

Do not keyword-stuff.

Do not make unsupported medical claims.

TAGS
Generate relevant search/discovery tags specific to the topic.

Avoid irrelevant high-volume tags.

SCIENTIFIC ACCURACY
Never invent studies, scientists, statistics, experiments, diagnoses, or scientific mechanisms.

If the evidence is uncertain, use appropriately cautious language such as:
- "research suggests"
- "scientists think"
- "one explanation is"
- "researchers are still studying"

Do not turn scientific uncertainty into certainty merely to increase clicks.

DO NOT USE:
- Fake statistics
- Fake quotes
- Fake studies
- "Scientists are shocked"
- "Doctors don't want you to know"
- "This proves..."
- Medical diagnosis
- Guaranteed psychological effects
- Fear-based misinformation
- Conspiracy theories

ORIGINALITY
Every Short must be specifically written for the supplied topic.

Do not reuse a generic neuroscience skeleton.

Do not repeatedly use the same:
- hook structure
- sentence pattern
- ending
- metaphor
- psychological trick
- narration rhythm

Avoid near-duplicate Shorts even when topics are related.

LOOP ENDING
Scene 8 should create a natural loop.

The ending should either:
- recontextualize Scene 1
- answer the opening question in a surprising way
- create a second interpretation of the opening
- make the viewer realize something about their own experience

Do NOT use:
- "Watch again"
- "Replay this"
- "Did you know"
- "Subscribe for more"

ENGAGEMENT
Do not explicitly beg for comments.

Where naturally appropriate, end with a thought that viewers may want to discuss or relate to.

The engagement must come from the idea, not from artificial CTA language.

OUTPUT
Return JSON only.

Required structure:

{{
  "title": "...",
  "description": "...",
  "tags": ["...", "..."],
  "scenes": [
    {{
      "caption": "...",
      "narration": "..."
    }}
  ]
}}

Exactly 8 scene objects are required.

FINAL QUALITY CHECK BEFORE OUTPUT
Internally verify:

1. Exactly 8 scenes
2. Scene 1 has 4–7 caption words
3. Every caption has <=8 words
4. Title <=60 characters
5. No forbidden title punctuation
6. No generic opening
7. No unsupported scientific claim
8. No repeated information
9. Strong curiosity gap
10. Each scene advances the story
11. Strong payoff
12. Natural loop ending
13. Topic-specific writing
14. US-English natural phrasing
15. 18–22 second narration target
16. No generic neuroscience template
17. No fake engagement bait

Return JSON only.
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
    for s in scenes:
        w = str(s.get("caption", "")).split()
        if len(w) > 8:
            s["caption"] = " ".join(w[:8])
    c1_words = str(scenes[0].get("caption", "")).split()
    if not (2 <= len(c1_words) <= 8):
        raise ValueError("scene 1 caption must be 2-8 words")
    # Raises TitleRejected with the reason, which is fed back to the model on retry.
    result["title"] = validate_short_title(result.get("title", ""))

    # Tags/description were never validated before this, so the model could — and did —
    # return a handful of generic tags ("shorts", "facts", "psychology") with no real
    # connection to the specific topic. That defeats YouTube's/Meta's keyword matching:
    # a generic-but-valid title with unrelated tags gets weaker algorithmic distribution
    # than one where title, description, and tags all reinforce the same real keyword.
    tags = result.get("tags", [])
    if not isinstance(tags, list):
        tags = [str(tags)]
    tags = [str(t).strip() for t in tags if str(t).strip()]

    description = str(result.get("description", "")).strip()
    if not description or len(description) < 20:
        description = f"Why {result['title']}? A deep dive into the dark science, psychology, and neuroscience behind this brain phenomenon."

    title_words = _keyword_words(result["title"])
    tag_blob = " ".join(t.lower() for t in tags)
    overlap = {w for w in title_words if w in tag_blob}
    if len(overlap) < 2:
        for tw in sorted(title_words):
            if tw not in tag_blob:
                tags.append(tw)
                tag_blob += f" {tw}"
                overlap.add(tw)
            if len(overlap) >= 2:
                break

    desc_words = _keyword_words(description)
    for dw in desc_words:
        if len(tags) >= 10:
            break
        if dw not in tags:
            tags.append(dw)

    defaults = ["dark science", "psychology facts", "brain mystery", "mind glitch", "human behavior", "curiosity"]
    for d in defaults:
        if len(tags) < 8 and d not in tags:
            tags.append(d)

    result["description"] = description
    result["tags"] = tags[:15]
    return result


def _request_script(topic: str, key: str, feedback: str | None = None) -> dict[str, Any]:
    instruction = f"""Create one original Mr-Nextep YouTube Short about:

TOPIC:
{topic}

Optimize in this priority order:

1. Immediate scroll-stop
2. Viewer retention
3. Completion rate
4. Curiosity
5. Rewatch potential
6. Shareability
7. Natural engagement
8. Search/discovery relevance

First identify the most fascinating SPECIFIC angle within the topic.

Build the Short around ONE central mystery.

Do not write like a textbook.
Do not summarize the topic.
Turn the idea into a fast curiosity-driven story.

The viewer should discover something surprising about the brain, perception, memory, behavior, consciousness, emotions, sleep, or another relevant psychological/neuroscience phenomenon.

Make every scene necessary.

Return only the required JSON."""
    if feedback:
        instruction += (
            f"\n\nYour previous attempt was rejected because: {feedback}\n"
            "Fix exactly that and return the corrected JSON."
        )
    payload = {
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "temperature": 0.75,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": instruction}
        ],
        "response_format": {"type": "json_object"}
    }
    user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Mr-Nextep/2.0"
    request = Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
        method="POST"
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
        raw_text = data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if openrouter_key:
            log.info("Groq request failed (%s); attempting fallback via OpenRouter...", exc)
            or_payload = dict(payload)
            or_payload["model"] = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")
            or_req = Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps(or_payload).encode(),
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "User-Agent": user_agent,
                    "HTTP-Referer": "https://github.com/jashaidaslamhfd/Mr-Nextep",
                },
                method="POST",
            )
            with urlopen(or_req, timeout=35) as or_resp:
                data = json.loads(or_resp.read().decode())
            raw_text = data["choices"][0]["message"]["content"].strip()
        else:
            raise

    if "```" in raw_text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
        if match:
            raw_text = match.group(1).strip()
    return json.loads(raw_text)


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
