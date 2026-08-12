#!/usr/bin/env python3
"""Collect REAL metrics from all 3 platforms and compare each video's actual
performance against the system's heuristic scores.

Outputs a readable report + writes data/metrics_audit.json (one flat row per
video with real views + the scores the system assigned).

Usage:
  python scripts/metrics_report.py
  python scripts/metrics_report.py --json   # print raw json too
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _load(name, default):
    p = DATA / name
    if not p.exists():
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def norm_topic(t):
    import re
    s = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", " ", str(t or ""))
    s = re.sub(r"#[A-Za-z0-9_]+", "", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def main() -> int:
    vh = _load("video_history.json", [])
    fb = _load("facebook_real_data.json", {})

    # --- build maps by topic (normalized) for cross-referencing ---
    yt_by_topic = {}
    for v in vh:
        t = norm_topic(v.get("title") or v.get("youtube_title"))
        if t and (v.get("analytics_fetched_at") or v.get("views")):
            yt_by_topic[t] = v
    fb_by_topic = {}
    for r in (fb.get("reels") or []):
        t = norm_topic(r.get("title") or r.get("description"))
        if t:
            fb_by_topic[t] = r

    # --- build the merged audit rows ---
    rows = []
    seen = set()
    for t, v in yt_by_topic.items():
        if t in seen:
            continue
        seen.add(t)
        fbrow = fb_by_topic.get(t)
        row = {
            "topic": t[:60],
            "title": (v.get("title") or v.get("youtube_title") or ""),
            "youtube_views": v.get("views"),
            "youtube_ctr_pred": v.get("predicted_ctr"),
            "youtube_hook": v.get("hook_score"),
            "youtube_seo": v.get("seo_score"),
            "youtube_retention": v.get("predicted_retention"),
            "youtube_avg_view_pct": v.get("average_view_percentage"),
            "facebook_views": (fbrow or {}).get("views"),
            "published_at": (v.get("published_at") or v.get("posted_at") or "")[:16],
        }
        rows.append(row)

    # sort by youtube views desc
    rows.sort(key=lambda r: (r["youtube_views"] or 0), reverse=True)

    # --- write audit json ---
    (DATA / "metrics_audit.json").write_text(
        json.dumps({"generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
            "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- print report ---
    print("=" * 100)
    print("ALL-PLATFORM METRICS vs SYSTEM SCORES  (sorted by YouTube views)")
    print("=" * 100)
    print(f"{'YTviews':>7} {'hook':>5} {'ctr':>4} {'seo':>4} {'ret':>5} {'FBviews':>8} | topic")
    print("-" * 100)
    for r in rows:
        print(f"{str(r['youtube_views']):>7} {str(r['youtube_hook']):>5} "
              f"{str(r['youtube_ctr_pred']):>4} {str(r['youtube_seo']):>4} "
              f"{str(r['youtube_retention']):>5} {str(r['facebook_views']):>8} | {r['topic'][:45]}")

    # summary stats
    yv = [r["youtube_views"] or 0 for r in rows if r["youtube_views"]]
    print("\n--- SUMMARY ---")
    print(f"Videos with YouTube analytics: {len(yv)}")
    if yv:
        print(f"YouTube views: total={sum(yv)} avg={sum(yv)/len(yv):.1f} "
              f"max={max(yv)} min={min(yv)}")
    # Show the worst offenders: high score but low views
    print("\nWorst offenders (high hook>=80 but low views <50):")
    bad = [r for r in rows if (r['youtube_hook'] or 0) >= 80 and (r['youtube_views'] or 0) < 50]
    for r in bad[:15]:
        print(f"  hook={r['youtube_hook']} ctr={r['youtube_ctr_pred']} "
              f"seo={r['youtube_seo']}  -> {r['youtube_views']} views  | {r['topic'][:40]}")
    print(f"\nTotal bad (high-score/low-view): {len(bad)}")
    print("\nReport written to data/metrics_audit.json")

    # --- Facebook section ---
    print("\n" + "=" * 70)
    print("FACEBOOK REELS (real views)")
    print("=" * 70)
    fbs = sorted((fb.get("reels") or []), key=lambda r: -(r.get("views") or 0))
    for r in fbs[:15]:
        print(f"  {str(r.get('views')):>5} views | len={r.get('length')} | "
              f"{str(r.get('title') or r.get('description') or '')[:35]}")
    print(f"  FB total: {len(fbs)} reels, "
          f"{sum(r.get('views') or 0 for r in fbs)} views, "
          f"max={fbs[0]['views'] if fbs else 0}")

    # --- Instagram section ---
    ig = _load("instagram_real_data.json", {})
    print("\n" + "=" * 70)
    print("INSTAGRAM REELS (real reach)")
    print("=" * 70)
    igs = sorted((ig.get("reels") or []), key=lambda r: -(r.get("reach") or 0))
    for r in igs[:15]:
        print(f"  {str(r.get('reach')):>5} reach | {r.get('avg_watch_ms')}ms | "
              f"{str(r.get('caption',''))[:30]}")
    print(f"  IG total: {len(igs)} reels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
