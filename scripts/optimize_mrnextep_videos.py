"""Retrofit winning US-targeted viral SEO metadata to YouTube and Meta (Facebook / Instagram).
Upgrades titles, descriptions, and hashtags for maximum Shorts feed algorithmic velocity.
"""
from __future__ import annotations

import os
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("mrnextep.optimizer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# High-CTR winning hooks for US Dark Science Shorts:
WINNING_METADATA_MAP = {
    # 1. Broken news headline -> High CTR dark science curiosity
    "8_zEwa2Uups": {
        "title": "Why Your Memory Glitches Like A Computer 🧠",
        "tags": ["memory loss", "brain hacks", "neuroscience", "mental fatigue", "brain facts", "shorts", "us psychology"],
        "description": "Ever feel like your brain suddenly froze or forgot a simple word? Here is what your neurons are actually doing.\n\n#Shorts #brain #psychology #science #memory"
    },
    "ZtjSJrG8uiY": {
        "title": "The Dark Effect Of Late Night Scrolling 📱",
        "tags": ["dopamine detox", "phone addiction", "sleep quality", "brain fatigue", "dark science", "shorts", "psychology"],
        "description": "Your brain doesn't just get tired when scrolling late—it triggers a false alertness loop that kills deep sleep.\n\n#Shorts #brain #sleep #dopamine #science"
    },
    "GC8edOg5src": {
        "title": "Why Sleeping In On Weekends Destroys Energy 😴",
        "tags": ["sleep debt", "circadian rhythm", "fatigue", "brain fog", "sleep tips", "shorts", "health facts"],
        "description": "Think you can catch up on sleep over the weekend? Science proves your brain's internal clock gets completely wrecked.\n\n#Shorts #sleep #brain #tired #science"
    },
    "nvPkQwsw5HI": {
        "title": "What Chronic Stress Secretly Does To Memory 🤯",
        "tags": ["stress relief", "cortisol", "brain health", "memory loss", "dark psychology", "shorts", "science"],
        "description": "High cortisol levels physically shrink synaptic connections responsible for rapid recall. Watch what happens inside.\n\n#Shorts #stress #memory #brain #neuroscience"
    },
    "QDrUftgxMqs": {
        "title": "Why Sleeping Less Than 6 Hours Makes You Hungry",
        "tags": ["sleep deprivation", "ghrelin", "leptin", "metabolism", "brain science", "shorts", "body hacks"],
        "description": "Lack of deep sleep triggers ghrelin and suppresses leptin, making your subconscious brain crave survival calories.\n\n#Shorts #sleep #health #brain #science"
    },
    "5o_Bh7Eth5s": {
        "title": "Never Force Yourself To Sleep Like This...",
        "tags": ["insomnia hacks", "sleep tips", "brain reset", "deep sleep", "shorts", "science"],
        "description": "Staring at the ceiling while trying to sleep forces your amygdala into fight-or-flight mode. Do this instead.\n\n#Shorts #sleep #brain #insomnia #shortsfeed"
    },
    "noqU5MhjY3c": {
        "title": "Eat This To Shield Your Brain From Aging 🫐",
        "tags": ["brain food", "memory booster", "neurogenesis", "superfoods", "shorts", "health"],
        "description": "The exact anthocyanin compounds that cross the blood-brain barrier and protect neurons from oxidative stress.\n\n#Shorts #brain #nutrition #health #science"
    },
    "focYBww7N7U": {
        "title": "How Artificial Memories Form Inside Your Mind 🧠",
        "tags": ["false memory", "psychological tricks", "subconscious mind", "brain facts", "shorts", "dark psychology"],
        "description": "Did that memory really happen, or did your brain construct it from suggestions? Here is the proof.\n\n#Shorts #psychology #brain #mind #memory"
    },
    "Q7I4kViqNbM": {
        "title": "Why Your Immune System Attacks While You Sleep",
        "tags": ["immune system", "cytokines", "deep sleep", "body secrets", "shorts", "science"],
        "description": "Why you always feel sicker at night: your immune system unleashes inflammatory defense signals during sleep cycles.\n\n#Shorts #sleep #body #health #science"
    },
    "2_zPGKTYYsw": {
        "title": "Scientists Can Now Read Thoughts In Real Time 🤯",
        "tags": ["brain scan", "neurotechnology", "mind reading", "future science", "shorts", "tech"],
        "description": "Neural decoding models can reconstruct visual imagery directly from your visual cortex activity.\n\n#Shorts #science #brain #tech #future"
    },
    "VzOMr3qUmMA": {
        "title": "The Psychological Trick That Controls Crowds 👁️",
        "tags": ["dark psychology", "mind control", "mass psychology", "human behavior", "shorts", "psychology"],
        "description": "How subconscious mirroring and conformity bias force normal people to abandon independent thinking.\n\n#Shorts #psychology #darkscience #behavior #mind"
    },
    "tl7QdjkJJDo": {
        "title": "Your Brain Erases Emotional Trauma While Sleeping",
        "tags": ["rem sleep", "dream therapy", "ptsd", "emotional healing", "brain reset", "shorts"],
        "description": "During REM sleep, norepinephrine shuts off while memories replay, stripping the emotional pain away.\n\n#Shorts #dreams #sleep #therapy #neuroscience"
    },
    "R_UohzlKxjY": {
        "title": "The Extreme Cold Reflex That Saves Your Life 🌊",
        "tags": ["mammalian dive reflex", "survival instinct", "human body", "heart rate", "shorts", "biology"],
        "description": "The moment ice water touches your face, your vagus nerve instantly drops your heart rate to conserve oxygen.\n\n#Shorts #survival #bodyfacts #science #extreme"
    },
    "Mc_KsQZw25E": {
        "title": "Why High Achievers Suddenly Burn Out",
        "tags": ["burnout", "dopamine crash", "productivity", "mental health", "shorts", "psychology"],
        "description": "The hidden neurochemical drop behind sudden loss of drive and emotional exhaustion.\n\n#Shorts #burnout #psychology #dopamine #motivation"
    },
    "KytnrV4NPr4": {
        "title": "Why Déjà Vu Moments Feel Terrifyingly Real 👁️",
        "tags": ["deja vu", "temporal lobe", "brain glitch", "mysteries", "shorts", "neuroscience"],
        "description": "A microsecond delay between two sensory processing pathways creates the eerie illusion of having lived this before.\n\n#Shorts #dejavu #brain #mystery #science"
    },
    # Top viewed videos optimization
    "LIHZLv8a9ps": {
        "title": "Why Your Knees Crack When You Squat 🦵",
        "tags": ["crepitus", "joint cracking", "knee pain", "body sounds", "shorts", "health facts"],
        "description": "Is that popping sound in your knees nitrogen gas bubbles or cartilage damage? Here is the real answer.\n\n#Shorts #joints #bodyfacts #health #science"
    },
    "KbNYV-0mX_4": {
        "title": "The Real Reason You Forgot Your Childhood Memories",
        "tags": ["infantile amnesia", "childhood memory", "hippocampus", "brain growth", "shorts", "psychology"],
        "description": "Why nobody can remember being 2 years old: explosive neurogenesis in the hippocampus literally overwrote the hard drive.\n\n#Shorts #memory #brain #childhood #science"
    },
    "qy9GhQJ8Gyc": {
        "title": "Why Brain Freeze Actually Happens in 5 Seconds 🍦",
        "tags": ["brain freeze", "sphenopalatine ganglion", "headache hack", "shorts", "body secrets"],
        "description": "Rapid cooling of the palate triggers a massive surge of blood through the anterior cerebral artery.\n\n#Shorts #brainfreeze #headache #body #facts"
    },
    "2dBMH64Fyms": {
        "title": "Why Your Hands Are Always Ice Cold ❄️",
        "tags": ["cold hands", "vasoconstriction", "raynauds", "blood circulation", "shorts", "health"],
        "description": "When your core senses even a minor temp drop, your sympathetic nervous system cuts extremity circulation instantly.\n\n#Shorts #circulation #health #bodyfacts #cold"
    }
}


def get_youtube():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        None,
        refresh_token=os.environ["REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
    )
    credentials.refresh(Request())
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def optimize_youtube(youtube):
    logger.info("=== Starting YouTube Metadata Retrofit ===")
    for vid, meta in WINNING_METADATA_MAP.items():
        try:
            res = youtube.videos().list(part="snippet,status", id=vid).execute()
            items = res.get("items", [])
            if not items:
                logger.warning("Video %s not found on YouTube", vid)
                continue
            item = items[0]
            snippet = item["snippet"]
            status = item.get("status", {})

            old_title = snippet.get("title", "")
            snippet["title"] = meta["title"]
            snippet["tags"] = meta["tags"]
            snippet["description"] = meta["description"]

            # Also ensure video is public if scheduled/unlisted
            update_body = {
                "id": vid,
                "snippet": snippet
            }
            if status.get("privacyStatus") == "private" and status.get("publishAt"):
                logger.info("[%s] Removing private schedule, transitioning to PUBLIC!", vid)
                status_update = {
                    "privacyStatus": "public"
                }
                youtube.videos().update(part="snippet,status", body={"id": vid, "snippet": snippet, "status": status_update}).execute()
            else:
                youtube.videos().update(part="snippet", body=update_body).execute()

            logger.info("[%s] Successfully updated: '%s' -> '%s'", vid, old_title, meta["title"])
            time.sleep(1.0)
        except Exception as e:
            logger.error("[%s] Error updating YouTube video: %s", vid, e)


def optimize_meta():
    logger.info("=== Starting Meta (Facebook Page) Metadata Retrofit ===")
    fb_token = os.environ.get("FACEBOOK_ACCESS_TOKEN") or os.environ.get("FB_ACCESS_TOKEN")
    if not fb_token:
        logger.warning("No FACEBOOK_ACCESS_TOKEN found. Skipping Meta.")
        return

    try:
        import requests
    except ImportError:
        logger.warning("requests package not available for Meta.")
        return

    # Load video history to find Facebook Video IDs
    history_file = Path("data/video_history.json")
    if not history_file.exists():
        logger.warning("No data/video_history.json found.")
        return

    try:
        history = json.loads(history_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Could not read video_history.json: %s", e)
        return

    session = requests.Session()

    for entry in history:
        yt_id = entry.get("youtube_video_id")
        meta_info = entry.get("meta", {}).get("facebook", {})
        fb_id = meta_info.get("id")

        if not fb_id or fb_id == "None":
            continue

        if yt_id in WINNING_METADATA_MAP:
            winning = WINNING_METADATA_MAP[yt_id]
            logger.info("Updating Facebook Reel/Video %s (YT: %s)...", fb_id, yt_id)
            try:
                url = f"https://graph.facebook.com/v21.0/{fb_id}"
                data = {
                    "access_token": fb_token,
                    "title": winning["title"],
                    "description": winning["description"]
                }
                resp = session.post(url, data=data, timeout=15)
                if resp.status_code == 200:
                    logger.info("Facebook video %s updated successfully: %s", fb_id, resp.json())
                else:
                    logger.warning("Facebook update for %s returned %d: %s", fb_id, resp.status_code, resp.text)
            except Exception as ex:
                logger.error("Error updating Facebook video %s: %s", fb_id, ex)
            time.sleep(1.0)


def main():
    try:
        yt = get_youtube()
        optimize_youtube(yt)
    except Exception as e:
        logger.error("YouTube optimization failed: %s", e)

    try:
        optimize_meta()
    except Exception as e:
        logger.error("Meta optimization failed: %s", e)


if __name__ == "__main__":
    main()
