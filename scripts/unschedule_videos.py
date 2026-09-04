from __future__ import annotations
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
ids=[x.strip() for x in os.getenv('UNSCHEDULE_IDS','').split(',') if x.strip()]
if not ids: raise SystemExit('UNSCHEDULE_IDS is required')
creds=Credentials(None,refresh_token=os.environ['REFRESH_TOKEN'],token_uri='https://oauth2.googleapis.com/token',client_id=os.environ['GOOGLE_CLIENT_ID'],client_secret=os.environ['GOOGLE_CLIENT_SECRET'],scopes=['https://www.googleapis.com/auth/youtube'])
creds.refresh(Request()); yt=build('youtube','v3',credentials=creds,cache_discovery=False)
for video_id in ids:
    items=yt.videos().list(part='status',id=video_id).execute().get('items',[])
    if not items: raise SystemExit(f'Video not found: {video_id}')
    s=items[0]['status']; yt.videos().update(part='status',body={'id':video_id,'status':{'privacyStatus':'private','selfDeclaredMadeForKids':s.get('selfDeclaredMadeForKids',False)}}).execute()
    print({'video_id':video_id,'status':'private_unscheduled'})
