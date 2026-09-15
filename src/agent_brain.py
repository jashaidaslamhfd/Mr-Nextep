"""Autonomous AI Agent Brain for Mr-Nextep.
Implements the Sense -> Reason -> Act -> Learn loop:
1. Sense: Ingests YouTube Analytics & audience performance signals (focusing on US audience 65%+).
2. Memory: Maintains episodic knowledge of high-retention topics, hooks, and keywords.
3. Reason: Formulates video strategy, pacing, and mobile-first title constraints.
4. Act: Executes resilient generation, audio synthesis, and visual rendering.
5. Learn: Reflects on production metrics, updates channel memory, and self-optimizes.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc  # noqa: UP017

logger = logging.getLogger("mrnextep.agent")

DEFAULT_MEMORY = {
    "version": "2.0.0",
    "agent_name": "Mr-Nextep Autonomous Dark-Science Agent",
    "created_at": datetime.now(UTC).isoformat(),
    "last_cycle_at": None,
    "total_cycles": 0,
    "strategy": {
        "preferred_hook_style": "PSYCHOLOGICAL_CURIOSITY_GAP",
        "target_duration_window": [18.0, 22.0],
        "max_title_chars": 48,
        "mobile_feed_optimized": True,
        "active_narrative_role": "DARK_SCIENCE_INVESTIGATION",
        "target_geography": "US-English"
    },
    "high_velocity_keywords": [
        {"keyword": "brain", "weight": 1.6, "engagement_avg": 9.2},
        {"keyword": "sleep", "weight": 1.5, "engagement_avg": 8.9},
        {"keyword": "stress", "weight": 1.4, "engagement_avg": 8.4},
        {"keyword": "memory", "weight": 1.5, "engagement_avg": 8.8},
        {"keyword": "dark psychology", "weight": 1.7, "engagement_avg": 9.4},
        {"keyword": "human body", "weight": 1.4, "engagement_avg": 8.5},
        {"keyword": "dopamine", "weight": 1.5, "engagement_avg": 9.0}
    ],
    "winning_hooks": [
        "Why Your Brain Freezes Under Stress",
        "Never Ignore This Strange Body Signal",
        "Why Your Knees Crack When You Move",
        "What Your Brain Actually Does While You Sleep",
        "The Dark Truth About Why We Forget Dreams",
        "Why Your Foot Falls Asleep So Easily"
    ],
    "channel_learnings": [
        "Questions that start with broken news headlines (e.g. Why does apple acquires...) collapse CTR.",
        "Short, direct curiosity-gap titles under 48 chars consistently generate >800 views.",
        "Meta Reels require #Reels and strong curiosity first-line before the caption fold.",
        "Immediate psychological hooks within the first 2 seconds drive >70% view-through rate."
    ]
}


class AgentBrain:
    """Self-learning brain for autonomous YouTube & Meta shorts production."""

    def __init__(self, memory_file: Path | None = None):
        if memory_file is None:
            self.memory_file = Path(__file__).resolve().parent.parent / "data" / "agent_memory.json"
        else:
            self.memory_file = memory_file
        self.memory = self._load_memory()

    def _load_memory(self) -> dict[str, Any]:
        if self.memory_file.exists():
            try:
                data = json.loads(self.memory_file.read_text(encoding="utf-8"))
                logger.info("Agent memory loaded from %s (Cycles: %s)", self.memory_file, data.get("total_cycles", 0))
                return data
            except Exception as e:
                logger.warning("Failed to load agent memory (%s), initializing default.", e)
        return DEFAULT_MEMORY.copy()

    def save_memory(self) -> None:
        try:
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)
            self.memory["last_cycle_at"] = datetime.now(UTC).isoformat()
            self.memory_file.write_text(json.dumps(self.memory, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Agent memory successfully persisted to %s", self.memory_file)
        except Exception as e:
            logger.error("Could not persist agent memory: %s", e)

    def sense(self, performance_data: Any = None) -> dict[str, Any]:
        """Sense channel performance and extract learning signals."""
        signals = {
            "top_performing_topics": [],
            "avg_view_rate": 0.0,
            "sample_size": 0
        }
        if not performance_data:
            return signals

        videos = getattr(performance_data, "videos", None)
        if videos is None and isinstance(performance_data, dict):
            videos = performance_data.get("videos", [])
        if not videos:
            return signals

        signals["sample_size"] = len(videos)
        view_counts = []
        topic_scores = []
        for v in videos:
            v_views = getattr(v, "views", None) if not isinstance(v, dict) else v.get("views")
            v_title = getattr(v, "title", "") if not isinstance(v, dict) else v.get("title", "")
            if v_views is not None:
                view_counts.append(v_views)
                topic_scores.append((v_title, v_views))

        if view_counts:
            signals["avg_view_rate"] = sum(view_counts) / len(view_counts)
            topic_scores.sort(key=lambda x: x[1], reverse=True)
            signals["top_performing_topics"] = [t[0] for t in topic_scores[:5]]

        return signals

    def reason_title(self, raw_topic: str) -> str:
        """Transform any topic or headline into a high-CTR mobile hook."""
        cleaned = re.sub(r"^Why does\s+|^Why do\s+|^Why\s+", "", raw_topic, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"[""'’]", "", cleaned)
        cleaned = re.sub(r"\s*—.*$", "", cleaned)
        cleaned = re.sub(r"\s*#.*$", "", cleaned)
        cleaned = cleaned.strip()

        if not cleaned.endswith("?") and not cleaned.endswith("!"):
            candidate = "Why Your Brain Does This Under Stress" if "stress" in cleaned.lower() else cleaned
        else:
            candidate = cleaned

        if len(candidate) > 48:
            candidate = candidate[:45].rsplit(" ", 1)[0] + "..."

        return candidate

    def learn(self, published_item: dict[str, Any]) -> None:
        """Learn from an executed production run."""
        self.memory["total_cycles"] = self.memory.get("total_cycles", 0) + 1
        title = published_item.get("title")
        if title and title not in self.memory["winning_hooks"]:
            self.memory["winning_hooks"].append(title)
            if len(self.memory["winning_hooks"]) > 25:
                self.memory["winning_hooks"].pop(0)
        self.save_memory()
