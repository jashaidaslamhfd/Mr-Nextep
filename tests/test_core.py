from __future__ import annotations

from src.config import Settings
from src.content import fallback


def test_fallback_has_eight_scenes():
    assert len(fallback('Why do dreams feel real?')['scenes']) == 8


def test_dry_run_config_is_valid():
    settings = Settings(dry_run=True)
    assert settings.check_config() == []


def test_output_is_vertical_policy():
    script = fallback('Why does déjà vu happen?')
    assert all(scene['narration'] for scene in script['scenes'])
    assert script['title']
