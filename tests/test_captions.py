"""Tests for the SRT caption track.

The channel showed 92.5% of views with no subtitles/CC. Burned-in word overlays already
existed, but the platform cannot read pixels — these tests cover the real track.
"""
from __future__ import annotations

import pytest

from src.media import _srt_timestamp, build_srt


def test_timestamp_format_uses_comma_decimal_separator():
    # SRT requires a comma, not a period. A period silently breaks some players.
    assert _srt_timestamp(0) == "00:00:00,000"
    assert _srt_timestamp(2.5) == "00:00:02,500"
    assert _srt_timestamp(61.25) == "00:01:01,250"
    assert _srt_timestamp(3661.004) == "01:01:01,004"


def test_negative_timestamp_raises():
    with pytest.raises(ValueError):
        _srt_timestamp(-1.0)


def test_cues_are_sequential_and_contiguous(tmp_path):
    target = tmp_path / "out.srt"
    build_srt([("First line here", 2.0), ("Second line here", 3.0)], target)
    content = target.read_text(encoding="utf-8")

    assert "1\n00:00:00,000 --> 00:00:02,000\nFirst line here" in content
    # The second cue must start exactly where the first ended, or captions drift.
    assert "2\n00:00:02,000 --> 00:00:05,000\nSecond line here" in content


def test_uses_real_scene_durations_so_captions_track_the_voiceover(tmp_path):
    target = tmp_path / "out.srt"
    build_srt([("a", 2.34), ("b", 3.11), ("c", 2.05)], target)
    content = target.read_text(encoding="utf-8")
    assert "00:00:02,340 --> 00:00:05,450" in content
    assert content.strip().endswith("c")


def test_whitespace_is_collapsed(tmp_path):
    target = tmp_path / "out.srt"
    build_srt([("  ragged   spacing\nhere  ", 2.0)], target)
    assert "ragged spacing here" in target.read_text(encoding="utf-8")


def test_empty_text_becomes_a_placeholder_not_an_empty_cue(tmp_path):
    target = tmp_path / "out.srt"
    build_srt([("   ", 2.0)], target)
    assert "..." in target.read_text(encoding="utf-8")


def test_no_cues_raises():
    with pytest.raises(ValueError):
        build_srt([], None)  # type: ignore[arg-type]


def test_non_positive_duration_raises(tmp_path):
    with pytest.raises(ValueError):
        build_srt([("text", 0.0)], tmp_path / "out.srt")


def test_caption_upload_is_non_fatal_when_file_missing(tmp_path):
    """The video is already public by then; a caption failure must not raise."""
    from src.youtube import upload_caption_track

    result = upload_caption_track(object(), "vid123", tmp_path / "absent.srt")
    assert "skipped" in result


def test_caption_upload_reports_failure_instead_of_raising(tmp_path):
    from src.youtube import upload_caption_track

    caption = tmp_path / "x.srt"
    caption.write_text("1\n00:00:00,000 --> 00:00:02,000\nhi\n", encoding="utf-8")

    class _Boom:
        def captions(self):
            raise RuntimeError("api exploded")

    result = upload_caption_track(_Boom(), "vid123", caption)
    assert result.startswith("failed:")
