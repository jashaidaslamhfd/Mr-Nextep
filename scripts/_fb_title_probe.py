#!/usr/bin/env python3
"""Read back title+description for a few Reels straight from Graph API."""
import json, os, urllib.parse, urllib.request
API=os.environ.get("FB_API_VERSION","v23.0")
TOKEN=(os.environ.get("FB_ACCESS_TOKEN") or "").strip()
PAGE=os.environ.get("FB_PAGE_ID","").strip()
def g(path,**p):
    p["access_token"]=TOKEN
    with urllib.request.urlopen(f"https://graph.facebook.com/{API}/{path}?{urllib.parse.urlencode(p)}",timeout=45) as r:
        return json.load(r)
d=g(f"{PAGE}/video_reels", limit=8, fields="id,title,description,created_time")
for it in d.get("data",[]):
    t=it.get("title")
    print(f"  {it['id'][:17]}  title={'(EMPTY)' if not t else repr(t)[:52]}")
    print(f"       desc1={(it.get('description') or '').splitlines()[0][:56] if it.get('description') else ''}")
