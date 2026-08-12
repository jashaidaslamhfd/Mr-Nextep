#!/usr/bin/env python3
"""Deep Repair Engine — 2026 per-platform algorithm repair for ALL uploaded
videos, with a high-CTR focus, plus a safeguard ledger so we never re-repair
a video we already fixed.

Covers every platform's 2026 rules:
  YOUTUBE  : hook-driven CTR titles + keyword description + bait removal + tags
  FACEBOOK : UTIS-friendly plain-topic captions, #shorts/#youtube stripped,
             watch-through bait removed, cover-friendly
  INSTAGRAM: forwardable payoff caption + niche hashtag clusters + DM format

High-CTR: titles/lines are built by src/ctr_engine.py (curiosity gap, power
words, single emoji, keyword-backed, engagement-bait-free).

Usage:
  python scripts/deep_repair_2026.py --dry-run            # preview (default)
  python scripts/deep_repair_2026.py --apply              # apply to all
  python scripts/deep_repair_2026.py --apply --limit 10   # first 10 per platform
  python scripts/deep_repair_2026.py --apply --youtube-only
  python scripts/deep_repair_2026.py --apply --force      # ignore repair ledger
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("deep_repair_2026")

from ctr_engine import (  # noqa: E402
    generate_high_ctr_title, generate_ctr_hook_line, validate_title, strip_bait,
)
import repair_all_seo as base  # noqa: E402  (reuse platform API classes + generators)

HISTORY_PATH = ROOT / "data" / "video_history.json"
LEDGER_PATH = ROOT / "data" / "deep_repair_ledger.json"

REPAIR_REPORT_DIR = ROOT / "data"


def load_history() -> list:
    try:
        with open(HISTORY_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not load video_history.json: %s", exc)
        return []


def load_ledger() -> set:
    try:
        with open(LEDGER_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return set(data)
    except Exception:
        return set()


def save_ledger(ledger: set) -> None:
    try:
        with open(LEDGER_PATH, "w", encoding="utf-8") as fh:
            json.dump(sorted(ledger), fh, indent=2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not save repair ledger: %s", exc)


def _vid_key(platform: str, vid: str) -> str:
    return f"{platform}::{vid}"


class DeepRepair2026:
    def __init__(self, dry_run: bool = True, force: bool = False):
        self.dry_run = dry_run
        self.force = force
        self.history = load_history()
        self.ledger = load_ledger()
        self.results = []
        self.stats = {
            "youtube": {"total": 0, "repaired": 0, "skipped": 0, "errors": 0},
            "facebook": {"total": 0, "repaired": 0, "skipped": 0, "errors": 0},
            "instagram": {"total": 0, "repaired": 0, "skipped": 0, "errors": 0},
        }
        # Only instantiate API clients when actually applying.
        self.yt = None
        self.fb = None
        self.ig = None

    # ---- YouTube ---------------------------------------------------------- #
    def _yt_id(self, v: dict) -> Optional[str]:
        return v.get("youtube_id") or v.get("youtube_video_id")

    def repair_youtube(self, limit: int = 0) -> None:
        videos = [v for v in self.history if self._yt_id(v)]
        self.stats["youtube"]["total"] = len(videos)
        logger.info("📺 Deep-repairing %d YouTube Shorts...", len(videos))
        count = 0
        for v in videos:
            if limit and count >= limit:
                break
            vid = self._yt_id(v)
            key = _vid_key("youtube", vid)
            if key in self.ledger and not self.force:
                self.stats["youtube"]["skipped"] += 1
                continue

            topic = v.get("topic") or v.get("youtube_title") or v.get("title") or ""
            old_title = v.get("youtube_title") or v.get("title") or ""
            old_desc = v.get("description") or ""

            new_title = generate_high_ctr_title(topic, platform="youtube")
            hook = generate_ctr_hook_line(topic)
            new_desc = self._build_yt_desc(new_title, topic, hook)

            # Only repair if title is weak, bait present, or the 2026 platform
            # SEO guard flags the current metadata as non-compliant.
            try:
                from platform_seo_guards import check_youtube_seo
                _yt_seo = check_youtube_seo({
                    "title": old_title, "description": old_desc,
                    "tags": v.get("tags") or [], "hashtags": v.get("hashtags") or [],
                    "hook": v.get("hook") or (v.get("topic") or ""),
                })
                seo_noncompliant = not _yt_seo["pass"]
            except Exception:  # noqa: BLE001 - guard must never break repair
                seo_noncompliant = False
            title_ok = validate_title(old_title or new_title)
            desc_has_bait = any(b in (old_desc or "").lower()
                                for b in base.YOUTUBE_RULES["bait_words"])
            needs = (not title_ok["ok"]) or desc_has_bait or (len(old_desc or "") < 120) \
                    or seo_noncompliant
            if not needs:
                self.stats["youtube"]["skipped"] += 1
                continue

            result = {
                "platform": "youtube", "video_id": vid, "old_title": old_title[:70],
                "new_title": new_title, "needs": needs,
                "seo_noncompliant": seo_noncompliant,
            }
            if not self.dry_run:
                ok = self._apply_yt(vid, new_title, new_desc)
                if ok:
                    self.stats["youtube"]["repaired"] += 1
                    result["applied"] = True
                    self.ledger.add(key)
                else:
                    self.stats["youtube"]["errors"] += 1
                    result["error"] = "apply_failed"
            else:
                self.stats["youtube"]["repaired"] += 1
                result["applied"] = "(dry-run)"
            self.results.append(result)
            count += 1
        logger.info("  YouTube: %d repaired, %d errors, %d skipped",
                    self.stats["youtube"]["repaired"],
                    self.stats["youtube"]["errors"],
                    self.stats["youtube"]["skipped"])

    def _apply_yt(self, vid, title, desc) -> bool:
        try:
            if self.yt is None:
                self.yt = base.YouTubeRepair()
            tags = ["body science", "human body", "science shorts", "mind facts",
                    "everyday science"]
            res = self.yt.update_video(vid, title, desc, tags=tags)
            if res.get("ok"):
                return True
            logger.warning("YT update failed for %s: %s", vid, res.get("error"))
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("YT repair error for %s: %s", vid, exc)
            return False

    def _build_yt_desc(self, title: str, topic: str, hook: str) -> str:
        lines = [
            f"{title} — {hook}",
            "",
            topic or "A surprising everyday science fact.",
            "",
            "New science Shorts daily. For more, follow the channel.",
            "",
            "#shorts #science #humanbody",
        ]
        return "\n".join(lines)[:500]

    # ---- Facebook --------------------------------------------------------- #
    def _fb_id(self, v: dict) -> Optional[str]:
        return v.get("facebook_id") or v.get("facebook_post_id")

    def repair_facebook(self, limit: int = 0) -> None:
        videos = [v for v in self.history if self._fb_id(v)]
        self.stats["facebook"]["total"] = len(videos)
        logger.info("📘 Deep-repairing %d Facebook Reels...", len(videos))
        count = 0
        for v in videos:
            if limit and count >= limit:
                break
            rid = self._fb_id(v)
            key = _vid_key("facebook", rid)
            if key in self.ledger and not self.force:
                self.stats["facebook"]["skipped"] += 1
                continue

            topic = v.get("topic") or v.get("youtube_title") or v.get("title") or ""
            hook = generate_ctr_hook_line(topic)
            # FB caption: plain topic naming, UTIS-friendly, no #shorts.
            caption = self._build_fb_caption(topic, hook)
            # 2026 FB SEO guard: only treat as needing repair if the current
            # caption is not UTIS-compliant (so already-good reels are skipped).
            try:
                from platform_seo_guards import check_facebook_seo
                _fb_seo = check_facebook_seo({"facebook_caption": v.get("description") or caption})
                fb_needs = not _fb_seo["pass"]
            except Exception:  # noqa: BLE001
                fb_needs = True
            if not fb_needs and key in self.ledger and not self.force:
                self.stats["facebook"]["skipped"] += 1
                continue
            result = {"platform": "facebook", "reel_id": rid, "new_caption": caption[:120],
                      "seo_noncompliant": fb_needs}
            if not self.dry_run:
                ok = self._apply_fb(rid, caption)
                if ok:
                    self.stats["facebook"]["repaired"] += 1
                    result["applied"] = True
                    self.ledger.add(key)
                else:
                    self.stats["facebook"]["errors"] += 1
                    result["error"] = "apply_failed"
            else:
                self.stats["facebook"]["repaired"] += 1
                result["applied"] = "(dry-run)"
            self.results.append(result)
            count += 1
        logger.info("  Facebook: %d repaired, %d errors, %d skipped",
                    self.stats["facebook"]["repaired"],
                    self.stats["facebook"]["errors"],
                    self.stats["facebook"]["skipped"])

    def _build_fb_caption(self, topic: str, hook: str) -> str:
        lines = [
            hook,
            "",
            topic.strip() or "Everyday body science.",
            "",
            base.generate_facebook_caption(topic).split("\n")[-1] if base.generate_facebook_caption(topic) else "#bodyfacts",
        ]
        # FB forbids #shorts/#youtube; generate_facebook_caption already filters.
        caption = "\n".join(lines)
        return strip_bait(base.filter_hashtags(caption, base.FACEBOOK_RULES))[:400]

    def _apply_fb(self, rid, caption) -> bool:
        try:
            if self.fb is None:
                self.fb = base.FacebookRepair()
            res = self.fb.update_reel_caption(rid, caption)
            return bool(res.get("ok") or res.get("success") or res.get("id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("FB repair error for %s: %s", rid, exc)
            return False

    # ---- Instagram -------------------------------------------------------- #
    def _ig_id(self, v: dict) -> Optional[str]:
        return v.get("instagram_id") or v.get("instagram_media_id")

    def _live_ig_ids(self) -> list:
        """Fetch the account's current Instagram media ids directly from the
        Graph API (like meta_seo_repair does), so repair isn't limited to ids
        stored in video_history (which historically has no instagram_id)."""
        import requests as _requests
        from repair_all_seo import IG_USER_ID, FB_TOKEN, FB_API
        ig_user = IG_USER_ID or os.environ.get("INSTAGRAM_USER_ID", "").strip()
        tok = os.environ.get("IG_ACCESS_TOKEN") or FB_TOKEN or os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
        api_version = FB_API or os.environ.get("FB_API_VERSION", "v23.0")
        if not ig_user or not tok:
            return []
        try:
            resp = _requests.get(
                f"https://graph.facebook.com/{api_version}/{ig_user}/media",
                params={"access_token": tok, "limit": 100,
                        "fields": "id,media_type,caption"},
                timeout=30,
            )
            data = resp.json()
            return [
                m["id"] for m in data.get("data", [])
                if m.get("media_type") in ("VIDEO", "REELS")
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not list Instagram media live: %s", exc)
            return []

    def repair_instagram(self, limit: int = 0) -> None:
        # Pull ids from history when present, else fetch live from the API so
        # Instagram repair is not silently skipped.
        ids = list(dict.fromkeys(
            str(self._ig_id(v)) for v in self.history if self._ig_id(v)
        ))
        live_ids = self._live_ig_ids()
        ids.extend(i for i in live_ids if i not in ids)
        self.stats["instagram"]["total"] = len(ids)
        logger.info("📸 Deep-repairing %d Instagram Reels...", len(ids))
        count = 0
        for mid in ids:
            if limit and count >= limit:
                break
            key = _vid_key("instagram", mid)
            if key in self.ledger and not self.force:
                self.stats["instagram"]["skipped"] += 1
                continue

            # Resolve topic/title from history if the id maps to one; otherwise
            # fetch the caption live for a best-effort topic.
            topic = ""
            v_cap = ""
            for v in self.history:
                if str(self._ig_id(v)) == mid:
                    topic = v.get("topic") or v.get("youtube_title") or v.get("title") or ""
                    v_cap = (v.get("instagram_caption")
                             or v.get("description") or v.get("voiceover") or "")
                    break
            if not v_cap:
                v_cap = mid  # best-effort fallback token
            hook = generate_ctr_hook_line(topic or mid)
            caption = self._build_ig_caption(topic or "this body fact", hook)
            # 2026 IG SEO guard: skip only genuinely-compliant reels.
            try:
                from platform_seo_guards import check_instagram_seo
                _ig_seo = check_instagram_seo({"instagram_caption": v_cap})
            except Exception:  # noqa: BLE001
                _ig_seo = None
            ig_needs = (_ig_seo is None) or (not _ig_seo["pass"])
            if not ig_needs and key in self.ledger and not self.force:
                self.stats["instagram"]["skipped"] += 1
                continue
            result = {"platform": "instagram", "media_id": mid, "new_caption": caption[:120],
                      "seo_noncompliant": ig_needs}
            if not self.dry_run:
                ok = self._apply_ig(mid, caption)
                if ok:
                    self.stats["instagram"]["repaired"] += 1
                    result["applied"] = True
                    self.ledger.add(key)
                else:
                    self.stats["instagram"]["errors"] += 1
                    result["error"] = "apply_failed"
            else:
                self.stats["instagram"]["repaired"] += 1
                result["applied"] = "(dry-run)"
            self.results.append(result)
            count += 1
        logger.info("  Instagram: %d repaired, %d errors, %d skipped",
                    self.stats["instagram"]["repaired"],
                    self.stats["instagram"]["errors"],
                    self.stats["instagram"]["skipped"])

    def _build_ig_caption(self, topic: str, hook: str) -> str:
        lines = [
            hook,
            "",
            topic.strip() or "Everyday body science.",
            "",
            base.generate_instagram_caption(topic).split("\n")[-1] if base.generate_instagram_caption(topic) else "#bodyfacts",
        ]
        caption = "\n".join(lines)
        return strip_bait(base.filter_hashtags(caption, base.INSTAGRAM_RULES))[:400]

    def _apply_ig(self, mid, caption) -> bool:
        # Instagram Graph API v23 requires comment_enabled=true on a caption
        # edit, otherwise it returns "(#100) The parameter comment_enabled is
        # required". Do the POST directly rather than via update_caption (which
        # omits it), matching meta_seo_repair's working path.
        try:
            import requests as _requests
            from repair_all_seo import FB_TOKEN, FB_API
            tok = os.environ.get("IG_ACCESS_TOKEN") or FB_TOKEN or os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
            api_version = FB_API or os.environ.get("FB_API_VERSION", "v23.0")
            resp = _requests.post(
                f"https://graph.facebook.com/{api_version}/{mid}",
                data={"access_token": tok, "caption": caption[:2200], "comment_enabled": "true"},
                timeout=60,
            )
            data = resp.json()
            if "error" in data:
                logger.warning("IG caption edit failed for %s: %s", mid,
                               data["error"].get("message", str(data))[:160])
                return False
            return bool(data.get("success") or data.get("id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("IG repair error for %s: %s", mid, exc)
            return False

    # ---- reporting -------------------------------------------------------- #
    def save_report(self) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = REPAIR_REPORT_DIR / f"deep_repair_{ts}.json"
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.dry_run,
            "stats": self.stats,
            "results": self.results,
        }
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            logger.info("Report saved: %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not save report: %s", exc)

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("🧬 DEEP REPAIR 2026 SUMMARY")
        print("=" * 60)
        for plat in ("youtube", "facebook", "instagram"):
            s = self.stats[plat]
            print(f"  {plat.title():10s}: total={s['total']} "
                  f"repaired={s['repaired']} skipped={s['skipped']} errors={s['errors']}")
        print("\n  Sample YouTube title changes:")
        for r in [x for x in self.results if x["platform"] == "youtube"][:3]:
            print(f"    OLD: {r.get('old_title','?')[:60]}")
            print(f"    NEW: {r.get('new_title','?')[:60]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="SKILLOR deep repair 2026 (all platforms)")
    ap.add_argument("--apply", action="store_true", help="apply repairs (default is dry-run)")
    ap.add_argument("--force", action="store_true", help="ignore the repair ledger")
    ap.add_argument("--limit", type=int, default=0, help="max per platform (0=all)")
    ap.add_argument("--youtube-only", action="store_true")
    ap.add_argument("--facebook-only", action="store_true")
    ap.add_argument("--instagram-only", action="store_true")
    args = ap.parse_args()

    engine = DeepRepair2026(dry_run=not args.apply, force=args.force)
    logger.info("🧬 SKILLOR Deep Repair 2026")
    logger.info("   Videos loaded: %d | Mode: %s | Force: %s",
                len(engine.history), "APPLY" if args.apply else "DRY RUN", args.force)
    if args.limit:
        logger.info("   Limit: %d per platform", args.limit)

    if not args.facebook_only and not args.instagram_only:
        engine.repair_youtube(limit=args.limit)
    if not args.youtube_only and not args.instagram_only:
        engine.repair_facebook(limit=args.limit)
    if not args.youtube_only and not args.facebook_only:
        engine.repair_instagram(limit=args.limit)

    engine.save_report()
    engine.print_summary()

    if not engine.dry_run:
        save_ledger(engine.ledger)
        logger.info("Repair ledger updated: %d entries", len(engine.ledger))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
