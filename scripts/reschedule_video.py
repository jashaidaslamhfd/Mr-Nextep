from __future__ import annotations

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from youtube_inputs import require_publish_at, require_video_id


def main() -> int:
    video_id = require_video_id(os.getenv('VIDEO_ID', ''))
    publish_at = require_publish_at(os.getenv('PUBLISH_AT', ''))
    refresh_token = (os.getenv('REFRESH_TOKEN') or os.getenv('YT_REFRESH_TOKEN', '')).strip()
    client_id = (os.getenv('GOOGLE_CLIENT_ID') or os.getenv('YT_CLIENT_ID', '')).strip()
    client_secret = (os.getenv('GOOGLE_CLIENT_SECRET') or os.getenv('YT_CLIENT_SECRET', '')).strip()
    if not (refresh_token and client_id and client_secret):
        raise SystemExit('Missing YouTube credentials: REFRESH_TOKEN/GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET')

    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=client_id,
        client_secret=client_secret,
        scopes=['https://www.googleapis.com/auth/youtube'],
    )
    creds.refresh(Request())
    youtube = build('youtube', 'v3', credentials=creds, cache_discovery=False)
    item = youtube.videos().list(part='status', id=video_id).execute().get('items')
    if not item:
        raise SystemExit(f'Video not found: {video_id}')
    youtube.videos().update(
        part='status',
        body={
            'id': video_id,
            'status': {
                'privacyStatus': 'private',
                'publishAt': publish_at,
                'selfDeclaredMadeForKids': item[0]['status'].get('selfDeclaredMadeForKids', False),
            },
        },
    ).execute()
    print({'video_id': video_id, 'publish_at': publish_at, 'url': f'https://youtu.be/{video_id}'})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
