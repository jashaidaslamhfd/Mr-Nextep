from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from config import Settings
from content import fallback

def test_fallback_has_eight_scenes():
    assert len(fallback('Why do dreams feel real?')['scenes']) == 8

def test_dry_run_config_is_valid():
    settings = Settings(dry_run=True)
    assert settings.validate() == []

def test_output_is_vertical_policy():
    script = fallback('Why does déjà vu happen?')
    assert all(scene['narration'] for scene in script['scenes'])
    assert script['title']
