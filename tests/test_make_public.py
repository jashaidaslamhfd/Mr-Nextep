from __future__ import annotations

import pytest

from scripts.make_public import validate_video_ids


def test_validate_video_ids_accepts_and_deduplicates_explicit_ids() -> None:
    assert validate_video_ids(["abcdefghijk", "abcdefghijk", "ABCDEFGHIJK"]) == [
        "abcdefghijk",
        "ABCDEFGHIJK",
    ]


@pytest.mark.parametrize("ids", [[], [""], ["short"], ["abcdefghij!"], ["validID12345", "bad"]])
def test_validate_video_ids_rejects_invalid_input(ids: list[str]) -> None:
    with pytest.raises(ValueError):
        validate_video_ids(ids)
