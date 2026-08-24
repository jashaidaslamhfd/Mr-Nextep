#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MrNextep NICHE INTELLIGENCE — Competitor + Demand + Sub-Niche Engine      ║
║  ───────────────────────────────────────────────────────────────────────  ║
║  1. Competitor Analysis — Top body-science channels, viral videos        ║
║  2. Sub-Niche Discovery — High-demand topics within body science         ║
║  3. Combined ML Training — Our data + competitor patterns               ║
║  4. Opportunity Scoring — Which sub-niche to attack next                ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import time
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("MrNextep_DATA_DIR", "data"))
NICHE_INTEL_PATH = DATA_DIR / "niche_intelligence.json"

YT_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "")

# ═══════════════════════════════════════════════════════════════════
# COMPETITOR CHANNELS — Body Science / Faceless Shorts Niche
# ═══════════════════════════════════════════════════════════════════

COMPETITOR_CHANNELS = [
    # Direct body-science competitors
    {"handle": "@hashem.alghaili", "name": "Hashem Al-Ghaili", "niche": "science_explained"},
    {"handle": "@WhatIfScienceShow", "name": "What If", "niche": "science_explained"},
    {"handle": "@AsapSCIENCE", "name": "AsapSCIENCE", "niche": "body_facts"},
    {"handle": "@brightsideofficial", "name": "BRIGHT SIDE", "niche": "body_facts"},
    {"handle": "@BodyHubYT", "name": "Body Hub", "niche": "body_facts"},
    {"handle": "@HumanBodyExplained", "name": "Human Body Explained", "niche": "body_facts"},
    {"handle": "@ScienceChannel", "name": "Science Channel", "niche": "science_explained"},
    {"handle": "@DoctorMike", "name": "Doctor Mike", "niche": "medical_explained"},
    {"handle": "@MedlifeCrisis", "name": "Medlife Crisis", "niche": "medical_explained"},
    {"handle": "@ZackDFilms", "name": "Zack D Films", "niche": "body_mystery"},
    
    # Faceless shorts competitors (very similar format)
    {"handle": "@FactasticShorts", "name": "Factastic Shorts", "niche": "body_facts"},
    {"handle": "@TheInfographicsShow", "name": "The Infographics Show", "niche": "science_explained"},
    {"handle": "@BEAMAZED", "name": "Be Amazed", "niche": "body_facts"},
    {"handle": "@BrainBurstShorts", "name": "Brain Burst", "niche": "brain_facts"},
    {"handle": "@DailyDoseOfInternet", "name": "Daily Dose Of Internet", "niche": "viral_moments"},
]

# ═══════════════════════════════════════════════════════════════════
# SUB-NICHE DEFINITIONS — Body Science Categories
# ═══════════════════════════════════════════════════════════════════

SUBNICHES = {
    "brain_mysteries": {
        "label": "🧠 Brain Mysteries",
        "keywords": ["brain", "memory", "forget", "deja vu", "dream", "subconscious",
                     "neuron", "mind", "think", "iq", "intelligence", "psychology",
                     "cognitive", "thought", "consciousness", "brain fog", "focus"],
        "demand": "HIGH",
        "avg_views_competitor": 450000,
        "content_angles": [
            "why your brain does [weird thing]",
            "the neuroscience behind [everyday phenomenon]",
            "your brain on [situation]",
        ],
    },
    "body_reactions": {
        "label": "⚡ Body Reactions",
        "keywords": ["twitch", "cramp", "spasm", "jerk", "reflex", "reaction",
                     "goosebumps", "shiver", "shaking", "tremble", "freeze",
                     "sweat", "hiccup", "sneeze", "yawn", "gag", "blush"],
        "demand": "VERY HIGH",
        "avg_views_competitor": 680000,
        "content_angles": [
            "why your body [reaction] without warning",
            "the real reason you [reaction]",
            "your body's hidden reflex when [trigger]",
        ],
    },
    "sensory_phenomena": {
        "label": "👁️ Sensory Phenomena",
        "keywords": ["ringing", "ears", "tinnitus", "vision", "spots", "floaters",
                     "taste", "smell", "numb", "tingle", "pins", "needles",
                     "hearing", "sight", "touch", "phantom", "sensation"],
        "demand": "VERY HIGH",
        "avg_views_competitor": 520000,
        "content_angles": [
            "why you [sense] when [situation]",
            "the strange reason your [body part] [sensation]",
            "your [sense] is lying to you — here's why",
        ],
    },
    "sleep_body": {
        "label": "😴 Sleep & Body",
        "keywords": ["sleep", "dream", "nightmare", "insomnia", "wake", "tired",
                     "rest", "circadian", "melatonin", "snore", "paralysis",
                     "sleepwalk", "nap", "jetlag", "alarm", "morning"],
        "demand": "HIGH",
        "avg_views_competitor": 390000,
        "content_angles": [
            "what your body does while you sleep",
            "why you [sleep phenomenon]",
            "the scary truth about [sleep state]",
        ],
    },
    "pain_signals": {
        "label": "🩺 Pain & Signals",
        "keywords": ["pain", "ache", "sore", "hurt", "headache", "migraine",
                     "cramp", "sting", "burn", "inflammation", "chronic",
                     "back pain", "joint", "arthritis", "nerve pain"],
        "demand": "HIGH",
        "avg_views_competitor": 410000,
        "content_angles": [
            "why [body part] hurts when [action]",
            "the hidden cause of your [pain]",
            "your body's warning signal you ignore",
        ],
    },
    "aging_body": {
        "label": "⏳ Aging & Body",
        "keywords": ["aging", "age", "wrinkle", "grey hair", "old", "youth",
                     "longevity", "lifespan", "regenerate", "heal", "repair",
                     "collagen", "elasticity", "metabolism", "hormone"],
        "demand": "MEDIUM",
        "avg_views_competitor": 320000,
        "content_angles": [
            "after 25, your body stops [doing thing]",
            "the age your body secretly changes",
            "why your body ages faster when [habit]",
        ],
    },
    "heart_circulation": {
        "label": "💓 Heart & Circulation",
        "keywords": ["heart", "blood", "pulse", "beat", "circulation", "pressure",
                     "vein", "artery", "oxygen", "cardio", "heartbeat",
                     "palpitation", "bp", "hypertension", "cholesterol"],
        "demand": "HIGH",
        "avg_views_competitor": 380000,
        "content_angles": [
            "your heart does [weird thing] every day",
            "why your heartbeat [reaction]",
            "the one-second body check for heart health",
        ],
    },
}

# ═══════════════════════════════════════════════════════════════════
# NICHE INTELLIGENCE ENGINE
# ═══════════════════════════════════════════════════════════════════

class NicheIntelligence:
    """Comprehensive competitor + sub-niche demand analysis."""

    def __init__(self):
        self.competitor_data: Dict[str, Dict] = {}
        self.subniche_scores: Dict[str, Dict] = {}
        self.trending_topics: List[Dict] = []
        self.opportunity_ranking: List[Dict] = []
        self.our_videos: List[Dict] = []
        self.our_coverage: Dict[str, int] = {}

    def _get_oauth_token(self) -> Optional[str]:
        if not REFRESH_TOKEN or not GOOGLE_CLIENT_ID:
            return None
        try:
            resp = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": REFRESH_TOKEN,
                "grant_type": "refresh_token",
            }, timeout=15)
            return resp.json().get("access_token")
        except Exception:
            return None

    def _yt_search(self, query: str, max_results: int = 20) -> List[Dict]:
        """Search YouTube for trending content."""
        token = self._get_oauth_token()
        
        results = []
        params = {
            "part": "snippet",
            "q": query,
            "maxResults": min(max_results, 50),
            "type": "video",
            "videoDuration": "short",
            "order": "viewCount",
            "relevanceLanguage": "en",
            "regionCode": "US",
        }

        if token:
            headers = {"Authorization": f"Bearer {token}"}
        elif YT_API_KEY:
            params["key"] = YT_API_KEY
            headers = {}
        else:
            return results

        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params=params, headers=headers, timeout=20
            )
            data = resp.json() if resp.content else {}
            
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                results.append({
                    "video_id": item.get("id", {}).get("videoId", ""),
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "published": snippet.get("publishedAt", ""),
                    "query": query,
                })

            # Get stats for these videos
            if results:
                ids = ",".join(r["video_id"] for r in results[:50])
                stats_params = {
                    "part": "statistics",
                    "id": ids,
                }
                if token:
                    stats_params.pop("key", None)
                elif YT_API_KEY:
                    stats_params["key"] = YT_API_KEY
                
                stats_resp = requests.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params=stats_params, headers=headers if token else {}, timeout=20
                )
                stats_data = stats_resp.json() if stats_resp.content else {}
                
                for item in stats_data.get("items", []):
                    vid = item["id"]
                    stats = item.get("statistics", {})
                    for r in results:
                        if r["video_id"] == vid:
                            r["views"] = int(stats.get("viewCount", 0))
                            r["likes"] = int(stats.get("likeCount", 0))
                            r["comments"] = int(stats.get("commentCount", 0))
        except Exception as e:
            logger.warning("YouTube search failed for '%s': %s", query, e)

        return results

    def scan_competitors(self) -> Dict:
        """Scan all competitor channels for top-performing content."""
        logger.info("🔍 Scanning %d competitor channels...", len(COMPETITOR_CHANNELS))
        
        for comp in COMPETITOR_CHANNELS:
            try:
                # Search for channel by handle
                ch_data = self._yt_search(f"body science shorts {comp['niche']}", 5)
                
                self.competitor_data[comp["handle"]] = {
                    "name": comp["name"],
                    "niche": comp["niche"],
                    "top_videos": ch_data,
                    "scanned_at": datetime.now(timezone.utc).isoformat(),
                }
                
                if ch_data:
                    top_views = max(v.get("views", 0) for v in ch_data)
                    logger.info("  %-25s → top video: %,d views", comp["name"], top_views)
                
                time.sleep(0.5)  # Rate limit
            except Exception as e:
                logger.warning("  Failed to scan %s: %s", comp["name"], e)

        return self.competitor_data

    def analyze_subniche_demand(self) -> Dict:
        """Analyze demand for each sub-niche based on search + competitor data."""
        logger.info("\n📊 Analyzing sub-niche demand...")
        
        for niche_key, niche_data in SUBNICHES.items():
            # Score factors:
            # 1. Built-in demand rating
            demand_scores = {"VERY HIGH": 100, "HIGH": 75, "MEDIUM": 50, "LOW": 25}
            base_score = demand_scores.get(niche_data["demand"], 50)
            
            # 2. Competitor avg views (normalize)
            comp_views = niche_data.get("avg_views_competitor", 0)
            view_score = min(comp_views / 5000, 100)  # Cap at 100
            
            # 3. Our coverage gap (less = more opportunity)
            our_count = self.our_coverage.get(niche_key, 0)
            gap_score = max(100 - (our_count * 10), 10) if our_count < 30 else 10
            
            # 4. Topic catalog coverage
            niche_keywords = set(niche_data.get("keywords", []))
            catalog_match = 0
            for kw in niche_keywords:
                if any(kw in (t or "") for t in self.our_videos):
                    catalog_match += 1
            catalog_coverage = min(catalog_match * 10, 40)
            
            # 5. Diversity of content angles
            angle_score = len(niche_data.get("content_angles", [])) * 15
            
            total_score = (
                base_score * 0.25 +
                view_score * 0.30 +
                gap_score * 0.20 +
                catalog_coverage * 0.10 +
                angle_score * 0.15
            )
            
            self.subniche_scores[niche_key] = {
                "label": niche_data["label"],
                "demand_rating": niche_data["demand"],
                "competitor_avg_views": niche_data["avg_views_competitor"],
                "our_video_count": our_count,
                "coverage_gap": "🟢 UNTAPPED" if our_count < 3 else ("🟡 LOW" if our_count < 8 else "🔴 SATURATED"),
                "total_score": round(total_score, 1),
                "content_angles": niche_data["content_angles"],
                "keywords": niche_data["keywords"][:8],
            }
            
            logger.info("  %-22s → Score:%5.0f | Our vids:%3d | Gap: %s",
                       niche_data["label"], total_score, our_count,
                       self.subniche_scores[niche_key]["coverage_gap"])
        
        return self.subniche_scores

    def scan_trending_topics(self) -> List[Dict]:
        """Scan YouTube for currently trending body-science topics."""
        logger.info("\n🔥 Scanning trending body-science topics...")
        
        trending_queries = [
            "why your body",
            "body science explained", 
            "strange body facts",
            "human body mystery",
            "why does my body",
            "body reacts when",
            "weird body things",
            "your body is",
        ]
        
        all_results = []
        seen_ids = set()
        
        for query in trending_queries:
            results = self._yt_search(f"{query} shorts", 10)
            for r in results:
                if r["video_id"] not in seen_ids:
                    seen_ids.add(r["video_id"])
                    
                    # Classify into sub-niche
                    title_lower = r.get("title", "").lower()
                    matched_niche = "other"
                    for niche_key, niche_data in SUBNICHES.items():
                        if any(kw in title_lower for kw in niche_data["keywords"]):
                            matched_niche = niche_key
                            break
                    
                    r["subniche"] = matched_niche
                    r["subniche_label"] = SUBNICHES.get(matched_niche, {}).get("label", "Other")
                    all_results.append(r)
            
            time.sleep(0.6)  # Rate limit
        
        # Sort by views descending
        all_results.sort(key=lambda x: x.get("views", 0), reverse=True)
        self.trending_topics = all_results[:50]
        
        logger.info("  Found %d trending topics across %d queries", 
                   len(self.trending_topics), len(trending_queries))
        
        # Show top subniches
        niche_counts = Counter(r.get("subniche", "other") for r in self.trending_topics)
        for niche, count in niche_counts.most_common(5):
            logger.info("    %-25s: %d trending", 
                       SUBNICHES.get(niche, {}).get("label", niche), count)
        
        return self.trending_topics

    def rank_opportunities(self) -> List[Dict]:
        """Rank sub-niches by opportunity score (demand × gap)."""
        self.opportunity_ranking = sorted(
            self.subniche_scores.values(),
            key=lambda x: x["total_score"],
            reverse=True
        )
        
        logger.info("\n🏆 OPPORTUNITY RANKING:")
        for i, opp in enumerate(self.opportunity_ranking, 1):
            icon = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else f"{i:2d}."))
            logger.info("  %s %-22s Score: %5.0f | %s | %s",
                       icon, opp["label"], opp["total_score"],
                       opp["coverage_gap"], opp["demand_rating"])
        
        return self.opportunity_ranking

    def load_our_videos(self):
        """Load our video history for gap analysis."""
        history_path = DATA_DIR / "video_history.json"
        if not history_path.exists():
            return
        
        with open(history_path) as f:
            videos = json.load(f)
        
        self.our_videos = [v.get("topic", v.get("youtube_title", "")) for v in videos
                          if v.get("youtube_id")]
        
        # Calculate coverage per subniche
        for niche_key, niche_data in SUBNICHES.items():
            count = 0
            for topic in self.our_videos:
                topic_lower = (topic or "").lower()
                if any(kw in topic_lower for kw in niche_data["keywords"]):
                    count += 1
            self.our_coverage[niche_key] = count
        
        logger.info("📺 Our videos: %d across niches", len(self.our_videos))

    def generate_attack_plan(self) -> Dict:
        """Generate a concrete attack plan for the best sub-niches."""
        if not self.opportunity_ranking:
            self.rank_opportunities()
        
        plan = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall_strategy": "Attack UNTAPPED high-demand sub-niches with 5-10 videos each",
            "priority_targets": [],
            "content_ideas": [],
        }
        
        for opp in self.opportunity_ranking[:3]:
            target = {
                "subniche": opp["label"],
                "score": opp["total_score"],
                "our_coverage": opp["our_video_count"],
                "gap": opp["coverage_gap"],
                "competitor_avg_views": opp["competitor_avg_views"],
                "recommended_videos": 10 if opp["our_video_count"] < 3 else (5 if opp["our_video_count"] < 8 else 3),
                "content_angles": opp.get("content_angles", []),
                "sample_topics": self._generate_topic_ideas(opp),
            }
            plan["priority_targets"].append(target)
        
        # Add trending topics as quick wins
        if self.trending_topics:
            plan["trending_quick_wins"] = []
            for t in self.trending_topics[:5]:
                if t.get("views", 0) > 100000:
                    plan["trending_quick_wins"].append({
                        "trending_title": t.get("title", ""),
                        "views": t.get("views", 0),
                        "subniche": t.get("subniche_label", ""),
                        "hijack_angle": f"Our version: {t.get('title','')} — but body-science focused",
                    })
        
        return plan

    def _generate_topic_ideas(self, opportunity: Dict) -> List[str]:
        """Generate specific topic ideas for a sub-niche."""
        label_to_key = {
            "🧠 Brain Mysteries": "brain_mysteries",
            "⚡ Body Reactions": "body_reactions",
            "👁️ Sensory Phenomena": "sensory_phenomena",
            "😴 Sleep & Body": "sleep_body",
            "🩺 Pain & Signals": "pain_signals",
            "⏳ Aging & Body": "aging_body",
            "💓 Heart & Circulation": "heart_circulation",
        }
        label = opportunity.get("label", "")
        key = label_to_key.get(label, "")
        templates = {
            "brain_mysteries": [
                "why your brain forgets names immediately after hearing them",
                "deja vu — your brain glitching in real time",
                "why your brain plays random songs on repeat at 2am",
                "your brain can predict the future by 0.5 seconds",
                "why your brain decides to forget traumatic memories",
                "the strange reason your brain feels foggy after bad sleep",
                "why your brain makes you forget why you walked into a room",
                "your brain physically changes when you learn something new",
            ],
            "body_reactions": [
                "a sudden charley horse cramp in your calf at night",
                "why your body jerks awake right as you fall asleep",
                "goosebumps — your body ancient survival reflex",
                "why your eyes water when you laugh uncontrollably",
                "hiccups — your body strangest glitch explained",
                "the real reason you yawn when someone else yawns",
                "why brushing back teeth triggers a sudden gag reflex",
                "your body freezes when scared — here is the neuroscience",
            ],
            "sensory_phenomena": [
                "your ears ringing in absolute silence — explained",
                "why your foot falls asleep and feels like static",
                "why you see glowing spots after looking at bright light",
                "your hands wrinkling in water — not what you think",
                "why your nose runs when you cry or eat hot food",
                "phantom phone vibration — your body strangest illusion",
                "why you lose taste sensation after burning your tongue",
                "your voice sounds different in recordings — the real reason",
            ],
            "sleep_body": [
                "what your body does while you sleep — minute by minute",
                "why your body paralyzes itself during dreams",
                "the scary reason you sometimes cannot move when waking up",
                "why your body temperature drops right before sleep",
                "your brain cleans itself while you sleep — literally",
                "why you forget 95 percent of your dreams within 5 minutes",
            ],
            "pain_signals": [
                "why your head hurts when you eat ice cream too fast",
                "the hidden cause of your random sharp chest pain",
                "why your back hurts after sitting all day — the science",
                "your body warning signals you have been ignoring",
                "why old injuries hurt when the weather changes",
                "the real reason your joints crack and pop",
                "why your stomach hurts when you are anxious",
                "why your muscles feel sore 2 days after exercise",
            ],
            "aging_body": [
                "after 25 your body stops producing collagen — here is why",
                "why your metabolism slows down every decade after 30",
                "the age your brain peaks — and when it starts declining",
                "why your hair turns grey — the exact mechanism",
                "your body replaces itself completely every 7 years",
            ],
            "heart_circulation": [
                "why your heart beats faster when you are nervous",
                "your heart skips a beat — when it is actually serious",
                "why you feel lightheaded after standing up too fast",
                "your blood vessels could circle the earth twice",
                "why your hands and feet get cold when you are stressed",
                "the real reason your heart rate spikes during exercise",
            ],
        }
        return templates.get(key, templates.get("body_reactions", []))[:10]
    def save(self):
        """Save the complete intelligence report."""
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "competitors_scanned": len(self.competitor_data),
            "subniches_analyzed": len(self.subniche_scores),
            "trending_topics_found": len(self.trending_topics),
            "subniche_scores": self.subniche_scores,
            "opportunity_ranking": [
                {"label": o["label"], "score": o["total_score"], "gap": o["coverage_gap"]}
                for o in self.opportunity_ranking
            ],
            "trending_topics": self.trending_topics[:20],
            "attack_plan": self.generate_attack_plan(),
            "our_coverage": self.our_coverage,
        }
        
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = str(NICHE_INTEL_PATH) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        os.replace(tmp, NICHE_INTEL_PATH)
        logger.info("\n💾 Niche intelligence saved → %s", NICHE_INTEL_PATH)

    def print_battle_plan(self):
        """Print a visual battle plan."""
        plan = self.generate_attack_plan()
        
        print("\n" + "=" * 70)
        print("  ⚔️  MrNextep BATTLE PLAN — Sub-Niche Attack Strategy")
        print("=" * 70)
        
        for i, target in enumerate(plan.get("priority_targets", [])[:3]):
            icon = ["🥇", "🥈", "🥉"][i]
            print(f"\n  {icon} PRIORITY {i+1}: {target['subniche']}")
            print(f"     Score: {target['score']:.0f}/100")
            print(f"     Our Videos: {target['our_coverage']} | Gap: {target['gap']}")
            print(f"     Competitors Avg: {target['competitor_avg_views']:,} views")
            print(f"     ⇒ Make {target['recommended_videos']} videos in this niche")
            print("     Content Angles:")
            for angle in target.get("content_angles", [])[:3]:
                print(f"       • {angle}")
            print("     Sample Topics:")
            for idea in target.get("sample_topics", [])[:4]:
                print(f"       ✏️  {idea}")
        
        print("\n  ⚡ QUICK WINS (Trending Now):")
        for win in plan.get("trending_quick_wins", [])[:3]:
            print(f"     📈 {win['trending_title'][:60]}")
            print(f"        Views: {win['views']:,} | {win['subniche']}")
        print("\n" + "=" * 70)


# ═══════════════════════════════════════════════════════════════════
# COMPETITOR ML FEED — Feed competitor data into ML Brain
# ═══════════════════════════════════════════════════════════════════

class CompetitorMLFeed:
    """Feed competitor intelligence into the ML training pipeline."""
    
    def __init__(self, niche_intel: NicheIntelligence):
        self.niche = niche_intel
        self.combined_features: List[np.ndarray] = []
        self.combined_labels: List[float] = []
    
    def build_combined_dataset(self) -> Tuple[np.ndarray, np.ndarray]:
        """Build a combined training dataset from our videos + competitor patterns."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        
        try:
            from ml_brain import FeatureExtractor
            extractor = FeatureExtractor()
        except Exception as e:
            logger.error("Could not load FeatureExtractor: %s", e)
            return np.array([]), np.array([])
        
        # 1. Our existing training data
        our_X, our_y = [], []
        if DATA_DIR.joinpath("video_history.json").exists():
            with open(DATA_DIR.joinpath("video_history.json")) as f:
                videos = json.load(f)
            for v in videos:
                topic = v.get("topic", v.get("youtube_title", ""))
                views = v.get("views", 0) or 0
                if topic and len(topic) > 5:
                    our_X.append(extractor.extract_from_topic(topic))
                    our_y.append(float(views))
        
        logger.info("Our data: %d samples", len(our_X))
        
        # 2. Competitor virtual samples (weighted by subniche demand)
        comp_X, comp_y = [], []
        for opp in self.niche.opportunity_ranking[:5]:
            if opp["coverage_gap"] in ("🟢 UNTAPPED", "🟡 LOW"):
                # Create synthetic training samples from competitor angles
                for angle in opp.get("content_angles", [])[:3]:
                    for kw in opp.get("keywords", [])[:3]:
                        topic = angle.replace("[weird thing]", kw)
                        topic = topic.replace("[X]", kw)
                        topic = topic.replace("[reaction]", kw)
                        topic = topic.replace("[body part]", "body")
                        topic = topic.replace("[situation]", kw)
                        topic = topic.replace("[trigger]", kw)
                        topic = topic.replace("[sensation]", f"{kw}")
                        
                        if len(topic) > 10:
                            comp_X.append(extractor.extract_from_topic(topic))
                            # Weight by competitor avg views
                            weighted_views = opp.get("competitor_avg_views", 100000) / 1000
                            comp_y.append(float(weighted_views))
        
        logger.info("Competitor virtual samples: %d", len(comp_X))
        
        # 3. Trending topic samples
        trend_X, trend_y = [], []
        for t in self.niche.trending_topics[:15]:
            topic = t.get("title", "")
            views = t.get("views", 0)
            if topic and views > 0:
                trend_X.append(extractor.extract_from_topic(topic))
                trend_y.append(float(views))
        
        logger.info("Trending samples: %d", len(trend_X))
        
        # Combine all
        all_X = our_X + comp_X[:100] + trend_X[:30]
        all_y = our_y + comp_y[:100] + trend_y[:30]
        
        self.combined_features = np.array(all_X, dtype=np.float64) if all_X else np.array([])
        self.combined_labels = np.array(all_y, dtype=np.float64) if all_y else np.array([])
        
        logger.info("✅ Combined dataset: %d total samples", len(self.combined_features))
        return self.combined_features, self.combined_labels
    
    def retrain_brain(self):
        """Retrain ML Brain with combined dataset."""
        # Add scripts dir to path
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        
        try:
            from ml_brain import MLBrain, RidgeRegression, LogisticClassifier, FeatureExtractor
        except Exception as e:
            logger.error("Could not import ML Brain: %s", e)
            return
        
        X, y = self.build_combined_dataset()
        if len(X) < 10:
            logger.warning("Not enough data to retrain.")
            return
        
        brain = MLBrain()
        brain.load()
        
        # Retrain with combined data
        brain.extractor = FeatureExtractor()
        brain.n_samples = len(X)
        
        y_log = np.log1p(y)
        brain.views_model = RidgeRegression(alpha=0.5)
        brain.views_model.fit(X, y_log)
        brain.views_r2 = brain.views_model.score(X, y_log)
        
        viral_threshold = np.percentile(y, 75)
        y_viral = (y >= viral_threshold).astype(int)
        if np.sum(y_viral) >= 3 and np.sum(y_viral == 0) >= 3:
            brain.viral_model = LogisticClassifier(lr=0.05, epochs=800)
            brain.viral_model.fit(X, y_viral)
            pred_viral = brain.viral_model.predict(X)
            brain.viral_accuracy = float(np.mean(pred_viral == y_viral))
        
        brain.trained = True
        brain.save()
        
        logger.info("🧠 Brain retrained with %d samples (ours + competitors + trends)", len(X))
        logger.info("   Views R²: %.3f | Viral Accuracy: %.1f%%",
                   brain.views_r2, brain.viral_accuracy * 100 if brain.viral_model else 0)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 70)
    print("  🧬 MrNextep NICHE INTELLIGENCE — Competitor + Demand Engine")
    print("=" * 70)
    
    intel = NicheIntelligence()
    
    # Step 1: Load our data
    intel.load_our_videos()
    
    # Step 2: Scan competitors (API-based, skips if no key)
    if YT_API_KEY or (GOOGLE_CLIENT_ID and REFRESH_TOKEN):
        intel.scan_competitors()
        intel.scan_trending_topics()
    else:
        logger.info("No YouTube API key — using built-in competitor data")
        # Use bundled data from SUBNICHES
        intel.competitor_data = {
            c["handle"]: {"name": c["name"], "niche": c["niche"]}
            for c in COMPETITOR_CHANNELS
        }
    
    # Step 3: Analyze demand
    intel.analyze_subniche_demand()
    
    # Step 4: Rank opportunities
    intel.rank_opportunities()
    
    # Step 5: Print battle plan
    intel.print_battle_plan()
    
    # Step 6: Save
    intel.save()
    
    # Step 7: Feed into ML Brain
    print("\n🧠 Feeding competitor intelligence into ML Brain...")
    feed = CompetitorMLFeed(intel)
    feed.retrain_brain()
    
    print("\n✅ DONE! Niche intelligence ready.")
    print(f"   Report: {NICHE_INTEL_PATH}")
    print("   Run 'python scripts/niche_intel.py' to refresh daily.")


if __name__ == "__main__":
    main()
