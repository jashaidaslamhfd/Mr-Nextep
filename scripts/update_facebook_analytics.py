"""Best-effort Facebook Reels analytics updater.

Reads completed Reel IDs from data/upload_state.json and writes metrics to
 data/facebook_analytics.json. Missing/expired Meta permissions are logged and
never make the scheduled analytics workflow fail.
"""
from __future__ import annotations

import json
import logging
import os
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

# Meta can change availability by account/API version; query independently so
# one unsupported metric does not discard the metrics that still work.
METRICS = (
    "total_video_views",
    "total_video_avg_time_watched",
    "total_video_view_total_time",
    "post_impressions",
    "post_reactions_by_type_total",
)


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
        url = f"https://graph.facebook.com/{API_VERSION}/{video_id}/insights"
        try:
            response = requests.get(
                url,
                params={"metric": metric, "access_token": TOKEN},
                timeout=30,
            )
            data = response.json()
            if response.status_code >= 400 or "error" in data:
                msg = str(data.get("error", {}).get("message", response.status_code))
                # A missing read_insights grant (or a deprecated Reels
                # insights endpoint) fails EVERY metric identically — stop
                # hammering after the first one instead of writing 5 warnings.
                if "read_insights permission missing" in msg or "nonexisting field" in msg:
                    unavailable = ("insights_unavailable: grant `read_insights` and "
                                   "`pages_read_engagement` to the page token")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
