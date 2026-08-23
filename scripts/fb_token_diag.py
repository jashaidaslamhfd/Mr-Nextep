#!/usr/bin/env python3
"""
FB Token Diagnostic — mobile-friendly health check for the Facebook token.

Reads the token from env (FACEBOOK_ACCESS_TOKEN or FB_ACCESS_TOKEN), calls
Meta's Graph API read-only, and prints:
  1. Token present/expired?
  2. Granted permissions (read_insights, pages_read_engagement, ...)
  3. Which Page the token manages
  4. A REAL insights probe against one uploaded Reel
  5. A clear VERDICT

The token itself is NEVER printed. Safe to run from GitHub Actions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

TOKEN = (os.environ.get("FACEBOOK_ACCESS_TOKEN") or
         os.environ.get("FB_ACCESS_TOKEN") or "").strip()
API_VERSION = os.environ.get("FB_API_VERSION", "v23.0").strip()
GRAPH = f"https://graph.facebook.com/{API_VERSION}"

WANTED = [
    "read_insights",
    "pages_read_engagement",
    "pages_manage_posts",
    "pages_show_list",
    "publish_video",
    "pages_read_user_content",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
]


def call(node: str, params: dict = None):
    p = dict(params or {})
    p["access_token"] = TOKEN
    r = requests.get(f"{GRAPH}/{node}", params=p, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:300]}
    return r.status_code, data


def main() -> int:
    print("=" * 58)
    print("FB TOKEN DIAGNOSTIC  (API " + API_VERSION + ")")
    print("=" * 58)

    if not TOKEN:
        print("❌ RESULT: FACEBOOK_ACCESS_TOKEN / FB_ACCESS_TOKEN env NOT SET.")
        print("   GitHub Actions mein secret nahi mila — secret ka naam check karo.")
        return 1

    print(f"🔑 Token present (length {len(TOKEN)}) — NOT printed for safety.\n")

    # 1) is the token alive?
    sc, me = call("me", {"fields": "id,name"})
    if sc >= 400 or "error" in me:
        msg = me.get("error", {}).get("message", f"HTTP {sc}")[:180]
        print("❌ RESULT: Token INVALID / EXPIRED / REVOKED")
        print(f"   Meta says: {msg}")
        print("   Fix: Graph API Explorer se naya long-lived Page Access Token banao.")
        return 1
    print(f"✅ Token VALID — logged in as: {me.get('name')} (id {me.get('id')})")
    me_id = me.get("id")

    # 2) granted permissions
    sc, perm = call(f"{me_id}/permissions")
    granted = set()
    if sc < 400 and "data" in perm:
        granted = {p.get("permission") for p in perm["data"]
                   if p.get("status") == "granted"}
    print("\n--- GRANTED PERMISSIONS ---")
    if not granted:
        print("  (koi permission list nahi mili — yeh usually User-token ki nishani hai)")
    for w in WANTED:
        print(f"  {'✅' if w in granted else '❌'} {w}")
    has_read_insights = "read_insights" in granted

    # 3) pages managed
    sc, acc = call("me/accounts", {"fields": "id,name,access_token"})
    pages = acc.get("data", []) if sc < 400 else []
    print(f"\n--- PAGES MANAGED ({len(pages)}) ---")
    is_page_token = False
    for p in pages:
        pt = p.get("access_token", "")
        if pt and TOKEN == pt:
            is_page_token = True
            print(f"  ✅ TOKEN IS THIS PAGE'S TOKEN → {p.get('name')} (id {p.get('id')})")
        else:
            print(f"  · {p.get('name')} (id {p.get('id')}) — alag token hai")
    if pages and not is_page_token:
        print("  → Token 'me' par hai (User token), Page par nahi.")

    # 4) real insights probe on one reel
    reel_id = _find_reel_id()
    print("\n--- REAL INSIGHTS PROBE ---")
    if not reel_id:
        print("  (data/facebook_analytics.json mein koi reel id nahi mili — probe skip)")
    else:
        print(f"  Reel: {reel_id}")
        probes_ok = 0
        for metric in ("total_video_views", "total_video_avg_time_watched",
                       "post_video_avg_time_watched"):
            s2, r2 = call(f"{reel_id}/video_insights", {"metric": metric})
            ok = s2 < 400 and "error" not in r2
            msg = "OK" if ok else str(r2.get("error", {}).get("message", f"HTTP {s2}"))[:140]
            print(f"  {metric:32} {'✅' if ok else '❌'} {msg}")
            if ok:
                probes_ok += 1

    # 5) verdict
    print("\n" + "=" * 58)
    print("VERDICT")
    print("=" * 58)
    if not has_read_insights:
        print("❌ Effective token ko 'read_insights' permission nahi mil rahi.")
        print("   Settings mein grant hone ke bawajood Page token ko refresh/reissue karein.")
        print("   Video Insights ke liye Page access token, ANALYZE task, read_insights,")
        print("   aur current API ke mutabiq pages_manage_engagement verify karein.")
        print("   Naya Page Access Token banao aur GitHub secret update karo.")
    elif is_page_token:
        print("✅ Token Page-token hai AUR read_insights granted hai.")
        print("   Agar phir bhi insights nahi aa rahe to masla token ka nahi —")
        print("   upar wali probe ke ❌ metrics ko screenshot karke batao.")
    else:
        print("⚠️  Token mein read_insights HAI lekin yeh User-token lagta hai.")
        print("   Page Access Token banao (Explorer mein 'Page' select karke).")
    print()
    return 0 if (has_read_insights and is_page_token) else 2


def _find_reel_id():
    for pth in ("data/facebook_analytics.json", "data/upload_state.json"):
        try:
            d = json.loads(Path(pth).read_text(encoding="utf-8"))
            if isinstance(d, dict):
                for v in d.values():
                    if isinstance(v, dict):
                        vid = v.get("video_id") or v.get("facebook_video_id")
                        if vid:
                            return str(vid)
        except Exception:
            continue
    return None


if __name__ == "__main__":
    sys.exit(main())
