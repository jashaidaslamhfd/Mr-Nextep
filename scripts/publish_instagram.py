from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import requests

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
    response.raise_for_status()
    return response.json()


def wait_until_ready(media_id: str, token: str, timeout: int | None = None, wait_seconds: int | None = None) -> None:
    timeout = timeout if timeout is not None else max(120, int(os.getenv('INSTAGRAM_PROCESSING_TIMEOUT_SECONDS', '300')))
    wait_seconds = wait_seconds if wait_seconds is not None else max(1, int(os.getenv('INSTAGRAM_PROCESSING_WAIT_SECONDS', '10')))
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = requests.get(
            f'{GRAPH}/{media_id}',
            params={'access_token': token, 'fields': 'status_code'},
            timeout=60,
        )
        response.raise_for_status()
        status = response.json().get('status_code', '')
        if status == 'FINISHED':
            return
        if status in {'ERROR', 'EXPIRED'}:
            raise RuntimeError(f'Instagram media processing failed: {status}')
        time.sleep(wait_seconds)
    raise TimeoutError('Instagram media processing timed out')


def main() -> int:
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
        raise SystemExit(f'Instagram container response did not include an id: {container}')
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
