from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SETTINGS  # noqa: E402


def collect_errors(
    settings: Any = SETTINGS,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Return non-secret configuration/runtime errors without printing credentials."""
    env = os.environ if environ is None else environ
    errors = list(settings.check_config())

    if not which("ffmpeg"):
        errors.append("ffmpeg is required")
    if not which("ffprobe"):
        errors.append("ffprobe is required")

    if not settings.dry_run:
        if not (env.get("GROQ_API_KEY", "").strip() or env.get("OPENROUTER_API_KEY", "").strip()):
            errors.append("Configure GROQ_API_KEY or OPENROUTER_API_KEY for a production run")

        client_id = env.get("GOOGLE_CLIENT_ID") or env.get("YT_CLIENT_ID")
        client_secret = env.get("GOOGLE_CLIENT_SECRET") or env.get("YT_CLIENT_SECRET")
        refresh_token = env.get("REFRESH_TOKEN") or env.get("YT_REFRESH_TOKEN")
        if not all((client_id, client_secret, refresh_token)):
            errors.append(
                "YouTube OAuth credentials missing: configure GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET and REFRESH_TOKEN (or their YT_* aliases)"
            )

        facebook_page = env.get("FACEBOOK_PAGE_ID", "").strip()
        facebook_token = env.get("FACEBOOK_ACCESS_TOKEN", "").strip()
        if bool(facebook_page) != bool(facebook_token):
            errors.append("Facebook publishing is partially configured: provide both FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN")

        instagram_id = env.get("INSTAGRAM_USER_ID", "").strip()
        if instagram_id and not facebook_token:
            errors.append("Instagram publishing requires FACEBOOK_ACCESS_TOKEN")
        if instagram_id and not env.get("PUBLIC_VIDEO_URL", "").strip():
            errors.append("INSTAGRAM_USER_ID is configured but PUBLIC_VIDEO_URL is missing")

    return errors


def main() -> int:
    errors = collect_errors()
    result = {"ok": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
