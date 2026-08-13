"""USA Repair Pack generator - NOT IMPLEMENTED.

This module used to write `output/USA_Repair_2026_07_29/repaired_metadata.json`
containing 23 entirely fabricated videos:

    {"youtube_video_id": "vid_repair_1",
     "original_title": "Original Title 1",
     "new_title": "Why Your Body Does This Repair 1", ...}

No real video was ever read and no metadata was ever repaired. A downstream
uploader or report consuming that file would act on placeholder IDs, and the
setup script reported it as a success ("USA Repair Pack generated").

Real catalog repair lives in `scripts/deep_repair_2026.py` and
`src/full_platform_repair.py`, which read the actual channel and write a ledger.

This shim now refuses to write fake data. Delete it once
`scripts/perfect_setup.py` no longer references it.
"""

from typing import Any, Dict

IMPLEMENTED = False

_NOTE = (
    "us_audience_full_repair is a stub: it previously wrote 23 placeholder "
    "videos. Use scripts/deep_repair_2026.py for real catalog repair."
)


def main() -> Dict[str, Any]:
    """Report honestly instead of writing fabricated repair metadata."""
    print(f"SKIPPED: {_NOTE}")
    return {"implemented": False, "note": _NOTE, "total_repairs": None, "videos": []}


if __name__ == "__main__":
    main()
