"""Offline regression tests for the 2026-08-13 retention-first pass.

Each test here locks in one of the fixes that stopped the pipeline from
actively damaging its own distribution:

  1. Cadence can no longer be forced to 3/day while retention is failing.
  2. A below-gate platform is reported as a COMPLETION barrier, not a
     "push more volume" barrier.
  3. Barrier detection survives a health dict with no `gate_ratio`.
  4. Measured YouTube metrics are recovered from video_history when the live
     metrics store is empty, so the learning loop is never blind.
  5. The Meta cut floor is low enough that the completion gate is reachable.
  6. The repair stubs no longer fabricate numbers.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import algorithm_policy as policy  # noqa: E402
import strategy_engine  # noqa: E402
from continuity import retention_cadence_ceiling  # noqa: E402


class CadenceIsEarnedTests(unittest.TestCase):
    """A failing format must never be given more slots."""

    def test_critical_platform_caps_cadence_at_one(self):
        ceiling, reason = retention_cadence_ceiling(
            {"facebook_reels": {"status": "critical"}}
        )
        self.assertEqual(ceiling, 1)
        self.assertIn("critical", reason.lower())

    def test_strategy_decision_never_publishes_3_while_critical(self):
        decision = strategy_engine.decide_from_state(
            platform_health={
                "youtube_shorts": {"status": "below_gate", "gate_ratio": 0.94},
                "facebook_reels": {"status": "critical", "gate_ratio": 0.27},
            },
        )
        self.assertEqual(decision["barrier"], strategy_engine.BARRIER_COMPLETION)
        self.assertLessEqual(decision["cadence"], 1)


class BarrierHonestyTests(unittest.TestCase):
    def test_below_gate_is_a_completion_barrier_not_volume(self):
        """94% of the gate is still under the gate. Telling the operator to
        raise volume there is what produced 3 uploads/day of a losing format."""
        barrier, advice = strategy_engine._detect_barrier(
            {"youtube_shorts": {"status": "below_gate", "gate_ratio": 0.937}}, []
        )
        self.assertEqual(barrier, strategy_engine.BARRIER_COMPLETION)
        self.assertNotIn("increase cadence", advice.lower())

    def test_missing_gate_ratio_is_derived_not_assumed_healthy(self):
        """The old code defaulted a missing gate_ratio to 1.0, so a critical
        platform read as perfectly healthy."""
        barrier, _ = strategy_engine._detect_barrier(
            {"facebook_reels": {"avg_completion": 0.19, "gate": 0.72}}, []
        )
        self.assertEqual(barrier, strategy_engine.BARRIER_COMPLETION)

    def test_status_only_health_is_understood(self):
        barrier, _ = strategy_engine._detect_barrier(
            {"instagram_reels": {"status": "critical"}}, []
        )
        self.assertEqual(barrier, strategy_engine.BARRIER_COMPLETION)

    def test_no_data_platform_does_not_fake_a_completion_barrier(self):
        barrier, _ = strategy_engine._detect_barrier(
            {"facebook_reels": {"status": "no_data"}}, []
        )
        self.assertNotEqual(barrier, strategy_engine.BARRIER_COMPLETION)


class MetricsRecoveryTests(unittest.TestCase):
    """An empty metrics store must not erase numbers we already measured."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.history_path = os.path.join(self.tmp, "video_history.json")
        self.metrics_path = os.path.join(self.tmp, "platform_metrics.json")
        history = [
            {
                "content_fingerprint": "fp-old-measured",
                "title": "Why your body freezes",
                "topic": "freeze response",
                "posted_at": "2026-01-01T00:00:00+00:00",
                "average_view_percentage": 31.8,
                "views": 156,
                "average_view_duration_sec": 10,
                "duration_seconds": 33,
                "analytics_fetched_at": "2026-01-03T00:00:00+00:00",
            },
            {
                # No analytics yet -> must be ignored, not invented.
                "content_fingerprint": "fp-no-metrics",
                "title": "Unmeasured",
                "posted_at": "2026-01-02T00:00:00+00:00",
            },
        ]
        Path(self.history_path).write_text(json.dumps(history), encoding="utf-8")
        Path(self.metrics_path).write_text("{}", encoding="utf-8")

        self._saved = {
            "VIDEO_HISTORY_PATH": os.environ.get("VIDEO_HISTORY_PATH"),
            "PLATFORM_METRICS_PATH": os.environ.get("PLATFORM_METRICS_PATH"),
        }
        os.environ["VIDEO_HISTORY_PATH"] = self.history_path
        os.environ["PLATFORM_METRICS_PATH"] = self.metrics_path

        import importlib

        import platform_metrics

        self.platform_metrics = importlib.reload(platform_metrics)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import importlib

        import platform_metrics

        importlib.reload(platform_metrics)

    def test_measured_youtube_data_is_recovered_from_history(self):
        store = self.platform_metrics.load_metrics()
        self.assertIn("fp-old-measured", store)
        record = store["fp-old-measured"][policy.YOUTUBE]
        self.assertAlmostEqual(record["completion"], 0.318, places=3)
        self.assertEqual(record["views"], 156)

    def test_videos_without_analytics_are_not_invented(self):
        store = self.platform_metrics.load_metrics()
        self.assertNotIn("fp-no-metrics", store)

    def test_meta_platforms_stay_honest_about_having_no_data(self):
        """History never mirrors Meta insights, so they must not be faked."""
        store = self.platform_metrics.load_metrics()
        record = store["fp-old-measured"]
        self.assertNotIn(policy.FACEBOOK, record)
        self.assertNotIn(policy.INSTAGRAM, record)

    def test_live_records_are_never_overwritten_by_the_fallback(self):
        Path(self.metrics_path).write_text(
            json.dumps(
                {
                    "fp-old-measured": {
                        "age_hours": 500,
                        policy.YOUTUBE: {"completion": 0.9, "views": 99999},
                    }
                }
            ),
            encoding="utf-8",
        )
        store = self.platform_metrics.load_metrics()
        self.assertEqual(store["fp-old-measured"][policy.YOUTUBE]["views"], 99999)


class MetaCutIsReachableTests(unittest.TestCase):
    def test_meta_floor_allows_a_cut_that_can_clear_the_gate(self):
        """With 2.6-7.5s of measured watch time, an 18s floor made the 72% gate
        arithmetically unreachable. The floor must permit a short enough cut."""
        fb_floor = policy.duration_policy(policy.FACEBOOK)[0]
        ig_floor = policy.duration_policy(policy.INSTAGRAM)[0]
        shortest_meta_cut = max(fb_floor, ig_floor)
        best_measured_watch = 7.5
        self.assertLessEqual(shortest_meta_cut, 14.0)
        self.assertGreater(
            best_measured_watch / shortest_meta_cut,
            0.5,
            "the shortest permitted Meta cut should reach at least 50% completion",
        )

    def test_meta_cuts_stay_shorter_than_youtube(self):
        yt_ideal = policy.duration_policy(policy.YOUTUBE)[1]
        for platform in (policy.FACEBOOK, policy.INSTAGRAM):
            self.assertLess(policy.duration_policy(platform)[1], yt_ideal)

    def test_duration_tuples_stay_ordered(self):
        for platform in policy.PLATFORMS:
            floor, ideal, ceiling = policy.duration_policy(platform)
            self.assertLess(floor, ideal)
            self.assertLess(ideal, ceiling)


class StubsAreHonestTests(unittest.TestCase):
    def test_auto_repair_reports_not_implemented(self):
        from auto_repair_engine import run_auto_repair

        report = run_auto_repair(dry_run=True, limit=3)
        self.assertFalse(report["implemented"])
        self.assertIsNone(report["candidates_found"])

    def test_usa_repair_pack_writes_nothing(self):
        import us_audience_full_repair

        result = us_audience_full_repair.main()
        self.assertFalse(result["implemented"])
        self.assertEqual(result["videos"], [])


class OutlierDefenceTests(unittest.TestCase):
    """A couple of extreme videos must not decide the channel's strategy.

    This channel's real history contained averageViewPercentage = 293.6% (a
    195-view video whose replays counted) and 114.6% (a video with TWO views).
    Averaged in unweighted, they made a 0.63x channel report as 0.94x - and the
    retention index is what sets cadence and the quality gate.
    """

    def setUp(self):
        import importlib

        import growth_engine

        self.ge = importlib.reload(growth_engine)

    def _record(self, completion, views, seconds=36.0):
        return {
            "age_hours": 200,
            "duration_seconds": seconds,
            "meta_cut_seconds": 14.0,
            policy.YOUTUBE: {"completion": completion, "views": views},
        }

    def test_completion_on_almost_no_views_is_ignored(self):
        """114% retention on a 2-view video is one looping viewer."""
        score = self.ge._platform_score(self._record(1.146, 2), policy.YOUTUBE)
        self.assertIsNone(score)

    def test_completion_with_real_traffic_is_kept(self):
        score = self.ge._platform_score(self._record(0.35, 400), policy.YOUTUBE)
        self.assertIsNotNone(score)
        self.assertAlmostEqual(score, 0.35 / 0.5, places=3)

    def test_one_video_cannot_score_unbounded(self):
        """A replay-heavy video is good news, not a licence to skew the mean."""
        score = self.ge._platform_score(self._record(2.936, 195), policy.YOUTUBE)
        self.assertIsNotNone(score)
        self.assertLessEqual(score, self.ge.MAX_TRUSTED_SCORE)

    def test_channel_centre_is_robust_to_extremes(self):
        failing = [0.6] * 20
        self.assertAlmostEqual(self.ge._robust_centre(failing + [5.9, 2.3]), 0.6, places=3)

    def test_two_outliers_cannot_inflate_a_failing_channel(self):
        """The exact regression, with this channel's real numbers.

        22 videos: 20 failing plus the 293.6% and 114.6% entries. The unweighted
        mean read 0.937x the gate ("close but under - hold 2/day") while the
        honest centre was 0.634x. The mean never crossed 1.0, which is why this
        went unnoticed for weeks: it just quietly overstated the channel by
        ~50%, and 0.937 vs 0.634 is the difference between comfortable and one
        step from critical (0.6).
        """
        scores = [0.6] * 20 + [5.87, 2.29]
        naive_mean = sum(scores) / len(scores)
        robust = self.ge._robust_centre(scores)

        self.assertGreater(
            naive_mean, robust * 1.3,
            "the old mean should be materially inflated by the two extremes",
        )
        self.assertLess(robust, 1.0, "the robust centre must still read as failing")
        self.assertAlmostEqual(robust, 0.6, places=3)

    def test_health_ignores_low_traffic_completion(self):
        records = [self._record(0.30, 400) for _ in range(4)]
        records.append(self._record(2.90, 2))  # dead video, huge percentage
        health = self.ge._platform_health(records, policy.YOUTUBE)
        self.assertEqual(health["samples"], 4)
        self.assertAlmostEqual(health["avg_completion"], 0.30, places=2)
        self.assertNotEqual(health["status"], "healthy")


class RealCtrIsUnavailableTests(unittest.TestCase):
    """Guard against building a feature on data this channel does not have.

    `impressions` and `impressionsClickThroughRate` are requested by
    seo_analytics.fetch_actual_performance, but YouTube does not serve them for
    this channel, so 0 of 118 history entries carry a real CTR. Any "CTR-driven"
    ranking would therefore be scoring on an estimate while claiming to use
    measured data - exactly the kind of fabrication this repo removed from the
    repair stubs. This test documents the constraint so the idea is not
    reintroduced silently.
    """

    def test_ctr_metrics_are_still_requested_so_data_can_start_arriving(self):
        source = (ROOT / "src" / "seo_analytics.py").read_text(encoding="utf-8")
        self.assertIn("impressionsClickThroughRate", source)
        self.assertIn("impressions", source)

    def test_history_has_no_real_ctr_yet(self):
        """If this ever fails, real CTR has started arriving - at that point a
        measured-CTR title ranker becomes buildable. Until then, do not."""
        history = json.loads((ROOT / "data" / "video_history.json").read_text(encoding="utf-8"))
        with_ctr = [h for h in history
                    if isinstance(h, dict) and h.get("actual_ctr") is not None]
        self.assertEqual(
            with_ctr, [],
            "real CTR is now available - a measured-CTR ranker can replace "
            "predicted_ctr, which the lever analysis scored at only 0.148",
        )


if __name__ == "__main__":
    unittest.main()
