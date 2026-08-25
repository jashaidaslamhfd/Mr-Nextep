"""
video_optimizer.py — Diagnose and fix dead/low-performing YouTube, Facebook,
and Instagram videos.

Root causes addressed:
  1. Completion rate too low (<50%) → YouTube won't push
  2. Over-saturation (5-7/day) → algorithm spam-flag
  3. Weak/missing metadata (titles, descriptions, tags)
  4. Duplicate generic titles ("Why Your Body Does This: X 😳")
  5. Facebook/Instagram uploads never completed
"""

import json
import logging
import os
import re
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HISTORY_PATH = os.environ.get("VIDEO_HISTORY_PATH", "data/video_history.json")
METRICS_PATH = "data/platform_metrics.json"
OPTIMIZER_REPORT_PATH = "data/optimizer_report.json"

# ── Thresholds ────────────────────────────────────────────────────────────
MIN_COMPLETION_YT = 0.50       # YouTube needs 50%+ to push
MIN_COMPLETION_META = 0.30     # Meta needs 30%+ for decent distribution
MIN_VIEWS_VIABLE_YT = 10       # Below this = dead
MIN_VIEWS_VIABLE_META = 5      # Below this = dead
MAX_UPLOADS_PER_DAY = 2        # Spam threshold — YouTube penalises >3/day
MIN_HOOK_SCORE = 78            # Below this = weak hook = poor retention
MIN_SEO_SCORE = 75             # Below this = poor discoverability
TITLE_DUPLICATE_THRESHOLD = 3  # ≥3 videos with same pattern = spam risk

# ── Title patterns to fix ─────────────────────────────────────────────────
WEAK_TITLE_PATTERNS = [
    (r"^Why Your Body Does This:", "Generic prefix — hurts CTR"),
    (r"^Body Glitch #\d+:", "Numbered prefix — low curiosity"),
    (r"🫀\s*$", "Redundant emoji suffix"),
    (r"😴\s*$", "Sleep emoji = low energy signal"),
    (r"😳\s*$", "Shocked emoji overused across catalog"),
]


def _safe_int(v, default=0):
    return v if isinstance(v, (int, float)) else default


def _load_json(path: str) -> Any:
    if not os.path.exists(path):
        return {} if "metric" in path.lower() or "report" in path.lower() else []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _get_title(v: dict) -> str:
    return v.get("title") or v.get("youtube_title") or v.get("topic") or "Unknown"


def _get_yt_id(v: dict) -> str:
    return v.get("youtube_video_id") or v.get("youtube_id") or ""


# ── Diagnosis ─────────────────────────────────────────────────────────────

def diagnose_all() -> dict:
    """Run full diagnosis on every video and return a structured report."""
    videos = _load_json(HISTORY_PATH)
    metrics = _load_json(METRICS_PATH)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(videos),
        "summary": {},
        "issues": [],
        "dead_videos": [],
        "low_performers": [],
        "spam_risk_days": [],
        "title_issues": [],
        "fixable_videos": [],
    }

    yt_dead = []
    yt_low = []
    fb_dead = []
    ig_dead = []
    weak_hooks = []
    weak_seo = []
    low_completion = []
    no_upload = []
    title_issues = []

    for v in videos:
        fp = v.get("content_fingerprint", "")
        title = _get_title(v)
        yt_id = _get_yt_id(v)
        m = metrics.get(fp, {})
        yt = m.get("youtube_shorts", {}) or {}
        fb = m.get("facebook_reels", {}) or {}
        ig = m.get("instagram_reels", {}) or {}

        yt_views = _safe_int(yt.get("views"))
        fb_views = _safe_int(fb.get("views"))
        ig_views = _safe_int(ig.get("views"))
        yt_comp = _safe_int(yt.get("completion"))
        fb_comp = _safe_int(fb.get("completion"))
        hook = _safe_int(v.get("hook_score"))
        seo = _safe_int(v.get("seo_score"))
        fb_success = v.get("facebook_success", False)
        ig_success = v.get("instagram_success", False)

        # ── YouTube dead ──
        if not yt_id:
            no_upload.append({"title": title, "fp": fp, "reason": "no_youtube_id"})
        elif yt_views <= MIN_VIEWS_VIABLE_YT and yt_comp == 0:
            yt_dead.append({
                "title": title, "fp": fp, "yt_id": yt_id,
                "views": yt_views, "hook": hook, "seo": seo,
                "posted_at": v.get("posted_at", ""),
            })
        elif yt_views > 0 and yt_comp < MIN_COMPLETION_YT:
            low_completion.append({
                "title": title, "fp": fp, "yt_id": yt_id,
                "views": yt_views, "completion": yt_comp,
                "retention_pct": f"{yt_comp:.0%}",
            })
        elif yt_views > 0 and yt_views < 100:
            yt_low.append({
                "title": title, "fp": fp, "yt_id": yt_id,
                "views": yt_views, "completion": yt_comp,
            })

        # ── Facebook dead ──
        if not fb_views and not fb_success:
            fb_dead.append({"title": title, "fp": fp, "reason": "no_fb_data"})

        # ── Instagram dead ──
        if not ig_views and not ig_success:
            ig_dead.append({"title": title, "fp": fp})

        # ── Weak hook ──
        if hook and 0 < hook < MIN_HOOK_SCORE:
            weak_hooks.append({"title": title, "hook_score": hook, "fp": fp})

        # ── Weak SEO ──
        if seo and 0 < seo < MIN_SEO_SCORE:
            weak_seo.append({"title": title, "seo_score": seo, "fp": fp})

        # ── Title issues ──
        for pattern, reason in WEAK_TITLE_PATTERNS:
            if re.search(pattern, title):
                title_issues.append({"title": title, "pattern": pattern, "reason": reason, "fp": fp})
                break

    # ── Upload frequency analysis ──
    from collections import Counter
    date_counts = Counter()
    for v in videos:
        pa = v.get("posted_at", "")
        if pa:
            date_counts[pa[:10]] += 1

    spam_days = [
        {"date": d, "count": c}
        for d, c in sorted(date_counts.items())
        if c > MAX_UPLOADS_PER_DAY
    ]

    # ── Duplicate title patterns ──
    title_groups = Counter()
    for v in videos:
        t = _get_title(v)
        normalized = re.sub(r"[🫀😴😳🧠👂]+", "", t).strip().lower()
        normalized = re.sub(r"\s+", " ", normalized)
        title_groups[normalized] += 1

    duplicate_patterns = [
        {"pattern": p, "count": c}
        for p, c in title_groups.most_common(10)
        if c >= TITLE_DUPLICATE_THRESHOLD
    ]

    report["summary"] = {
        "yt_dead": len(yt_dead),
        "yt_low": len(yt_low),
        "fb_dead": len(fb_dead),
        "ig_dead": len(ig_dead),
        "weak_hooks": len(weak_hooks),
        "weak_seo": len(weak_seo),
        "low_completion": len(low_completion),
        "no_upload": len(no_upload),
        "spam_days": len(spam_days),
        "title_issues": len(title_issues),
        "duplicate_title_patterns": len(duplicate_patterns),
    }

    report["dead_videos"] = yt_dead
    report["low_performers"] = low_completion
    report["yt_low_views"] = yt_low
    report["fb_dead"] = fb_dead
    report["ig_dead"] = ig_dead
    report["weak_hooks"] = weak_hooks
    report["weak_seo"] = weak_seo
    report["no_upload"] = no_upload
    report["spam_risk_days"] = spam_days
    report["title_issues"] = title_issues
    report["duplicate_title_patterns"] = duplicate_patterns

    return report


# ── Fix Generation ────────────────────────────────────────────────────────

def generate_fixes(report: dict) -> dict:
    """From the diagnosis, generate actionable fixes."""
    fixes = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_fixes": [],
        "metadata_fixes": [],
        "schedule_fixes": [],
        "revival_candidates": [],
    }

    # ── Pipeline fixes for future videos ──
    fixes["pipeline_fixes"] = [
        {
            "id": "F1",
            "area": "upload_rate",
            "problem": f"{report['summary'].get('spam_days', 0)} days had >{MAX_UPLOADS_PER_DAY} uploads/day",
            "fix": f"Hard cap: max {MAX_UPLOADS_PER_DAY} videos per day in main.py pipeline",
            "impact": "Prevents algorithm spam-flag — biggest single lever for new videos",
            "code_change": "Add daily_upload_limit() check at pipeline start",
        },
        {
            "id": "F2",
            "area": "completion_gate",
            "problem": f"{report['summary'].get('low_completion', 0)} videos with <{MIN_COMPLETION_YT:.0%} completion",
            "fix": f"Raise retention gate from current to {MIN_COMPLETION_YT:.0%} minimum",
            "impact": "Only publishes videos YouTube will actually push",
            "code_change": "Update MIN_RETENTION_PCT in algorithm_policy.py",
        },
        {
            "id": "F3",
            "area": "hook_enforcement",
            "problem": f"{report['summary'].get('weak_hooks', 0)} videos with hook score <{MIN_HOOK_SCORE}",
            "fix": f"Enforce MIN_HOOK_SCORE={MIN_HOOK_SCORE} before publishing",
            "impact": "Kills weak hooks before they waste an upload slot",
            "code_change": "Add hook_score gate in viral_optimizer.py",
        },
        {
            "id": "F4",
            "area": "title_variety",
            "problem": f"{report['summary'].get('duplicate_title_patterns', 0)} duplicate title patterns",
            "fix": "Enforce unique title patterns — no 2 consecutive videos with same prefix",
            "impact": "Avoids audience fatigue and algorithm repetition penalty",
            "code_change": "Add title variety check in main.py before publish",
        },
        {
            "id": "F5",
            "area": "meta_upload_recovery",
            "problem": f"{report['summary'].get('fb_dead', 0)} Facebook + {report['summary'].get('ig_dead', 0)} Instagram dead",
            "fix": "Add retry queue for failed Meta uploads — re-upload on next pipeline run",
            "impact": "Recover ~120+ dead Facebook/Instagram Reels",
            "code_change": "Add meta_recovery_queue.json processing in main.py",
        },
    ]

    # ── Schedule fixes ──
    fixes["schedule_fixes"] = [
        {
            "id": "S1",
            "problem": "Some days had 5-7 uploads — YouTube spam-throttled the channel",
            "fix": "Reduce to max 2 uploads/day, 6-8 hours apart",
            "detail": "YouTube's spam threshold is ~3 Shorts/day. Stay at 2 for safety margin.",
        },
        {
            "id": "S2",
            "problem": "No cooldown after burst days",
            "fix": "Add 24h cooldown if >2 videos posted in last 24h",
            "detail": "Prevents consecutive burst uploads from compounding the spam flag",
        },
    ]

    # ── Metadata fixes for existing dead videos ──
    for v in report.get("dead_videos", [])[:30]:
        fixes["metadata_fixes"].append({
            "fp": v["fp"],
            "yt_id": v.get("yt_id", ""),
            "title": v["title"],
            "current_hook": v.get("hook"),
            "current_seo": v.get("seo"),
            "action": "re_optimize_metadata",
            "notes": "Update tags, description, pinned comment if YouTube allows edits via API",
        })

    # ── Revival candidates (dead but with decent hook/seo) ──
    for v in report.get("dead_videos", []):
        hook = v.get("hook", 0) or 0
        seo = v.get("seo", 0) or 0
        if hook >= 80 or seo >= 80:
            fixes["revival_candidates"].append({
                "fp": v["fp"],
                "yt_id": v.get("yt_id", ""),
                "title": v["title"],
                "hook": hook,
                "seo": seo,
                "strategy": "reshare_via_end_screen + new_thumbnail",
            })

    return fixes


# ── Pipeline Hard Limits ──────────────────────────────────────────────────

def check_daily_upload_limit() -> Tuple[bool, str]:
    """Check if we've hit the daily upload limit. Returns (allowed, reason)."""
    videos = _load_json(HISTORY_PATH)
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    today_count = sum(
        1 for v in videos
        if (v.get("posted_at") or "").startswith(today)
    )

    if today_count >= MAX_UPLOADS_PER_DAY:
        return False, f"Daily limit reached: {today_count}/{MAX_UPLOADS_PER_DAY} videos today"

    recent_24h = sum(
        1 for v in videos
        if v.get("posted_at") and _is_within_hours(v["posted_at"], 24, now)
    )
    if recent_24h >= MAX_UPLOADS_PER_DAY:
        return False, f"24h limit reached: {recent_24h} videos in last 24h"

    return True, f"OK: {today_count} videos today, {recent_24h} in last 24h"


def _is_within_hours(iso_str: str, hours: int, now: datetime) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds() < hours * 3600
    except Exception:
        return False


# ── Completion Rate Optimizer ─────────────────────────────────────────────

def get_completion_diagnosis() -> dict:
    """Detailed breakdown of why videos have low completion."""
    videos = _load_json(HISTORY_PATH)
    metrics = _load_json(METRICS_PATH)

    diagnosis = {
        "avg_yt_completion": 0,
        "avg_fb_completion": 0,
        "videos_below_50pct": [],
        "videos_above_50pct": [],
        "root_causes": [],
    }

    yt_comps = []
    fb_comps = []

    for v in videos:
        fp = v.get("content_fingerprint", "")
        m = metrics.get(fp, {})
        yt = m.get("youtube_shorts", {}) or {}
        fb = m.get("facebook_reels", {}) or {}

        yt_c = _safe_int(yt.get("completion"))
        fb_c = _safe_int(fb.get("completion"))
        yt_v = _safe_int(yt.get("views"))

        if yt_c > 0:
            yt_comps.append(yt_c)
            entry = {
                "title": _get_title(v),
                "completion": f"{yt_c:.0%}",
                "views": yt_v,
            }
            if yt_c < MIN_COMPLETION_YT:
                diagnosis["videos_below_50pct"].append(entry)
            else:
                diagnosis["videos_above_50pct"].append(entry)

        if fb_c > 0:
            fb_comps.append(fb_c)

    if yt_comps:
        diagnosis["avg_yt_completion"] = f"{sum(yt_comps)/len(yt_comps):.0%}"
    if fb_comps:
        diagnosis["avg_fb_completion"] = f"{sum(fb_comps)/len(fb_comps):.0%}"

    # Root causes
    below_50 = len(diagnosis["videos_below_50pct"])
    above_50 = len(diagnosis["videos_above_50pct"])
    total_with_data = below_50 + above_50

    if total_with_data > 0:
        pct_below = below_50 / total_with_data * 100
        diagnosis["root_causes"] = [
            f"{pct_below:.0f}% of videos with data have <50% completion",
            "YouTube Shorts algorithm requires >50% for push — below this = dead",
            "Likely causes: weak hooks (first 2s), slow pacing, too-long videos",
            "Fix: raise retention gate, enforce hook score, cut video length to 25-35s",
        ]

    return diagnosis


# ── Main entry point ──────────────────────────────────────────────────────

def run_optimization() -> dict:
    """Full optimization cycle: diagnose → fix → report."""
    logger.info("Running video_optimizer diagnostics...")

    report = diagnose_all()
    fixes = generate_fixes(report)
    completion = get_completion_diagnosis()

    full_report = {
        "diagnosis": report,
        "fixes": fixes,
        "completion_analysis": completion,
    }

    _save_json(OPTIMIZER_REPORT_PATH, full_report)

    # Log summary
    s = report["summary"]
    logger.info("=" * 60)
    logger.info("VIDEO OPTIMIZER REPORT")
    logger.info("=" * 60)
    logger.info(f"Total videos: {report['total_videos']}")
    logger.info(f"YT Dead (0 views): {s.get('yt_dead', 0)}")
    logger.info(f"YT Low (<100 views): {s.get('yt_low_views', 0)}")
    logger.info(f"YT Low Completion (<50%): {s.get('low_completion', 0)}")
    logger.info(f"FB Dead: {s.get('fb_dead', 0)}")
    logger.info(f"IG Dead: {s.get('ig_dead', 0)}")
    logger.info(f"Weak Hooks (<{MIN_HOOK_SCORE}): {s.get('weak_hooks', 0)}")
    logger.info(f"Weak SEO (<{MIN_SEO_SCORE}): {s.get('weak_seo', 0)}")
    logger.info(f"Spam Days (>{MAX_UPLOADS_PER_DAY}/day): {s.get('spam_days', 0)}")
    logger.info(f"Title Issues: {s.get('title_issues', 0)}")
    logger.info(f"Pipeline Fixes: {len(fixes['pipeline_fixes'])}")
    logger.info(f"Revival Candidates: {len(fixes['revival_candidates'])}")
    logger.info(f"Avg YT Completion: {completion.get('avg_yt_completion', 'N/A')}")
    logger.info("=" * 60)

    return full_report


if __name__ == "__main__":
    run_optimization()
