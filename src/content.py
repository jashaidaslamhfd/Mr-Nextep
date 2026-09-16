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

Create original US-English dark-science, neuroscience, and psychology YouTube Shorts optimized for:

1. Immediate scroll-stop
2. Viewer retention
3. Completion rate
4. Curiosity
5. Rewatch potential
6. Shareability
7. Natural comment potential
8. Topic relevance for US and global English-speaking audiences

Never sacrifice scientific credibility merely to increase clicks.

TARGET AUDIENCE

Primarily US viewers, while remaining understandable and interesting to global English-speaking viewers.

The audience is interested in:
- neuroscience
- psychology
- memory
- dreams
- perception
- consciousness
- human behavior
- strange mental experiences
- cognitive illusions
- subconscious processes
- sleep
- emotions
- unusual everyday brain phenomena

CONTENT STYLE

Mr-Nextep should feel:

- Dark
- Mysterious
- Intelligent
- Scientific
- Cinematic
- Modern
- Fast
- Credible
- Intriguing

The writing should feel like a fascinating discovery, not a classroom lesson.

Do NOT sound like:
- a textbook
- a news report
- a motivational speaker
- a medical advertisement
- generic AI content

TOPIC ANGLE

Before writing the Short, identify the single strongest curiosity angle within the supplied topic.

If the topic is broad, narrow it to ONE specific phenomenon or idea.

Prefer:
- strange everyday experiences
- surprising contradictions
- hidden brain mechanisms
- unexpected psychological effects
- questions people have experienced themselves
- scientific mysteries
- counterintuitive explanations

Do not combine multiple unrelated facts into one Short.

HOOK

Scene 1 must immediately create an information gap.

The viewer should instantly think:

"Wait, why does that happen?"

or:

"I've experienced that."

or:

"How is that possible?"

The hook must introduce the mystery BEFORE explaining it.

Never start with:
- Did you know
- Have you ever wondered
- Today we're going to
- In this video
- Scientists discovered
- Welcome
- Here's something interesting
- generic background information

Do not waste the first sentence establishing context.

RETENTION ARCHITECTURE

Build the Short as a curiosity chain.

Scene 1:
Create the strongest possible hook.

Scene 2:
Introduce the strange phenomenon.

Scene 3:
Deepen the mystery.

Scene 4:
Reveal an unexpected clue or mechanism.

Scene 5:
Create another curiosity escalation.

Scene 6:
Introduce the key scientific insight.

Scene 7:
Deliver the strongest payoff.

Scene 8:
Create a natural loop-back that connects with Scene 1.

Each scene must add NEW information.

Do not repeat an idea using different words.

Do not reveal the complete explanation too early.

Every scene should make the viewer want the next scene.

PACING

Target approximately 18–22 seconds total narration.

Use concise spoken US English.

Prefer short, punchy sentences.

Remove filler words.

Avoid unnecessarily complex scientific terminology.

When technical terminology is necessary, explain it naturally in simple language.

CAPTIONS

Exactly 8 scenes.

Every scene must contain:

- caption
- narration

Scene 1 caption:
- 4–7 words
- strongest scroll-stop phrase

All other captions:
- maximum 8 words

Captions must complement the narration rather than simply copy it.

Captions should be understandable instantly on a mobile screen.

TITLE

Maximum {SHORTS_TITLE_MAX_CHARS} characters.

Title must:
- contain 4–12 words
- be one sentence
- create a genuine curiosity gap
- be specific to the topic
- sound natural to a US audience

Never use:
- hashtags
- emojis
- colon
- dash
- ellipsis
- excessive capitalization
- generic titles
- fake urgency
- misleading claims

Do not automatically start with:
- Why does
- Why do

Do not directly copy the source headline.

A strong title should make the viewer want to discover the explanation without revealing the entire payoff.

SCIENTIFIC CREDIBILITY

Never invent:
- studies
- scientists
- statistics
- experiments
- medical facts
- scientific mechanisms
- quotations

Never present speculation as established fact.

When evidence is uncertain, use appropriate wording such as:
- research suggests
- scientists think
- one explanation is
- researchers are still studying

Never use scientific misinformation simply because it sounds more viral.

Do not diagnose viewers or make claims about their mental or physical health.

ENGAGEMENT

Create discussion naturally through the idea.

Do not beg for:
- comments
- likes
- shares
- subscriptions

Do not use artificial CTA phrases such as:
- Comment below
- Follow for more
- Like and subscribe
- What do you think

If a topic naturally creates disagreement, recognition, or personal experience, allow the final thought to create that engagement organically.

LOOP ENDING

Scene 8 must connect back to Scene 1.

Use one of these mechanisms:

- Recontextualize the opening
- Answer the opening question in an unexpected way
- Reveal that the opening experience had a different meaning
- End on a thought that makes the viewer reinterpret Scene 1

The ending should feel satisfying while naturally allowing the Short to restart.

Never explicitly tell viewers to replay the video.

ORIGINALITY

Every Short must be specifically written for the supplied topic.

Do not reuse:
- generic neuroscience templates
- identical hooks
- identical endings
- repeated metaphors
- repeated sentence structures
- repeated psychological explanations

Avoid near-duplicate Shorts across the channel.

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

FINAL INTERNAL QUALITY CHECK

Before returning JSON, silently verify:

- Exactly 8 scenes
- Scene 1 caption is 4–7 words
- Every caption is <=8 words
- Title is <= {SHORTS_TITLE_MAX_CHARS} characters
- Title contains 4–12 words
- No forbidden title punctuation
- No generic opening
- Strong curiosity gap
- One specific topic angle
- Every scene advances the story
- No unnecessary repetition
- Strong payoff
- Natural loop ending
- Scientific claims are responsible
- No invented facts
- US-English sounds natural
- Narration targets 18–22 seconds
- Content does not feel like a generic AI template

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
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
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
