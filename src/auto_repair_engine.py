"""Self-learning auto-repair - NOT IMPLEMENTED.

This module used to return a hardcoded report:

    {"candidates_found": 18, "repairs_generated": 3,
     "learned_patterns": {"best_starter": "Why Your", "cooldown_days": 7}}

Those numbers were invented. Nothing was ever read, learned, or repaired. Any
caller printing them produced a confident "18 videos need repair, learned
best='Why Your'" line that was pure fiction, which is worse than no feature at
all: it hides the fact that the capability does not exist.

The real repair capability lives in `scripts/deep_repair_2026.py` and
`src/full_platform_repair.py`, which talk to the actual platform APIs.

This shim now reports honestly instead of fabricating. Delete it once
`scripts/perfect_setup.py` no longer references it.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]

IMPLEMENTED = False

_NOTE = (
    "auto_repair_engine is a stub: it has no learning or repair logic. "
    "Use scripts/deep_repair_2026.py (real API repairs) instead."
)


def run_auto_repair(dry_run: bool = True, limit: int = 3) -> Dict[str, Any]:
    """Return an explicit not-implemented report. Never fabricates counts."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "implemented": False,
        "note": _NOTE,
        "dry_run": dry_run,
        "limit": limit,
        "candidates_found": None,
        "repairs_generated": None,
        "learned_patterns": {},
        "repairs": [],
    }
