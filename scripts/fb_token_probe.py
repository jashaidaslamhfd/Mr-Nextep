#!/usr/bin/env python3
"""Read-only probe: scans EVERY candidate secret name where a Facebook token
could have been pasted, and for each non-empty one reports:
  - does it resolve the Mr. Nextep page?
  - read_insights?      (reel view analytics)
  - read page posts?    (pages_read_engagement)
  - page-level insights (read_insights alt path)
The pipeline/tune-up workflows ONLY read FACEBOOK_ACCESS_TOKEN and
FB_ACCESS_TOKEN — a token pasted under ANY other name stays invisible to them.
"""
import json, os, urllib.parse, urllib.request, urllib.error

VER = os.environ.get("FB_API_VERSION") or "v23.0"
PAGE = os.environ["FB_PAGE_ID"]

# (label, env var in this job) — workflow maps secrets.* into these
CANDIDATES = [
    ("FACEBOOK_ACCESS_TOKEN", "FB_TOK_A"),
    ("FB_ACCESS_TOKEN", "FB_TOK_B"),
    ("FB_TOKEN", "FB_TOK_C"),
    ("META_ACCESS_TOKEN", "FB_TOK_D"),
    ("FACEBOOK_PAGE_TOKEN", "FB_TOK_E"),
    ("PAGE_ACCESS_TOKEN", "FB_TOK_F"),
    ("FB_PAGE_ACCESS_TOKEN", "FB_TOK_G"),
    ("INSTAGRAM_ACCESS_TOKEN", "FB_TOK_H"),
    ("META_TOKEN", "FB_TOK_I"),
    ("FACEBOOK_TOKEN", "FB_TOK_J"),
]


def _try(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        return None, str(e)[:40]


def probe(tok, label):
    q = urllib.parse.quote(tok)
    page, err = _try(f"https://graph.facebook.com/{VER}/{PAGE}?fields=name&access_token={q}")
    if err:
        print(f"{label}: INVALID/EXPIRED ({err})")
        return
    caps = [f"page='{page['name']}'"]
    _, ins = _try(f"https://graph.facebook.com/{VER}/{PAGE}/video_insights?metric=total_video_views&access_token={q}")
    caps.append(f"read_insights={'OK' if not ins else f'NO ({ins})'}")
    _, posts = _try(f"https://graph.facebook.com/{VER}/{PAGE}/posts?limit=1&access_token={q}")
    caps.append(f"read_posts={'OK' if not posts else f'NO ({posts})'}")
    _, pgins = _try(f"https://graph.facebook.com/{VER}/{PAGE}/insights?metric=page_impressions&access_token={q}")
    caps.append(f"page_insights={'OK' if not pgins else f'NO ({pgins})'}")
    print(f"{label}: " + " | ".join(caps))


found = 0
for label, env in CANDIDATES:
    tok = os.environ.get(env, "").strip()
    if tok:
        found += 1
        probe(tok, label)
    else:
        print(f"{label}: (empty)")
print(f"\nSCAN RESULT: {found} secret(s) contain a token.")
if found:
    print("NOTE: the pipeline reads ONLY 'FACEBOOK_ACCESS_TOKEN' and 'FB_ACCESS_TOKEN'.")
