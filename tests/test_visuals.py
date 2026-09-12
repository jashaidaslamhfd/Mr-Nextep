from __future__ import annotations

import pytest

from src.visuals import MAX_CLIP_BYTES, _write_bounded_download


class _Response:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    def iter_content(self, chunk_size: int):
        return iter(self.chunks)


def test_bounded_download_writes_response_within_limit(tmp_path):
    destination = tmp_path / "clip.source"
    _write_bounded_download(_Response([b"abc", b"def"]), destination, 6)
    assert destination.read_bytes() == b"abcdef"


def test_bounded_download_rejects_response_without_content_length(tmp_path):
    destination = tmp_path / "clip.source"
    with pytest.raises(ValueError, match="byte limit"):
        _write_bounded_download(_Response([b"a" * (MAX_CLIP_BYTES + 1)]), destination, MAX_CLIP_BYTES)
    assert not destination.exists() or destination.stat().st_size <= MAX_CLIP_BYTES
