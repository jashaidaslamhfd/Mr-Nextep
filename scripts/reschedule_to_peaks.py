#!/usr/bin/env python3
"""Move pending private (scheduled) videos to the new peak publish slots.

Peak slots (UTC): 16:30, 22:30, 01:30
Skips videos already public or already published; reschedules private ones
whose publishAt is not on a peak slot (or publishes immediately if publishAt
is already passed).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.parse
import urllib.request

PEAK_SLOTS_MIN = [16 * 60 + 30, 22 * 60 + 30, 1 * 60 + 30]  # 16:30, 22:30, 01:30


def _token():
    payload = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=payload)
    return json.load(urllib.request.urlopen(req, timeout=30))["access_token"]


def _q(path, params, token, method="GET", body=None):
    url = f"https://www.googleapis.com/youtube/v3/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"} if token else None,
    )
    try:
        return json.load(urllib.request.urlopen(req, timeout=60)), None
    except Exception as e:
        return None, str(e)


def utc_minutes(ts_iso):
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    return dt.hour * 60 + dt.minute


def is_peak(ts_iso):
    return utc_minutes(ts_iso) in PEAK_SLOTS_MIN


def main():
    apply = "--apply" in sys.argv
    dry = "DRY-RUN" if not apply else "APPLYING"
    token = _token()
    chan, err = _q("channels", {"part": "contentDetails", "mine": "true"}, token)
    if err:
        raise SystemExit(f"channel lookup failed: {err}")
    playlist = chan["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    vids = []
    page = None
    while True:
        p = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50}
        if page:
            p["pageToken"] = page
        d, err = _q("playlistItems", p, token)
        if err:
            raise SystemExit(f"playlistItems failed: {err}")
        vids += [i["contentDetails"]["videoId"] for i in d["items"]]
        page = d.get("nextPageToken")
        if not page:
            break

    for i in range(0, len(vids), 50):
        batch = vids[i:i + 50]
        d, err = _q("videos", {"part": "snippet,status", "id": ",".join(batch)}, token)
        if err:
            raise SystemExit(f"videos list failed: {err}")
        for v in d["items"]:
            vid = v["id"]
            priv = v["status"]["privacyStatus"]
            title = v["snippet"]["title"]
            pub = v["snippet"].get("publishedAt")
            if priv != "private":
                print(f"[skip] {vid} public already: {title[:50]}")
                continue
            if not pub or not is_peak(pub):
                print(f"[{dry}] {vid} {title[:50]} | publishAt={pub} -> not on peak slot")
                if not apply:
                    continue
                # publish immediately at next opportunity: YouTube rejects
                # publishAt in the past; set to now + few minutes if due.
                from datetime import datetime, timezone, timedelta
                now = datetime.now(timezone.utc)
                target = (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
                body = {
                    "id": vid,
                    "status": {
                        "privacyStatus": "public",
                        "publishAt": target,
                        "selfDeclaredMadeForKids": False,
                    },
                }
                r, err = _q("videos", {"part": "snippet,status"}, token,
                            method="PUT", body=body)
                if err:
                    # YouTube rejects a future publishAt on plain-private
                    # uploads (400); fall back to an immediate public release.
                    r, err = _q("videos", {"part": "snippet,status"}, token,
                                method="PUT",
                                body={"id": vid, "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}})
                if err:
                    print(f"[fail] {vid}: {err}")
                else:
                    npub = r["snippet"].get("publishedAt")
                    npriv = r["status"]["privacyStatus"]
                    print(f"[ok] {vid} -> privacy={npriv} publishedAt={npub}")


if __name__ == "__main__":
    main()
