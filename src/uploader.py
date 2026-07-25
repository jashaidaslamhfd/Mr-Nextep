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
#   (12:30 / 16:30 / 20:00 America/New_York — kept in sync with
#   scheduler.USAPeakTimeScheduler.PEAK_TIMES and the workflow cron table).
# ---------------------------------------------------------------------------
YT_SCHEDULE_PUBLISH = os.environ.get("YT_SCHEDULE_PUBLISH", "false").lower() == "true"
_PUBLISH_TZ = pytz.timezone("America/New_York")
_PUBLISH_SLOTS = [(12, 30), (16, 30), (20, 0)]  # (hour, minute) New York time
# DATA-DRIVEN (2026-07-25 diag): every 06:00-slot upload died (139/133/10/0
# views) — the audience is asleep at 6am NY. Winners all came from the
# 12:30 and 20:00 slots, so the third slot moved to 4:30pm (school/work end).
_PUBLISH_MIN_LEAD_MINUTES = 30  # video must sit privately at least this long


def _compute_publish_at(now: datetime = None) -> str:
    """Next US peak slot in UTC RFC-3339 ('…Z'), always at least
    _PUBLISH_MIN_LEAD_MINUTES in the future. Scans today's and tomorrow's
    slots so a late-evening run rolls cleanly into tomorrow 12:30."""
    now_ny = (now or datetime.now(_PUBLISH_TZ)).astimezone(_PUBLISH_TZ)
    candidates = []
    for day_offset in (0, 1):
        for hour, minute in _PUBLISH_SLOTS:
            slot = now_ny.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
            if slot >= now_ny + timedelta(minutes=_PUBLISH_MIN_LEAD_MINUTES):
                candidates.append(slot)
    best = min(candidates) if candidates else (now_ny + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    return best.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")



def _build_youtube_description(script_data: dict, tags: list) -> str:
    """CTR-optimized YouTube description. Delegates to
    seo_generator.generate_description() so upload and the SEO-package
    preview (script_data['description'] set in main.py) can never drift
    out of sync - this used to be a separate copy of the same logic."""
    return generate_description(script_data, tags)


def _build_facebook_description(script_data: dict, tags: list) -> str:
    """Build a Facebook-native Reel caption, never a copied YouTube block.

    Facebook gets a short natural-language caption for NLP/topic matching;
    YouTube gets its own search-oriented description. We deliberately use
    `summary` first and strip old hashtags/formatting so a legacy YouTube
    description cannot be pasted inside the Facebook caption a second time.
    """
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
        publish_at = _compute_publish_at()
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
                files={"file": (os.path.basename(thumb_path), fh, "image/jpeg")},
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

    logger.error("Facebook Reels upload failed after all retries")
    return False


def upload_all(video_path, thumb_path, script_data):
    """Upload video to YouTube and Facebook Reels with comprehensive error handling."""

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
            "dry_run": True,
        }

    youtube_success, yt_video_id = _upload_youtube(video_path, thumb_path, script_data, tags)
    facebook_success = _upload_facebook_reels(video_path, script_data, tags, thumb_path)

    logger.info(f"YouTube Upload: {'SUCCESS' if youtube_success else 'FAILED/SKIPPED'}")
    if yt_video_id:
        logger.info(f"  URL: https://youtu.be/{yt_video_id}")
    logger.info(f"Facebook Upload: {'SUCCESS' if facebook_success else 'FAILED/SKIPPED'}")

    # YouTube is the primary channel. A Facebook-only success must never mark
    # the run complete, otherwise the scheduler records a successful upload
    # while the required YouTube Short is missing.
    if not youtube_success:
        raise RuntimeError("YouTube upload failed; Facebook success cannot replace the primary upload")

    return {
        "youtube_success": youtube_success,
        "youtube_video_id": yt_video_id,
        "facebook_success": facebook_success,
    }
