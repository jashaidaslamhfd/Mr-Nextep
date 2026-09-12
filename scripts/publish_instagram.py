from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import requests

GRAPH = 'https://graph.facebook.com/v23.0'
instagram_id = os.environ['INSTAGRAM_USER_ID']
token = os.environ['FACEBOOK_ACCESS_TOKEN']
video_url = os.environ['PUBLIC_VIDEO_URL'].strip()
caption = os.environ['INSTAGRAM_CAPTION']
parsed_url = urlparse(video_url)
if parsed_url.scheme != 'https' or not parsed_url.netloc:
    raise SystemExit('PUBLIC_VIDEO_URL must be a public HTTPS video URL')

def post(path, **kwargs):
    response = requests.post(f'{GRAPH}/{path}', timeout=90, **kwargs)
    response.raise_for_status()
    return response.json()


def wait_until_ready(media_id: str) -> None:
    timeout = max(120, int(os.getenv('INSTAGRAM_PROCESSING_TIMEOUT_SECONDS', '300')))
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
        time.sleep(10)
    raise TimeoutError('Instagram media processing timed out')


container = post(f'{instagram_id}/media', params={'access_token': token}, data={'media_type': 'REELS', 'video_url': video_url, 'caption': caption})
wait_until_ready(container['id'])
published = post(f'{instagram_id}/media_publish', params={'access_token': token}, data={'creation_id': container['id']})
print({'status': 'published', 'instagram_media_id': published.get('id')})
