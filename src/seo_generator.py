"""
src/seo_generator.py

PRD "AI SEO Generator" feature, adapted to SKILLOR's dark-facts Shorts niche.
Pure post-processing on top of an already-generated script_data dict — no
extra LLM calls, so it's free and instant to run for every video.

Produces:
  - title_options: 5 SEO-friendly title variants (different hook angles)
  - description: CTR-optimized YouTube description (reuses the same shape
    uploader.py already builds, factored out here so it's the single
    source of truth)
  - hashtags: deduplicated, ranked hashtag list
  - pinned_comment: a comment worth auto-pinning post-upload to seed
    engagement (main.py/uploader.py can pin it via commentThreads.insert)
  - playlist_suggestion: which existing playlist this video best fits
  - seo_score: 0-100 with a breakdown, so low-scoring videos can be
    flagged the same way quality_checker flags weak scripts

Nothing here calls the network or an LLM - it's deterministic string/rule
based scoring, matching the pattern already used in quality_checker.py and
anti_spam.py.
"""

import re
import logging
import random
from typing import Dict, List

from niche_strategy import generate_seo_tags, get_topic_category, make_seo_title

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TITLE_MAX_LEN = 60
TITLE_MAX_WORDS = 8  # Concise mobile-first titles with full search intent terms
DESCRIPTION_MAX_LEN = 5000  # YouTube hard limit
PINNED_COMMENT_MAX_LEN = 200

# Existing playlists this channel maintains (edit to match your real
# playlist names/IDs - used only for suggestion text, not an API call).
PLAYLISTS_BY_CATEGORY = {
    "Brain": "Dark Brain Facts",
    "Body": "Dark Body Facts",
    "Mystery": "Body Mysteries",
    "Health": "Health & Science Shorts",
}

# Short title frames. ``generate_title_options`` only uses a frame when it
# remains grammatical after enforcing the channel's five-word maximum.
_TITLE_TEMPLATES = (
    "Why {topic} Matters",
    "How {topic} Works",
    "{topic} Explained Simply",
    "The Science Of {topic}",
)

# Closing lines for the description's context sentence. Rotated by topic hash
# so the channel does not ship one identical sentence on every upload.
_CONTEXT_CLOSERS = (
    "Follow for clear science explained simply.",
    "Subscribe for more of what your body does and why.",
    "Follow for one strange body fact a day.",
    "More everyday science, explained in seconds.",
    "Follow if your body keeps surprising you.",
    "Subscribe for short, honest science.",
)

_TITLE_STOP_WORDS = {
    "a", "an", "and", "are", "at", "does", "do", "for", "from", "helps",
    "how", "in", "is", "it", "make", "of", "on", "the", "this", "to", "what",
    "when", "why", "with", "your", "you",
    # Bare verbs, gerunds and loose adjectives carry no search intent on their
    # own. They were reaching live descriptions as trailing junk — published
    # examples: "...neuroscience, having." and "...body science, sudden,
    # charley." A viewer reads that as broken English and YouTube gets a
    # keyword nobody searches.
    "having", "being", "getting", "doing", "going", "making", "taking",
    "feeling", "happens", "happening", "sudden", "suddenly", "really",
    "very", "just", "some", "more", "most", "other", "such", "into",
    "about", "after", "before", "while", "during", "because", "that",
    "these", "those", "there", "here", "then", "than", "also", "even",
    "charley", "stuck", "own", "new", "old", "big", "small", "good", "bad",
}


# HIGH-VOLUME TAGS BY CATEGORY
_HIGH_VOLUME_TAGS = {
    "Brain": ["neuroscience", "brainfacts", "mindblowing", "psychology", "brainpower", "cognitivescience"],
    "Body": ["humanbody", "anatomy", "healthfacts", "biology", "physiology", "bodysecrets"],
    "Mystery": ["mystery", "unsolved", "creepyfacts", "paranormal", "weirdfacts", "conspiracy"],
    "Health": ["healthtips", "wellness", "medicalfacts", "science", "healthyliving", "nutrition"],
}

# TRENDING TAGS (YouTube Shorts specific)
_TRENDING_TAGS = ["shorts", "viralfacts", "didyouknow", "interestingfacts", "education", "sciencefacts"]


def _title_words(value: str) -> List[str]:
    """Return readable title tokens without punctuation-only fragments."""
    return re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", value or "")


_EN_DANGLING_ENDINGS = {
    "your", "yours", "the", "a", "an", "to", "of", "with", "when", "while",
    "seems", "seem", "makes", "gets", "does", "is", "are", "was", "were",
    "will", "can", "just", "really", "actually", "ever", "every", "you",
    "we", "they", "it", "this", "that", "these", "those", "my", "our",
    "their", "his", "her", "feel", "feels", "says", "telling", "why",
    "how", "what", "and", "or", "if", "so", "too", "very", "into", "on",
}


def _five_word_title(value: str, *, fallback: str = "Science Made Simple Today") -> str:
    """Create a clean title of no more than five words and 60 characters.

    Truncating by word—not character—prevents ugly cut-off mobile titles. A
    script title is preferred because it carries the video's actual angle.
    """
    words = _title_words(value)[:TITLE_MAX_WORDS]
    if not words:
        words = _title_words(fallback)[:TITLE_MAX_WORDS]
    out = " ".join(words)
    if len(out) > TITLE_MAX_LEN:
        out = out[:TITLE_MAX_LEN].rsplit(" ", 1)[0]
    # Never end on a dangling connector/verb — a title clipped mid-thought
    # ("Why Your Body Freezes When") reads broken in the feed.
    parts = out.split()
    while len(parts) > 1 and parts[-1].lower().rstrip("?!.") in _EN_DANGLING_ENDINGS:
        parts.pop()
    return (" ".join(parts) or fallback).strip()


def _topic_keywords(topic: str, limit: int = 2) -> str:
    """Extract a grammatical short subject for title frames.

    Common science pairs get a natural phrase instead of raw keyword soup such
    as “Sleep Brain”.
    """
    words = [w.lower() for w in _title_words(topic) if w.lower() not in _TITLE_STOP_WORDS and len(w) > 2]
    word_set = set(words)
    if "sleep" in word_set and ({"memory", "memories"} & word_set):
        return "Sleep And Memory"
    if "brain" in word_set and "sleep" in word_set:
        return "Sleep And Your Brain"
    if "brain" in word_set:
        return "Your Brain"
    if "body" in word_set:
        return "Your Body"
    return " ".join(words[:limit]).title() or "Science Facts"


def generate_title_options(topic: str, script_data: Dict, n: int = 5) -> List[str]:
    """Return topic-relevant, mobile-readable titles of at most five words."""
    base_title = script_data.get("title") or topic
    keyword_phrase = _topic_keywords(topic)
    templates = _TITLE_TEMPLATES
    if " And " in keyword_phrase:
        # Compound subjects take “work”, not “works”.
        templates = tuple(
            "How {topic} Work" if template == "How {topic} Works" else template
            for template in _TITLE_TEMPLATES
        )
    candidates = [
        base_title,
        topic,
        *[template.format(topic=keyword_phrase) for template in templates],
    ]
    options: List[str] = []
    seen = set()
    for candidate in candidates:
        title = _five_word_title(candidate)
        key = title.lower()
        if title and key not in seen:
            seen.add(key)
            options.append(title)
        if len(options) >= n:
            break
    return options


def _topic_tag_phrases(topic: str, category: str) -> List[str]:
    """Build useful searchable tag phrases and discard grammar/filler words."""
    words = [w.lower() for w in _title_words(topic) if w.lower() not in _TITLE_STOP_WORDS and len(w) > 2]
    # Topic-specific useful combinations are stronger than generic verbs or
    # mechanically joined word pairs such as “sleep brain”.
    word_set = set(words)
    phrases: List[str] = []
    if {"sleep", "memory"} <= word_set or {"sleep", "memories"} <= word_set:
        phrases.extend(["sleep science", "sleep and memory", "memory formation"])
    if "brain" in word_set:
        phrases.extend(["brain facts", "brain science", "neuroscience"])
    if category == "Body":
        phrases.extend(["human body", "body science"])
    phrases.extend(words)
    return phrases


def generate_hashtags(topic: str, category: str, n: int = 3) -> List[str]:
    """Return up to three searchable, topic-specific hashtags."""
    candidates = _topic_tag_phrases(topic, category)
    candidates.extend(_HIGH_VOLUME_TAGS.get(category, ["science facts"]))
    # Prefer descriptive two-word phrases over broad one-word labels.
    specific = [tag for tag in candidates if " " in str(tag).strip()]
    clean = _normalise_tags(specific or candidates, limit=n)
    return [f"#{tag.replace(' ', '')}" for tag in clean]



def _normalise_tags(tags: List[str], limit: int = 3) -> List[str]:
    """Return unique clean hashtag words regardless of whether callers pass
    `science`, `#science`, or a mixture of both."""
    clean, seen = [], set()
    for raw in tags or []:
        tag = re.sub(r"[^A-Za-z0-9_ ]", "", str(raw).lstrip("#"))
        tag = re.sub(r"\s+", " ", tag).strip()
        # Skip grammar/filler tokens. generate_upload_tags() already filters
        # these for the YouTube tag field, but this helper feeds the
        # DESCRIPTION, which had no filter — so live descriptions read
        # "Learn the science behind brain facts, brain science, neuroscience,
        # having." and "... human body, body science, sudden, charley."
        # A trailing bare verb like "having" reads as broken English to the
        # viewer and adds no search value.
        if not tag or tag.lower() in _TITLE_STOP_WORDS:
            continue
        if len(tag) < 3:
            continue
        if tag.lower() not in seen:
            seen.add(tag.lower())
            clean.append(tag)
        if len(clean) >= limit:
            break
    return clean


def generate_upload_tags(topic: str, category: str, limit: int = 20) -> List[str]:
    """Return meaningful YouTube tag phrases, never grammar/filler tokens."""
    candidates = _topic_tag_phrases(topic, category)
    candidates.extend(_HIGH_VOLUME_TAGS.get(category, []))
    candidates.extend(generate_seo_tags(topic, category))
    clean: List[str] = []
    seen = set()
    for raw in candidates:
        tag = re.sub(r"\s+", " ", str(raw).strip().lstrip("#"))
        # A one-word tag that is only a grammar verb has no search value.
        if not tag or tag.lower() in _TITLE_STOP_WORDS:
            continue
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            clean.append(tag)
        if len(clean) >= limit:
            break
    return clean


def generate_description(script_data: Dict, tags: List[str]) -> str:
    """Build one concise description exactly once.

    `main.py` stores the LLM's original summary as `summary`. We never feed a
    previously formatted YouTube description back into this function; that
    was the cause of duplicated paragraphs, dividers, CTAs and hashtags.
    """
    hook = re.sub(r"\s+", " ", script_data.get("hook", "")).strip()
    summary = re.sub(r"\s+", " ", script_data.get("summary", "")).strip()
    if not summary:
        candidate = script_data.get("description", "")
        # Old runs may contain an already-formatted description. Do not nest it.
        if "━━━━━━━━" not in candidate and "#" not in candidate and len(candidate) <= 500:
            summary = re.sub(r"\s+", " ", candidate).strip()
    if not summary:
        summary = "A clear, concise explanation of how this process works in your body."

    # Avoid repeating the same sentence as both hook and summary.
    parts = []
    if hook:
        parts.append(hook[:140].rstrip(" .") + ".")
    if summary and summary.lower() not in hook.lower():
        parts.append(summary[:320].rstrip())

    # Keyword-rich context line. 2026 YouTube guidance rewards a longer,
    # keyword-natural description (search snippet + categorisation) over a
    # bare hook+hashtags block. Built from the video's own tags so it stays
    # relevant and never keyword-stuffed.
    context_tags = _normalise_tags(tags, 4)
    if context_tags:
        readable = ", ".join(t.replace("_", " ") for t in context_tags)
        # Vary the closing line. The identical sentence "Follow for clear
        # science and brain facts explained simply." was on all 83 published
        # videos — byte-for-byte. Identical boilerplate across an entire
        # channel is a templated-content signal, and it also wastes the one
        # line a viewer might actually read. Seeded by topic so a given video
        # always renders the same text (idempotent for the repair sweep).
        import hashlib as _hashlib
        seed = int(_hashlib.sha256(readable.encode("utf-8")).hexdigest()[:8], 16)
        closing = _CONTEXT_CLOSERS[seed % len(_CONTEXT_CLOSERS)]
        parts.append(f"Learn the science behind {readable}. {closing}")

    # #Shorts FIRST so YouTube categorises this correctly as a Short, then
    # up to 3 topic hashtags (YouTube only surfaces the first 3 above the
    # title, and ignores everything past 15). #Shorts is deduped against the
    # topic tags so it never appears twice.
    # A hashtag cannot contain a space. Multi-word tags such as "brain facts"
    # were emitted verbatim as "#brain facts", which YouTube parses as the
    # hashtag "#brain" followed by the loose word "facts" — so the intended
    # tag never existed and the description ended in dangling words. Live
    # examples on the channel: "#brain facts #brain science #neuroscience"
    # and "#human body #body science #sudden".
    # Words are joined into a single CamelCase-free token instead.
    def _as_hashtag(tag: str) -> str:
        # Capitalise only the first letter of each word. .title() lowercases
        # the rest, so an already-correct "BrainFacts" would degrade to
        # "Brainfacts" on every pass.
        parts = [p for p in tag.replace("_", " ").split() if p]
        joined = "".join(p[0].upper() + p[1:] for p in parts)
        return "".join(ch for ch in joined if ch.isalnum())

    ht_words = ["Shorts"] + [t for t in _normalise_tags(tags, 3) if t.lower() != "shorts"]
    seen, clean_tags = set(), []
    for tag in ht_words:
        token = _as_hashtag(tag)
        if len(token) > 2 and token.lower() not in seen:
            seen.add(token.lower())
            clean_tags.append(token)
    hashtags = " ".join(f"#{tag}" for tag in clean_tags[:4])
    if hashtags:
        parts.append(hashtags)
    return "\n\n".join(parts)[:DESCRIPTION_MAX_LEN]


def generate_thumbnail_text(script_data: Dict, title: str) -> str:
    """Use the script's short thumbnail angle, with a safe 2–4 word fallback."""
    raw = script_data.get("thumbnail_text") or title
    words = _title_words(raw)[:4]
    if len(words) < 2:
        words = _title_words(title)[:4]
    return " ".join(words).upper()


def generate_pinned_comment(script_data: Dict) -> str:
    """A short comment worth pinning right after upload to seed the first
    reply/engagement signal. Keep it a genuine question or prompt - not an
    engagement-bait command like 'like if you agree', which YouTube's spam
    systems increasingly downrank."""
    topic = script_data.get('topic', script_data.get('title', 'this'))
    
    # Multiple comment templates for variety
    comment_templates = [
        f"Did you know this about {topic.lower()}? Curious what surprised you most 👇",
        f"What's your reaction to this {topic.lower()} fact? Let me know 👇",
        f"Which part of this {topic.lower()} explanation blew your mind the most? 🤯",
        f"Did you already know this about {topic.lower()}? Or was it a shock? 👇",
        "What should I explain next? Drop your suggestions below! 🔬",
    ]
    
    comment = random.choice(comment_templates)
    return comment[:PINNED_COMMENT_MAX_LEN]


def suggest_playlist(category: str) -> str:
    return PLAYLISTS_BY_CATEGORY.get(category, "Dark Body Facts")


def _score_title(title: str) -> int:
    """0-100. Rewards length in the sweet spot, a power word, and presence
    of a number - all correlate with higher Shorts CTR without tipping into
    all-caps/clickbait territory that risks a policy strike."""
    if not title:
        return 0
    
    score = 30  # Base score
    
    # Length sweet spot (30-60 chars is YouTube's favorite)
    length = len(title)
    if 30 <= length <= 55:
        score += 30
    elif 20 <= length < 30:
        score += 20
    elif length < 20:
        score += 10
    else:
        score += 5
    
    # Reward useful specificity, not manipulative clickbait.
    useful_words = ["why", "how", "what", "science", "body", "brain", "sleep", "daily", "your"]
    if any(re.search(r"\b" + re.escape(w) + r"\b", title.lower()) for w in useful_words):
        score += 20
    clickbait = ["shocking", "won't believe", "doctors won't", "forbidden", "this is real", "blow your mind", "secret rhythms", "hidden truth"]
    if any(w in title.lower() for w in clickbait):
        score -= 30

    # Mobile titles are strongest when concise. Reward clarity instead of
    # random numbers/emojis/question marks, which are not universal CTR wins.
    if len(_title_words(title)) <= TITLE_MAX_WORDS:
        score += 15
    else:
        score -= 20
    
    # Personal pronouns (YOU/Your)
    if re.search(r'\b(your|you)\b', title, re.IGNORECASE):
        score += 10
    
    # Exclamation marks (limited)
    exclamation_count = title.count('!')
    if exclamation_count == 1:
        score += 5
    elif exclamation_count > 2:
        score -= 5
    
    # Penalties
    if title.isupper():
        score -= 20
    if len(set(title)) < 10:  # Too repetitive
        score -= 10
    
    return max(0, min(score, 100))


def _score_description(description: str, hook: str) -> int:
    """0-100. Rewards putting the hook in the visible first ~125 chars
    (before YouTube's 'Show more' cutoff) and including hashtags."""
    if not description:
        return 0
    score = 20
    if hook and hook[:60].lower() in description[:150].lower():
        score += 30
    if '#' in description:
        score += 15
    # 2026: #Shorts explicitly helps YouTube categorise short-form content.
    if '#shorts' in description.lower():
        score += 10
    length = len(description)
    if 150 <= length <= 1000:
        score += 25
    elif length > 0:
        score += 10
    return max(0, min(score, 100))


def _score_tags(tags: List[str]) -> int:
    """0-100. Rewards having enough tags for reach without over-stuffing
    (YouTube ignores tags past a certain total character budget, and
    excessive tagging is itself a spam-flag risk anti_spam.py watches for)."""
    if not tags:
        return 0
    count = len(tags)
    if 8 <= count <= 15:
        score = 90
    elif count < 8:
        score = 50 + count * 5
    else:
        score = max(40, 90 - (count - 15) * 5)

    unique_ratio = len(set(t.lower() for t in tags)) / count
    score = int(score * unique_ratio)
    return max(0, min(score, 100))


def calculate_seo_score(title: str, description: str, tags: List[str], script_data: Dict) -> Dict:
    """Overall 0-100 SEO score plus a per-component breakdown, mirroring
    the shape quality_checker.check_script_quality() returns so both can be
    logged/displayed the same way in main.py."""
    hook = script_data.get('hook', '')
    components = {
        'title_score': _score_title(title),
        'description_score': _score_description(description, hook),
        'tags_score': _score_tags(tags),
    }
    overall = round(sum(components.values()) / len(components))
    components['overall_seo_score'] = overall

    if overall >= 85:
        rating = "🟢 EXCELLENT"
    elif overall >= 70:
        rating = "🟡 GOOD"
    elif overall >= 50:
        rating = "🟠 NEEDS WORK"
    else:
        rating = "🔴 POOR"

    return {'scores': components, 'rating': rating}


def generate_seo_package(topic: str, script_data: Dict) -> Dict:
    """Single entry point main.py can call once per video. Returns
    everything the PRD's 'AI SEO Generator' section asks for, scoped to
    what actually applies to a YouTube Short (chapters are skipped - not
    supported on sub-60s videos)."""
    category = get_topic_category(topic)
    tags = generate_upload_tags(topic, category)
    title_options = generate_title_options(topic, script_data)
    # Score every candidate and pick the best-scoring one instead of
    # always taking title_options[0] - the score was previously computed
    # only for logging and never actually influenced which title got
    # used, so a weak title could ship even when a stronger option was
    # sitting right there in the list.
    # A named series must keep its branded episode title instead of letting a
    # generic template erase the sequence number.
    chosen_title = script_data.get('series_title') or (
        max(title_options, key=_score_title) if title_options else script_data.get('title', 'Untitled')
    )
    # Append a topic-relevant emoji (e.g. "Your Heart Skips Beats 🫀").
    # make_seo_title() strips any existing emoji first, so this is safe to
    # call even on an already-emoji'd series_title.
    chosen_title = make_seo_title(chosen_title, topic)
    description = generate_description(script_data, tags)
    hashtags = generate_hashtags(topic, category)
    thumbnail_text = generate_thumbnail_text(script_data, chosen_title)
    pinned_comment = generate_pinned_comment(script_data)
    playlist = suggest_playlist(category)
    seo_score = calculate_seo_score(chosen_title, description, tags, script_data)

    logger.info(f"SEO package built for '{topic}' - score: {seo_score['scores']['overall_seo_score']}/100 ({seo_score['rating']})")

    return {
        'title_options': title_options,
        'chosen_title': chosen_title,
        'description': description,
        'tags': tags,
        'hashtags': hashtags,
        'thumbnail_text': thumbnail_text,
        'pinned_comment': pinned_comment,
        'playlist_suggestion': playlist,
        'seo_score': seo_score,
    }


if __name__ == "__main__":
    import json
    test_script = {
        'title': 'Your Heart Has Its Own Brain',
        'hook': "Doctors don't want you to know this about your heart...",
        'cta': 'Follow for more dark body secrets',
        'description': 'Your heart contains its own independent nervous system.',
    }
    result = generate_seo_package("Your Heart Has Its Own Brain", test_script)
    print(json.dumps(result, indent=2, ensure_ascii=False))
