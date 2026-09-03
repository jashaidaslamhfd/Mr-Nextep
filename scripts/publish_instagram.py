from __future__ import annotations
import os
import time
import requests

GRAPH = 'https://graph.facebook.com/v23.0'
instagram_id = os.environ['INSTAGRAM_USER_ID']
token = os.environ['FACEBOOK_ACCESS_TOKEN']
video_url = os.environ['PUBLIC_VIDEO_URL']
caption = os.environ['INSTAGRAM_CAPTION']

def post(path, **kwargs):
    response = requests.post(f'{GRAPH}/{path}', timeout=90, **kwargs)
    response.raise_for_status()
    return response.json()

container = post(f'{instagram_id}/media', params={'access_token': token}, data={'media_type': 'REELS', 'video_url': video_url, 'caption': caption})
time.sleep(int(os.getenv('INSTAGRAM_PROCESSING_WAIT_SECONDS', '60')))
published = post(f'{instagram_id}/media_publish', params={'access_token': token}, data={'creation_id': container['id']})
print({'status': 'published', 'instagram_media_id': published.get('id')})
