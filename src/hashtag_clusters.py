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
    """Combine base tags with US-optimized clusters based on topic keywords."""
    topic_l = topic.lower()
    final_tags = set(base_tags)
    
    # 1. Map keywords to clusters
    if any(w in topic_l for w in ["brain", "memory", "mind", "think", "deja"]):
        final_tags.update(HASHTAG_CLUSTERS["brain_science"])
    if any(w in topic_l for w in ["body", "muscle", "twitch", "heart", "skin"]):
        final_tags.update(HASHTAG_CLUSTERS["body_mysteries"])
    if any(w in topic_l for w in ["dark", "mystery", "creepy", "scary", "why"]):
        final_tags.update(HASHTAG_CLUSTERS["mystery_dark"])
        
    # 2. Always add discovery cluster for US reach
    final_tags.update(HASHTAG_CLUSTERS["us_discovery"])
    
    # 3. Clean and limit (Meta/IG preference: 5-10 strong tags)
    import re
    clean = [re.sub(r'[^a-z0-9]', '', t.lower()) for t in final_tags]
    return sorted(list(set(clean)))[:12]

