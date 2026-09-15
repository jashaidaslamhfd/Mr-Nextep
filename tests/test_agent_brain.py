from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from src.agent_brain import AgentBrain
from src.utils import SHORTS_TITLE_MAX_CHARS, validate_short_title


def test_agent_brain_initialization(tmp_path):
    mem_file = tmp_path / "memory.json"
    brain = AgentBrain(memory_file=mem_file)
    assert brain.memory["version"] == "3.0.0"
    assert "strategy" in brain.memory
    assert brain.memory["strategy"]["max_title_chars"] == 48


def test_agent_brain_reason_title_handles_malformed_headlines():
    brain = AgentBrain()
    bad_headline = "Why does apple acquires brain imaging firm for health and accessibility"
    title = brain.reason_title(bad_headline)
    assert len(title) <= SHORTS_TITLE_MAX_CHARS
    assert validate_short_title(title) == title


def test_agent_brain_generate_candidate_hooks_ranking():
    brain = AgentBrain()
    hooks = brain.generate_candidate_hooks("Why does your body jolt as you fall asleep?", count=3)
    assert len(hooks) >= 1
    for h in hooks:
        assert "title" in h
        assert "predicted_ctr" in h
        assert len(h["title"]) <= SHORTS_TITLE_MAX_CHARS
        assert validate_short_title(h["title"]) == h["title"]
    # Verify ranking (highest CTR first)
    if len(hooks) > 1:
        assert hooks[0]["predicted_ctr"] >= hooks[1]["predicted_ctr"]


def test_agent_brain_predict_retention():
    brain = AgentBrain()
    valid_script = {
        "title": "Why Does Your Body Jolt?",
        "scenes": [
            {"caption": "Your body suddenly jolts.", "narration": "You are drifting to sleep when your entire body violently jolts awake."},
            {"caption": "A terrifying sensation.", "narration": "Your sensory neurons misinterpret your relaxing muscles as free fall."},
            {"caption": "Survival reflexes take over.", "narration": "An ancient brainstem circuit seizes control before awareness reactivates."},
            {"caption": "The hypnic spasm triggers.", "narration": "Neuroscientists classify this sudden misfire as a hypnic jerk."},
            {"caption": "Your brain panics.", "narration": "To rescue you from imaginary falling, motor cortex fires full impulse."},
            {"caption": "It is purely biological.", "narration": "Nothing about this reflex is dangerous, but your subconscious panics."},
            {"caption": "A primitive loop closing.", "narration": "You literally caught your nervous system switching operating states."},
            {"caption": "Which is why it happens.", "narration": "Which is why your body jolts the exact moment sleep begins."}
        ]
    }
    verdict = brain.predict_retention(valid_script)
    assert verdict["passed"] is True
    assert verdict["overall_score"] >= 0.75
    assert "hook_potency" in verdict
    assert "pacing_velocity" in verdict
    assert "loopback_seamlessness" in verdict


def test_agent_brain_enrich_visual_prompts():
    brain = AgentBrain()
    script = {
        "title": "Why Does Your Brain Freeze Under Stress?",
        "scenes": [
            {"caption": "Your brain instantly freezes.", "narration": "Under sudden extreme stress your prefrontal cortex shuts down completely."}
        ]
    }
    enriched = brain.enrich_visual_prompts(script)
    assert "visual_prompt" in enriched["scenes"][0]
    assert "camera_motion" in enriched["scenes"][0]
    assert "9:16 vertical" in enriched["scenes"][0]["visual_prompt"]


def test_agent_brain_scout_trending_topics():
    brain = AgentBrain()
    topics = brain.scout_trending_topics(count=3)
    assert len(topics) == 3
    for t in topics:
        assert len(t) <= SHORTS_TITLE_MAX_CHARS
        assert validate_short_title(t) == t


def test_agent_brain_sense_and_learn_cycle(tmp_path):
    mem_file = tmp_path / "memory.json"
    brain = AgentBrain(memory_file=mem_file)
    mock_perf = MagicMock()
    mock_perf.videos = [
        {"title": "Why Your Brain Freezes Under Stress #Shorts", "views": 1500},
        {"title": "What Your Brain Does While You Sleep #Shorts", "views": 2200}
    ]
    signals = brain.sense(mock_perf)
    assert signals["sample_size"] == 2
    assert signals["avg_view_rate"] == 1850.0

    brain.learn({
        "title": "The Dark Science Of Sleep Paralysis #Shorts",
        "retention_verdict": {"passed": True}
    })
    assert brain.memory["total_cycles"] == 1
    assert "The Dark Science Of Sleep Paralysis" in brain.memory["winning_hooks"]
