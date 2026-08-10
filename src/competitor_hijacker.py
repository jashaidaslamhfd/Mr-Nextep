import json
import os
import re
import urllib.parse
import urllib.request
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPETITOR_INTEL_PATH = ROOT / "data" / "competitor_intel.json"
VIRAL_INTEL_PATH = ROOT / "data" / "viral_intelligence.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("competitor_hijacker")

# Niche keywords for relevance checking
BODY_KEYWORDS = {
    "brain", "body", "health", "medical", "sleep", "heart", "memory", 
    "nerve", "muscle", "skin", "breath", "gut", "yawn", "blink", 
    "dizzy", "twitch", "tingle", "cramp", "freeze", "goosebump", "deja vu"
}

def fetch_youtube_autosuggest(seed: str) -> list[str]:
    """
    Scrapes Google's public YouTube autosuggest endpoint to find real-time 
    high-demand keyword variations for a given seed.
    """
    try:
        encoded_seed = urllib.parse.quote(seed)
        url = f"http://suggestqueries.google.com/complete/search?client=youtube&ds=yt&q={encoded_seed}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode("utf-8", "ignore")
            # The format is a javascript array callback: window.google.ac.h([...])
            # We can extract strings inside double quotes using a simple regex
            queries = re.findall(r'"([^"]*)"', content)
            # Filter out the original seed itself and keep actual suggestions
            suggestions = [q for q in queries if q.lower() != seed.lower() and len(q) > len(seed)]
            return list(dict.fromkeys(suggestions)) # Deduplicate
    except Exception as exc:
        logger.warning(f"YouTube autosuggest fetch failed for seed '{seed}': {exc}")
        return []

def get_competitor_channels() -> list[dict]:
    """Loads competitor channel configurations from intel file."""
    if COMPETITOR_INTEL_PATH.exists():
        try:
            with open(COMPETITOR_INTEL_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            channels = []
            for name, ch in data.get("per_channel", {}).items():
                channels.append({
                    "name": name,
                    "channel_id": ch.get("channel_id"),
                    "videos": ch.get("videos", [])
                })
            return channels
        except Exception as exc:
            logger.warning(f"Error reading competitor intel: {exc}")
    return []

def fetch_live_competitor_videos(channel_id: str, api_key: str) -> list[dict]:
    """
    If YOUTUBE_API_KEY is available, fetches the most popular uploads from a competitor 
    channel dynamically to check what is currently viral.
    """
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "order": "viewCount",
        "type": "video",
        "maxResults": 10,
        "key": api_key
    }
    try:
        encoded_params = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{url}?{encoded_params}", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        videos = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId")
            if video_id:
                videos.append({
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "channel_id": channel_id
                })
        return videos
    except Exception as exc:
        logger.warning(f"Failed to fetch live videos for channel {channel_id}: {exc}")
        return []

def score_topic(topic: str, source: str, views: int = 0) -> dict:
    """
    Scores a candidate topic out of 100 on Niche Fit, Demand, and Virality potential.
    """
    score = 50 # Base score
    lowered = topic.lower()
    
    # 1. Niche Fit (Body / Brain / Science alignment)
    matches = sum(1 for kw in BODY_KEYWORDS if kw in lowered)
    score += min(matches * 15, 30) # Max 30 points for keyword density
    
    # 2. Strong Hook Structure Check
    if lowered.startswith("why your"):
        score += 15
    elif lowered.startswith("what happens"):
        score += 10
    elif lowered.startswith("the secret behind"):
        score += 10
        
    # 3. Virality Multiplier
    if views > 1000000:
        score += 10
    elif views > 500000:
        score += 5
        
    return {
        "topic": topic,
        "title": topic,
        "source": source,
        "score": min(score, 100),
        "views": views
    }

def get_hijacked_viral_topic(exclude_list: list[str] = None) -> dict:
    """
    Main orchestrator for the Viral Hijacker strategy:
    1. Scrapes YouTube autosuggest for popular searches.
    2. Analyzes competitor channels (via cached JSON or Live API).
    3. Scores all candidates on niche relevance and virality metrics.
    4. Picks the single best-performing topic.
    """
    exclude_list = exclude_list or []
    normalized_excludes = [t.lower().strip() for t in exclude_list]
    
    candidates = []
    
    # --- Step 1: Real-time YouTube Autosuggest Scraping ---
    logger.info("Step 1/3: Harvesting real-time YouTube search trends...")
    seeds = ["why your body", "why do you", "what happens when you sleep", "why does my eye"]
    for seed in seeds:
        suggestions = fetch_youtube_autosuggest(seed)
        for sug in suggestions:
            # Simple cleanup of title casing
            topic_title = sug.capitalize()
            candidates.append(score_topic(topic_title, "youtube_autosuggest"))
            
    # --- Step 2: Competitor Viral Hijacking ---
    logger.info("Step 2/3: Analyzing competitor million-view uploads...")
    api_key = os.environ.get("YOUTUBE_API_KEY")
    competitors = get_competitor_channels()
    
    for comp in competitors:
        live_vids = []
        if api_key and comp["channel_id"]:
            live_vids = fetch_live_competitor_videos(comp["channel_id"], api_key)
            
        # Fallback to rich pre-analyzed video profiles
        vids_to_process = live_vids if live_vids else comp["videos"]
        for vid in vids_to_process:
            title = vid.get("title", "")
            # Clean HTML codes from API titles
            title = re.sub(r"&amp;|&quot;|&#39;|&#x27;", "", title)
            # Clean bracketed tags e.g. [Body Glitch]
            title = re.sub(r"\[.*?\]|\(.*?\)", "", title).strip()
            
            view_count = vid.get("view_count", vid.get("views", 1000000))
            candidates.append(score_topic(title, f"competitor_hijack_{comp['name'].lower()}", view_count))
            
    # Also load curated high-performing patterns
    if VIRAL_INTEL_PATH.exists():
        try:
            with open(VIRAL_INTEL_PATH, "r", encoding="utf-8") as f:
                viral_data = json.load(f)
            for vid in viral_data.get("viral_videos", []):
                candidates.append(score_topic(vid["title"], "viral_intelligence_curated", vid.get("view_count", 500000)))
        except Exception as e:
            logger.debug(f"Media generation cleanup failed: {e}")

    # --- Step 3: Filtering, Deduplicating, and Selection ---
    logger.info("Step 3/3: Evaluating, filtering and selecting the ultimate winner...")
    
    # Filter candidates by niche relevance (must contain at least one body keyword)
    relevant_candidates = []
    seen = set()
    for cand in candidates:
        topic_normalized = cand["topic"].lower().strip()
        # Ensure it is not excluded, not already seen, and relevant
        if (topic_normalized not in seen and 
            topic_normalized not in normalized_excludes and 
            any(kw in topic_normalized for kw in BODY_KEYWORDS)):
            seen.add(topic_normalized)
            relevant_candidates.append(cand)
            
    if not relevant_candidates:
        # Emergency fallback to a highly proven pillar if filters left nothing
        fallback_topic = "Why your eye twitches randomly"
        logger.warning(f"No suitable dynamic candidates found; falling back to: {fallback_topic}")
        return score_topic(fallback_topic, "viral_hijack_fallback", 1200000)
        
    # Sort candidates by score (highest first)
    relevant_candidates.sort(key=lambda x: -x["score"])
    
    # We pick from the top 5 highest-scoring candidates to maintain algorithmic variety
    top_candidates = relevant_candidates[:5]
    import random
    winner = random.choice(top_candidates)
    
    logger.info(f"🏆 Winner Chosen: '{winner['topic']}' | Source: {winner['source']} | Score: {winner['score']}/100")
    
    return winner
