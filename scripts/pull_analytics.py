#!/usr/bin/env python3
"""Pull real channel performance from the YouTube Analytics API into the local cache.

Why this exists: nothing in the pipeline ever read how a published video performed, so
every topic, hook and gate decision was made blind. This script is the input side of that
feedback loop. It is read-only against YouTube and writes one file:
data/performance_history.json, which src.guards.enforce reads to gate on measured
retention instead of a self-fulfilling structural score.

Run it on a schedule (daily is plenty; YouTube data lags ~1-2 days anyway), before the
publishing run.

Usage:
    python -m scripts.pull_analytics --dry-run
    python -m scripts.pull_analytics --lookback-days 90

Requires the upload run's YouTube credentials (YT_CLIENT_ID, YT_CLIENT_SECRET,
YT_REFRESH_TOKEN) AND the yt-analytics.readonly scope on that refresh token. A token
minted only for uploads will get a 403 here; the error message says exactly that.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics import (  # noqa: E402
    AnalyticsError,
    enrich_titles,
    fetch_channel_performance,
    load_performance,
    save_performance,
)

log = logging.getLogger("pull_analytics")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data"), help="Where the cache lives."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report, but do not write the cache.",
    )
    parser.add_argument("--no-titles", action="store_true", help="Skip the Data API title lookup.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    target = args.data_dir / "performance_history.json"

    try:
        performance = fetch_channel_performance(lookback_days=args.lookback_days)
        if not args.no_titles:
            performance = enrich_titles(performance)
    except AnalyticsError as exc:
        # Loud and specific: this is the whole point of the script, so a failure here is
        # never downgraded to "no data".
        log.error("Could not pull analytics: %s", exc)
        return 1

    print(f"videos with data : {performance.videos_with_data}")
    print(f"window           : {performance.start_date} .. {performance.covered_through}")
    median = performance.median_retention
    print(f"median retention : {median:.1%}" if median is not None else "median retention : n/a (not enough videos)")

    if performance.videos:
        print("\ntop by retention:")
        for video in performance.top_by_retention(5):
            print(f"  {video.retention:6.1%}  {video.views:6d} views  {video.title[:58]!r}")
        print("\nbottom by retention:")
        for video in performance.bottom_by_retention(5):
            print(f"  {video.retention:6.1%}  {video.views:6d} views  {video.title[:58]!r}")

    if args.dry_run:
        previous = load_performance(target) if target.exists() else None
        if previous is not None:
            print(f"\n[dry-run] existing cache has {previous.videos_with_data} videos; not overwriting.")
        else:
            print("\n[dry-run] no cache written.")
        return 0

    save_performance(target, performance)
    print(f"\nwrote {performance.videos_with_data} videos to the performance cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
