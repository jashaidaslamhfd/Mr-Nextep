from __future__ import annotations

import re
from datetime import UTC, datetime

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def require_video_id(value: str, field_name: str = "VIDEO_ID") -> str:
    video_id = (value or "").strip()
    if not _VIDEO_ID.fullmatch(video_id):
        raise SystemExit(f"{field_name} must be an 11-character YouTube video ID")
    return video_id


def require_publish_at(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise SystemExit("PUBLISH_AT is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit("PUBLISH_AT must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise SystemExit("PUBLISH_AT must include a UTC timezone (Z or +00:00)")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def require_video_ids(value: str) -> list[str]:
    ids = [item.strip() for item in (value or "").split(",") if item.strip()]
    if not ids:
        raise SystemExit("UNSCHEDULE_IDS is required")
    return [require_video_id(item, "UNSCHEDULE_IDS item") for item in ids]
