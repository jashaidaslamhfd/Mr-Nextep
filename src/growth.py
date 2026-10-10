"""Data-informed topic ranking, hook experiments, and pre-render content checks.

Scores in this module are prioritization heuristics, not predictions of virality.
Only metrics fetched from YouTube Analytics are treated as measured performance.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from .guards import duplicate_reason, token_similarity

HOOK_STYLES: dict[str, str] = {
    "concrete_observation": (
        "Open on a specific, recognizable moment the viewer may have experienced. "
        "Use a concrete image or sensation; avoid a generic question."
    ),
    "counterintuitive": (
        "Open with a surprising but defensible contrast between what people expect "
        "and what the evidence supports. Do not exaggerate or invent a fact."
    ),
    "specific_question": (
        "Open with one short, sharply specific question about the central mystery. "
        "Avoid broad openers such as 'Have you ever wondered'."
    ),
}
EXPERIMENT_ID = "hook-style-v1"
_STOP = {
    "the", "and", "for", "with", "that", "this", "your", "you", "why", "what",
    "when", "where", "does", "how", "from", "into", "about", "are", "can",
    "does", "have", "has", "was", "were", "their", "they", "then", "than",
}


def _tokens(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(word) > 2 and word not in _STOP
    }


def topic_cluster(topic: str) -> str:
    text = str(topic or "").lower()
    groups = {
        "ai_trust": ("ai", "artificial intelligence", "deepfake", "voice clone", "chatbot", "algorithm"),
        "sleep_dreams": ("sleep", "dream", "nightmare", "falling asleep", "sleep paralysis"),
        "memory_perception": ("memory", "déjà vu", "deja vu", "mirror", "shadow", "illusion", "perception"),
        "brain_behavior": ("brain", "neuron", "psychology", "behavior", "behaviour", "emotion", "consciousness"),
    }
    for cluster, terms in groups.items():
        if any((bool(re.search(r"\\bai\\b", text)) if term == "ai" else term in text) for term in terms):
            return cluster
    return "general_science"


def build_hook_variations(topic: str) -> list[dict[str, Any]]:
    """Return three safe candidate directions; scores are structural heuristics only."""
    clean = " ".join(str(topic or "").strip().rstrip("?.!").split())
    noun = re.sub(r"^(?:why\s+(?:does|do|is|are)|how\s+(?:does|do|is|are)|what\s+(?:makes|happens\s+when|does|do)|when|where|why|how|what|can|does|do)\s+", "", clean, flags=re.I)
    candidates = [
        {"style": "concrete_observation", "instruction": HOOK_STYLES["concrete_observation"],
         "example": f"The odd feeling behind {noun.lower()}."},
        {"style": "counterintuitive", "instruction": HOOK_STYLES["counterintuitive"],
         "example": f"The obvious explanation for {noun.lower()} may be wrong."},
        {"style": "specific_question", "instruction": HOOK_STYLES["specific_question"],
         "example": f"What explains the strange feeling behind {noun.lower()}?"},
    ]
    for item in candidates:
        words = _tokens(item["example"])
        # Reward specificity and brevity, not emotional intensity or unsupported claims.
        item["hook_heuristic_score"] = min(100, 35 + len(words) * 5 + min(15, len(_tokens(clean))))
        item["score_type"] = "heuristic_not_ctr"
    return sorted(candidates, key=lambda item: item["hook_heuristic_score"], reverse=True)


def assign_hook_experiment(topic: str, history: list[dict[str, Any]]) -> dict[str, str]:
    """Assign the least-used hook style within a topic cluster for rough balancing.

    This is a between-video experiment, not a same-video thumbnail/title A/B test.
    """
    cluster = topic_cluster(topic)
    counts: Counter[str] = Counter()
    for row in history if isinstance(history, list) else []:
        experiment = row.get("growth_experiment", {}) if isinstance(row, dict) else {}
        if experiment.get("experiment_id") == EXPERIMENT_ID and experiment.get("cluster") == cluster:
            style = experiment.get("variant")
            if style in HOOK_STYLES:
                counts[str(style)] += 1
    styles = list(HOOK_STYLES)
    minimum = min(counts[style] for style in styles)
    tied = [style for style in styles if counts[style] == minimum]
    # Deterministic tie-break means reruns don't silently re-randomize a selected variant.
    digest = hashlib.sha256(f"{cluster}:{topic}".encode("utf-8")).hexdigest()
    variant = tied[int(digest[:8], 16) % len(tied)]
    return {
        "experiment_id": EXPERIMENT_ID,
        "variant": variant,
        "cluster": cluster,
    }


def rank_topic_candidates(
    candidates: list[dict[str, Any]],
    performance: Any = None,
    history: list[dict[str, Any]] | None = None,
    excluded_topics: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Rank trend candidates using source score, real similar-video retention and novelty."""
    history = history or []
    excluded = {str(value).strip().lower() for value in (excluded_topics or set())}
    videos = getattr(performance, "videos", []) if performance is not None else []
    median = getattr(performance, "median_retention", None) if performance is not None else None
    ranked: list[dict[str, Any]] = []

    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        topic = str(raw.get("topic") or raw.get("title") or "").strip()
        if not topic or topic.lower() in excluded:
            continue
        trend = raw.get("score", raw.get("trend_score", 50))
        try:
            trend_score = max(0.0, min(100.0, float(trend)))
        except (TypeError, ValueError):
            trend_score = 50.0
        tokens = _tokens(topic)
        close_history = []
        for old in history:
            if not isinstance(old, dict):
                continue
            old_title = str(old.get("topic") or old.get("title") or "")
            if old_title and (old_title.lower() == topic.lower() or token_similarity(topic, old_title) >= 0.72):
                close_history.append(old)
        novelty_score = 100.0 if not close_history else max(0.0, 100.0 - 30.0 * len(close_history))

        measured_matches: list[tuple[float, float]] = []
        for video in videos or []:
            title = getattr(video, "title", "") if not isinstance(video, dict) else video.get("title", "")
            retention = getattr(video, "retention", None) if not isinstance(video, dict) else video.get("average_view_percentage")
            overlap_tokens = _tokens(str(title))
            union = tokens | overlap_tokens
            overlap = len(tokens & overlap_tokens) / len(union) if union else 0.0
            if overlap >= 0.20 and isinstance(retention, (int, float)):
                measured_matches.append((overlap, float(retention)))
        analytics_score = 50.0
        rationale = "No similar measured videos; analytics score neutral."
        if measured_matches and median is not None:
            total_weight = sum(weight for weight, _ in measured_matches)
            neighbour_retention = sum(weight * retention for weight, retention in measured_matches) / total_weight
            relative = neighbour_retention - float(median)
            analytics_score = max(0.0, min(100.0, 50.0 + relative * 150.0))
            rationale = f"Similar measured videos retained {neighbour_retention:.0%}; channel median {float(median):.0%}."

        total = round(0.45 * trend_score + 0.35 * analytics_score + 0.20 * novelty_score, 2)
        ranked.append({
            **raw,
            "topic": topic,
            "growth_score": total,
            "score_type": "ranking_heuristic_not_virality_prediction",
            "growth_reasons": [f"Trend/source score {trend_score:.0f}/100.", rationale,
                               f"Novelty score {novelty_score:.0f}/100."],
        })
    return sorted(ranked, key=lambda item: item["growth_score"], reverse=True)


def choose_growth_topic(
    settings: Any,
    performance: Any = None,
    history: list[dict[str, Any]] | None = None,
    excluded_topics: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return the highest-ranked current trend candidate, or None when no queue exists."""
    queue_path = settings.data_dir / "search_demand_queue_us.json"
    if not queue_path.exists():
        return None
    try:
        payload = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A bad queue should fall back to the existing topic rotation rather than stop publishing.
        return None
    candidates = payload.get("topics", []) if isinstance(payload, dict) else []
    if not isinstance(candidates, list) or not candidates:
        return None
    ranked = rank_topic_candidates(
        candidates, performance=performance, history=history, excluded_topics=excluded_topics
    )
    return ranked[0] if ranked else None


def check_originality(script: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the existing duplicate detector before the expensive render step."""
    reason = duplicate_reason(script, history or [])
    current_body = " ".join(str(scene.get("caption", "")) for scene in script.get("scenes", []))
    for old in history or []:
        if not isinstance(old, dict):
            continue
        old_body = str(old.get("body", ""))
        if old_body and token_similarity(current_body, old_body) >= 0.85:
            reason = reason or "scene captions are highly similar to a recent script"
            break
    return {"passed": reason is None, "reason": reason or "No near-duplicate found."}


def check_claim_sources(script: dict[str, Any]) -> dict[str, Any]:
    """Require source URLs for numeric or study-attributed claims; this is not fact proof."""
    narration = " ".join(str(scene.get("narration", "")) for scene in script.get("scenes", []))
    precise_claim = bool(re.search(
        r"\b\d+(?:\.\d+)?\s?%|\b\d+(?:\.\d+)?\s?(?:million|billion|thousand)\b|"
        r"\b(?:a study found|researchers proved|scientists proved|according to a study)\b",
        narration, flags=re.I,
    ))
    sources = script.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]
    valid_sources = [
        str(source).strip() for source in sources
        if isinstance(source, str) and str(source).strip().startswith(("https://", "http://"))
    ] if isinstance(sources, list) else []
    if precise_claim and not valid_sources:
        return {
            "passed": False,
            "reason": "Numeric or study-attributed claim needs at least one HTTP(S) source URL.",
            "source_count": 0,
            "verified": False,
        }
    return {
        "passed": True,
        "reason": "No unsupported precision pattern detected." if not precise_claim else "Source URL supplied; source content still requires review.",
        "source_count": len(valid_sources),
        "verified": False,
    }
