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
    "us_discovery": [
        "americanstem", "usscience", "discoverusa", "sciencenews",
        "dailyfactsusa", "learnontiktok", "reelsusa", "stemeducation"
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
    final_tags = set(base_tags)

    # 1. Map keywords to clusters
    if any(w in topic_l for w in ["brain", "memory", "mind", "think", "deja"]):
        final_tags.update(HASHTAG_CLUSTERS["brain_science"])
    if any(w in topic_l for w in ["body", "muscle", "twitch", "heart", "skin"]):
        final_tags.update(HASHTAG_CLUSTERS["body_mysteries"])
    if any(w in topic_l for w in ["dark", "mystery", "creepy", "scary", "why"]):
        final_tags.update(HASHTAG_CLUSTERS["mystery_dark"])

    # 2. Always add a few discovery tags for US reach (varied subset/order).
    final_tags.update(HASHTAG_CLUSTERS["us_discovery"])

    # 3. Clean
    import re
    clean = sorted({re.sub(r'[^a-z0-9]', '', t.lower()) for t in final_tags})

    # 4. Humanised variation: anchor tags first, then a deterministic varied
    #    subset so no two videos carry the identical set/order.
    try:
        from humanizer import rotate_hashtags
        return rotate_hashtags(clean, topic, keep_top=3, total=10)
    except Exception:  # noqa: BLE001 - humanizer must never break tag generation
        return clean[:12]

