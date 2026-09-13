from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SETTINGS  # noqa: E402

errors = SETTINGS.check_config()

if not shutil.which("ffmpeg"):
    errors.append("ffmpeg is required")
if not shutil.which("ffprobe"):
    errors.append("ffprobe is required")

if not SETTINGS.dry_run:
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not groq_key and not openrouter_key:
        errors.append("Neither GROQ_API_KEY nor OPENROUTER_API_KEY is configured for production run")

    client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("YT_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("YT_CLIENT_SECRET")
    refresh_token = os.getenv("REFRESH_TOKEN") or os.getenv("YT_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        errors.append("YouTube OAuth credentials missing (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, REFRESH_TOKEN)")

if errors:
    print({"ok": False, "errors": errors})
    raise SystemExit(1)

print({"ok": True, "errors": []})
