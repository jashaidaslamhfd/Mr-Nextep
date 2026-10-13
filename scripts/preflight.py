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


def _configured(env: Mapping[str, str], *names: str) -> bool:
    """Return whether at least one accepted alias is non-empty, without exposing it."""
    return any(str(env.get(name, "") or "").strip() for name in names)


def collect_errors(
    settings: Any = SETTINGS,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Return actionable, non-secret configuration/runtime errors."""
    env = os.environ if environ is None else environ
    errors = list(settings.check_config())

    if not which("ffmpeg"):
        errors.append("ffmpeg is required but was not found on PATH")
    if not which("ffprobe"):
        errors.append("ffprobe is required but was not found on PATH")

    if not settings.dry_run:
        if not _configured(env, "GROQ_API_KEY", "OPENROUTER_API_KEY"):
            errors.append(
                "Missing LLM provider credential: set GROQ_API_KEY or OPENROUTER_API_KEY "
                "in repository Settings > Secrets and variables > Actions"
            )

        credential_groups = (
            (("GOOGLE_CLIENT_ID", "YT_CLIENT_ID"), "Google OAuth client ID", "GOOGLE_CLIENT_ID or YT_CLIENT_ID"),
            (("GOOGLE_CLIENT_SECRET", "YT_CLIENT_SECRET"), "Google OAuth client secret", "GOOGLE_CLIENT_SECRET or YT_CLIENT_SECRET"),
            (("REFRESH_TOKEN", "YT_REFRESH_TOKEN"), "YouTube OAuth refresh token", "REFRESH_TOKEN or YT_REFRESH_TOKEN"),
        )
        missing = [
            description
            for aliases, description, _hint in credential_groups
            if not _configured(env, *aliases)
        ]
        if missing:
            hints = [
                hint
                for aliases, _description, hint in credential_groups
                if not _configured(env, *aliases)
            ]
            errors.append(
                "Missing YouTube OAuth credential(s): "
                + ", ".join(missing)
                + ". Configure "
                + ", ".join(hints)
                + " in repository Actions secrets."
            )

        facebook_page = str(env.get("FACEBOOK_PAGE_ID", "") or "").strip()
        facebook_token = str(env.get("FACEBOOK_ACCESS_TOKEN", "") or "").strip()
        if bool(facebook_page) != bool(facebook_token):
            errors.append(
                "Facebook publishing is partially configured: provide both "
                "FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN, or leave both empty"
            )

        instagram_id = str(env.get("INSTAGRAM_USER_ID", "") or "").strip()
        if instagram_id and not facebook_token:
            errors.append(
                "Instagram publishing is configured but FACEBOOK_ACCESS_TOKEN is empty"
            )
        # PUBLIC_VIDEO_URL is optional: src.meta.publish() hosts the rendered MP4
        # on a per-run GitHub Release when no external HTTPS URL is configured.
        # Keep the secret optional so a missing URL does not block YouTube/Facebook.

    return errors


def main() -> int:
    errors = collect_errors()
    result = {"ok": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
