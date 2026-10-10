#!/usr/bin/env python3
"""Refresh optional Meta insights and build a unified weekly growth report.

YouTube data is read from data/performance_history.json after scripts/pull_analytics.py
has refreshed it. Meta reads are optional and read-only; missing/unsupported permissions
produce explicit coverage warnings instead of fabricated zeros.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.platform_analytics import build_growth_report, collect_meta_performance, write_growth_report  # noqa: E402

log = logging.getLogger("pull_platform_analytics")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--history", type=Path, help="Optional alternate video_history.json path")
    parser.add_argument("--skip-meta", action="store_true", help="Build report from cached data without calling Meta")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    history_path = args.history or args.data_dir / "video_history.json"
    history = _read_json(history_path, [])
    if not isinstance(history, list):
        raise RuntimeError(f"Expected a JSON list in {history_path}")

    meta_path = args.data_dir / "meta_performance_history.json"
    previous_meta = _read_json(meta_path, {"records": [], "errors": []})
    if not args.skip_meta:
        snapshot = collect_meta_performance(
            history,
            facebook_page_id=os.getenv("FACEBOOK_PAGE_ID", "").strip(),
            instagram_user_id=os.getenv("INSTAGRAM_USER_ID", "").strip(),
            access_token=os.getenv("FACEBOOK_ACCESS_TOKEN", "").strip(),
        )
        # Keep old records for IDs no longer present in the 500-entry history, but replace
        # current IDs with their latest snapshot. Never persist token values or raw API errors.
        existing = previous_meta.get("records", []) if isinstance(previous_meta, dict) else []
        current_keys = {(r.get("platform"), r.get("media_id")) for r in snapshot["records"]}
        preserved = [r for r in existing if isinstance(r, dict) and (r.get("platform"), r.get("media_id")) not in current_keys]
        snapshot["records"] = preserved + snapshot["records"]
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        previous_meta = snapshot

    youtube_payload = _read_json(args.data_dir / "performance_history.json", {"videos": []})
    report = build_growth_report(youtube_payload, previous_meta)
    write_growth_report(report, args.output_dir / "weekly_growth_report.json", args.output_dir / "weekly_growth_report.md")
    print(json.dumps({"coverage": report["coverage"], "recommendations": len(report["recommendations"]),
                      "json_report": str(args.output_dir / 'weekly_growth_report.json'),
                      "markdown_report": str(args.output_dir / 'weekly_growth_report.md')}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
