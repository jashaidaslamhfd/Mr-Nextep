#!/usr/bin/env python3
"""Diagnostic: does the REFRESH_TOKEN actually have yt-analytics.readonly, and
does real CTR/impressions data come back?

Fetches real performance for a known video id from video_history and reports
what the API actually returns — so we know whether the channel can learn from
real viewer data (CTR, retention) or is publishing blind.

Usage:
  python scripts/check_analytics_scope.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

# known missing scopes → explicit error
KNOWN_SCOPE_ERR = ("needs yt-analytics.readonly scope", "invalid_scope",
                   "insufficient", "forbidden")


def main() -> int:
    vh = []
    p = ROOT / "data" / "video_history.json"
    if p.exists():
        vh = json.load(open(p, encoding="utf-8"))

    vid = None
    for v in vh:
        if v.get("youtube_video_id"):
            vid = v["youtube_video_id"]
            break
    if not vid:
        print("NO video id in history to test analytics on")
        return 1

    print(f"Testing analytics scope using video: {vid}")
    try:
        from seo_analytics import fetch_actual_performance
        result = fetch_actual_performance(vid)
    except Exception as exc:  # noqa: BLE001
        print(f"EXCEPTION: {exc}")
        return 1

    if "error" in result:
        err = str(result.get("error", ""))
        print(f"ERROR: {err}")
        if any(k in err.lower() for k in KNOWN_SCOPE_ERR):
            print("\nRESULT: SCOPE MISSING / INSUFFICIENT — the REFRESH_TOKEN "
                  "does not carry yt-analytics.readonly. Re-issue the token "
                  "via scripts/get_refresh_token.py (which requests it).")
            return 1
        print("\nRESULT: API returned an error (may be transient or channel "
              "not serving CTR/impressions).")
        return 2

    # success — report what real data is available
    print("\n✅ Analytics query SUCCEEDED. Real data available:")
    for k, v in result.items():
        print(f"   {k}: {v}")
    has_ctr = result.get("actual_ctr") not in (None, 0)
    has_views = result.get("views", 0) > 0
    print(f"\nRESULT: scope_OK={True}  real_CTR={'YES' if has_ctr else 'NO'}  "
          f"views={'YES' if has_views else 'NO'}")
    if not has_ctr:
        print("Note: CTR present but 0 — YouTube may not serve impressions/"
              "impressionsClickThroughRate for this channel/video yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
