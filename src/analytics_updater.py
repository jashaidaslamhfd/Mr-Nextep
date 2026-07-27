"""
src/analytics_updater.py

Standalone entrypoint for pulling REAL YouTube Analytics numbers into
output/video_history.json.

IMPORTANT: run this on a SEPARATE cron/GitHub Actions schedule from the
main pipeline (main.py) - e.g. once a day. YouTube Analytics data is not
available immediately after upload (usually needs 24-48h to populate),
so this only touches history entries that are already at least
`min_hours_old` (default 24h).

Requires the SAME OAuth env vars as uploader.py:
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, REFRESH_TOKEN
...and that REFRESH_TOKEN must additionally have been issued with the
`yt-analytics.readonly` scope (uploader.py's upload flow only needs
youtube.upload + youtube.force-ssl, so if your existing token was minted
before this feature, you'll need to re-consent once with the extra scope).

Usage:
    python src/analytics_updater.py

Example GitHub Actions cron (runs daily at 06:00 UTC):
    on:
      schedule:
        - cron: '0 6 * * *'
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(__file__))
from seo_analytics import update_history_with_real_metrics

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    result = update_history_with_real_metrics(min_hours_old=24)
    logger.info(f"Analytics update complete: {result}")

    # Exit non-zero when the sync achieved nothing. Every per-video error is
    # caught and logged as a warning, so this script used to exit 0 while all
    # 17 videos failed with invalid_scope — the workflow showed a green tick
    # for four consecutive days while data/video_history.json stayed empty.
    # A broken feedback loop must be visible.
    if result.get("api_disabled"):
        logger.error(
            "YouTube Analytics API is disabled for this Google Cloud project. "
            "Enable it at console.cloud.google.com -> APIs & Services, then "
            "re-run. This cannot be fixed in code."
        )
        sys.exit(2)

    if result.get("failed") and not result.get("updated"):
        logger.error(
            "Every analytics fetch failed (%s videos) and nothing was written. "
            "Failing loudly so this is not mistaken for a healthy run.",
            result["failed"],
        )
        sys.exit(1)
