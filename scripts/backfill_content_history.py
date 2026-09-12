#!/usr/bin/env python3
"""Backfill content_history.json from the channel's published uploads.

Why this exists: the duplicate guard compares a candidate script against
data/content_history.json, but that file only contains entries this pipeline wrote
itself — 9 of them, against a channel with hundreds of published videos. The guard was
effectively blind to everything published before the pipeline started recording, so a
topic could be published again with no objection.

This pulls the titles of the channel's uploads from the YouTube Data API and writes them
as title-only history entries. They carry no script body (the API does not expose one),
which is why guards.duplicate_reason treats title similarity on its own as sufficient
grounds to reject a candidate.

Usage:
    python -m scripts.backfill_content_history --dry-run
    python -m scripts.backfill_content_history --limit 500

Requires the same YouTube credentials as an upload run (YT_CLIENT_ID, YT_CLIENT_SECRET,
YT_REFRESH_TOKEN). Read-only: it never writes to YouTube.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.guards import fingerprint, normalize  # noqa: E402
from src.youtube import _load_credentials_from_env  # noqa: E402

log = logging.getLogger("backfill")

BACKFILL_SOURCE = "youtube_backfill"


def uploads_playlist_id(service: Any) -> str:
    response = service.channels().list(part="contentDetails", mine=True).execute()
    items = response.get("items") or []
    if not items:
        raise RuntimeError(
            "The authenticated account owns no channel; check which account the "
            "YT_REFRESH_TOKEN belongs to."
        )
    related = items[0].get("contentDetails", {}).get("relatedPlaylists", {})
    playlist = related.get("uploads")
    if not playlist:
        raise RuntimeError(f"Channel returned no uploads playlist: {related!r}")
    return str(playlist)


def fetch_published_titles(service: Any, playlist: str, limit: int) -> list[dict[str, str]]:
    """Return [{title, video_id, published_at}] for up to `limit` uploads, newest first."""
    collected: list[dict[str, str]] = []
    page_token: str | None = None
    while len(collected) < limit:
        response = service.playlistItems().list(
            part="snippet",
            playlistId=playlist,
            maxResults=min(50, limit - len(collected)),
            pageToken=page_token,
        ).execute()
        for item in response.get("items", []):
            snippet = item.get("snippet") or {}
            title = str(snippet.get("title") or "").strip()
            if not title:
                continue
            collected.append({
                "title": title,
                "video_id": str((snippet.get("resourceId") or {}).get("videoId") or ""),
                "published_at": str(snippet.get("publishedAt") or ""),
            })
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return collected


def merge_into_history(
    history: list[dict[str, Any]], published: list[dict[str, str]]
) -> tuple[list[dict[str, Any]], int]:
    """Prepend title-only entries for uploads the history does not already know.

    Existing entries are never modified — an entry the pipeline wrote carries a real script
    body, which is stronger evidence than a title alone.
    """
    known = {normalize(str(item.get("title", ""))) for item in history if isinstance(item, dict)}
    known.discard("")
    known_ids = {
        str(item.get("video_id", ""))
        for item in history
        if isinstance(item, dict) and item.get("video_id")
    }

    additions: list[dict[str, Any]] = []
    for entry in reversed(published):  # oldest first, so history stays chronological
        key = normalize(entry["title"])
        if not key or key in known:
            continue
        if entry["video_id"] and entry["video_id"] in known_ids:
            continue
        known.add(key)
        record = {
            "title": entry["title"],
            "body": "",
            "text": entry["title"],
            "fingerprint": fingerprint({"title": entry["title"], "scenes": []}),
            "video_id": entry["video_id"],
            "published_at": entry["published_at"],
            "source": BACKFILL_SOURCE,
        }
        additions.append(record)

    return additions + history, len(additions)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", default="data/content_history.json")
    parser.add_argument("--limit", type=int, default=500, help="Maximum uploads to read.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be added without writing the history file.",
    )
    args = parser.parse_args()

    history_path = Path(args.history)
    history: list[dict[str, Any]] = []
    if history_path.exists():
        loaded = json.loads(history_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise RuntimeError(f"{history_path} does not contain a JSON list")
        history = loaded

    service = build("youtube", "v3", credentials=_load_credentials_from_env(), cache_discovery=False)
    playlist = uploads_playlist_id(service)
    published = fetch_published_titles(service, playlist, args.limit)
    log.info("Read %d published uploads from playlist %s", len(published), playlist)

    merged, added = merge_into_history(history, published)
    if args.dry_run:
        log.info("Dry run: %d new title-only entries would be added", added)
        for record in merged[:added][:10]:
            log.info("  + %s", record["title"])
        print(json.dumps({"published": len(published), "would_add": added, "written": False}))
        return 0

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote %d entries (%d new) to %s", len(merged), added, history_path)
    print(json.dumps({"published": len(published), "added": added, "total": len(merged), "written": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
