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


IG_ID_CANDIDATES = [
    ("INSTAGRAM_USER_ID", "IG_ID_A"),
    ("IG_USER_ID", "IG_ID_B"),
    ("INSTAGRAM_BUSINESS_ACCOUNT_ID", "IG_ID_C"),
    ("IG_BUSINESS_ACCOUNT_ID", "IG_ID_D"),
    ("INSTAGRAM_ACCOUNT_ID", "IG_ID_E"),
    ("IG_ACCOUNT_ID", "IG_ID_F"),
]


def probe_ig(ig_id, label, tok):
    q = urllib.parse.quote(tok)
    data, err = _try(
        f"https://graph.facebook.com/{VER}/{ig_id}"
        f"?fields=username,name,followers_count,ig_id&access_token={q}")
    if err:
        print(f"{label}: id present but NOT readable via token ({err})")
        return
    print(f"{label}: INSTAGRAM OK -> @{data.get('username')} "
          f"(name={data.get('name')}, followers={data.get('followers_count')}, "
          f"ig_id={data.get('ig_id', data.get('id'))})")


found = 0
best_token = ""
best_score = -1
for label, env in CANDIDATES:
    tok = os.environ.get(env, "").strip()
    if tok:
        found += 1
        probe(tok, label)
        q = urllib.parse.quote(tok)
        _, err = _try(f"https://graph.facebook.com/{VER}/{PAGE}?fields=name&access_token={q}")
        if not err:
            score = 1
            _, ins = _try(f"https://graph.facebook.com/{VER}/{PAGE}/insights?metric=page_impressions&access_token={q}")
            if not ins:
                score = 2
            if score > best_score:
                best_score, best_token = score, tok
    else:
        print(f"{label}: (empty)")
print(f"\nSCAN RESULT: {found} token secret(s).")
if found:
    print("NOTE: the pipeline reads ONLY 'FACEBOOK_ACCESS_TOKEN' and 'FB_ACCESS_TOKEN'.")
    print("\n[FIX] If read_insights=NO, do this:")
    print("1. https://developers.facebook.com/tools/explorer/")
    print("2. Select app + Mr. Nextep page (1122980080905302)")
    print("3. Add: read_insights, pages_read_engagement, pages_show_list, pages_manage_posts, instagram_basic, instagram_manage_insights")
    print("4. Generate NEW Page Access Token -> save as FACEBOOK_ACCESS_TOKEN + FB_ACCESS_TOKEN")
    print("5. Re-run probe -> should show read_insights=OK")
else:
    print("No token found - add FACEBOOK_ACCESS_TOKEN secret")

print("\n--- INSTAGRAM scan ---")
for label, env in IG_ID_CANDIDATES:
    ig_id = os.environ.get(env, "").strip()
    if ig_id and best_token:
        probe_ig(ig_id, label, best_token)
    elif ig_id:
        print(f"{label}: id present but no working FB token to test it with")
    else:
        print(f"{label}: (empty)")
