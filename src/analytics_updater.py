"""
src/analytics_updater.py

Daily learning entry point. Run on its OWN schedule (not inside the
generation pipeline) — platform metrics need ~24-48h after upload before they
mean anything.

WHY THIS FILE DOES MORE THAN ITS NAME SUGGESTS
----------------------------------------------
The new cross-platform learning loop was written as a separate workflow
(docs/workflow_updates/growth_loop.yml). Installing that file requires
GitHub's `workflows` permission, which the automation maintaining this repo
does not hold — so a new workflow cannot be added here.

Rather than leave the most valuable part of the system waiting on a manual
step, the loop hangs off THIS module, which the already-deployed
`.github/workflows/analytics.yml` calls every day at 09:20 UTC with exactly
the right secrets and a `data/` commit step. That workflow was already:

  * scheduled daily, before the day's first generation run
  * given GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / REFRESH_TOKEN
  * given FB_ACCESS_TOKEN
  * committing whatever lands in data/

...which is precisely what the learning loop needs. So the work runs there.

Three stages, each independent — a failure in one never blocks the others,
because partial learning beats none:

  1. YouTube Analytics -> data/video_history.json     (the original job)
  2. All three platforms -> data/platform_metrics.json
  3. Learn from it     -> data/growth_state.json + docs/GROWTH_REPORT.md

Stage 3 is what the generation pipeline reads on its next run to pick slots,
topic pillars, hook frames and cadence.

REQUIRED (each degrades gracefully if absent):
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / REFRESH_TOKEN
        The refresh token additionally needs the `yt-analytics.readonly`
        scope. Tokens minted before that feature was added must be re-issued
        once — a scope cannot be added to an existing token.
    FB_ACCESS_TOKEN (or FACEBOOK_ACCESS_TOKEN) + INSTAGRAM_USER_ID
        Needs `read_insights`, `pages_read_engagement`,
        `instagram_manage_insights`.

Usage:
    python src/analytics_updater.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _run_youtube_history_sync() -> dict:
    """Stage 1: real YouTube numbers into video_history.json (original job)."""
    from seo_analytics import update_history_with_real_metrics
    result = update_history_with_real_metrics(min_hours_old=24)
    logger.info("YouTube history sync: %s", result)
    return result


def _run_cross_platform_collection() -> dict:
    """Stage 2: normalise YouTube + Facebook + Instagram into one store.

    This is the piece that makes platforms comparable: each one's average
    watch time is divided by the length of the cut THAT platform received, so
    a 26s Reel and a 36s Short are judged on the same scale.
    """
    from platform_metrics import collect
    result = collect(
        min_hours_old=int(os.environ.get("METRICS_MIN_HOURS", "24")),
        refresh_hours=int(os.environ.get("METRICS_REFRESH_HOURS", "20")),
    )
    logger.info("Cross-platform metrics: %s", result.get("stats"))
    return result


def _run_growth_analysis() -> dict:
    """Stage 3: learn, then write the state the pipeline reads next run."""
    from growth_engine import analyse
    state = analyse()
    logger.info(
        "Growth state: %d mature videos, cadence=%s/day, best slot=%s",
        state.get("sample_size", 0),
        state.get("recommended_cadence"),
        state.get("best_slot") or "not enough data",
    )
    for alert in state.get("alerts", []):
        level = logging.ERROR if alert.get("level") == "error" else logging.WARNING
        logger.log(level, "ALERT: %s", alert.get("message"))
    return state


def _write_report(state: dict) -> None:
    """Human-readable verdict, committed with the state by the workflow."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        from growth_report import build_report

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(root, "docs", "GROWTH_REPORT.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(build_report(state))
        logger.info("Wrote docs/GROWTH_REPORT.md")
    except Exception as exc:  # noqa: BLE001 - the report is a convenience
        logger.warning("Could not write the growth report: %s", exc)


if __name__ == "__main__":
    exit_code = 0

    # ---- Stage 1: YouTube history (the original responsibility) ----------
    yt_result = {}
    try:
        yt_result = _run_youtube_history_sync()
    except Exception as exc:  # noqa: BLE001
        logger.error("YouTube history sync failed: %s", exc)
        yt_result = {"failed": 1}

    if yt_result.get("api_disabled"):
        # A Google Cloud console setting, not a code or token problem. Say so
        # plainly instead of sending the next debugging round down the wrong
        # path, as an earlier version of this message did.
        logger.error(
            "YouTube Analytics API is DISABLED for this Google Cloud project. "
            "Enable it at console.cloud.google.com -> APIs & Services, wait a "
            "minute, then re-run. No code change can work around this."
        )
        exit_code = 2
    elif yt_result.get("failed") and not yt_result.get("updated"):
        # Every per-video error is caught and logged as a warning, so this
        # script used to exit 0 while all 17 videos failed with invalid_scope
        # — four consecutive green ticks over an empty history file. A broken
        # feedback loop must be visible.
        logger.error(
            "Every YouTube analytics fetch failed (%s videos) and nothing was "
            "written. Failing loudly so this is not mistaken for a healthy run.",
            yt_result.get("failed"),
        )
        exit_code = 1

    # ---- Stages 2 and 3: the cross-platform learning loop -----------------
    # Deliberately still attempted when stage 1 failed: Meta data is useful on
    # its own, and a YouTube permission problem should not blind the channel
    # to Instagram as well.
    try:
        _run_cross_platform_collection()
    except Exception as exc:  # noqa: BLE001
        logger.error("Cross-platform metric collection failed: %s", exc)

    try:
        state = _run_growth_analysis()
        _write_report(state)
    except Exception as exc:  # noqa: BLE001
        logger.error("Growth analysis failed: %s", exc)

    sys.exit(exit_code)
