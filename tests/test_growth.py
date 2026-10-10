from __future__ import annotations

from src.analytics import ChannelPerformance, VideoPerformance
from src.growth import (
    assign_hook_experiment,
    build_hook_variations,
    check_claim_sources,
    check_originality,
    rank_topic_candidates,
)


def test_hook_variations_are_distinct_and_do_not_claim_ctr():
    variants = build_hook_variations("Why does your body jolt as you fall asleep?")
    assert len(variants) == 3
    assert len({item["style"] for item in variants}) == 3
    assert all(item["score_type"] == "heuristic_not_ctr" for item in variants)


def test_experiment_assignment_balances_variants_within_cluster():
    history = []
    first = assign_hook_experiment("Why do dreams feel real?", history)
    history.append({"growth_experiment": first})
    second = assign_hook_experiment("Why does sleep paralysis happen?", history)
    assert first["experiment_id"] == second["experiment_id"]
    assert first["cluster"] == second["cluster"]
    # The second choice is selected from the least-used style(s), not a claimed random test.
    assert second["variant"] != first["variant"]


def test_topic_ranking_uses_real_analytics_and_novelty():
    performance = ChannelPerformance(videos=[
        VideoPerformance("1", "Why Does Sleep Paralysis Happen", 1000, 0.48, 10.0),
        VideoPerformance("2", "Sleep Paralysis Explained", 800, 0.46, 9.0),
    ], start_date="2026-01-01", end_date="2026-09-01", covered_through="2026-09-01")
    ranked = rank_topic_candidates([
        {"topic": "Why does sleep paralysis happen?", "score": 60},
        {"topic": "A new question about ocean tides", "score": 60},
    ], performance=performance, history=[])
    assert ranked[0]["topic"] == "Why does sleep paralysis happen?"
    assert ranked[0]["score_type"] == "ranking_heuristic_not_virality_prediction"


def test_claim_source_gate_flags_unsupported_numbers():
    script = {"scenes": [{"narration": "Researchers found a 37% increase in activity."}]}
    result = check_claim_sources(script)
    assert result["passed"] is False
    script["sources"] = ["https://example.org/paper"]
    assert check_claim_sources(script)["passed"] is True


def test_originality_gate_rejects_duplicate_title_or_body():
    script = {"title": "Why do dreams feel real?", "scenes": [{"caption": "Your brain predicts dreams"}]}
    history = [{"title": "Why do dreams feel real?", "body": "Your brain predicts dreams"}]
    assert check_originality(script, history)["passed"] is False
