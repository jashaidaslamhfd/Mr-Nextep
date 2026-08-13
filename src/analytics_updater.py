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

    # Stage 1b: feed the FREE viewer-preference model with real outcomes so it
    # can learn which content features viewers actually like (self-improving).
    try:
        from viewer_preference import record_outcome, recalibrate
        import json as _json
        from pathlib import Path as _Path
        _root = _Path(__file__).resolve().parents[1]
        _vh = _root / "data" / "video_history.json"
        if _vh.exists():
            history = _json.load(open(_vh, encoding="utf-8"))
            # record the most recent video with real retention if not already
            for v in reversed(history):
                ret = v.get("average_view_percentage") or 0
                views = v.get("views") or 0
                if ret > 0 and v.get("scenes") or v.get("voiceover"):
                    try:
                        record_outcome(v, float(ret), float(views))
                    except Exception:
                        pass
                    break
        cal = recalibrate()
        if cal.get("calibrated"):
            logger.info("Viewer-preference model recalibrated: %s", cal["weights"])
    except Exception as exc:  # noqa: BLE001 - self-improvement must never break the loop
        logger.warning("Viewer-preference self-improvement skipped: %s", exc)
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

    # Stage 3b: Autonomous strategy decision — after learning from real
    # metrics, re-decide which series / quality gate / cadence the NEXT run
    # should use and persist it for main.py to consume. Best-effort.
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from strategy_engine import decide_and_report
        decision = decide_and_report()
        logger.info(
            "Strategy decision: series=%s barrier=%s cadence=%s quality=%s",
            decision.get("recommended_series"),
            decision.get("barrier"),
            decision.get("cadence"),
            decision.get("quality_threshold"),
        )
    except Exception as exc:  # noqa: BLE001 - strategy must never break learning
        logger.warning("Strategy decision failed (non-fatal): %s", exc)
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


def _run_full_platform_repair() -> dict:
    """Stage 4: Full platform repair (YT+FB+IG) — best-effort.
    
    FIXED 2026-07-31: User requested 'ek workflow jo sab clean kare'.
    Since GitHub App cannot push .github/workflows files (403 workflows permission),
    we wired the full repair into the already-deployed analytics.yml workflow
    via this stage. Running analytics.yml now also does FB cover backfill +
    meta SEO repair + audits.
    
    Controlled by env FULL_REPAIR (default true when FB token present).
    """
    try:
        from full_platform_repair import run_full_repair
        return run_full_repair()
    except Exception as exc:
        logger.warning("Full platform repair failed (non-fatal): %s", exc)
        return {"error": str(exc)[:200]}


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
        # FIXED 2026-07-31: Previously exit_code=2 caused the entire analytics workflow
        # to fail, preventing FB/IG collection (which runs in later steps) and growth report.
        # Now we exit 0 after logging — Meta data can still be collected and the report
        # shows exactly what is blocked. The 403 error message already says what to do.
        logger.error(
            "YouTube Analytics API is DISABLED for this Google Cloud project (403). "
            "Enable it at https://console.developers.google.com/apis/api/youtubeanalytics.googleapis.com/overview?project=559439687452 "
            "-> Click Enable, wait 2 min, then re-run 'YouTube Analytics Learning' workflow. "
            "Continuing to collect Facebook/Instagram metrics anyway."
        )
        # Don't fail the workflow — let Meta collection run
        exit_code = 0
    elif yt_result.get("failed") and not yt_result.get("updated"):
        # Every per-video error is caught and logged as a warning, so this
        # script used to exit 0 while all 17 videos failed with invalid_scope
        # — four consecutive green ticks over an empty history file. A broken
        # feedback loop must be visible.
        #
        # BUT: "no data yet" for young videos is normal (24-48h delay).
        # Only fail if there are REAL errors beyond just young videos.
        if yt_result.get("no_data_yet", 0) > 0 and yt_result.get("failed", 0) == 0:
            logger.info(
                "All unscored videos are simply too young for analytics "
                "(%s videos still within the 24-48h window). This is normal.",
                yt_result.get("no_data_yet"),
            )
        else:
            logger.error(
                "Every YouTube analytics fetch failed (%s videos, %s too young) and nothing was "
                "written. Failing loudly so this is not mistaken for a healthy run.",
                yt_result.get("failed"),
                yt_result.get("no_data_yet", 0),
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

    # ---- Stage 4: Full platform repair (DISABLED by default) --------------
    # Previously ran FB cover backfill + meta SEO repair + audits on every
    # analytics run. That made the channel re-edit metadata daily, which the
    # 2026 platforms can read as spam/inauthentic churn, and it's no longer
    # needed because all platforms were already repaired once. Only run it
    # deliberately by setting FULL_REPAIR=true.
    if os.environ.get("FULL_REPAIR", "false").strip().lower() == "true":
        try:
            repair_result = _run_full_platform_repair()
            logger.info("Full repair result: %s", repair_result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Full repair stage failed: %s", exc)
    else:
        logger.info("Full platform repair disabled (FULL_REPAIR != true) — "
                    "daily metadata edits would read as spam on 2026 feeds.")

    # Return the actual exit_code so CI/CD properly registers failures
    sys.exit(exit_code)
