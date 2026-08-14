import os
import json
import logging
import time
import hashlib
from datetime import datetime, timedelta
import pytz
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import requests
from seo_generator import generate_description

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5
FB_API_VERSION = os.environ.get("FB_API_VERSION", "v23.0").strip()
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# ---------------------------------------------------------------------------
# IMPORTANT: YouTube video uploads require OAuth 2.0 USER credentials, not a
# service-account key. Credentials are read from THREE separate secrets/env
# vars: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, REFRESH_TOKEN.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# YOUTUBE "MADE FOR KIDS" (COPPA)
# This channel's content is dark/mystery body-science facts aimed at adults
# (18+), so MADE_FOR_KIDS defaults to False. If your niche or audience
# changes again, re-verify this setting - COPPA fines are no joke.
# ---------------------------------------------------------------------------
MADE_FOR_KIDS = os.environ.get("YT_MADE_FOR_KIDS", "false").lower() == "true"
YT_PRIVACY_STATUS = os.environ.get("YT_PRIVACY_STATUS", "private").strip().lower()
if YT_PRIVACY_STATUS not in {"private", "unlisted", "public"}:
    raise ValueError("YT_PRIVACY_STATUS must be private, unlisted, or public")

# ---------------------------------------------------------------------------
# SCHEDULED PUBLISHING (publishAt) — this env var existed in the workflow
# for months but NO code read it, so every video published the moment the
# run finished and the "PublishAt will handle" comments were wishful
# thinking. Implemented for real now:
#   YT_SCHEDULE_PUBLISH=true  →  upload as private with a publishAt timestamp
#   YouTube then flips it to public automatically at the next US peak slot
#   (12:30 / 18:30 / 20:00 America/New_York — kept in sync with
#   scheduler.USAPeakTimeScheduler.PEAK_TIMES and the workflow cron table).
# ---------------------------------------------------------------------------
YT_SCHEDULE_PUBLISH = os.environ.get("YT_SCHEDULE_PUBLISH", "false").lower() == "true"
_PUBLISH_TZ = pytz.timezone("America/New_York")

# DATA-DRIVEN (2026-07-26, 87-video time-vs-views analysis):
#   12:30 lunch  → avg 231 views (fresh ≤21d avg 252) — channel's best slot
#   18:30 early  → commute/wind-down slot, paired with the 20:40 UTC cron
#   20:00 prime  → avg 261 views (n=11) — proven evening winner
#   16:30        → RETIRED: fresh median only 53, work-end crowd never came
#
# Sourced from the scheduler rather than re-typed, because these three slots
# also drive Instagram's wait-for-slot logic and the workflow cron table. The
# duplicated literal list had already drifted once (it still said 21:30 after
# the scheduler moved to 18:30), which silently sends the YouTube publishAt
# and the Instagram publish to two different clocks.
def _peak_publish_slots() -> list:
    """(hour, minute) New York slots, single-sourced from the scheduler."""
    try:
        from scheduler import USAPeakTimeScheduler
        slots = [(p["hour"], p["minute"]) for p in USAPeakTimeScheduler.PEAK_TIMES]
        if slots:
            return sorted(slots)
    except Exception:  # noqa: BLE001 — scheduling must never block an upload
        logger.warning("Peak slot lookup failed; using the built-in fallback slots.")
    return [(12, 30), (18, 30), (20, 0)]


_PUBLISH_SLOTS = _peak_publish_slots()  # (hour, minute) New York time
_PUBLISH_MIN_LEAD_MINUTES = 30  # video must sit privately at least this long

# ---------------------------------------------------------------------------
# ONE VIDEO PER SLOT LOCK (ported from the FR channel fix, 2026-07-26)
# The old clock-only picker let two adjacent runs grab the SAME NY slot —
# both videos would then go public at the exact same minute, and the
# ENFORCE_POSTING_GAP guard could silently skip the late-evening run. Now
# every claim is re-checked against THREE sources before a slot is chosen:
#   1. _CLAIMED_PUBLISH_ATS — claims made by this same process
#   2. data/video_history.json — the publish_at ledger persisted via git
#   3. the YouTube channel itself — private+publishAt videos already queued
#      (best-effort: needs youtube.force-ssl; failure falls back to 1+2)
# _RUN_PUBLISH_AT caches the result: one run = one video = one slot, so the
# YT upload and the FB stagger always reference the SAME locked slot.
# ---------------------------------------------------------------------------
_CLAIMED_PUBLISH_ATS = []  # timezone-aware datetimes, this process only
SLOT_CLAIM_TOLERANCE_SECONDS = 30 * 60  # slots are >=90 min apart; 30 is safe
_SCHEDULE_LOOKAHEAD_DAYS = 3  # claims can push a late run into tomorrow
_RUN_PUBLISH_AT = None


def _parse_iso_quiet(value):
    try:
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=pytz.UTC)
    except Exception:
        return None


def _channel_scheduled_publish_ats(yt) -> list:
    """Slots already occupied by private+publishAt videos queued on the
    channel — the cross-run source of truth. Best-effort: any failure
    returns [] and the local ledger still protects us."""
    claimed = []
    if yt is None:
        return claimed
    try:
        channels = yt.channels().list(part="contentDetails", mine=True).execute()
        items = channels.get("items") or []
        if not items:
            return claimed
        uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        video_ids = [
            item["contentDetails"]["videoId"]
            for item in yt.playlistItems().list(
                part="contentDetails", playlistId=uploads_playlist, maxResults=25
            ).execute().get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]
        if not video_ids:
            return claimed
        videos = yt.videos().list(part="status", id=",".join(video_ids)).execute()
        cutoff = datetime.now(pytz.UTC) - timedelta(hours=3)
        for video in videos.get("items", []):
            publish_at = _parse_iso_quiet(video.get("status", {}).get("publishAt"))
            if publish_at and publish_at > cutoff:
                claimed.append(publish_at)
        if claimed:
            logger.info("Channel already holds %d scheduled slot(s).", len(claimed))
    except Exception as exc:
        logger.warning("Scheduled-slot API check skipped (%s); local ledger only.", exc)
    return claimed


def _claimed_publish_times(yt=None) -> list:
    """Every publish time already taken, from all three sources."""
    now = datetime.now(pytz.UTC)
    claimed = [c for c in _CLAIMED_PUBLISH_ATS if c and c > now - timedelta(hours=3)]
    try:
        if os.path.exists(VIDEO_HISTORY_PATH):
            with open(VIDEO_HISTORY_PATH, encoding="utf-8") as handle:
                for entry in json.load(handle):
                    publish_at = _parse_iso_quiet(entry.get("publish_at"))
                    if publish_at and publish_at > now - timedelta(hours=3):
                        claimed.append(publish_at)
    except Exception as exc:
        logger.warning("Local publish_at ledger unreadable (%s).", exc)
    claimed.extend(_channel_scheduled_publish_ats(yt))
    return claimed


def _slot_is_taken(when, claimed) -> bool:
    return any(abs((when - taken).total_seconds()) < SLOT_CLAIM_TOLERANCE_SECONDS
               for taken in claimed)


def _compute_publish_at(now: datetime = None, yt=None) -> str:
    """Next FREE US peak slot in UTC RFC-3339 ('…Z'): at least
    _PUBLISH_MIN_LEAD_MINUTES in the future and NOT already claimed by any
    other upload (process set + history ledger + live channel queue). The
    result is cached per run, so the YouTube upload and the Facebook
    stagger always use the same locked slot. Two videos can never again go
    public at the same minute."""
    global _RUN_PUBLISH_AT
    if _RUN_PUBLISH_AT and now is None:
        return _RUN_PUBLISH_AT
    now_ny = (now or datetime.now(_PUBLISH_TZ)).astimezone(_PUBLISH_TZ)
    claimed = _claimed_publish_times(yt)
    first_future = None
    for day_offset in range(_SCHEDULE_LOOKAHEAD_DAYS + 1):
        for hour, minute in _PUBLISH_SLOTS:
            slot = now_ny.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
            if slot < now_ny + timedelta(minutes=_PUBLISH_MIN_LEAD_MINUTES):
                continue
            slot_utc = slot.astimezone(pytz.UTC)
            if first_future is None:
                first_future = slot_utc
            if _slot_is_taken(slot_utc, claimed):
                logger.info("Publish slot %s NY already claimed — taking the next one.",
                            slot.strftime("%m-%d %H:%M"))
                continue
            _CLAIMED_PUBLISH_ATS.append(slot_utc)
            result = slot_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            if now is None:
                _RUN_PUBLISH_AT = result
            return result
    return (first_future or (now_ny + timedelta(days=1)).astimezone(pytz.UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")



def _build_youtube_description(script_data: dict, tags: list) -> str:
    """Search-oriented YouTube description.

    Delegates to platform_captions, which writes one caption per platform
    against that platform's own ranking system, instead of shipping a single
    block everywhere. Falls back to the legacy builder if the new module is
    unavailable, so an import problem can never block an upload.
    """
    try:
        from platform_captions import build_youtube_description
        return build_youtube_description(script_data, tags)
    except Exception as exc:  # noqa: BLE001 - never fail an upload over copy
        logger.warning("Platform caption builder unavailable (%s); using legacy.", exc)
        return generate_description(script_data, tags)


def _build_facebook_description(script_data: dict, tags: list) -> str:
    """Build a Facebook-native Reel caption, never a copied YouTube block.

    Facebook gets a short natural-language caption for NLP/topic matching;
    YouTube gets its own search-oriented description. We deliberately use
    `summary` first and strip old hashtags/formatting so a legacy YouTube
    description cannot be pasted inside the Facebook caption a second time.

    Primary implementation lives in platform_captions, which also targets
    Meta's UTIS true-interest model (Jan 2026). The inline version below is
    kept as a dependency-free fallback and as the reference for what the
    caption must never contain.
    """
    try:
        from platform_captions import build_facebook_caption
        caption = build_facebook_caption(script_data, tags)
        if caption:
            return caption
    except Exception as exc:  # noqa: BLE001
        logger.warning("Facebook caption builder unavailable (%s); using legacy.", exc)

    import re

    def clean(value: object, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        # Remove hashtags and old divider/CTA fragments from descriptions
        # created by earlier versions of the pipeline.
        text = re.sub(r"#[A-Za-z0-9_]+", "", text)
        text = re.sub(r"[━═─]{3,}", " ", text)
        return re.sub(r"\s+", " ", text).strip(" .")[:limit]

    hook = clean(script_data.get("hook"), 180)
    summary = clean(script_data.get("summary") or script_data.get("description"), 420)

    # Meta's engagement-bait ranking demotes Reels whose caption begs for
    # likes/shares/comments. If the (YouTube-oriented) spoken CTA slipped in
    # here, swap it for the FB-safe default instead of posting bait.
    _bait_words = ("like", "share", "comment", "subscribe", "tag")
    cta_raw = str(script_data.get("cta") or "").strip()
    if any(bait in cta_raw.lower() for bait in _bait_words):
        cta_raw = "Follow for more body science."
    cta = clean(cta_raw or "Follow for more body science.", 100)

    # Facebook caption: one hook, one explanation, one natural CTA. Do not
    # repeat hook/summary when the model generated overlapping sentences.
    parts = []
    if hook:
        parts.append(hook)
    if summary and summary.lower() not in hook.lower() and hook.lower() not in summary.lower():
        parts.append(summary)
    if cta and cta.lower() not in " ".join(parts).lower():
        parts.append(cta)

    generic = {"facts", "science", "shorts", "viral", "fyp", "reels",
               "education", "trending", "video", "youtube"}
    specific = []
    seen = set()
    for raw in tags:
        tag = str(raw).lstrip("#").strip()
        key = tag.lower()
        if tag and key not in generic and key not in seen:
            seen.add(key)
            specific.append(tag.replace(" ", ""))
    hashtags = " ".join(f"#{tag}" for tag in specific[:3])
    if hashtags:
        parts.append(hashtags)
    return "\n\n".join(parts)[:2200]


VIDEO_HISTORY_PATH = os.environ.get("VIDEO_HISTORY_PATH", "data/video_history.json")
UPLOAD_STATE_PATH = os.environ.get("UPLOAD_STATE_PATH", "data/upload_state.json")


def _load_upload_state() -> dict:
    if not os.path.exists(UPLOAD_STATE_PATH):
        return {}
    try:
        with open(UPLOAD_STATE_PATH, encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load upload state: %s", exc)
        return {}


def _save_upload_state(state: dict) -> None:
    os.makedirs(os.path.dirname(UPLOAD_STATE_PATH) or ".", exist_ok=True)
    temp_path = UPLOAD_STATE_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file_handle:
        json.dump(state, file_handle, indent=2)
    os.replace(temp_path, UPLOAD_STATE_PATH)


def _content_fingerprint(script_data: dict) -> str:
    """Stable identity for a script, independent of temporary media paths."""
    material = "|".join(
        str(script_data.get(key, "")).strip().lower()
        for key in ("topic", "title", "voiceover", "hook")
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _load_upload_history() -> list:
    if not os.path.exists(VIDEO_HISTORY_PATH):
        return []
    try:
        with open(VIDEO_HISTORY_PATH, encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load upload history: %s", exc)
        return []


def _existing_youtube_upload(script_data: dict) -> str | None:
    """Return a prior upload ID for the exact script, preventing retry duplicates."""
    fingerprint = _content_fingerprint(script_data)
    state = _load_upload_state().get(fingerprint, {})
    if state.get("status") == "completed" and state.get("youtube_video_id"):
        return str(state["youtube_video_id"])
    if state.get("status") == "started":
        # We cannot safely know whether a timeout happened before or after
        # YouTube accepted the binary. Block rather than risk a duplicate.
        raise RuntimeError(
            "An earlier YouTube upload has unknown completion state for this script. "
            "Review YouTube Studio, then clear or resolve its data/upload_state.json record."
        )
    for item in reversed(_load_upload_history()):
        if item.get("content_fingerprint") == fingerprint and item.get("youtube_video_id"):
            return str(item["youtube_video_id"])
    return None


def _already_uploaded_to_facebook(script_data: dict) -> bool:
    """Prevent a duplicate Facebook Reel for an already recorded script."""
    fingerprint = _content_fingerprint(script_data)
    return any(
        item.get("content_fingerprint") == fingerprint and item.get("facebook_success")
        for item in _load_upload_history()
    )


def _upload_youtube(video_path, thumb_path, script_data, tags):
    """Returns (success: bool, video_id: str|None)."""
    existing_video_id = _existing_youtube_upload(script_data)
    if existing_video_id:
        logger.warning("Duplicate script blocked; existing YouTube upload: %s", existing_video_id)
        return True, existing_video_id

    google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")

    missing = [
        name for name, val in {
            "GOOGLE_CLIENT_ID": google_client_id,
            "GOOGLE_CLIENT_SECRET": google_client_secret,
            "REFRESH_TOKEN": refresh_token,
        }.items() if not val
    ]
    if missing:
        logger.error(f"YouTube upload skipped - missing secrets: {missing}")
        return False, None

    title = script_data.get('title', 'Untitled')
    enhanced_title = title  # already selected/scored by generate_seo_package
    desc = _build_youtube_description(script_data, tags)

    # NOTE: captions.insert (SRT upload) and commentThreads.insert (posting
    # the pinned_comment from seo_generator) both need the broader
    # youtube.force-ssl scope, not just youtube.upload. Listing it here
    # doesn't grant it by itself - your REFRESH_TOKEN has to have actually
    # been issued with consent for this scope, or those two calls below
    # will fail with a 403 and get skipped (logged as a warning, not fatal -
    # the video upload itself only needs youtube.upload and is unaffected).
    creds = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=google_client_id,
        client_secret=google_client_secret,
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ],
    )
    yt = build('youtube', 'v3', credentials=creds)

    body = {
        'snippet': {
            'title': enhanced_title[:100],
            'description': desc[:5000],
            'categoryId': '28',
            # FIX: was a fixed hardcoded list on every single video - now
            # topic/category-aware tags from niche_strategy.generate_seo_tags,
            # which also helps SEO reach and avoids duplicate-metadata spam risk.
            'tags': tags,
            'defaultLanguage': 'en-US',
            'defaultAudioLanguage': 'en-US',
        },
        'status': {
            'privacyStatus': YT_PRIVACY_STATUS,
            'selfDeclaredMadeForKids': MADE_FOR_KIDS,
            'containsSyntheticMedia': True,  # YouTube AI/altered-content disclosure
        }
    }

    if YT_SCHEDULE_PUBLISH:
        publish_at = _compute_publish_at(yt=yt)  # slot lock + live channel queue check
        # YouTube requires privacyStatus='private' whenever publishAt is set;
        # the platform itself flips the video to public at publishAt.
        body['status']['privacyStatus'] = 'private'
        body['status']['publishAt'] = publish_at
        logger.info(
            "YT_SCHEDULE_PUBLISH=true → video uploads PRIVATE and YouTube "
            "auto-publishes at %s (next US peak slot). Manual review is "
            "possible until then.",
            publish_at,
        )

    fingerprint = _content_fingerprint(script_data)
    upload_state = _load_upload_state()
    upload_state[fingerprint] = {
        "status": "started",
        "title": enhanced_title,
        "started_at": time.time(),
    }
    _save_upload_state(upload_state)

    logger.info("Uploading to YouTube...")
    yt_video_id = None
    youtube_success = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = yt.videos().insert(
                part="snippet,status",
                body=body,
                media_body=MediaFileUpload(video_path, chunksize=1024 * 1024, resumable=True)
            )
            res = req.execute()
            yt_video_id = res.get('id')
            if not yt_video_id:
                raise RuntimeError(f"YouTube upload returned no video ID: {res}")
            upload_state[fingerprint] = {
                "status": "completed",
                "title": enhanced_title,
                "youtube_video_id": yt_video_id,
                "completed_at": time.time(),
            }
            _save_upload_state(upload_state)
            logger.info(f"YouTube upload successful: https://youtu.be/{yt_video_id}")
            youtube_success = True

            if thumb_path and os.path.exists(thumb_path):
                try:
                    yt.thumbnails().set(
                        videoId=yt_video_id,
                        media_body=MediaFileUpload(thumb_path)
                    ).execute()
                    logger.info("Thumbnail uploaded successfully")
                except Exception as thumb_error:
                    logger.warning(f"Thumbnail upload failed: {thumb_error}")

            # Optional: real closed-caption track from seo/shorts modules'
            # SRT export (main.py sets script_data['srt_path']). Best-effort
            # only - see scope note above.
            srt_path = script_data.get('srt_path')
            if srt_path and os.path.exists(srt_path):
                try:
                    yt.captions().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "videoId": yt_video_id,
                                "language": "en",
                                "name": "English",
                                "isDraft": False,
                            }
                        },
                        media_body=MediaFileUpload(srt_path, mimetype="application/octet-stream"),
                    ).execute()
                    logger.info("Captions uploaded successfully")
                except Exception as captions_error:
                    logger.warning(
                        f"Captions upload failed (needs youtube.force-ssl scope on REFRESH_TOKEN): {captions_error}"
                    )

            # Optional: post the pinned_comment from seo_generator as the
            # first top-level comment. NOTE: this only posts the comment -
            # the YouTube Data API has no public endpoint to actually pin a
            # comment, so pinning it still needs one manual click in Studio.
            pinned_comment = script_data.get('pinned_comment')
            if pinned_comment:
                try:
                    yt.commentThreads().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "videoId": yt_video_id,
                                "topLevelComment": {
                                    "snippet": {"textOriginal": pinned_comment}
                                },
                            }
                        },
                    ).execute()
                    logger.info("Seed comment posted (pin it manually in YouTube Studio for best effect)")
                except Exception as comment_error:
                    logger.warning(
                        f"Seed comment post failed (needs youtube.force-ssl scope on REFRESH_TOKEN): {comment_error}"
                    )
            break

        except HttpError as e:
            if e.resp.status in [429, 500, 502, 503]:
                logger.warning(f"YouTube API error {e.resp.status} (attempt {attempt}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * (2 ** (attempt - 1)))
                continue
            else:
                logger.error(f"YouTube upload failed: {e}")
                break
        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            break

    return youtube_success, yt_video_id


def _set_fb_reel_cover(video_id, thumb_path, fb_token):
    """Attach the designed YouTube thumbnail as the Reel's custom cover at
    publish time (best-effort, never fatal). Root fix for the '47 reels have
    no cover' audit finding — previously covers were only applied by the
    after-the-fact tune-up matcher, which misses pipeline-posted reels."""
    if not thumb_path or not os.path.exists(thumb_path):
        logger.info("No thumbnail asset available for FB cover — auto frame stays.")
        return
    try:
        with open(thumb_path, "rb") as fh:
            resp = requests.post(
                f"https://graph.facebook.com/{FB_API_VERSION}/{video_id}/thumbnails",
                data={"access_token": fb_token},
                # The field MUST be named "source" for the video-thumbnails
                # endpoint — "file" returns "The parameter source is required".
                files={"source": (os.path.basename(thumb_path), fh, "image/jpeg")},
                timeout=60,
            )
        ok = resp.status_code == 200 and "error" not in (
            resp.json() if resp.content else {})
        logger.info("Facebook Reel cover %s.", "attached" if ok else
                    f"rejected ({resp.text[:120]})")
    except Exception as exc:
        logger.warning("FB cover attach failed (non-fatal): %s", exc)


def _upload_facebook_reels(video_path, script_data, tags, thumb_path=None):
    """
    FIX: previously this posted to /{page-id}/videos as a plain video post.
    Facebook's 2026 recommendation algorithm gives materially better organic
    reach to content published through the actual Reels pipeline. This now
    uses the correct 3-phase Reels publishing flow:
      1. upload_phase=start   -> get video_id + upload_url
      2. POST binary to upload_url (rupload host)
      3. upload_phase=finish  -> attach description/hashtags and publish
      4. attach the custom cover (audit 2026-07-25: 47/81 reels coverless)
    Returns success: bool.
    """
    # Facebook Reels has no equivalent private-review workflow in this code.
    # Keep it opt-in so a private YouTube review run never publishes a public
    # Reel by surprise.
    if os.environ.get("FB_UPLOAD_ENABLED", "false").lower() != "true":
        logger.info("Facebook upload disabled (set FB_UPLOAD_ENABLED=true to publish a Reel).")
        return False

    fb_token = os.environ.get("FB_ACCESS_TOKEN")
    fb_page = os.environ.get("FB_PAGE_ID")

    if not fb_token or not fb_page:
        logger.warning("FB_ACCESS_TOKEN or FB_PAGE_ID missing - Facebook upload skipped")
        return False

    # Duplicate prevention: if this exact video title was already successfully
    # posted to Facebook in a previous run, skip it rather than uploading again.
    if _already_uploaded_to_facebook(script_data):
        logger.info(f"Facebook: '{script_data.get('title')}' already uploaded — skipping duplicate.")
        return True  # treat as success so pipeline doesn't retry/fail

    # Max 3 hashtags — Facebook's own algorithm penalises Reels with >5 hashtags
    description = _build_facebook_description(script_data, tags)
    fingerprint = _content_fingerprint(script_data)
    upload_state = _load_upload_state()
    fb_state = upload_state.get(fingerprint, {}).get("facebook", {})
    if fb_state.get("status") == "completed" and fb_state.get("video_id"):
        logger.info("Facebook duplicate blocked; existing Reel: %s", fb_state["video_id"])
        return True
    if fb_state.get("status") == "started":
        raise RuntimeError(
            "Earlier Facebook Reel has unknown completion state. Review the Page before retrying."
        )
    upload_state.setdefault(fingerprint, {})["facebook"] = {
        "status": "started",
        "started_at": time.time(),
    }
    _save_upload_state(upload_state)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # ---- Phase 1: start ----
            start_resp = requests.post(
                f"https://graph.facebook.com/{FB_API_VERSION}/{fb_page}/video_reels",
                data={"upload_phase": "start", "access_token": fb_token},
                timeout=30,
            )
            start_data = start_resp.json()
            if "error" in start_data or "video_id" not in start_data:
                raise RuntimeError(f"Reels start phase failed: {start_data}")

            video_id = start_data["video_id"]
            upload_url = start_data["upload_url"]

            # ---- Phase 2: upload binary ----
            file_size = os.path.getsize(video_path)
            with open(video_path, "rb") as f:
                upload_resp = requests.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {fb_token}",
                        "offset": "0",
                        "file_size": str(file_size),
                    },
                    data=f,
                    timeout=300,
                )
            upload_data = upload_resp.json() if upload_resp.content else {}
            if upload_resp.status_code != 200 or upload_data.get("success") is False:
                raise RuntimeError(f"Reels upload phase failed: {upload_resp.status_code} {upload_data}")

            # ---- Phase 3: finish/publish ----
            video_state = "PUBLISHED"
            # Platform-native staggering: firing identical content at YouTube
            # and Facebook at the same minute is both a spam-pattern and a
            # waste — each platform's "new content boost" then competes with
            # the other's. FB_STAGGER_MINUTES schedules the Reel that many
            # minutes after the YouTube publishAt slot (or after now).
            stagger_minutes = int(os.environ.get("FB_STAGGER_MINUTES", "0") or "0")
            finish_payload = {
                "upload_phase": "finish",
                "video_id": video_id,
                "description": description,
                # Reels carry a separate `title` field; without it FB shows an
                # empty title slot (audit 2026-07-25: 58/80 reels title-less).
                "title": (script_data.get("title") or "")[:65],
                "access_token": fb_token,
            }
            if stagger_minutes >= 10:
                base_ts = time.time()
                if YT_SCHEDULE_PUBLISH:
                    # Same deterministic slot the YT stage just used (this runs
                    # minutes after it, inside the same generation window), so
                    # the Reel trails the Short consistently.
                    base_ts = datetime.strptime(
                        _compute_publish_at(), "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=pytz.UTC).timestamp()
                scheduled_ts = int(base_ts + stagger_minutes * 60)
                if scheduled_ts > time.time() + 600:
                    finish_payload["scheduled_publish_time"] = scheduled_ts
                    finish_payload["video_state"] = "SCHEDULED"
                    logger.info(
                        "Facebook Reel scheduled %d min after YouTube slot (native stagger).",
                        stagger_minutes,
                    )
                else:
                    finish_payload["video_state"] = video_state
            else:
                finish_payload["video_state"] = video_state
            finish_resp = requests.post(
                f"https://graph.facebook.com/{FB_API_VERSION}/{fb_page}/video_reels",
                data=finish_payload,
                timeout=60,
            )
            finish_data = finish_resp.json()
            if "error" in finish_data and "scheduled" in str(finish_data.get("error", "")).lower():
                # Older/unverified apps may reject reel scheduling — degrade
                # gracefully to immediate publish instead of losing the post.
                logger.warning("FB scheduling rejected (%s); publishing immediately.", finish_data["error"])
                finish_payload.pop("scheduled_publish_time", None)
                finish_payload["video_state"] = "PUBLISHED"
                finish_resp = requests.post(
                    f"https://graph.facebook.com/{FB_API_VERSION}/{fb_page}/video_reels",
                    data=finish_payload,
                    timeout=60,
                )
                finish_data = finish_resp.json()
            if finish_resp.status_code == 200 and finish_data.get("success", True) and "error" not in finish_data:
                logger.info(f"Facebook Reels published successfully: video_id={video_id}")
                upload_state[fingerprint]["facebook"] = {
                    "status": "completed",
                    "video_id": str(video_id),
                    "completed_at": time.time(),
                }
                _save_upload_state(upload_state)
                _set_fb_reel_cover(str(video_id), thumb_path, fb_token)
                return True
            else:
                raise RuntimeError(f"Reels finish phase failed: {finish_data}")

        except Exception as e:
            logger.warning(f"Facebook Reels upload attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * (2 ** (attempt - 1)))
            continue

    # Mirror the Instagram path: mark this attempt FAILED instead of leaving
    # it stuck at "started". A stale "started" record makes the next run raise
    # RuntimeError ("unknown completion state") for this script and crash the
    # whole pipeline — even though Facebook is an optional/best-effort platform.
    # Only a genuine mid-upload crash should leave "started" behind.
    upload_state[fingerprint]["facebook"] = {
        "status": "failed",
        "failed_at": time.time(),
    }
    _save_upload_state(upload_state)
    logger.error("Facebook Reels upload failed after all retries")
    return False


# ---------------------------------------------------------------------------
# INSTAGRAM REELS (Graph API, resumable upload)
# The Page's linked IG Business account (@mrnextep) gets the same Short as a
# native Reel, in the 4-phase flow verified working 2026-07-26:
#   1. POST /{ig-user-id}/media (media_type=REELS, upload_type=resumable)
#      -> container id + rupload uri   (permission smoke-test passed live)
#   2. POST the mp4 binary to the rupload uri
#   3. poll /{container-id}?fields=status_code until FINISHED
#   4. POST /{ig-user-id}/media_publish?creation_id=<container>
# ---------------------------------------------------------------------------

def _build_instagram_caption(script_data, tags):
    """Instagram-native caption.

    This used to be Facebook's caption plus a YouTube pointer, which ignored
    the two things Instagram actually ranks on: caption keywords (IG indexes
    caption text for search, and niche keywords outperform hashtags) and
    sends-per-reach, the confirmed #2 signal for reaching non-followers. The
    dedicated builder writes for both, then the YouTube handle is appended as
    plain text because IG captions have no clickable links.
    """
    try:
        from platform_captions import build_instagram_caption
        caption = build_instagram_caption(script_data, tags)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Instagram caption builder unavailable (%s); using legacy.", exc)
        caption = _build_facebook_description(script_data, tags)

    pointer = "More body science on YouTube @MrNextep"
    room = max(0, 2200 - len(pointer) - 2)
    return caption[:room].rstrip() + "\n\n" + pointer


def _already_uploaded_to_instagram(script_data) -> bool:
    """Prevent a duplicate Instagram Reel for an already recorded script."""
    fingerprint = _content_fingerprint(script_data)
    state = _load_upload_state().get(fingerprint, {}).get("instagram", {})
    if state.get("status") == "completed" and state.get("media_id"):
        return True
    return any(
        item.get("content_fingerprint") == fingerprint and item.get("instagram_success")
        for item in _load_upload_history()
    )


def _wait_for_instagram_slot() -> None:
    """Sleep until the next locked peak slot, so the Reel goes live on-peak.

    Instagram's Graph API cannot schedule a publish, so the only way to hit a
    peak is to hold the already-uploaded container and call media_publish at
    the right moment. The container is valid for roughly 24 hours.

    Reads the same slot table the YouTube scheduler uses, so all three
    platforms target one consistent set of times. Bounded by
    IG_MAX_WAIT_MINUTES (default 150) — if the next slot is further out than
    that, publish now instead of stalling the runner.
    """
    if os.environ.get("IG_WAIT_FOR_SLOT", "true").lower() != "true":
        logger.info("Instagram slot wait disabled (IG_WAIT_FOR_SLOT=false).")
        return

    max_wait_minutes = int(os.environ.get("IG_MAX_WAIT_MINUTES", "150") or "150")
    try:
        from scheduler import USAPeakTimeScheduler
        slots = USAPeakTimeScheduler().get_next_posting_times(3)
        if not slots:
            return
        target = min(s["time"] for s in slots)
    except Exception as exc:  # noqa: BLE001 — timing must never break upload
        logger.warning("Instagram slot lookup failed (%s); publishing now.", exc)
        return

    from datetime import datetime as _dtm
    import pytz as _pytz

    wait_seconds = (target - _dtm.now(_pytz.UTC).astimezone(target.tzinfo)).total_seconds()
    if wait_seconds <= 0:
        return
    if wait_seconds > max_wait_minutes * 60:
        logger.info(
            "Next Instagram peak is %.0f min away (cap %d min) — publishing now.",
            wait_seconds / 60, max_wait_minutes,
        )
        return

    logger.info(
        "Holding Instagram Reel %.0f min until the %s peak (%s).",
        wait_seconds / 60,
        next((s["peak_name"] for s in slots if s["time"] == target), "next"),
        target.strftime("%H:%M %Z"),
    )
    time.sleep(wait_seconds)


def _upload_instagram_reel(video_path, script_data, tags):
    """Cross-post the Short to the linked Instagram account. Best-effort by
    design: any permission/network failure logs a warning and returns False —
    the YouTube upload above it is never affected by IG trouble."""
    if os.environ.get("IG_UPLOAD_ENABLED", "false").lower() != "true":
        logger.info("Instagram upload disabled (set IG_UPLOAD_ENABLED=true to publish a Reel).")
        return False

    ig_user = os.environ.get("INSTAGRAM_USER_ID", "").strip()
    ig_token = (os.environ.get("IG_ACCESS_TOKEN") or os.environ.get("FB_ACCESS_TOKEN") or "").strip()
    if not ig_user or not ig_token:
        logger.warning("INSTAGRAM_USER_ID or access token missing - Instagram upload skipped")
        return False

    if _already_uploaded_to_instagram(script_data):
        logger.info("Instagram: '%s' already uploaded — skipping duplicate.", script_data.get("title"))
        return True

    fingerprint = _content_fingerprint(script_data)
    upload_state = _load_upload_state()
    ig_state = upload_state.get(fingerprint, {}).get("instagram", {})
    if ig_state.get("status") == "started":
        raise RuntimeError(
            "Earlier Instagram Reel has unknown completion state. Review @mrnextep before retrying."
        )
    upload_state.setdefault(fingerprint, {})["instagram"] = {
        "status": "started",
        "started_at": time.time(),
    }
    _save_upload_state(upload_state)

    caption = _build_instagram_caption(script_data, tags)

    for attempt in range(1, 3):  # max 2 attempts — IG must never stall the run
        try:
            # ---- Phase 1: resumable container ----
            container_resp = requests.post(
                f"https://graph.facebook.com/{FB_API_VERSION}/{ig_user}/media",
                data={
                    "media_type": "REELS",
                    "upload_type": "resumable",
                    "caption": caption,
                    "share_to_feed": "true",
                    "access_token": ig_token,
                },
                timeout=30,
            )
            container = container_resp.json()
            if "error" in container or "id" not in container:
                logger.warning("IG container create failed: %s", str(container)[:200])
                upload_state[fingerprint]["instagram"] = {
                    "status": "failed", "error": str(container)[:200], "failed_at": time.time(),
                }
                _save_upload_state(upload_state)
                return False
            container_id = container["id"]
            upload_url = container.get("uri") or (
                f"https://rupload.facebook.com/ig-api-upload/{FB_API_VERSION}/{container_id}"
            )

            # ---- Phase 2: binary upload ----
            file_size = os.path.getsize(video_path)
            with open(video_path, "rb") as fh:
                up_resp = requests.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {ig_token}",
                        "offset": "0",
                        "file_size": str(file_size),
                        "Content-Type": "application/octet-stream",
                    },
                    data=fh,
                    timeout=300,
                )
            if up_resp.status_code not in (200, 201):
                raise RuntimeError(f"IG binary upload failed: {up_resp.status_code} {up_resp.text[:150]}")

            # ---- Phase 3: wait for processing ----
            for _ in range(40):  # up to ~6.5 minutes
                time.sleep(10)
                status_resp = requests.get(
                    f"https://graph.facebook.com/{FB_API_VERSION}/{container_id}",
                    params={"fields": "status_code,status", "access_token": ig_token},
                    timeout=30,
                )
                code = (status_resp.json() or {}).get("status_code", "")
                if code == "FINISHED":
                    break
                if code in ("ERROR", "EXPIRED"):
                    raise RuntimeError(f"IG container processing failed: {status_resp.text[:200]}")
            else:
                raise RuntimeError("IG container processing timed out")

            # ---- Phase 4: publish ----
            # Hold the publish until the locked peak slot. YouTube uses
            # status.publishAt and Facebook uses scheduled_publish_time, but
            # the Instagram Graph API has NO scheduling parameter on
            # media_publish — so before this, every Reel went live the moment
            # generation finished (~10:45 / ~18:15 / ~19:45 NY), i.e. never at
            # a peak. Measured on this channel's own 15 videos: 12:00 NY
            # averaged 833 views and 20:00 averaged 730, while the 06:00-09:00
            # band averaged 50-79. Publishing off-peak was giving away the
            # single easiest gain.
            #
            # The container stays valid for ~24h, so waiting is safe. Capped
            # by IG_MAX_WAIT_MINUTES so a runner is never held hostage; if the
            # slot is further away than the cap, it publishes immediately
            # rather than failing — a live Reel beats a lost one.
            _wait_for_instagram_slot()

            pub_resp = requests.post(
                f"https://graph.facebook.com/{FB_API_VERSION}/{ig_user}/media_publish",
                data={"creation_id": container_id, "access_token": ig_token},
                timeout=60,
            )
            pub = pub_resp.json()
            if "error" in pub or "id" not in pub:
                raise RuntimeError(f"IG media_publish failed: {str(pub)[:200]}")

            upload_state[fingerprint]["instagram"] = {
                "status": "completed",
                "media_id": str(pub["id"]),
                "completed_at": time.time(),
            }
            _save_upload_state(upload_state)
            logger.info("Instagram Reel published successfully: media_id=%s", pub["id"])
            return True

        except Exception as exc:
            logger.warning("Instagram upload attempt %d/2 failed: %s", attempt, exc)
            if attempt < 2:
                time.sleep(15)

    upload_state[fingerprint]["instagram"] = {"status": "failed", "failed_at": time.time()}
    _save_upload_state(upload_state)
    logger.error("Instagram Reels upload failed (non-fatal)")
    return False


def upload_all(video_path, thumb_path, script_data, meta_video_path=None):
    """Publish to YouTube, Facebook Reels and Instagram Reels.

    video_path       the master cut — YouTube's edit (policy window ~30-42s)
    meta_video_path  the shorter Meta cut (~20-32s) for Facebook/Instagram.
                     Optional: when omitted both Meta platforms receive the
                     master cut, which is what happened before the dual-cut
                     change and is still an acceptable degraded mode.

    Passing two files matters because Facebook and Instagram grade completion
    on a much tighter curve than YouTube; sending one length to all three
    guaranteed that at least two of them saw an under-performing video.
    """

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if not script_data or 'title' not in script_data:
        raise ValueError("Invalid script data - missing title")

    title = script_data.get('title', 'Untitled')
    # Tags come from script_data (set by main.py via niche_strategy.generate_seo_tags).
    # Fallback below only fires if that ever comes back empty - matches the
    # current dark-facts niche, not the old parenting-channel tags.
    tags = script_data.get('tags') or ['facts', 'shorts', 'science', 'darkfacts', 'bodyfacts']

    logger.info(f"Starting upload process for: {title}")
    logger.info(f"selfDeclaredMadeForKids = {MADE_FOR_KIDS} (verify this is correct for your content!)")
    logger.info(f"YouTube privacy status = {YT_PRIVACY_STATUS}")
    logger.info(f"SEO tags for this video: {tags}")

    if DRY_RUN:
        youtube_description = _build_youtube_description(script_data, tags)
        facebook_description = _build_facebook_description(script_data, tags)
        logger.info("DRY_RUN: YouTube description length=%d", len(youtube_description))
        logger.info("DRY_RUN: Facebook caption length=%d", len(facebook_description))
        return {
            "youtube_success": True,
            "youtube_video_id": None,
            "facebook_success": True,
            "instagram_success": True,
            "dry_run": True,
        }

    # Meta gets its own shorter cut when one was rendered; otherwise it falls
    # back to the master so a failed second encode never costs us the Reels.
    meta_path = meta_video_path if (meta_video_path and os.path.exists(meta_video_path)) else video_path
    if meta_path != video_path:
        logger.info("Meta platforms receive the short cut: %s", os.path.basename(meta_path))

    youtube_success, yt_video_id = _upload_youtube(video_path, thumb_path, script_data, tags)
    facebook_success = _upload_facebook_reels(meta_path, script_data, tags, thumb_path)
    instagram_success = _upload_instagram_reel(meta_path, script_data, tags)

    logger.info(f"YouTube Upload: {'SUCCESS' if youtube_success else 'FAILED/SKIPPED'}")
    if yt_video_id:
        logger.info(f"  URL: https://youtu.be/{yt_video_id}")
    logger.info(f"Facebook Upload: {'SUCCESS' if facebook_success else 'FAILED/SKIPPED'}")
    logger.info(f"Instagram Upload: {'SUCCESS' if instagram_success else 'FAILED/SKIPPED'}")

    # YouTube is the primary channel. A Facebook/Instagram-only success must
    # never mark the run complete, otherwise the scheduler records a
    # successful upload while the required YouTube Short is missing.
    if not youtube_success:
        raise RuntimeError("YouTube upload failed; Facebook/Instagram success cannot replace the primary upload")

    # 2026-08-15: IG insights and IG repair were blocked because no platform
    # media ids ever reached video_history.json. upload_state recorded the IG
    # (and FB) ids, but upload_all did not surface them. Now the per-platform
    # ids flow through so the history ledger — the single source repair and
    # metrics scripts read — sees every platform.
    _state = _load_upload_state()
    _fp_state = _state.get(_content_fingerprint(script_data), {})
    return {
        "youtube_success": youtube_success,
        "youtube_video_id": yt_video_id,
        "facebook_success": facebook_success,
        "facebook_video_id": _fp_state.get("facebook", {}).get("video_id"),
        "instagram_success": instagram_success,
        "instagram_media_id": _fp_state.get("instagram", {}).get("media_id"),
        # The locked publishAt slot (None when scheduling is off) — main.py
        # persists it in video_history so future runs never claim it again.
        "publish_at": _RUN_PUBLISH_AT if YT_SCHEDULE_PUBLISH else None,
    }
