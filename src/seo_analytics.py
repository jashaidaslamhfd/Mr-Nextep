"""
src/seo_analytics.py

Second wave of the PRD "AI SEO Generator" section - the subset that needs
NO external API/keys (no Google Trends, no YouTube Analytics, no
competitor-channel access). Everything here is either a heuristic model
over data MrNextep already produces, or a PIL/numpy analysis of the actual
thumbnail file already on disk.

Honest scope note up front, since it matters for how much to trust this:
  - predict_ctr() is a HEURISTIC estimate calibrated from the same signals
    quality_checker/seo_generator already score (hook strength, title
    pattern, tag quality). It is NOT trained on real YouTube CTR data,
    because no analytics connection exists yet. Treat the number as "how
    well this follows known CTR-correlated patterns", not a guarantee.
  - score_thumbnail() analyzes contrast/text-length/layout from the actual
    generated image. It does NOT do face/emotion detection - that needs a
    CV model (e.g. opencv + a face/emotion classifier) which isn't in
    requirements.txt. That field is reported as "not_available" rather
    than faked.
  - get_historical_insights() mines output/video_history.json. Today that
    file has no real view/CTR data (nothing pulls YouTube Analytics yet),
    so insights are computed from our own predicted scores and flagged as
    such. The function is written so that the moment real 'actual_ctr' or
    'views' keys start appearing in history entries (once an analytics
    puller is added), it automatically prefers real data over predictions
    without any code changes needed here.
"""

import os
import json
import logging
from typing import Dict, List
from collections import defaultdict

import numpy as np
from PIL import Image

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

HISTORY_FILE = os.environ.get("VIDEO_HISTORY_PATH", "data/video_history.json")


# ---------------------------------------------------------------------------
# 1. CTR Prediction (heuristic, not ML-trained on real data - see module note)
# ---------------------------------------------------------------------------

def predict_ctr(script_data: Dict) -> Dict:
    """Combines signals already computed elsewhere in the pipeline
    (hook score, SEO score, title pattern) into a single 0-10 CTR estimate
    with a confidence label reflecting how many of those signals were
    actually available. Weights are hand-set from generally-known Shorts
    CTR correlations (strong hook + specific title + tight tags), not
    fitted on this channel's own data."""
    hook_score = None
    if 'shorts_report' in script_data:
        hook_score = script_data['shorts_report'].get('hook_detail', {}).get('score')
    seo_score = script_data.get('seo_score', {}).get('scores', {}).get('overall_seo_score')
    title = script_data.get('title', '')

    signals_available = sum(x is not None for x in (hook_score, seo_score, title))

    # Normalize each available signal to 0-10 and weight them.
    parts = []
    if hook_score is not None:
        parts.append((hook_score / 10, 0.45))
    if seo_score is not None:
        parts.append((seo_score / 10, 0.35))
    if title:
        title_len = len(title)
        title_len_score = 10 if 30 <= title_len <= 60 else 6
        parts.append((title_len_score, 0.20))

    if not parts:
        return {'ctr_prediction': None, 'confidence': 0.0, 'note': 'No signals available - run quality/SEO scoring first.'}

    weighted_sum = sum(score * weight for score, weight in parts)
    total_weight = sum(weight for _, weight in parts)
    ctr = round(weighted_sum / total_weight, 1)

    confidence = round(0.4 + 0.2 * signals_available, 2)  # 0.6-1.0 range across 1-3 signals
    confidence = min(confidence, 0.85)  # cap - this is a heuristic, never claim near-certainty

    return {
        'ctr_prediction': ctr,
        'confidence': confidence,
        'basis': 'heuristic (hook/SEO/title-length signals) - not trained on real channel CTR data yet',
    }


# ---------------------------------------------------------------------------
# 2. Thumbnail SEO scoring (real image analysis via PIL/numpy)
# ---------------------------------------------------------------------------

def score_thumbnail(thumb_path: str, title: str) -> Dict:
    """Analyzes the actual generated thumbnail file. Only measures what's
    computable without an ML model: contrast in the text-overlay strip,
    text length/line-wrap readability, and dominant-color warmth (a cheap
    proxy for 'color psychology' - warm/high-saturation colors are the
    well-documented CTR-correlated end of that scale, not literally
    modeling emotion)."""
    if not thumb_path or not os.path.exists(thumb_path):
        return {'error': f'Thumbnail not found at {thumb_path}'}

    with Image.open(thumb_path) as _src:
        img = _src.convert("RGB")
    arr = np.array(img)
    h, w, _ = arr.shape

    # video_editor.generate_thumbnail() draws the title in the bottom
    # ~220px strip over a dark gradient - check contrast there specifically,
    # since that's where readability actually matters.
    strip_top = max(h - 220, 0)
    strip = arr[strip_top:h, :, :]
    grayscale_strip = strip.mean(axis=2)
    contrast_std = float(grayscale_strip.std())
    # Dark gradient + white/bold text should produce a high std (bimodal
    # dark background / light text). Below ~35 usually means low contrast.
    contrast_score = min(100, round((contrast_std / 70) * 100))

    # Text length / mobile readability - shorter titles read faster at
    # thumbnail size, especially on phone screens.
    char_count = len(title)
    word_count = len(title.split())
    if char_count <= 35 and word_count <= 6:
        readability_score = 100
    elif char_count <= 50 and word_count <= 8:
        readability_score = 75
    else:
        readability_score = 50

    # Dominant color warmth as a color-psychology proxy: warm/saturated
    # thumbnails (red/orange/yellow dominant) are the well-known
    # CTR-correlated end for shock/curiosity-style content like this niche.
    r_mean, g_mean, b_mean = arr[:, :, 0].mean(), arr[:, :, 1].mean(), arr[:, :, 2].mean()
    warm_bias = (r_mean + g_mean) - 2 * b_mean  # positive = warmer image
    color_score = max(0, min(100, round(50 + warm_bias / 2)))

    overall = round((contrast_score * 0.45) + (readability_score * 0.35) + (color_score * 0.20))

    return {
        'contrast_score': contrast_score,
        'readability_score': readability_score,
        'color_score': color_score,
        'face_emotion_score': 'not_available (no face/emotion model configured)',
        'overall_thumbnail_score': overall,
        'title_char_count': char_count,
        'title_word_count': word_count,
    }


# ---------------------------------------------------------------------------
# 3. Hashtag ranking (proxy discovery/competition, no real search-volume API)
# ---------------------------------------------------------------------------

# BASE_TAGS in niche_strategy.py are broad/generic -> high volume, high
# competition. CATEGORY_TAGS are mid-specific -> medium/medium. Anything
# else (topic-word tags) is the long-tail -> low volume, low competition,
# highest relevance. This mirrors real tag-volume distributions without
# needing live search-volume data.
_BROAD_TAG_HINTS = {
    "darkfacts", "facts", "shorts", "youtubeshorts", "science",
    "didyouknow", "mindblowing", "funfacts", "scaryfacts", "viral",
}


def rank_hashtags(tags: List[str]) -> List[Dict]:
    """Returns each tag with proxy discovery/competition/trend scores and
    a recommendation, ranked by an overall 'discovery value' that favors a
    realistic broad+niche+long-tail mix over an all-broad or all-long-tail
    list."""
    ranked = []
    for tag in tags:
        clean = tag.lower().lstrip('#')
        if clean in _BROAD_TAG_HINTS:
            volume, competition, tier = 90, 90, "broad"
        elif len(clean) <= 12:
            volume, competition, tier = 55, 50, "niche"
        else:
            volume, competition, tier = 25, 15, "long_tail"

        # Discovery value rewards low competition relative to volume -
        # i.e. the classic "easier to rank, still gets found" sweet spot.
        discovery_score = round((volume * 0.5) + ((100 - competition) * 0.5))

        ranked.append({
            'tag': tag,
            'tier': tier,
            'volume_proxy': volume,
            'competition_proxy': competition,
            'discovery_score': discovery_score,
        })

    ranked.sort(key=lambda x: x['discovery_score'], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# 4. A/B variant generation + auto-ranking
# ---------------------------------------------------------------------------

def generate_ab_variants(script_data: Dict, title_options: List[str]) -> Dict:
    """Builds description variants (short-punchy vs longer-context) for
    each of the already-generated title options, scores every
    title+description pairing with predict_ctr(), and returns them ranked
    so the top of the list is the recommended combo - true A/B test PREP,
    not a live split test (that needs real traffic, which happens after
    upload)."""
    hook = script_data.get('hook', '')
    cta = script_data.get('cta', '')
    desc_base = script_data.get('description', '')

    description_variants = {
        'short_punchy': f"{hook}\n\n👇 {cta}",
        'context_first': f"{desc_base}\n\n{hook}\n\n👇 {cta}",
    }

    variants = []
    for title in title_options:
        for desc_label, desc_text in description_variants.items():
            trial_script = dict(script_data)
            trial_script['title'] = title
            trial_script['description'] = desc_text
            ctr = predict_ctr(trial_script)
            variants.append({
                'title': title,
                'description_variant': desc_label,
                'description_preview': desc_text[:120],
                'predicted_ctr': ctr.get('ctr_prediction'),
            })

    variants.sort(key=lambda v: (v['predicted_ctr'] or 0), reverse=True)
    return {
        'variants': variants,
        'recommended': variants[0] if variants else None,
    }


# ---------------------------------------------------------------------------
# 5. Historical learning over output/video_history.json
# ---------------------------------------------------------------------------

def _load_history() -> List[Dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return []


def _title_pattern(title: str) -> str:
    """Buckets a title by which seo_generator template family produced it,
    so patterns can be compared against each other over time."""
    t = title.lower()
    if 'truth about' in t:
        return 'THE_TRUTH'
    if "won't tell you" in t or "doctors" in t:
        return 'DOCTORS_WONT_TELL'
    if t.startswith('why'):
        return 'WHY'
    if '🫀' in title or any(e in title for e in ['🧠', '🔬']):
        return 'EMOJI_ENHANCED'
    return 'OTHER'


def get_historical_insights(min_sample: int = 3) -> Dict:
    """Groups past videos by title pattern and compares average performance.
    Uses 'actual_ctr'/'views' from history entries when present (once a
    YouTube Analytics puller is added upstream); otherwise falls back to
    each entry's own predicted_ctr/seo_score recorded at generation time.
    Buckets with fewer than min_sample videos are excluded - not enough
    data to say anything meaningful yet."""
    history = _load_history()
    if not history:
        return {'insights': [], 'note': 'No video history yet.'}

    using_real_data = any('actual_ctr' in v or 'views' in v for v in history)

    buckets = defaultdict(list)
    for v in history:
        title = v.get('title', '')
        if not title:
            continue
        pattern = _title_pattern(title)
        if 'actual_ctr' in v:
            metric = v['actual_ctr']
        elif 'predicted_ctr' in v:
            metric = v['predicted_ctr']
        elif 'seo_score' in v:
            metric = v['seo_score']
        else:
            continue
        if metric is not None:
            buckets[pattern].append(metric)

    insights = []
    for pattern, values in buckets.items():
        if len(values) >= min_sample:
            insights.append({
                'title_pattern': pattern,
                'sample_size': len(values),
                'avg_score': round(sum(values) / len(values), 2),
            })
    insights.sort(key=lambda x: x['avg_score'], reverse=True)

    return {
        'insights': insights,
        'data_source': 'real_analytics' if using_real_data else 'predicted_scores (no analytics connected yet)',
        'note': None if insights else f'Not enough videos per title-pattern yet (need >= {min_sample} each).',
    }


# ---------------------------------------------------------------------------
# 6. REAL YouTube Analytics fetch (needs OAuth creds - see uploader.py)
#
# Everything above this point is heuristic. This is the actual "system ab
# blind nahi" piece: it calls the real YouTube Analytics API (v2) for one
# video and returns real views / average-view-duration / real CTR.
#
# Reuses the SAME OAuth refresh-token creds uploader.py already uses for
# the Data API upload - it just additionally needs the
# `yt-analytics.readonly` scope to have been granted when that
# REFRESH_TOKEN was issued. If it wasn't, this returns an 'error' instead
# of raising, so a missing scope never crashes the pipeline.
# ---------------------------------------------------------------------------

def fetch_actual_performance(youtube_video_id: str, days_back: int = 30) -> Dict:
    """Pulls real lifetime-to-date performance for one video: views,
    averageViewDuration (seconds), averageViewPercentage (retention %),
    impressions, and impressionsClickThroughRate (real CTR - the actual
    metric predict_ctr() above can only estimate)."""
    import datetime as _dt
    import google.oauth2.credentials
    from googleapiclient.discovery import build as _build
    from googleapiclient.errors import HttpError

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")
    missing = [n for n, v in {
        "GOOGLE_CLIENT_ID": client_id, "GOOGLE_CLIENT_SECRET": client_secret,
        "REFRESH_TOKEN": refresh_token,
    }.items() if not v]
    if missing:
        return {"error": f"Missing credentials: {missing}"}

    # Do NOT pass `scopes=` here. google-auth then sends a `scope` field on
    # the refresh_token grant, and Google rejects any refresh that tries to
    # narrow or alter the scopes a token was minted with — returning
    # `invalid_scope: Bad Request` before a single metric is requested.
    #
    # This silently killed every analytics run: the workflow exited 0 (the
    # errors are caught per-video and logged as warnings) while all 17 videos
    # failed, so data/video_history.json never received a single real view
    # count. Confirmed in the 2026-07-26 run log, which reports "success".
    #
    # scripts/seo_diag.py reads the same Analytics reports with the same
    # REFRESH_TOKEN precisely because it posts a bare refresh grant with no
    # scope field. The token already carries yt-analytics.readonly and the
    # issued access token inherits it.
    creds = google.oauth2.credentials.Credentials(
        token=None, refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret,
    )
    yta = _build("youtubeAnalytics", "v2", credentials=creds)

    end = _dt.date.today()
    start = end - _dt.timedelta(days=max(days_back, 1))

    # Self-healing metric list. `impressions` and `impressionsClickThroughRate`
    # are not served for every channel; requesting them unconditionally makes
    # the API reject the WHOLE query with 400 "Unknown identifier", so a
    # channel that merely cannot report CTR also loses views and retention.
    # Drop the offending metric and retry instead of failing outright.
    import re as _re

    requested = [
        "views", "averageViewDuration", "averageViewPercentage",
        "impressions", "impressionsClickThroughRate",
    ]
    resp, dropped = None, []
    for _ in range(len(requested)):
        try:
            resp = yta.reports().query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics=",".join(requested),
                dimensions="video",
                filters=f"video=={youtube_video_id}",
            ).execute()
            break
        except HttpError as e:
            status = getattr(e.resp, "status", None)
            raw = e.content.decode("utf-8", "replace") if isinstance(e.content, bytes) else str(e.content or e)
            unknown = _re.search(r"Unknown identifier \((\w+)\)", raw)
            if status == 400 and unknown and unknown.group(1) in requested and len(requested) > 1:
                bad = unknown.group(1)
                requested.remove(bad)
                dropped.append(bad)
                logger.info("Metric '%s' unavailable on this channel -> retrying without it.", bad)
                continue
            # 403 here is almost always "YouTube Analytics API has not been
            # used in project N before or it is disabled" — a Google Cloud
            # console setting, NOT a code or token problem. FIXED 2026-07-31:
            # Now returns exact console link from GROWTH_SETUP.md so operator
            # can fix in 1 click instead of searching.
            if status == 403 and "has not been used in project" in raw:
                logger.error(
                    "YouTube Analytics API DISABLED — fix: https://console.developers.google.com/"
                    "apis/api/youtubeanalytics.googleapis.com/overview?project=559439687452 "
                    "-> Click ENABLE, wait 2 min, then re-run Analytics workflow. "
                    "This is a project setting, not a token problem."
                )
                return {"error": "analytics_api_disabled", "detail": raw[:300], "fix_url": "https://console.developers.google.com/apis/api/youtubeanalytics.googleapis.com/overview?project=559439687452"}
            logger.warning(f"YouTube Analytics fetch failed for {youtube_video_id}: {e}")
            if status in (401,):
                return {"error": f"HttpError {status}: needs yt-analytics.readonly scope on REFRESH_TOKEN"}
            return {"error": f"HttpError {status}: {raw[:200]}"}
        except Exception as e:
            logger.warning(f"YouTube Analytics fetch failed for {youtube_video_id}: {e}")
            return {"error": str(e)}

    if resp is None:
        return {"error": "No supported metric combination was accepted by the Analytics API."}

    rows = resp.get("rows") or []
    if not rows:
        return {"note": "No analytics rows yet - data can take 24-48h to populate after upload."}

    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    values = dict(zip(headers, rows[0]))

    return {
        "video_id": youtube_video_id,
        "views": values.get("views"),
        "average_view_duration_sec": values.get("averageViewDuration"),
        "average_view_percentage": values.get("averageViewPercentage"),
        "impressions": values.get("impressions"),
        "actual_ctr": values.get("impressionsClickThroughRate"),
        "unavailable_metrics": dropped,
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


def update_history_with_real_metrics(min_hours_old: int = 24) -> Dict:
    """Meant to run on its OWN schedule (separate cron/GitHub Action),
    NOT inside the main generation pipeline - real analytics data isn't
    available immediately after upload.

    Walks output/video_history.json, finds entries with a
    youtube_video_id but no 'actual_ctr' yet that are at least
    `min_hours_old` hours old, fetches real numbers for each via
    fetch_actual_performance(), and writes them back into that SAME
    history entry. Once this has run for a video,
    get_historical_insights() above automatically prefers
    'real_analytics' over predicted scores - no other code changes
    needed, it already checks for 'actual_ctr'/'views' first."""
    import datetime as _dt

    history = _load_history()
    if not history:
        return {"updated": 0, "note": "No history file yet."}

    now = _dt.datetime.now(_dt.timezone.utc)
    updated, failed, api_disabled = 0, 0, False
    no_data_yet = 0  # videos too young for analytics (normal, not a failure)
    for entry in history:
        vid = entry.get("youtube_video_id")
        posted_at = entry.get("posted_at")
        # Freshness is tracked by 'analytics_fetched_at', NOT by the presence
        # of an 'actual_ctr' key. On a channel where the API does not serve
        # CTR that key gets written as None, which would permanently freeze
        # the entry at its first empty reading and its views would never grow.
        if not vid or not posted_at:
            continue
        try:
            posted_dt = _dt.datetime.fromisoformat(posted_at)
            if posted_dt.tzinfo is None:
                posted_dt = posted_dt.replace(tzinfo=_dt.timezone.utc)
        except Exception:
            continue
        age_hours = (now - posted_dt).total_seconds() / 3600
        if age_hours < min_hours_old:
            continue
        last_fetch = entry.get("analytics_fetched_at")
        if last_fetch:
            try:
                last_dt = _dt.datetime.fromisoformat(last_fetch)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=_dt.timezone.utc)
                if (now - last_dt).total_seconds() / 3600 < 24:
                    continue
            except Exception:
                pass

        metrics = fetch_actual_performance(vid)
        if metrics.get("error") == "analytics_api_disabled":
            api_disabled = True
            break                      # pointless to try the other 16 videos
        if "error" in metrics or "note" in metrics:
            if "note" in metrics and "No analytics rows yet" in str(metrics.get("note", "")):
                no_data_yet += 1
                logger.info(f"{vid}: {metrics['note']}")
            else:
                failed += 1
                logger.info(f"{vid}: {metrics.get('error') or metrics.get('note')}")
            continue

        entry["views"] = metrics["views"]
        entry["actual_ctr"] = metrics["actual_ctr"]
        entry["average_view_duration_sec"] = metrics["average_view_duration_sec"]
        entry["average_view_percentage"] = metrics["average_view_percentage"]
        entry["analytics_fetched_at"] = metrics["fetched_at"]
        updated += 1
        logger.info(
            f"Updated real metrics for {vid}: views={metrics['views']}, "
            f"CTR={metrics['actual_ctr']}, avg_view_pct={metrics['average_view_percentage']}"
        )

    if updated:
        # Atomic write, matching the rest of the pipeline: a crash mid-write
        # previously truncated the whole channel history.
        os.makedirs(os.path.dirname(HISTORY_FILE) or ".", exist_ok=True)
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        os.replace(tmp, HISTORY_FILE)

    return {
        "updated": updated,
        "failed": failed,
        "no_data_yet": no_data_yet,
        "total_entries": len(history),
        "api_disabled": api_disabled,
    }


if __name__ == "__main__":
    test_script = {
        'title': "🫀 Your Heart Has Its Own Brain",
        'hook': "Doctors don't want you to know this about your heart...",
        'cta': 'Follow for more dark body secrets',
        'description': 'Your heart contains its own independent nervous system.',
        'seo_score': {'scores': {'overall_seo_score': 85}},
        'shorts_report': {'hook_detail': {'score': 60}},
    }
    print(json.dumps(predict_ctr(test_script), indent=2))
    print(json.dumps(rank_hashtags(['darkfacts', 'heartfacts', 'neuroscience']), indent=2))
    print(json.dumps(generate_ab_variants(test_script, ["Title A", "Title B"]), indent=2))
