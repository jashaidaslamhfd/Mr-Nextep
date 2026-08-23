"""Best-effort Facebook Reels analytics updater.

Reads completed Reel IDs from data/upload_state.json and writes metrics to
 data/facebook_analytics.json. Uses Meta's current ``/video_insights`` edge
for Reels; missing/expired Meta permissions are logged and never make the
scheduled analytics workflow fail.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

STATE_PATH = Path(os.environ.get("UPLOAD_STATE_PATH", "data/upload_state.json"))
OUTPUT_PATH = Path(os.environ.get("FACEBOOK_ANALYTICS_PATH", "data/facebook_analytics.json"))
API_VERSION = os.environ.get("FB_API_VERSION", "v23.0")
TOKEN = os.environ.get("FB_ACCESS_TOKEN")

# Query independently so one unsupported metric does not discard the metrics
# that still work. These are the current Video Insights/Reels fields; the old
# /{video-id}/insights edge and post_impressions fields produced a misleading
# permission warning even when the Page token had the required grants.
METRICS = (
    "total_video_views",
    "total_video_avg_time_watched",
    "total_video_view_total_time",
    "total_video_impressions",
    "total_video_impressions_unique",
    "post_video_avg_time_watched",
)
INSIGHTS_EDGE = "video_insights"


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return default


def _completed_reels() -> dict[str, str]:
    state = _load_json(STATE_PATH, {})
    result = {}
    for fingerprint, item in state.items() if isinstance(state, dict) else []:
        fb = item.get("facebook", {}) if isinstance(item, dict) else {}
        if fb.get("status") == "completed" and fb.get("video_id"):
            result[fingerprint] = str(fb["video_id"])
    return result


def fetch(video_id: str) -> dict:
    if not TOKEN:
        return {"error": "FB_ACCESS_TOKEN is not configured"}
    values: dict[str, Any] = {}
    errors = []
    unavailable = None
    for metric in METRICS:
        url = f"https://graph.facebook.com/{API_VERSION}/{video_id}/{INSIGHTS_EDGE}"
        try:
            response = requests.get(
                url,
                params={"metric": metric, "access_token": TOKEN},
                timeout=30,
            )
            data = response.json()
            if response.status_code >= 400 or "error" in data:
                msg = str(data.get("error", {}).get("message", response.status_code))
                # A genuine permission/token failure fails every metric
                # identically. Stop hammering after the first one, but name the
                # effective requirement rather than claiming the UI toggle is
                # definitely absent. A granted permission must also be present
                # on the Page token used by this workflow and the caller must
                # have ANALYZE access to the Page.
                error = data.get("error", {}) if isinstance(data, dict) else {}
                code = error.get("code")
                if code in {10, 190, 200, 283} or "permission" in msg.lower():
                    unavailable = (
                        "insights_unavailable: verify the effective Page access token "
                        "has `read_insights` and `pages_manage_engagement` and that "
                        "its user can perform ANALYZE on this Page"
                    )
                    break
                errors.append(f"{metric}: {msg}")
                continue
            rows = data.get("data", [])
            if rows and rows[0].get("values"):
                values[metric] = rows[0]["values"][-1].get("value")
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{metric}: {exc}")
    result = {"video_id": video_id, "fetched_at": datetime.now(timezone.utc).isoformat(), **values}
    if unavailable:
        result["status"] = unavailable
    if errors:
        result["warnings"] = errors
    return result


def _run_meta_learning() -> None:
    """Collect Facebook + Instagram metrics and re-learn from all platforms.

    WHY THIS LIVES HERE
    The cross-platform learning loop hangs off src/analytics_updater.py, which
    the analytics workflow runs in an EARLIER step — a step whose env block
    only carries the Google credentials. So when the loop reached Meta it had
    no token and reported Facebook and Instagram as "no_data" no matter how
    correct their permissions were: the most confusing failure available,
    because everything the operator had done was right.

    This step is the one that receives FB_ACCESS_TOKEN, so the Meta half of
    the collection runs here and the learning pass is repeated afterwards to
    fold the newly-fetched numbers in. Re-running the analysis is cheap (it is
    pure computation over a local JSON file) and idempotent.

    The alternative — adding the token to the earlier step — needs a workflow
    edit, which the automation maintaining this repo cannot perform. Doing it
    in code means the operator's permissions take effect immediately rather
    than waiting on a manual YAML change.
    """
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    try:
        from platform_metrics import collect
        from growth_engine import analyse
    except ImportError as exc:  # pragma: no cover
        log.warning("Learning modules unavailable (%s); Meta metrics only.", exc)
        return

    try:
        result = collect(
            min_hours_old=int(os.environ.get("METRICS_MIN_HOURS", "24")),
            refresh_hours=int(os.environ.get("METRICS_REFRESH_HOURS", "20")),
        )
        log.info("Cross-platform metrics (with Meta token): %s", result.get("stats"))
    except Exception as exc:  # noqa: BLE001 - never fail the analytics run
        log.warning("Cross-platform collection failed: %s", exc)
        return

    try:
        state = analyse()
        log.info(
            "Growth state refreshed: %d mature videos, cadence=%s/day, best slot=%s",
            state.get("sample_size", 0),
            state.get("recommended_cadence"),
            state.get("best_slot") or "not enough data",
        )
        for alert in state.get("alerts", []):
            level = logging.ERROR if alert.get("level") == "error" else logging.WARNING
            log.log(level, "ALERT: %s", alert.get("message"))

        sys.path.insert(0, str(root / "scripts"))
        from growth_report import build_report

        report_path = root / "docs" / "GROWTH_REPORT.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(build_report(state), encoding="utf-8")
        log.info("Wrote docs/GROWTH_REPORT.md")
    except Exception as exc:  # noqa: BLE001
        log.warning("Growth analysis failed: %s", exc)


def main() -> int:
    current = _load_json(OUTPUT_PATH, {})
    if not isinstance(current, dict):
        current = {}
    updated = 0
    for fingerprint, video_id in _completed_reels().items():
        result = fetch(video_id)
        current[fingerprint] = result
        if "error" not in result:
            updated += 1
        log.info("Facebook analytics %s: %s", video_id, result)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Facebook analytics updated: %d", updated)

    # This step holds the Meta token, so the cross-platform learning pass runs
    # here where it can actually reach Facebook and Instagram.
    _run_meta_learning()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
