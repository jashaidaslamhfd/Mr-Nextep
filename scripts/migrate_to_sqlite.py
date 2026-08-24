#!/usr/bin/env python3
"""
MrNextep JSON → SQLite Migration
--------------------------------
One-shot migration from flat JSON files to a single SQLite database.
Run once, then switch the pipeline to read from SQLite.

Usage:
    python scripts/migrate_to_sqlite.py           # dry-run (print what would happen)
    python scripts/migrate_to_sqlite.py --apply   # actually migrate

After migration:
    DB_PATH = os.environ.get("MrNextep_DB_PATH", "data/skillor.db")
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

DATA_DIR = Path(os.environ.get("MrNextep_DATA_DIR", "data"))
DB_PATH = Path(os.environ.get("MrNextep_DB_PATH", "data/skillor.db"))


def connect() -> sqlite3.Connection:
    """Return a connection with WAL mode and sensible defaults."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS video_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            youtube_id TEXT,
            facebook_id TEXT,
            instagram_id TEXT,
            title TEXT,
            published_at TEXT,
            word_count INTEGER,
            hook_score INTEGER,
            duration_seconds REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS platform_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER REFERENCES video_history(id),
            platform TEXT NOT NULL,  -- 'youtube_shorts', 'facebook_reels', 'instagram_reels'
            views INTEGER DEFAULT 0,
            completion REAL DEFAULT 0.0,  -- 0..1
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            saves INTEGER DEFAULT 0,
            sends_per_reach REAL,
            fetched_at TEXT DEFAULT (datetime('now')),
            UNIQUE(video_id, platform)
        );

        CREATE TABLE IF NOT EXISTS growth_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
            slot_weights TEXT NOT NULL DEFAULT '{}',   -- JSON
            topic_weights TEXT NOT NULL DEFAULT '{}',  -- JSON
            hook_weights TEXT NOT NULL DEFAULT '{}',   -- JSON
            platform_health TEXT NOT NULL DEFAULT '{}', -- JSON
            recommended_cadence INTEGER DEFAULT 2,
            generated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS media_hashes (
            hash TEXT PRIMARY KEY,
            used_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS upload_state (
            platform TEXT PRIMARY KEY,  -- 'youtube', 'facebook', 'instagram'
            last_upload_at TEXT,
            upload_count INTEGER DEFAULT 0,
            state_json TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS analytics_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_type TEXT NOT NULL,  -- 'seo_diag', 'fb_audit', 'channel_audit', etc.
            snapshot_date TEXT NOT NULL,
            data_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_video_history_published
            ON video_history(published_at);
        CREATE INDEX IF NOT EXISTS idx_video_history_youtube
            ON video_history(youtube_id) WHERE youtube_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_platform_metrics_platform
            ON platform_metrics(platform);
        CREATE INDEX IF NOT EXISTS idx_media_hashes_used
            ON media_hashes(used_at);
    """)


def load_json(path: Path) -> Any:
    """Load a JSON file, returning default on failure."""
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        print(f"  ⚠️  Could not load {path.name}: {e}")
    return None


def migrate_video_history(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Migrate data/video_history.json → video_history table."""
    data = load_json(DATA_DIR / "video_history.json")
    if not isinstance(data, list):
        return 0

    count = 0
    existing = {row[0] for row in conn.execute(
        "SELECT youtube_id FROM video_history WHERE youtube_id IS NOT NULL"
    ).fetchall()}

    for video in data:
        yt_id = video.get("youtube_id")
        if yt_id and yt_id in existing:
            continue

        if not dry_run:
            conn.execute(
                """INSERT INTO video_history
                   (topic, youtube_id, facebook_id, instagram_id, title,
                    published_at, word_count, hook_score, duration_seconds)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    video.get("topic", ""),
                    yt_id,
                    video.get("facebook_id"),
                    video.get("instagram_id"),
                    video.get("title", ""),
                    video.get("published_at") or video.get("timestamp", ""),
                    video.get("word_count"),
                    video.get("hook_score"),
                    video.get("duration_seconds"),
                ),
            )
        count += 1

    return count


def migrate_platform_metrics(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Migrate data/platform_metrics.json → platform_metrics table."""
    data = load_json(DATA_DIR / "platform_metrics.json")
    if not isinstance(data, dict):
        return 0

    count = 0
    for video_key, platforms in data.items():
        if not isinstance(platforms, dict):
            continue

        # Get video_id from the youtube_id
        yt_id = platforms.get("youtube_id", "")
        row = conn.execute(
            "SELECT id FROM video_history WHERE youtube_id = ?", (yt_id,)
        ).fetchone()
        video_id = row[0] if row else None

        for platform in ("youtube_shorts", "facebook_reels", "instagram_reels"):
            pdata = platforms.get(platform, {})
            if not pdata:
                continue

            if not dry_run:
                conn.execute(
                    """INSERT OR REPLACE INTO platform_metrics
                       (video_id, platform, views, completion, likes, comments,
                        shares, saves, sends_per_reach)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        video_id,
                        platform,
                        pdata.get("views", 0),
                        pdata.get("completion", 0.0),
                        pdata.get("likes", 0),
                        pdata.get("comments", 0),
                        pdata.get("shares", 0),
                        pdata.get("saves", 0),
                        pdata.get("sends_per_reach"),
                    ),
                )
            count += 1

    return count


def migrate_growth_state(conn: sqlite3.Connection, dry_run: bool) -> bool:
    """Migrate data/growth_state.json → growth_state table."""
    data = load_json(DATA_DIR / "growth_state.json")
    if not data:
        return False

    if not dry_run:
        conn.execute(
            """INSERT OR REPLACE INTO growth_state
               (id, slot_weights, topic_weights, hook_weights, platform_health,
                recommended_cadence, generated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?)""",
            (
                json.dumps(data.get("slot_weights", {})),
                json.dumps(data.get("topic_weights", {})),
                json.dumps(data.get("hook_weights", {})),
                json.dumps(data.get("platform_health", {})),
                data.get("recommended_cadence", 2),
                data.get("generated_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
    return True


def migrate_media_hashes(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Migrate data/media_hash_history.json → media_hashes table."""
    data = load_json(DATA_DIR / "media_hash_history.json")
    if not isinstance(data, list):
        return 0

    count = 0
    now = datetime.now(timezone.utc).isoformat()
    for h in data:
        if not dry_run:
            conn.execute(
                "INSERT OR IGNORE INTO media_hashes (hash, used_at) VALUES (?, ?)",
                (str(h), now),
            )
        count += 1
    return count


def migrate_analytics_snapshots(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Migrate diagnostic JSON files → analytics_snapshots table."""
    patterns = {
        "seo_diag": "seo_diag_*.json",
        "fb_audit": "fb_audit_*.json",
        "fb_diag": "fb_diag_*.json",
        "fb_tuneup": "fb_tuneup_*.json",
        "meta_seo_repair": "meta_seo_repair_*.json",
        "meta_reach_diag": "meta_reach_diag.json",
        "ig_diag": "ig_diag.json",
        "retention_analysis": "retention_analysis.json",
    }

    count = 0
    for snapshot_type, pattern in patterns.items():
        if "*" in pattern:
            files = sorted(DATA_DIR.glob(pattern))
        else:
            p = DATA_DIR / pattern
            files = [p] if p.exists() else []

        for fp in files:
            data = load_json(fp)
            if data is None:
                continue

            # Extract date from filename or use mtime
            stem = fp.stem
            date_str = stem.split("_")[-1] if "_" in stem else ""
            if len(date_str) == 8 and date_str.isdigit():
                snapshot_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            else:
                snapshot_date = datetime.fromtimestamp(fp.stat().st_mtime).strftime("%Y-%m-%d")

            if not dry_run:
                conn.execute(
                    """INSERT INTO analytics_snapshots
                       (snapshot_type, snapshot_date, data_json)
                       VALUES (?, ?, ?)""",
                    (snapshot_type, snapshot_date, json.dumps(data)),
                )
            count += 1

    return count


def print_summary(stats: Dict[str, int]) -> None:
    """Print a nice summary table."""
    print("\n" + "=" * 60)
    print("  MIGRATION SUMMARY")
    print("=" * 60)
    for label, count in stats.items():
        print(f"  {label:<30} {count:>6}")
    print("=" * 60)


def main():
    dry_run = "--apply" not in sys.argv
    mode = "DRY RUN" if dry_run else "APPLY"

    print(f"\n🔧 MrNextep JSON → SQLite Migration ({mode})")
    print(f"   Source: {DATA_DIR}")
    print(f"   Target: {DB_PATH}")
    print()

    if not DATA_DIR.exists():
        print("❌ Data directory not found. Run from repo root.")
        sys.exit(1)

    if not dry_run:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = connect()
    create_schema(conn)

    stats = {}

    # 1. Video history
    stats["video_history"] = migrate_video_history(conn, dry_run)
    print(f"  📹 Video history: {stats['video_history']} videos")

    # 2. Platform metrics
    stats["platform_metrics"] = migrate_platform_metrics(conn, dry_run)
    print(f"  📊 Platform metrics: {stats['platform_metrics']} records")

    # 3. Growth state
    stats["growth_state"] = 1 if migrate_growth_state(conn, dry_run) else 0
    print(f"  📈 Growth state: {'migrated' if stats['growth_state'] else 'not found'}")

    # 4. Media hashes
    stats["media_hashes"] = migrate_media_hashes(conn, dry_run)
    print(f"  🖼️  Media hashes: {stats['media_hashes']} hashes")

    # 5. Analytics snapshots
    stats["analytics_snapshots"] = migrate_analytics_snapshots(conn, dry_run)
    print(f"  📋 Analytics snapshots: {stats['analytics_snapshots']} files")

    if not dry_run:
        conn.commit()
        print(f"\n✅ Migration complete! Database: {DB_PATH} ({DB_PATH.stat().st_size:,} bytes)")
    else:
        conn.rollback()
        print("\n🔍 Dry run complete. Run with --apply to actually migrate.")

    print_summary(stats)
    conn.close()


if __name__ == "__main__":
    main()
