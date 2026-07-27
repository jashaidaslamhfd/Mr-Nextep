#!/usr/bin/env python3
"""One-shot read-only check: are the description CTAs varied on YouTube?

The public RSS feed serves heavily cached copies, which made an applied fix
look like it had failed. Only the Data API shows the current state.
"""
import json, os, re, urllib.parse, urllib.request
from collections import Counter

API = "https://www.googleapis.com/youtube/v3"

def token():
    d = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=d), timeout=30))["access_token"]

def get(url, tok):
    r = urllib.request.Request(url)
    r.add_header("Authorization", f"Bearer {tok}")
    return json.load(urllib.request.urlopen(r, timeout=45))

tok = token()
ch = get(f"{API}/channels?part=contentDetails&mine=true", tok)
up = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
ids, page = [], None
while True:
    u = f"{API}/playlistItems?part=contentDetails&playlistId={up}&maxResults=50"
    if page: u += f"&pageToken={page}"
    d = get(u, tok)
    ids += [i["contentDetails"]["videoId"] for i in d.get("items", [])]
    page = d.get("nextPageToken")
    if not page: break

closers, broken = Counter(), 0
for i in range(0, len(ids), 50):
    d = get(f"{API}/videos?part=snippet&id={','.join(ids[i:i+50])}", tok)
    for it in d.get("items", []):
        desc = it["snippet"].get("description", "")
        m = re.search(r"(Follow for [^\n]+|Subscribe for [^\n]+|More everyday[^\n]+)", desc)
        if m: closers[m.group(0).strip()] += 1
        for line in desc.split("\n"):
            if line.strip().startswith("#") and any(not t.startswith("#") for t in line.split()):
                broken += 1

print(f"videos checked      : {len(ids)}")
print(f"unique closing lines: {len(closers)}")
for k, v in closers.most_common():
    print(f"  {v:>3}x  {k[:66]}")
print(f"broken hashtag lines: {broken}")
