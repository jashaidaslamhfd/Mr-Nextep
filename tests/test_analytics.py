"""Tests for the analytics feedback loop.

The central property under test is honesty: with too little data the retention check must
report itself as ungrounded and refuse to block, and with real data it must reject on
measured evidence. The old retention_proxy failed exactly this property — it always
returned a passing number regardless of what the channel actually did.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from src.analytics import (
    MIN_VIDEOS_FOR_BASELINE,
    AnalyticsError,
    ChannelPerformance,
    MissingAnalyticsScope,
    VideoPerformance,
    evaluate_retention,
    fetch_channel_performance,
    load_performance,
    save_performance,
    similar_past_videos,
)


def perf(**kwargs) -> VideoPerformance:
    base = {
        "video_id": "v1",
        "title": "Why Babies Grab Your Finger",
        "views": 600,
        "average_view_percentage": 0.30,
        "average_view_duration_seconds": 6.0,
    }
    base.update(kwargs)
    return VideoPerformance(**base)


def channel(retentions: list[float], titles: list[str] | None = None) -> ChannelPerformance:
    titles = titles or [f"Science Fact Number {i}" for i in range(len(retentions))]
    return ChannelPerformance(
        videos=[
            perf(video_id=f"v{i}", title=titles[i], average_view_percentage=r)
            for i, r in enumerate(retentions)
        ],
        start_date="2026-06-14",
        end_date="2026-09-11",
        covered_through="2026-09-11",
    )


# --- the honesty property -------------------------------------------------------------


def test_median_retention_is_none_below_baseline_threshold():
    """No fabricated default. Too little data must read as None, not as a number."""
    thin = channel([0.30] * (MIN_VIDEOS_FOR_BASELINE - 1))
    assert thin.median_retention is None
    assert thin.has_baseline is False


def test_verdict_is_ungrounded_and_non_blocking_without_baseline():
    thin = channel([0.30] * 3)
    verdict = evaluate_retention({"title": "Why Do Your Fingers Wrinkle"}, thin)
    assert verdict.grounded is False
    assert verdict.passed is True
    assert "no retention baseline" in verdict.reason


def test_verdict_becomes_grounded_once_enough_data_exists():
    full = channel([0.30] * MIN_VIDEOS_FOR_BASELINE)
    verdict = evaluate_retention({"title": "A Totally Unrelated Subject Here"}, full)
    assert verdict.grounded is True
    assert verdict.channel_median == pytest.approx(0.30)


# --- rejecting on real evidence -------------------------------------------------------


def test_rejects_when_similar_past_videos_underperformed():
    """The whole point: a shape that already flopped must not be published again."""
    titles = ["Why Does Apple Acquire Brain Imaging"] + [f"Unrelated Topic {i}" for i in range(8)]
    retentions = [0.05] + [0.40] * 8
    performance = channel(retentions, titles)

    verdict = evaluate_retention({"title": "Why Does Apple Acquire Brain Imaging Firm"}, performance)
    assert verdict.grounded is True
    assert verdict.passed is False
    assert "below the" in verdict.reason
    assert "Apple" in verdict.reason


def test_passes_when_similar_past_videos_performed_well():
    titles = ["Why Babies Grab Your Finger"] + [f"Unrelated Topic {i}" for i in range(8)]
    retentions = [0.45] + [0.30] * 8
    performance = channel(retentions, titles)

    verdict = evaluate_retention({"title": "Why Babies Grab Your Finger So Hard"}, performance)
    assert verdict.passed is True
    assert verdict.neighbours >= 1


def test_no_similar_history_passes_but_stays_grounded():
    performance = channel([0.30] * MIN_VIDEOS_FOR_BASELINE)
    verdict = evaluate_retention({"title": "Zebra Quantum Tunnelling Explained"}, performance)
    assert verdict.grounded is True
    assert verdict.passed is True
    assert verdict.neighbours == 0


def test_similar_past_videos_matches_on_shared_vocabulary():
    performance = channel(
        [0.3, 0.3],
        ["Why Do Your Fingers Wrinkle in Water", "Completely Different Subject Matter"],
    )
    matches = similar_past_videos("Why Do Fingers Wrinkle Underwater", performance)
    assert [m.title for m in matches] == ["Why Do Your Fingers Wrinkle in Water"]


# --- cache round-trip and loud failure ------------------------------------------------


def test_performance_cache_round_trip(tmp_path):
    original = channel([0.31, 0.42])
    target = tmp_path / "performance_history.json"
    save_performance(target, original)
    restored = load_performance(target)
    assert restored.videos_with_data == 2
    assert [v.title for v in restored.videos] == [v.title for v in original.videos]
    assert restored.covered_through == "2026-09-11"


def test_missing_cache_is_empty_not_an_error(tmp_path):
    empty = load_performance(tmp_path / "nope.json")
    assert empty.videos_with_data == 0
    assert empty.median_retention is None


def test_corrupt_cache_raises_rather_than_reading_as_no_data(tmp_path):
    """A broken feedback loop must not look identical to an empty one."""
    bad = tmp_path / "performance_history.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(AnalyticsError):
        load_performance(bad)


def test_malformed_row_raises(tmp_path):
    bad = tmp_path / "performance_history.json"
    bad.write_text(json.dumps({"videos": [{"title": "no id or views"}]}), encoding="utf-8")
    with pytest.raises(AnalyticsError):
        load_performance(bad)


# --- API layer ------------------------------------------------------------------------


class _FakeReports:
    def __init__(self, rows):
        self._rows = rows
        self.captured = {}

    def query(self, **kwargs):
        self.captured = kwargs
        rows = self._rows

        class _Req:
            def execute(self):
                return {"rows": rows}

        return _Req()


class _FakeService:
    def __init__(self, rows):
        self._reports = _FakeReports(rows)

    def reports(self):
        return self._reports


def test_fetch_parses_rows_and_converts_percentage():
    service = _FakeService([["abc123", 826, 22.2, 5.4], ["def456", 619, 41.0, 8.1]])
    result = fetch_channel_performance(
        lookback_days=28, service=service, today=date(2026, 9, 12)
    )
    assert result.videos_with_data == 2
    # YouTube reports 22.2 (percent); we store 0.222 (fraction).
    assert result.videos[0].average_view_percentage == pytest.approx(0.222)
    assert result.videos[0].views == 826
    # End date backs off one day from today because YouTube data lags.
    assert result.covered_through == "2026-09-11"
    assert service.reports().captured["startDate"] == "2026-08-14"


def test_fetch_raises_on_unexpected_row_shape():
    service = _FakeService([["abc123", 826]])
    with pytest.raises(AnalyticsError):
        fetch_channel_performance(service=service, today=date(2026, 9, 12))


def test_403_is_reported_as_a_scope_problem_not_a_transient_error():
    from googleapiclient.errors import HttpError

    class _Resp:
        status = 403
        reason = "forbidden"

    class _Failing:
        def reports(self):
            class _R:
                def query(self, **kwargs):
                    class _Req:
                        def execute(self):
                            raise HttpError(_Resp(), b"forbidden")

                    return _Req()

            return _R()

    with pytest.raises(MissingAnalyticsScope) as excinfo:
        fetch_channel_performance(service=_Failing(), today=date(2026, 9, 12))
    assert "yt-analytics.readonly" in str(excinfo.value)
