"""Read-only cross-platform performance snapshots and evidence-based weekly reports.

This module never publishes, invents zero-valued metrics, or treats API failures as poor
performance. Meta metric availability varies by account type, media type, permissions and
Graph API version, so each candidate metric is attempted independently and only returned
values are stored.
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

import requests

log = logging.getLogger(__name__)

DEFAULT_GRAPH_VERSION = os.getenv("META_GRAPH_API_VERSION", "v21.0")
META_GRAPH_BASE = f"https://graph.facebook.com/{DEFAULT_GRAPH_VERSION}"

# Ordered aliases: try the most useful current metric first, then older names where
# Meta may still expose them. We record the actual API metric name alongside its value.
META_METRICS: dict[str, dict[str, tuple[str, ...]]] = {
    "instagram": {
        "views": ("views", "plays", "video_views"),
        "reach": ("reach",),
        "likes": ("likes", "like_count"),
        "comments": ("comments", "comments_count"),
        "shares": ("shares",),
        "saves": ("saved", "saves"),
        "watch_time_ms": ("ig_reels_video_view_total_time",),
        "average_watch_time_ms": ("ig_reels_avg_watch_time",),
    },
    "facebook": {
        "views": ("total_video_views", "post_video_views", "views"),
        "reach": ("total_video_views_unique", "post_impressions_unique", "reach"),
        "engaged_users": ("post_engaged_users",),
        "watch_time_ms": ("total_video_view_time",),
        "average_watch_time_ms": ("total_video_avg_time_watched",),
    },
}


def _numeric(value: Any) -> float | None:
    """Normalize scalar or breakdown values; missing/unparseable data remains None."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        values = [_numeric(v) for v in value.values()]
        numeric = [v for v in values if v is not None]
        return sum(numeric) if numeric else None
    if isinstance(value, list):
        values = [_numeric(item.get("value") if isinstance(item, dict) else item) for item in value]
        numeric = [v for v in values if v is not None]
        return sum(numeric) if numeric else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_value(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        return None, None
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _numeric(row.get("values", row.get("value")))
        if value is not None:
            return value, str(row.get("name") or "") or None
    return None, None


def fetch_meta_metrics(
    platform: str,
    media_id: str,
    token: str,
    *,
    session: requests.Session | None = None,
    graph_base: str | None = None,
) -> dict[str, Any]:
    """Fetch metrics available for one published Meta object, skipping unsupported metrics."""
    if platform not in META_METRICS:
        raise ValueError(f"Unsupported Meta platform: {platform}")
    if not media_id or not token:
        return {"status": "skipped", "metrics": {}, "unavailable": list(META_METRICS[platform])}

    client = session or requests.Session()
    base = (graph_base or META_GRAPH_BASE).rstrip("/")
    metrics: dict[str, float] = {}
    metric_names: dict[str, str] = {}
    unavailable: list[str] = []
    for canonical, aliases in META_METRICS[platform].items():
        found = False
        for alias in aliases:
            try:
                response = client.get(
                    f"{base}/{media_id}/insights",
                    params={"access_token": token, "metric": alias},
                    timeout=20,
                )
                if response.status_code >= 400:
                    continue
                payload = response.json()
                value, actual_name = _metric_value(payload)
                if value is None:
                    continue
                metrics[canonical] = value
                metric_names[canonical] = actual_name or alias
                found = True
                break
            except (requests.RequestException, ValueError, TypeError) as exc:
                log.debug("Meta metric %s unavailable for %s/%s: %s", alias, platform, media_id, type(exc).__name__)
        if not found:
            unavailable.append(canonical)

    return {
        "status": "ok" if metrics else "unavailable",
        "metrics": metrics,
        "metric_names": metric_names,
        "unavailable": unavailable,
    }


def collect_meta_performance(
    history: list[dict[str, Any]], *, facebook_page_id: str = "", instagram_user_id: str = "",
    access_token: str = "", session: requests.Session | None = None,
) -> dict[str, Any]:
    """Refresh Meta metrics for known published IDs; returns structured partial coverage."""
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    now = datetime.now(UTC).isoformat()
    for item in history:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        for platform, configured_id in (("facebook", facebook_page_id), ("instagram", instagram_user_id)):
            publish_result = meta.get(platform) if isinstance(meta.get(platform), dict) else {}
            media_id = str(publish_result.get("id") or "").strip()
            if not media_id or publish_result.get("status") != "published":
                continue
            if not access_token or (platform == "facebook" and not configured_id) or (platform == "instagram" and not configured_id):
                errors.append({"platform": platform, "media_id": media_id, "reason": "credentials or account ID missing"})
                continue
            try:
                snapshot = fetch_meta_metrics(platform, media_id, access_token, session=session)
                rows.append({
                    "platform": platform,
                    "media_id": media_id,
                    "title": str(item.get("title") or item.get("topic") or ""),
                    "published_at": str(item.get("created_at") or ""),
                    "fetched_at": now,
                    **snapshot,
                })
            except Exception as exc:  # one failed post must not discard other posts
                errors.append({"platform": platform, "media_id": media_id, "reason": type(exc).__name__})
                log.warning("Could not refresh %s insights for media %s (%s)", platform, media_id, type(exc).__name__)
    return {"generated_at": now, "records": rows, "errors": errors}


def build_growth_report(
    youtube_payload: dict[str, Any] | None,
    meta_payload: dict[str, Any] | None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Create an honest report with coverage, relative winners and actionable next tests."""
    youtube_payload = youtube_payload if isinstance(youtube_payload, dict) else {}
    meta_payload = meta_payload if isinstance(meta_payload, dict) else {}
    yt_rows = youtube_payload.get("videos") if isinstance(youtube_payload.get("videos"), list) else []
    meta_rows = meta_payload.get("records") if isinstance(meta_payload.get("records"), list) else []
    platform_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in yt_rows:
        if isinstance(row, dict) and row.get("video_id"):
            platform_rows["youtube"].append({
                "id": str(row["video_id"]), "title": str(row.get("title") or ""),
                "views": _numeric(row.get("views")),
                "retention_pct": (_numeric(row.get("average_view_percentage")) * 100
                                  if _numeric(row.get("average_view_percentage")) is not None else None),
                "average_watch_seconds": _numeric(row.get("average_view_duration_seconds")),
            })
    for row in meta_rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        platform_rows[str(row.get("platform") or "unknown")].append({
            "id": str(row.get("media_id") or ""), "title": str(row.get("title") or ""),
            "views": _numeric(metrics.get("views")), "reach": _numeric(metrics.get("reach")),
            "likes": _numeric(metrics.get("likes")), "comments": _numeric(metrics.get("comments")),
            "shares": _numeric(metrics.get("shares")), "saves": _numeric(metrics.get("saves")),
            "engaged_users": _numeric(metrics.get("engaged_users")),
            "average_watch_time_ms": _numeric(metrics.get("average_watch_time_ms")),
            "metrics_available": sorted(metrics.keys()),
        })

    summaries: dict[str, Any] = {}
    recommendations: list[dict[str, str]] = []
    for platform in ("youtube", "instagram", "facebook"):
        rows = platform_rows.get(platform, [])
        view_values = [row["views"] for row in rows if row.get("views") is not None]
        summary: dict[str, Any] = {
            "published_objects_with_analytics": len(rows),
            "objects_with_view_counts": len(view_values),
            "median_views": median(view_values) if view_values else None,
            "top_performers": sorted(
                [row for row in rows if row.get("views") is not None],
                key=lambda row: row["views"], reverse=True,
            )[:5],
        }
        if platform == "youtube":
            retention_values = [row["retention_pct"] for row in rows if row.get("retention_pct") is not None]
            summary["median_average_view_percentage"] = median(retention_values) if retention_values else None
        else:
            engaged_rates = []
            for row in rows:
                reach = row.get("reach")
                interactions = sum(row.get(key) or 0 for key in ("likes", "comments", "shares", "saves"))
                if reach and reach > 0 and any(row.get(key) is not None for key in ("likes", "comments", "shares", "saves")):
                    engaged_rates.append(interactions / reach * 100)
            summary["median_interactions_per_reach_pct"] = median(engaged_rates) if engaged_rates else None
        summaries[platform] = summary

        # Use only a minimally useful sample and compare against that platform's own median.
        measured = [row for row in rows if row.get("views") is not None]
        if len(measured) >= 3:
            baseline = median(row["views"] for row in measured)
            winners = [row for row in measured if row["views"] >= baseline * 1.5]
            laggards = [row for row in measured if row["views"] <= baseline * 0.5]
            if winners:
                recommendations.append({
                    "platform": platform, "action": "replicate_winner_pattern",
                    "detail": f"Review the {len(winners)} post(s) at least 1.5x this platform's median views; test one shared topic or hook trait next.",
                })
            if laggards:
                recommendations.append({
                    "platform": platform, "action": "diagnose_weak_opening",
                    "detail": f"Review the {len(laggards)} post(s) at or below half the platform median; inspect first-second visual, clarity and pacing before changing several variables.",
                })

    coverage = {
        "youtube_records": len(platform_rows.get("youtube", [])),
        "instagram_records": len(platform_rows.get("instagram", [])),
        "facebook_records": len(platform_rows.get("facebook", [])),
        "meta_fetch_errors": len(meta_payload.get("errors", [])) if isinstance(meta_payload.get("errors"), list) else 0,
    }
    if coverage["instagram_records"] == 0:
        recommendations.append({"platform": "instagram", "action": "connect_or_verify_insights", "detail": "No Instagram insight records were collected. Verify published media IDs, professional account access, token permissions and the configured Graph API version."})
    if coverage["facebook_records"] == 0:
        recommendations.append({"platform": "facebook", "action": "connect_or_verify_insights", "detail": "No Facebook insight records were collected. Verify Page/Reel IDs, Page access token permissions and the configured Graph API version."})
    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "coverage": coverage,
        "platforms": summaries,
        "recommendations": recommendations,
        "interpretation": "Within-platform descriptive comparisons only. Metrics and distribution differ by platform; small samples are not causal evidence and no result predicts virality.",
    }


def write_growth_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    """Write JSON and readable Markdown artifacts without storing credentials."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Mr-Nextep Weekly Cross-Platform Growth Report", "", f"Generated: {report.get('generated_at', 'unknown')}", "",
             "## Data coverage", "",
             "| Platform | Objects with records | Objects with view counts | Median views |", "|---|---:|---:|---:|"]
    for platform in ("youtube", "instagram", "facebook"):
        item = report.get("platforms", {}).get(platform, {})
        median_views = item.get("median_views")
        median_text = f"{median_views:.0f}" if isinstance(median_views, (int, float)) else "n/a"
        lines.append(f"| {platform.title()} | {item.get('published_objects_with_analytics', 0)} | {item.get('objects_with_view_counts', 0)} | {median_text} |")
    lines.extend(["", "## Recommendations", ""])
    for rec in report.get("recommendations", []):
        lines.append(f"- **{rec['platform'].title()} — {rec['action']}**: {rec['detail']}")
    if not report.get("recommendations"):
        lines.append("- Not enough data for evidence-based recommendations yet; collect more posts and refresh analytics.")
    lines.extend(["", "## Interpretation", "", str(report.get("interpretation", "")), ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
