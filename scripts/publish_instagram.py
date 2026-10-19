from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import redact_secrets  # noqa: E402

GRAPH_API_VERSION = os.getenv('META_GRAPH_API_VERSION', 'v21.0')
GRAPH = f'https://graph.facebook.com/{GRAPH_API_VERSION}'


def required_env(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise SystemExit(f'{name} is required')
    return value


def valid_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == 'https' and bool(parsed.netloc)


def post(path: str, **kwargs):
    response = requests.post(f'{GRAPH}/{path}', timeout=90, **kwargs)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        # Requests exceptions can include the full URL, including access_token query params.
        detail = redact_secrets(response.text or exc)
        raise RuntimeError(f'Meta API request failed ({response.status_code}): {detail}') from None
    return response.json()


def wait_until_ready(media_id: str, token: str, timeout: int | None = None, wait_seconds: int | None = None) -> None:
    timeout = timeout if timeout is not None else max(120, int(os.getenv('INSTAGRAM_PROCESSING_TIMEOUT_SECONDS', '300')))
    wait_seconds = wait_seconds if wait_seconds is not None else max(1, int(os.getenv('INSTAGRAM_PROCESSING_WAIT_SECONDS', '10')))
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = requests.get(
            f'{GRAPH}/{media_id}',
            params={'access_token': token, 'fields': 'status_code,status,error_message'},
            timeout=60,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = redact_secrets(response.text or exc)
            raise RuntimeError(f'Meta status request failed ({response.status_code}): {detail}') from None
        data = response.json()
        status = data.get('status_code', '')
        if status == 'FINISHED':
            return
        if status in {'ERROR', 'EXPIRED'}:
            error_msg = data.get('error_message') or data.get('status') or 'no error details'
            raise RuntimeError(f'Instagram media processing failed: {status} ({redact_secrets(error_msg)})')
        time.sleep(wait_seconds)
    raise TimeoutError('Instagram media processing timed out')


def main() -> int:
    if os.getenv("CONFIRM_PUBLISH", "false").strip().lower() not in {"true", "1", "yes"}:
        raise SystemExit("Public Instagram publishing requires CONFIRM_PUBLISH=true")
    instagram_id = required_env('INSTAGRAM_USER_ID')
    token = required_env('FACEBOOK_ACCESS_TOKEN')
    video_url = required_env('PUBLIC_VIDEO_URL')
    caption = os.getenv('INSTAGRAM_CAPTION', '')
    if not valid_https_url(video_url):
        raise SystemExit('PUBLIC_VIDEO_URL must be a public HTTPS video URL')

    container = post(
        f'{instagram_id}/media',
        params={'access_token': token},
        data={'media_type': 'REELS', 'video_url': video_url, 'caption': caption},
    )
    media_id = container.get('id')
    if not media_id:
        raise SystemExit(f'Instagram container response did not include an id: {redact_secrets(container)}')
    wait_until_ready(media_id, token)
    published = post(
        f'{instagram_id}/media_publish',
        params={'access_token': token},
        data={'creation_id': media_id},
    )
    print({'status': 'published', 'instagram_media_id': published.get('id')})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
