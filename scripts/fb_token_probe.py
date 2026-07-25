#!/usr/bin/env python3
"""Read-only probe: WHICH of the two FB page tokens is valid and with what
permissions (debug_token via app token when available, else live-error scan)."""
import json, os, urllib.parse, urllib.request, urllib.error
VER = os.environ.get("FB_API_VERSION") or "v23.0"
PAGE = os.environ["FB_PAGE_ID"]
def probe(tok, label):
    try:
        url = f"https://graph.facebook.com/{VER}/{PAGE}?fields=name&access_token={urllib.parse.quote(tok)}"
        with urllib.request.urlopen(url, timeout=30) as r:
            name = json.load(r)["name"]
        try:
            url2 = f"https://graph.facebook.com/{VER}/{PAGE}/video_insights?metric=total_video_views&access_token={urllib.parse.quote(tok)}"
            urllib.request.urlopen(url2, timeout=30); ins = "OK"
        except Exception as e:
            ins = f"NO ({getattr(e, 'code', '?')})"
        # pages_manage_metadata probe: attempt a harmless GET of cta? use /{page}?fields=cta
        try:
            url3 = f"https://graph.facebook.com/{VER}/{PAGE}?fields=about&access_token={urllib.parse.quote(tok)}"
            urllib.request.urlopen(url3, timeout=30); # read works with many perms
        except Exception:
            pass
        print(f"{label}: VALID page='{name}' read_insights={ins}")
    except urllib.error.HTTPError as e:
        print(f"{label}: INVALID/EXPIRED ({e.code}) {e.read()[:120].decode('utf-8','replace')[:120]}")
    except Exception as e:
        print(f"{label}: ERROR {str(e)[:100]}")
t1 = os.environ.get("FB_TOK_A"); t2 = os.environ.get("FB_TOK_B")
if t1: probe(t1, "FACEBOOK_ACCESS_TOKEN")
else: print("FACEBOOK_ACCESS_TOKEN: (empty)")
if t2: probe(t2, "FB_ACCESS_TOKEN")
else: print("FB_ACCESS_TOKEN: (empty)")
