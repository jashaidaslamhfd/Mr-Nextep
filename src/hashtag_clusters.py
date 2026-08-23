"""
US-Specific Hashtag Clusters for SKILLOR (Science/Body Science).
Targets high-retention US audiences on Instagram and YouTube.
"""

HASHTAG_CLUSTERS = {
    "body_mysteries": [
        "bodymysteries", "humanbiology", "sciencefacts", "howitworks",
        "medicalscience", "anatomy", "healthhacks", "bodyglitches"
    ],
    "brain_science": [
        "neuroscience", "brainfacts", "psychologyfacts", "mentalhealth",
        "cognitive", "brainpower", "mindblowing", "didyouknow"
    ],
    # Keep US discovery tags science-specific. Generic cross-platform tags
    # such as learnontiktok/reelsusa dilute Meta topic classification and do
    # not prove US audience fit; the account and caption language already do.
    "us_discovery": [
        "usscience", "americanbiology", "healthscience", "scienceexplained",
        "stemeducation"
    ],
    "mystery_dark": [
        "unsolved", "darkscience", "mysterious", "scaryfacts",
        "curiosity", "weirdfacts", "strangebuttrue", "hiddenworld"
    ]
}

def get_optimized_us_tags(topic: str, base_tags: list) -> list:
    """Combine base tags with US-optimized clusters based on topic keywords.

    Uses humanizer.rotate_hashtags so different topics get a varied (but
    deterministic and on-niche) subset/order — identical hashtag sets across
    every video is a machine tell that the 2026 feeds demote.
    """
    topic_l = topic.lower()
    # Preserve base topic tags first. A set + alphabetical sort used to make
    # generic discovery tags become the first three hashtags after rotation,
    # pushing the actual topic out of Meta's strongest caption signals.
    final_tags = []
    seen = set()
    for raw in list(base_tags or []):
        import re
        tag = re.sub(r'[^a-z0-9]', '', str(raw).lower())
        if tag and tag not in seen:
            seen.add(tag)
            final_tags.append(tag)

    def add_many(values):
        for raw in values:
            import re
            tag = re.sub(r'[^a-z0-9]', '', str(raw).lower())
            if tag and tag not in seen:
                seen.add(tag)
                final_tags.append(tag)

    # 1. Map keywords to clusters
    if any(w in topic_l for w in ["brain", "memory", "mind", "think", "deja"]):
        add_many(HASHTAG_CLUSTERS["brain_science"])
    if any(w in topic_l for w in ["body", "muscle", "twitch", "heart", "skin"]):
        add_many(HASHTAG_CLUSTERS["body_mysteries"])
    if any(w in topic_l for w in ["dark", "mystery", "creepy", "scary"]):
        add_many(HASHTAG_CLUSTERS["mystery_dark"])

    # 2. Add a small science-specific US cluster after topic anchors.
    add_many(HASHTAG_CLUSTERS["us_discovery"][:2])

    # 3. The list is already cleaned and priority ordered.
    clean = final_tags

    # 4. Humanised variation: keep topic anchors first, then vary the tail.
    try:
        from humanizer import rotate_hashtags
        return rotate_hashtags(clean, topic, keep_top=min(3, len(clean)), total=8)
    except Exception:  # noqa: BLE001 - humanizer must never break tag generation
        return clean[:8]

