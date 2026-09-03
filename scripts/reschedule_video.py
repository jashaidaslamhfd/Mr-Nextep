from __future__ import annotations
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

video_id = os.environ['VIDEO_ID']
publish_at = os.environ['PUBLISH_AT']
creds = Credentials(None, refresh_token=os.environ['REFRESH_TOKEN'], token_uri='https://oauth2.googleapis.com/token', client_id=os.environ['GOOGLE_CLIENT_ID'], client_secret=os.environ['GOOGLE_CLIENT_SECRET'], scopes=['https://www.googleapis.com/auth/youtube'])
creds.refresh(Request())
youtube = build('youtube', 'v3', credentials=creds, cache_discovery=False)
item = youtube.videos().list(part='status', id=video_id).execute().get('items')
if not item: raise SystemExit(f'Video not found: {video_id}')
youtube.videos().update(part='status', body={'id': video_id, 'status': {'privacyStatus': 'private', 'publishAt': publish_at, 'selfDeclaredMadeForKids': item[0]['status'].get('selfDeclaredMadeForKids', False)}}).execute()
print({'video_id': video_id, 'publish_at': publish_at, 'url': f'https://youtu.be/{video_id}'})
