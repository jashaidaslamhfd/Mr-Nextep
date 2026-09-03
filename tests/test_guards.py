from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from content import fallback
from guards import enforce, is_duplicate, retention_proxy

def test_duplicate_is_rejected():
    script = fallback('Why does déjà vu feel real?')
    assert is_duplicate(script, [{'fingerprint': __import__('guards').fingerprint(script)}])

def test_retention_proxy_meets_gate_for_short_format():
    script = fallback('Why does déjà vu feel real?')
    assert retention_proxy(script, 20.0) >= 0.70
    assert enforce(script, 20.0, {})['retention_proxy'] >= 0.70
