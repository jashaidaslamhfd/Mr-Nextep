"""Real channel performance data, pulled from the YouTube Analytics API.

Why this module exists
----------------------
Before this, nothing in the pipeline ever read how a published video performed. Topic
choice, hook wording and the retention gate were all decided from the script's own shape,
so the channel published ~100 videos without a single decision being informed by the
result of any of them.

`guards.retention_proxy` was the clearest symptom: it scored scene count, duration and
caption word counts — all three of which the generation prompt already forces — then
capped at 0.90 against a 0.70 target. It could not return a failing score for any script
the generator was capable of producing, so it never rejected anything while appearing to
be a quality gate.

This module supplies the missing input. It is deliberately read-only and side-effect free
apart from writing its own cache, so it can be run on a schedule independently of a
publishing run.

Credentials: the same YouTube OAuth client as an upload run (YT_CLIENT_ID,
YT_CLIENT_SECRET, YT_REFRESH_TOKEN). The Analytics API additionally requires the
`yt-analytics.readonly` scope on the refresh token; `MissingAnalyticsScope` is raised with
that instruction rather than a bare 403, because a scope problem is a setup step and not a
transient failure worth retrying.
"""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# A Short is ~20s. YouTube reports averageViewPercentage per video; the channel median is
# a far more honest target than a hardcoded constant, because it adapts as the channel
# improves instead of staying true forever.
DEFAULT_LOOKBACK_DAYS = 90

# Below this many videos with real data, a channel median is noise rather than a baseline.
MIN_VIDEOS_FOR_BASELINE = 8

# How far under the channel median a script's nearest historical neighbours may sit before
# the script is rejected. 0.80 = "no worse than 20% below what this channel normally does".
NEIGHBOUR_TOLERANCE = 0.80


class AnalyticsError(RuntimeError):
    """Analytics could not be read. Callers decide whether that is fatal."""


class MissingAnalyticsScope(AnalyticsError):
    """The refresh token lacks yt-analytics.readonly."""


@dataclass(frozen=True)
class VideoPerformance:
    """One published video's real measured performance.

    Every field comes from the API. There are no defaults that invent a value: a video
    YouTube has no data for is absent from the list rather than present with zeros, so
    "no data yet" can never be mistaken for "performed badly".
    """

    video_id: str
    title: str
    views: int
    average_view_percentage: float  # 0.0-1.0, YouTube's averageViewPercentage / 100
    average_view_duration_seconds: float

    @property
    def retention(self) -> float:
        return self.average_view_percentage


@dataclass
class ChannelPerformance:
    """The channel's measured behaviour over a window, plus its own coverage.

    `covered_through` and `videos_with_data` are part of the payload on purpose. A caller
    that wants to gate on retention has to be able to tell "the channel retains 31%" from
    "we have data for 3 videos", and those two look identical if you only return a number.
    """

    videos: list[VideoPerformance] = field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    covered_through: str = ""

    @property
    def videos_with_data(self) -> int:
        return len(self.videos)

    @property
    def has_baseline(self) -> bool:
        return self.videos_with_data >= MIN_VIDEOS_FOR_BASELINE

    @property
    def median_retention(self) -> float | None:
        """The channel's median retention, or None when there is not enough data.

        None is a real answer and callers must handle it. Returning a fabricated default
        here is exactly the mistake retention_proxy made.
        """
        if not self.has_baseline:
            return None
        return statistics.median(v.retention for v in self.videos)

    @property
    def median_views(self) -> float | None:
        if not self.has_baseline:
            return None
        return statistics.median(float(v.views) for v in self.videos)

    def top_by_retention(self, limit: int = 10) -> list[VideoPerformance]:
        return sorted(self.videos, key=lambda v: v.retention, reverse=True)[:limit]

    def bottom_by_retention(self, limit: int = 10) -> list[VideoPerformance]:
        return sorted(self.videos, key=lambda v: v.retention)[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "covered_through": self.covered_through,
            "videos_with_data": self.videos_with_data,
            "median_retention": self.median_retention,
            "median_views": self.median_views,
            "videos": [
                {
                    "video_id": v.video_id,
                    "title": v.title,
                    "views": v.views,
                    "average_view_percentage": v.average_view_percentage,
                    "average_view_duration_seconds": v.average_view_duration_seconds,
                }
                for v in self.videos
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChannelPerformance:
        rows = payload.get("videos")
        if not isinstance(rows, list):
            raise AnalyticsError("performance cache is missing its 'videos' list")
        videos: list[VideoPerformance] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                videos.append(
                    VideoPerformance(
                        video_id=str(row["video_id"]),
                        title=str(row.get("title", "")),
                        views=int(row["views"]),
                        average_view_percentage=float(row["average_view_percentage"]),
                        average_view_duration_seconds=float(
                            row.get("average_view_duration_seconds", 0.0)
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                # Loud, not silent: a malformed row means the cache is not what we think.
                raise AnalyticsError(f"malformed performance row {row!r}: {exc}") from exc
        return cls(
            videos=videos,
            start_date=str(payload.get("start_date", "")),
            end_date=str(payload.get("end_date", "")),
            covered_through=str(payload.get("covered_through", "")),
        )


def load_performance(path: Path) -> ChannelPerformance:
    """Read the cached performance file.

    A missing file yields an empty ChannelPerformance — that is a legitimate state
    (analytics have never been pulled). A *corrupt* file raises, because silently
    treating unreadable data as "no data" is how a broken feedback loop goes unnoticed.
    """
    if not path.exists():
        log.info("No performance cache at %s; running without real retention data.", path)
        return ChannelPerformance()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalyticsError(f"cannot read performance cache {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AnalyticsError(f"performance cache {path} is not a JSON object")
    return ChannelPerformance.from_dict(payload)


def save_performance(path: Path, performance: ChannelPerformance) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(performance.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _analytics_service() -> Any:
    """Build the YouTube Analytics client from the upload run's credentials."""
    from googleapiclient.discovery import build

    from .youtube import _load_credentials_from_env

    return build("youtubeAnalytics", "v2", credentials=_load_credentials_from_env())


def fetch_channel_performance(
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    service: Any | None = None,
    today: date | None = None,
) -> ChannelPerformance:
    """Pull real per-video retention and views from the YouTube Analytics API.

    `service` and `today` are injectable so this is testable without network access or a
    frozen clock.
    """
    from googleapiclient.errors import HttpError

    service = service or _analytics_service()
    today = today or date.today()
    # YouTube analytics lag by a day or two; asking for today returns a short window.
    end = today - timedelta(days=1)
    start = end - timedelta(days=lookback_days)

    try:
        response = (
            service.reports()
            .query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics="views,averageViewPercentage,averageViewDuration",
                dimensions="video",
                sort="-views",
                maxResults=200,
            )
            .execute()
        )
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status == 403:
            raise MissingAnalyticsScope(
                "YouTube Analytics returned 403. The refresh token most likely lacks the "
                "https://www.googleapis.com/auth/yt-analytics.readonly scope — re-run the "
                "OAuth consent with that scope added and replace YT_REFRESH_TOKEN."
            ) from exc
        raise AnalyticsError(f"YouTube Analytics query failed: {exc}") from exc

    rows = response.get("rows") or []
    if not rows:
        log.warning(
            "YouTube Analytics returned no rows for %s..%s. The channel may have no "
            "qualifying views in the window.", start, end
        )

    videos: list[VideoPerformance] = []
    for row in rows:
        # Row order follows the dimensions+metrics request: video, views, avgViewPct, avgViewDur
        if not isinstance(row, list) or len(row) < 4:
            raise AnalyticsError(f"unexpected analytics row shape: {row!r}")
        video_id = str(row[0])
        videos.append(
            VideoPerformance(
                video_id=video_id,
                title="",  # filled by enrich_titles; Analytics API does not return titles
                views=int(row[1] or 0),
                average_view_percentage=float(row[2] or 0.0) / 100.0,
                average_view_duration_seconds=float(row[3] or 0.0),
            )
        )

    return ChannelPerformance(
        videos=videos,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        covered_through=end.isoformat(),
    )


def enrich_titles(performance: ChannelPerformance, data_service: Any | None = None) -> ChannelPerformance:
    """Attach real titles to the performance rows via the YouTube Data API.

    Titles are what make the data actionable — "this hook shape retained 41%" needs the
    hook. Kept separate from fetch_channel_performance because it is a different API.
    """
    if not performance.videos:
        return performance

    if data_service is None:
        from googleapiclient.discovery import build

        from .youtube import _load_credentials_from_env

        data_service = build("youtube", "v3", credentials=_load_credentials_from_env())

    titles: dict[str, str] = {}
    ids = [v.video_id for v in performance.videos]
    for batch_start in range(0, len(ids), 50):
        batch = ids[batch_start : batch_start + 50]
        response = (
            data_service.videos().list(part="snippet", id=",".join(batch)).execute()
        )
        for item in response.get("items") or []:
            titles[str(item.get("id"))] = str(
                (item.get("snippet") or {}).get("title", "")
            )

    performance.videos = [
        VideoPerformance(
            video_id=v.video_id,
            title=titles.get(v.video_id, v.title),
            views=v.views,
            average_view_percentage=v.average_view_percentage,
            average_view_duration_seconds=v.average_view_duration_seconds,
        )
        for v in performance.videos
    ]
    return performance


# --- Feeding the data back into content decisions ------------------------------------


def _tokens(text: str) -> set[str]:
    return {w for w in "".join(c if c.isalnum() else " " for c in text.lower()).split() if len(w) > 2}


def similar_past_videos(
    title: str, performance: ChannelPerformance, limit: int = 5, min_overlap: float = 0.20
) -> list[VideoPerformance]:
    """Past videos whose titles share vocabulary with a candidate title.

    This is the join between a script we are about to publish and what actually happened
    when we published something like it.
    """
    candidate = _tokens(title)
    if not candidate:
        return []
    scored: list[tuple[float, VideoPerformance]] = []
    for video in performance.videos:
        if not video.title:
            continue
        other = _tokens(video.title)
        if not other:
            continue
        overlap = len(candidate & other) / len(candidate | other)
        if overlap >= min_overlap:
            scored.append((overlap, video))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [video for _, video in scored[:limit]]


@dataclass(frozen=True)
class RetentionVerdict:
    """The outcome of checking a script against real performance.

    `grounded` is the field that matters: False means this verdict is structural only and
    carries no evidence about retention. A caller must not report an ungrounded verdict as
    a retention measurement.
    """

    grounded: bool
    passed: bool
    reason: str
    channel_median: float | None = None
    neighbour_median: float | None = None
    neighbours: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.grounded,
            "passed": self.passed,
            "reason": self.reason,
            "channel_median_retention": self.channel_median,
            "neighbour_median_retention": self.neighbour_median,
            "neighbours_considered": self.neighbours,
        }


def evaluate_retention(
    script: dict[str, Any],
    performance: ChannelPerformance,
    tolerance: float = NEIGHBOUR_TOLERANCE,
) -> RetentionVerdict:
    """Judge a script against what this channel actually retains.

    Returns an ungrounded pass when there is no baseline yet. That is the honest answer:
    with no data, this check has nothing to say, and it says so instead of manufacturing a
    score the way retention_proxy did.
    """
    median = performance.median_retention
    if median is None:
        return RetentionVerdict(
            grounded=False,
            passed=True,
            reason=(
                f"no retention baseline yet ({performance.videos_with_data} videos with "
                f"data, {MIN_VIDEOS_FOR_BASELINE} needed); structural checks only"
            ),
        )

    title = str(script.get("title", ""))
    neighbours = similar_past_videos(title, performance)
    if not neighbours:
        return RetentionVerdict(
            grounded=True,
            passed=True,
            reason=f"no similar past video; channel median retention is {median:.0%}",
            channel_median=median,
            neighbours=0,
        )

    neighbour_median = statistics.median(v.retention for v in neighbours)
    floor = median * tolerance
    if neighbour_median < floor:
        worst = min(neighbours, key=lambda v: v.retention)
        return RetentionVerdict(
            grounded=True,
            passed=False,
            reason=(
                f"{len(neighbours)} similar past video(s) retained {neighbour_median:.0%}, "
                f"below the {floor:.0%} floor ({tolerance:.0%} of the {median:.0%} channel "
                f"median). Worst: {worst.title!r} at {worst.retention:.0%}"
            ),
            channel_median=median,
            neighbour_median=neighbour_median,
            neighbours=len(neighbours),
        )

    return RetentionVerdict(
        grounded=True,
        passed=True,
        reason=(
            f"{len(neighbours)} similar past video(s) retained {neighbour_median:.0%}, "
            f"at or above the {floor:.0%} floor"
        ),
        channel_median=median,
        neighbour_median=neighbour_median,
        neighbours=len(neighbours),
    )
