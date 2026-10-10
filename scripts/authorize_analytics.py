#!/usr/bin/env python3
"""Create a local YouTube OAuth refresh token with upload + read-only analytics scopes.

Run locally after setting GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in an ignored .env.
The token is written to .secrets/youtube-oauth.json with restrictive file permissions.
Never commit or share that file.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]
OUTPUT = Path(".secrets/youtube-oauth.json")


def main() -> int:
    load_dotenv()
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit(
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your local ignored .env first."
        )

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    credentials = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message="Open this URL to authorize Mr-Nextep analytics access: {url}",
        success_message="Authorization complete. You may close this browser tab.",
    )
    if not credentials.refresh_token:
        raise SystemExit(
            "Google did not return a refresh token. Revoke this app's access in your Google "
            "Account and run again with prompt=consent."
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(credentials.to_json(), encoding="utf-8")
    try:
        OUTPUT.chmod(0o600)
    except OSError:
        pass
    print(f"Saved OAuth credentials locally to {OUTPUT}. Do not commit or share this file.")
    print("Open the file locally and copy only the refresh_token value into GitHub Actions Secret REFRESH_TOKEN.")
    print("Keep GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in their existing GitHub Actions secrets.")
    print("This file includes sensitive OAuth material; keep it private and delete it after updating GitHub Secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
