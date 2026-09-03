from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from content import fallback
from seo import build_packages

def test_platform_seo_is_separate():
    packages = build_packages(fallback('Why does memory feel familiar?'))
    assert set(packages) == {'youtube', 'facebook', 'instagram'}
    assert packages['youtube']['tags']
    assert '#shorts' in packages['youtube']['description']
    assert '#reels' in packages['instagram']['caption']
    assert packages['facebook']['description'] != packages['youtube']['description']
