"""
src/sub_niche.py

UNIQUE sub-niche strategy — differentiates from 1000+ generic "body facts" channels.

3 Sub-niches with dedicated topic pools, hooks, and angles:
  1. "3AM Body Mysteries" — things that ONLY happen between 2-4 AM
  2. "Body Sounds Decoded" — every sound your body makes, explained
  3. "Your Body vs [X]" — what happens when X enters your body

Each sub-niche has:
  - 100+ specific topic prompts
  - Sub-niche-specific hook templates
  - Unique visual directions
  - Targeted hashtags
  - Cross-promotion angles

The main pipeline selects from these pools instead of generic "body facts"
to ensure every video has a UNIQUE ANGLE that competitors haven't covered.

Usage:
    from sub_niche import select_sub_niche, get_sub_niche_hooks, get_sub_niche_hashtags
    niche = select_sub_niche()
    hooks = get_sub_niche_hooks(niche)
    tags = get_sub_niche_hashtags(niche)
"""

import logging
import random
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


_3AM_TOPICS = [
    # Sleep mechanics
    "What your body does in the first 3 minutes of sleep",
    "Why your body paralyzes you every single night",
    "This is why you wake up at exactly 3AM and can't fall back asleep",
    "Your brain runs a full system diagnostic while you sleep",
    "Why your body temperature drops exactly 2 degrees at 3AM",
    "What happens to your muscles when you haven't moved for 6 hours",
    "Why your immune system goes into overdrive at 3AM",
    "Your body burns calories differently between 2AM and 4AM",
    "Why you sometimes feel like you're falling right before sleep",
    "The reason your brain replays your worst memories at 3AM",
    "Why your skin repairs itself only between midnight and 4AM",
    "What happens to your blood pressure when you fall asleep",
    "Your brain literally cleans itself with spinal fluid at night",
    "Why you can hear your own heartbeat clearly at 3AM",
    "What happens to your eyes when they're closed for 8 hours",
    "Why your body feels heavier at 3AM than any other time",
    "The reason you sometimes jerk awake without falling",
    "Why your dreams feel more real at 3AM than midnight",
    "What happens to your stomach acid when you sleep hungry",
    "Why your body starts aching more after midnight",
    "Your brain decides which memories to delete between 2AM and 4AM",
    "Why you sometimes talk in your sleep without knowing",
    "What happens to your spine when you lie flat for 8 hours",
    "Why your body craves sugar at 3AM if you haven't eaten",
    "The reason you sometimes can't move when you first wake up",
    "Why your brain produces more creativity at 3AM than noon",
    "What happens to your cells when you sleep in complete darkness",
    "Why your body sweats more at 3AM than during exercise",
    "The hidden process that happens to your bones between midnight and 4AM",
    "Why your dreams at 3AM are more vivid than any other time",
    "What happens to your brain's memory center when you sleep too little",
    "Why you sometimes hear your name called at 3AM",
    "Your body produces the most growth hormone between 1AM and 3AM",
    "Why your joints feel stiff at 3AM but flexible by morning",
    "What happens to your liver between 2AM and 3AM",
    "Why your brain processes emotions differently at night",
    "The reason you sometimes wake up with a racing heart at 3AM",
    "What happens to your blood when you sleep in a cold room",
    "Why your body heals cuts faster at night than during the day",
    "Your brain replays everything you learned today between 2AM and 4AM",
]

_3AM_HOOKS = [
    "Your body does this every night at 3AM — you just never noticed",
    "At 3AM, your body shuts down [X] — here's why",
    "While you're sleeping at 3AM, your brain is doing something terrifying",
    "This happens inside your body every night between 2 and 4 AM",
    "Your body has a secret schedule — and 3AM is the most important hour",
    "At exactly 3AM, your [body part] starts [action] — nobody knows why",
    "Most people don't know what their body does at 3AM",
    "Your body is most vulnerable at this exact hour",
    "This is the one thing your body does ONLY at 3AM",
    "Between 2AM and 4AM, your body runs its most important process",
]


_BODY_SOUNDS_TOPICS = [
    "That crack in your neck — it's not what you think",
    "Why your stomach growls when you're not hungry",
    "That popping sound in your ear on a plane — decoded",
    "Why your joints crack more in the morning",
    "The real reason your heart skips a beat sometimes",
    "Why your ears ring at night in complete silence",
    "That weird gurgling sound from your stomach during a meeting",
    "Why your voice sounds different on recordings",
    "The sound your bones make when you stand up too fast",
    "Why you hear a whooshing sound when you turn your head",
    "That click in your knee when you squat — decoded",
    "Why your eyes make a faint sound when you move them in the dark",
    "The popping sound when you press your earlobe — here's what it is",
    "Why your breathing sounds louder when you cover your ears",
    "That buzz you feel but can't hear — it's your eardrum vibrating",
    "Why your body makes clicking sounds when you stretch",
    "The reason your stomach makes sounds even when you're full",
    "Why you can sometimes hear your blood flowing",
    "That thud sound when you close your mouth — decoded",
    "Why your nose whistles when one side is blocked",
    "The sound your spine makes during a chiropractic adjustment",
    "Why your ears pop when you yawn",
    "That heartbeat sound you hear when you lie on someone's chest",
    "Why your knuckles pop and your doctor says it's fine",
    "The reason your stomach growls during a silent exam",
    "Why your joints crack louder as you get older",
    "That fizzing sound in your ear — it's not normal",
    "Why your body makes noise when you're falling asleep",
    "The real reason your tongue clicks when you speak",
    "Why you hear static when you press your hand over your ear",
    "Why your heart beats louder after running up stairs",
    "That weird sound when you stretch your neck sideways",
    "Why your stomach makes sounds 2 hours after eating",
    "The sound your nails make when you tap them on a table — your body is responding",
    "Why your ears feel full and make a humming sound",
    "That crunching sound when you bite into ice — what it does to your teeth",
    "Why your breathing sounds whistly when you have a cold",
    "The popping sound when you pull your finger — decoded",
    "Why your body makes bubbling sounds after drinking water fast",
    "That feeling when your ear 'opens up' and everything gets louder",
]

_BODY_SOUNDS_HOOKS = [
    "That sound your [body part] makes — it means something",
    "Your [body part] just made a sound. Here's what it's telling you",
    "Every sound your body makes has a reason — this one's the strangest",
    "That crack, pop, or fizz — your body is trying to communicate",
    "Most people ignore this body sound. Doctors don't.",
    "Your body makes 7 sounds that nobody talks about",
    "That weird noise from your [body part]? It's more serious than you think",
    "If your body makes this sound, pay attention",
    "Decode the sounds your body makes every single day",
    "Your body is louder than you think — here's proof",
]


_BODY_VS_TOPICS = [
    "What happens to your body 1 minute after you drink coffee",
    "What happens when a mosquito bite enters your bloodstream",
    "What happens to your brain 10 seconds after you hold your breath",
    "What happens when cold water hits your skin in winter",
    "What happens inside your stomach after you eat spicy food",
    "What happens to your blood when you stop eating for 24 hours",
    "What happens when you breathe in smoke from a candle",
    "What happens to your muscles after 100 pushups",
    "What happens when you look at your phone in the dark for 1 hour",
    "What happens inside your lungs when you smoke once",
    "What happens when sugar enters your bloodstream",
    "What happens to your bones after sitting for 8 hours straight",
    "What happens when you drink water on an empty stomach",
    "What happens inside your eye when you look at the sun",
    "What happens to your heart when you get scared",
    "What happens when you eat too much salt in one meal",
    "What happens inside your brain after 1 hour of TikTok",
    "What happens when you crack your knuckles for 10 years",
    "What happens to your body after 3 days without sleep",
    "What happens when cold air enters your lungs in winter",
    "What happens inside your stomach after you eat expired food",
    "What happens to your blood when you exercise at high altitude",
    "What happens when you hold in a sneeze — your body pays the price",
    "What happens inside your brain when you listen to music",
    "What happens to your muscles after sitting all day",
    "What happens when you eat a meal too fast",
    "What happens inside your ear when you hear a loud sound",
    "What happens to your body after drinking an energy drink",
    "What happens when you skip breakfast for a week",
    "What happens inside your nose when you smell food cooking",
    "What happens to your spine when you sit incorrectly for years",
    "What happens when you touch something extremely cold",
    "What happens to your immune system after one night of bad sleep",
    "What happens inside your mouth after you drink orange juice",
    "What happens to your body when you eat before bed",
    "What happens when you submerge your face in ice water",
    "What happens inside your brain after 10 minutes of meditation",
    "What happens to your blood sugar after eating white bread",
    "What happens when you stare at a screen for 4 hours straight",
    "What happens inside your body when you laugh really hard",
]

_BODY_VS_HOOKS = [
    "What happens when [X] enters your body — second by second",
    "Your body vs [X] — who wins?",
    "This is exactly what happens inside you after [X]",
    "1 minute after [X] — your body starts a war",
    "Your body has a plan for [X] — but it doesn't always work",
    "Watch what happens to your body when [X]",
    "Your body wasn't designed for [X] — here's the proof",
    "When [X] hits your body, 7 things happen instantly",
    "Your body's response to [X] is more dramatic than you think",
    "The journey of [X] through your body — start to finish",
]


# ============================================================================
# SUB-NICHE REGISTRY
# ============================================================================

SUB_NICHES = {
    "3am_body_mysteries": {
        "name": "3AM Body Mysteries",
        "tagline": "Things your body does when you're not watching",
        "topics": _3AM_TOPICS,
        "hooks": _3AM_HOOKS,
        "visual_style": "dark, nighttime, blue-purple palette, clock imagery",
        "hashtags": [
            "3ambodies", "bodysleepsecrets", "sleepscience", "nightmysteries",
            "bodyatnight", "sleepfacts", "3amthoughts", "circadianrhythm",
            "bodysleep", "nightsignals", "sleepbiology", "bodyclock",
        ],
        "thumbnail_colors": {"bg": (10, 0, 30), "text": (150, 200, 255), "accent": (100, 50, 200)},
        "description_template": "Your body does things at 3AM that nobody talks about. This is one of them.",
        "yt_search_terms": ["3am body", "body at night", "sleep secrets", "things at 3am"],
        "ig_discovery": ["3amthoughts", "bodiesatnight", "sleepsecrets"],
    },
    "body_sounds_decoded": {
        "name": "Body Sounds Decoded",
        "tagline": "Every sound your body makes — explained",
        "topics": _BODY_SOUNDS_TOPICS,
        "hooks": _BODY_SOUNDS_HOOKS,
        "visual_style": "close-up, medical diagrams, waveforms, sound visualization",
        "hashtags": [
            "bodysounds", "crackyourneck", "bodynoise", "jointpops",
            "bodydecoded", "stomachgrowls", "earpopping", "heartbeatfacts",
            "bodyexplained", "soundanalysis", "medicalexplained",
        ],
        "thumbnail_colors": {"bg": (0, 10, 30), "text": (0, 220, 255), "accent": (255, 200, 0)},
        "description_template": "That sound your body makes? It has a name and a reason.",
        "yt_search_terms": ["body sounds", "joint cracking", "ear popping", "stomach sounds"],
        "ig_discovery": ["bodysounds", "bodydecoded", "jointcracks"],
    },
    "body_vs": {
        "name": "Your Body vs [X]",
        "tagline": "What happens when X enters your body",
        "topics": _BODY_VS_TOPICS,
        "hooks": _BODY_VS_HOOKS,
        "visual_style": "timeline, journey animation, cross-section, microscopic view",
        "hashtags": [
            "bodyvs", "whatshappensinside", "bodyjourney", "internally",
            "bodyresponse", "microscopically", "bodybattles", "insideyourbody",
            "bodymechanics", "timelinebody", "biology101",
        ],
        "thumbnail_colors": {"bg": (20, 0, 0), "text": (255, 80, 80), "accent": (255, 200, 0)},
        "description_template": "Your body vs [X] — the results are shocking.",
        "yt_search_terms": ["what happens inside body", "body vs food", "body reaction"],
        "ig_discovery": ["bodyvs", "insideyourbody", "bodyreaction"],
    },
}

# Sub-niche rotation weights (higher = more likely to be selected)
SUB_NICHE_WEIGHTS = {
    "3am_body_mysteries": 0.40,    # Most unique, lowest competition
    "body_sounds_decoded": 0.35,   # Interactive, high share potential
    "body_vs": 0.25,              # Story format, high retention
}


# ============================================================================
# PUBLIC API
# ============================================================================

def select_sub_niche(force: str = None) -> str:
    """Select a sub-niche for the next video.

    Uses weighted random selection unless force is specified.
    Returns a sub-niche key: '3am_body_mysteries', 'body_sounds_decoded', 'body_vs'
    """
    if force and force in SUB_NICHES:
        return force

    niches = list(SUB_NICHE_WEIGHTS.keys())
    weights = [SUB_NICHE_WEIGHTS[n] for n in niches]
    return random.choices(niches, weights=weights, k=1)[0]


def get_sub_niche_topic(sub_niche: str = None) -> str:
    """Get a random topic from the selected sub-niche."""
    if sub_niche is None:
        sub_niche = select_sub_niche()
    niche_data = SUB_NICHES.get(sub_niche, SUB_NICHES["3am_body_mysteries"])
    return random.choice(niche_data["topics"])


def get_sub_niche_hook(sub_niche: str = None, topic: str = "") -> str:
    """Get a sub-niche-specific hook template."""
    if sub_niche is None:
        sub_niche = select_sub_niche()
    niche_data = SUB_NICHES.get(sub_niche, SUB_NICHES["3am_body_mysteries"])
    hook = random.choice(niche_data["hooks"])

    # Fill in topic-specific placeholders
    if "[X]" in hook and topic:
        # Extract the "X" from the topic
        x_match = _extract_vs_subject(topic)
        hook = hook.replace("[X]", x_match)
    if "[body part]" in hook:
        hook = hook.replace("[body part]", _extract_body_part(topic))
    if "[action]" in hook:
        hook = hook.replace("[action]", _extract_action(topic))

    return hook


def get_sub_niche_hashtags(sub_niche: str = None) -> List[str]:
    """Get sub-niche-specific hashtags for discovery."""
    if sub_niche is None:
        sub_niche = select_sub_niche()
    niche_data = SUB_NICHES.get(sub_niche, SUB_NICHES["3am_body_mysteries"])
    return niche_data["hashtags"]


def get_sub_niche_info(sub_niche: str = None) -> Dict:
    """Get full sub-niche metadata."""
    if sub_niche is None:
        sub_niche = select_sub_niche()
    return SUB_NICHES.get(sub_niche, SUB_NICHES["3am_body_mysteries"])


def get_sub_niche_description(topic: str, sub_niche: str = None) -> str:
    """Generate a sub-niche-specific description opener."""
    if sub_niche is None:
        sub_niche = select_sub_niche()
    niche_data = SUB_NICHES.get(sub_niche, SUB_NICHES["3am_body_mysteries"])
    template = niche_data["description_template"]

    if "[X]" in template:
        x_match = _extract_vs_subject(topic)
        template = template.replace("[X]", x_match)

    return template


def get_all_sub_niche_topics() -> List[Dict]:
    """Get all topics across all sub-niches with metadata."""
    all_topics = []
    for niche_key, niche_data in SUB_NICHES.items():
        for topic in niche_data["topics"]:
            all_topics.append({
                "topic": topic,
                "sub_niche": niche_key,
                "sub_niche_name": niche_data["name"],
            })
    return all_topics


# ============================================================================
# HELPERS
# ============================================================================

def _extract_body_part(topic: str) -> str:
    """Extract a body part from a topic string."""
    body_parts = [
        "neck", "stomach", "ear", "eyes", "heart", "brain", "hands",
        "muscles", "bones", "skin", "blood", "lungs", "spine",
        "knuckles", "joints", "knee", "nose", "teeth", "tongue",
        "earlobe", "fingers",
    ]
    topic_lower = topic.lower()
    for part in body_parts:
        if part in topic_lower:
            return part
    return "body"


def _extract_action(topic: str) -> str:
    """Extract the main action from a topic."""
    actions = [
        "pumps", "races", "jerks", "freezes", "activates",
        "repairs", "fights", "cleans", "burns", "produces",
    ]
    topic_lower = topic.lower()
    for action in actions:
        if action in topic_lower:
            return action
    return "activates"


def _extract_vs_subject(topic: str) -> str:
    """Extract the 'X' from a 'Your Body vs X' topic."""
    topic_lower = topic.lower()
    subjects = [
        "coffee", "mosquito bite", "cold water", "spicy food",
        "smoke", "sugar", "salt", "energy drink", "ice water",
        "expired food", "music", "phone", "screen",
    ]
    for subj in subjects:
        if subj in topic_lower:
            return subj
    # Fallback: extract after "after you" or "when you"
    import re
    match = re.search(r'(?:after|when) you (?:eat|drink|breathe|touch|hold|stare|sit|submerge|laugh|skip|hear|look|crack)\s+(.+?)(?:\s+(?:for|in|on|too|at)|$)', topic_lower)
    if match:
        return match.group(1).strip()
    return "this"


# ============================================================================
# PIPELINE INTEGRATION
# ============================================================================

def get_sub_niche_for_script() -> Dict:
    """Called by main.py to get sub-niche context for script generation.

    Returns a dict that can be injected into the script generation prompt:
    {
        'sub_niche': '3am_body_mysteries',
        'name': '3AM Body Mysteries',
        'topic': 'What your body does in the first 3 minutes of sleep',
        'hook': 'Your body does this every night at 3AM...',
        'hashtags': [...],
        'visual_style': 'dark, nighttime, blue-purple palette',
        'description_template': '...',
        'yt_search_terms': [...],
    }
    """
    niche_key = select_sub_niche()
    niche_data = SUB_NICHES[niche_key]
    topic = random.choice(niche_data["topics"])
    hook = random.choice(niche_data["hooks"])

    if "[X]" in hook:
        hook = hook.replace("[X]", _extract_vs_subject(topic))
    if "[body part]" in hook:
        hook = hook.replace("[body part]", _extract_body_part(topic))
    if "[action]" in hook:
        hook = hook.replace("[action]", _extract_action(topic))

    return {
        "sub_niche": niche_key,
        "name": niche_data["name"],
        "topic": topic,
        "hook": hook,
        "hashtags": niche_data["hashtags"],
        "visual_style": niche_data["visual_style"],
        "description_template": niche_data["description_template"],
        "yt_search_terms": niche_data["yt_search_terms"],
        "ig_discovery": niche_data["ig_discovery"],
        "thumbnail_colors": niche_data["thumbnail_colors"],
    }


if __name__ == "__main__":
    print("=== Sub-Niche Strategy ===\n")
    for key, data in SUB_NICHES.items():
        print(f"📌 {data['name']}")
        print(f"   Tagline: {data['tagline']}")
        print(f"   Topics: {len(data['topics'])}")
        print(f"   Weight: {SUB_NICHE_WEIGHTS[key]*100:.0f}%")
        print(f"   Sample topic: {random.choice(data['topics'])}")
        print(f"   Sample hook: {random.choice(data['hooks'])}")
        print()

    print("\n=== Test: get_sub_niche_for_script() ===")
    for i in range(5):
        ctx = get_sub_niche_for_script()
        print(f"  [{ctx['sub_niche']}] {ctx['topic'][:50]}")
