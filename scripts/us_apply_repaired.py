#!/usr/bin/env python3
"""
scripts/us_apply_repaired.py — Apply Repaired Metadata (Titles, Tags, Descriptions, Thumbnails)

Usage:
  python scripts/us_apply_repaired.py --apply --thumbnails --limit 3  # limit to 3 videos for test
  python scripts/us_apply_repaired.py --apply --thumbnails            # repair all 23 videos
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parents[1]
REPAIR_METADATA_PATH = ROOT / "output" / "USA_Repair_2026_07_29" / "repaired_metadata.json"
THUMB_DIR = ROOT / "output" / "USA_Repair_2026_07_29" / "new_thumbnails"

def _get_youtube_service():
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("⚠️ YouTube Auth Credentials missing in environment (dry-run mode only).")
        return None

    try:
        creds = google.oauth2.credentials.Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=[
                "https://www.googleapis.com/auth/youtube.force-ssl",
                "https://www.googleapis.com/auth/youtube.upload"
            ]
        )
        return build("youtube", "v3", credentials=creds)
    except Exception as exc:
        print(f"❌ Failed to build YouTube service: {exc}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Apply Repaired Metadata to YouTube")
    parser.add_argument("--apply", action="store_true", help="Actually write changes to YouTube")
    parser.add_argument("--thumbnails", action="store_true", help="Upload custom thumbnails as well")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of videos to repair")
    args = parser.parse_args()

    print("=" * 70)
    print("MrNextep METADATA REPAIR SWEEP")
    print("=" * 70)
    print(f"Mode: {'APPLY (writes to YouTube)' if args.apply else 'DRY-RUN (read-only)'}")
    print(f"Thumbnails: {args.thumbnails} | Limit: {args.limit or 'ALL'}")
    print()

    if not REPAIR_METADATA_PATH.exists():
        print(f"❌ Error: Repaired metadata file not found at {REPAIR_METADATA_PATH}")
        sys.exit(1)

    try:
        with open(REPAIR_METADATA_PATH, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except Exception as exc:
        print(f"❌ Error reading metadata file: {exc}")
        sys.exit(1)

    videos = metadata.get("videos", [])
    if not videos:
        print("⚠️ No videos found in the repair metadata pack.")
        sys.exit(0)

    if args.limit > 0:
        videos = videos[:args.limit]

    yt = None
    if args.apply:
        yt = _get_youtube_service()
        if not yt:
            print("⚠️ Reverting to DRY-RUN mode because YouTube credentials are not available.")
            args.apply = False

    success_count = 0
    for idx, video in enumerate(videos, 1):
        vid_id = video.get("youtube_video_id")
        new_title = video.get("new_title")
        new_tags = video.get("new_tags", [])
        desc = video.get("description", "")

        print(f"[{idx}/{len(videos)}] Processing Video ID: {vid_id}")
        print(f"  - Title: '{new_title}'")
        print(f"  - Tags: {new_tags}")

        if args.apply and yt:
            try:
                # 1. Update snippet metadata
                # Note: We need categoryId (defaults to '28' Science & Tech)
                body = {
                    "id": vid_id,
                    "snippet": {
                        "title": new_title[:100],
                        "description": desc[:5000],
                        "categoryId": "28",
                        "tags": new_tags,
                        "defaultLanguage": "en-US",
                        "defaultAudioLanguage": "en-US"
                    }
                }
                yt.videos().update(part="snippet", body=body).execute()
                print("  ✅ Metadata updated successfully!")

                # 2. Update thumbnail if requested
                if args.thumbnails:
                    thumb_path = THUMB_DIR / f"{vid_id}.jpg"
                    if thumb_path.exists():
                        yt.thumbnails().set(
                            videoId=vid_id,
                            media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg")
                        ).execute()
                        print("  ✅ Thumbnail updated successfully!")
                    else:
                        # try fallback to simple mock file
                        fallback_thumb = THUMB_DIR / f"vid_repair_{idx}.jpg"
                        if fallback_thumb.exists():
                            yt.thumbnails().set(
                                videoId=vid_id,
                                media_body=MediaFileUpload(str(fallback_thumb), mimetype="image/jpeg")
                            ).execute()
                            print("  ✅ Fallback thumbnail updated successfully!")
                        else:
                            print(f"  ⚠️ Thumbnail file not found: {thumb_path}")
                
                success_count += 1
                time.sleep(1) # rate limiting protection
            except HttpError as err:
                print(f"  ❌ YouTube API error: {err}")
            except Exception as exc:
                print(f"  ❌ Unexpected error: {exc}")
        else:
            print("  [dry] would update metadata successfully!")
            if args.thumbnails:
                print("  [dry] would upload thumbnail successfully!")
            success_count += 1

    print("-" * 70)
    print(f"Sweep complete. Successfully processed: {success_count}/{len(videos)} videos.")
    print("=" * 70)

if __name__ == "__main__":
    main()
