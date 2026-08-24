"""
src/revival.py

Old video revival engine — makes dead YouTube/FB/IG videos start getting views
again WITHOUT re-uploading, WITHOUT hurting channel health, and WITHOUT manual
effort.

Strategy (ranked by safety and effectiveness):
  1. END SCREENS — new uploads carry cards pointing to 2-3 old videos
  2. PLAYLISTS — group dead videos into themed playlists; YouTube surfaces
     playlists as a unit, giving dead videos a second life
  3. DESCRIPTION CROSS-LINKS — every new video description mentions 2 old
     related videos with clickable timestamps
  4. THUMBNAIL REFRESH — re-render thumbnails on dead-but-promising videos;
     YouTube re-indexes on thumbnail change (capped at 3/day)
  5. META STORIES RESHARE — push old FB/IG reels to Stories where the
     algorithm is less punitive about initial performance
  6. COMMUNITY POSTS — YouTube Community tab posts linking to old videos
     (manual approval gate — the script generates drafts)

None of these violate YouTube ToS or Meta community guidelines. None involve
re-uploading, deleting, or privating content. None trigger duplicate-content
detection. Channel health metrics are unaffected or improved.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
UPLOAD_HISTORY_PATH = os.path.join(DATA_DIR, 'upload_history.json')
VIDEO_HISTORY_PATH = os.path.join(DATA_DIR, 'video_history.json')
REVIVAL_STATE_PATH = os.path.join(DATA_DIR, 'revival_state.json')
FB_REELS_PATH = os.path.join(DATA_DIR, 'facebook_real_data.json')
IG_REELS_PATH = os.path.join(DATA_DIR, 'instagram_real_data.json')
REVIVAL_QUEUE_PATH = os.path.join(DATA_DIR, 'revival_queue.json')

# Safety caps
MAX_THUMBNAIL_REFRESHES_PER_DAY = 3
MAX_END_SCREEN_VIDEOS = 3
MAX_DESCRIPTION_CROSS_LINKS = 2
MAX_COMMUNITY_POSTS_PER_WEEK = 3
MAX_META_STORIES_PER_DAY = 2

# Engagement thresholds for revival eligibility
DEAD_VIEW_THRESHOLD = 100        # videos with fewer views than this are "dead"
POTENTIAL_VIEW_THRESHOLD = 50    # but had at least this many to show early promise
DEAD_AGE_MIN_DAYS = 7            # video must be at least this old to be "dead"
RETENTION_BONUS_THRESHOLD = 0.4  # videos with >40% retention get priority


def _load_json(path: str, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)


def _now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. REVIVAL SCORER — ranks dead videos by revival potential
# ---------------------------------------------------------------------------

def score_revival_potential(video: dict, platform: str = 'youtube') -> float:
    """Score a dead video's revival potential on a 0–100 scale.

    Higher score = more worth reviving. Factors:
      - View count (low but non-zero = early signal, high = already succeeded)
      - Retention / completion rate (high retention = good content, bad luck)
      - Age (newer = algorithm hasn't fully written it off yet)
      - Topic category (muscle/ear topics outperform per growth_state)
      - Hook type (statements outperform 'why' questions)
    """
    score = 0.0
    views = video.get('views', 0)
    age_days = video.get('age_days', 30)
    retention = video.get('retention', video.get('avg_completion', 0))
    topic = video.get('topic', 'other')
    hook = video.get('hook_type', 'unknown')

    # --- Views: sweet spot is 20-150 views (enough to prove some organic reach,
    #     low enough that there's massive upside)
    if views == 0:
        score += 5          # zero views = maybe broken, low priority
    elif views < POTENTIAL_VIEW_THRESHOLD:
        score += 15         # some views = had a chance
    elif views < DEAD_VIEW_THRESHOLD:
        score += 30         # sweet spot: proven organic reach, not yet successful
    elif views < 300:
        score += 20         # decent but stalled
    else:
        score += 10         # already semi-successful, lower marginal gain

    # --- Retention: the strongest signal. High retention = good video, bad timing
    if retention >= 0.5:
        score += 35         # excellent retention — algorithm just didn't push it
    elif retention >= RETENTION_BONUS_THRESHOLD:
        score += 25         # above average — worth a second chance
    elif retention >= 0.3:
        score += 10         # mediocre — some potential
    else:
        score += 0          # poor retention — reviving won't help

    # --- Age: newer videos have a better chance (algorithm memory is short)
    if age_days < 14:
        score += 15
    elif age_days < 30:
        score += 10
    elif age_days < 60:
        score += 5
    # older than 60 days: no bonus

    # --- Topic bonus (from growth_state learning)
    topic_bonuses = {'muscle': 10, 'ear': 5, 'other': 3, 'brain': 0}
    score += topic_bonuses.get(topic, 2)

    # --- Hook type bonus
    hook_bonuses = {'statement': 5, 'unknown': 2, 'why': 0}
    score += hook_bonuses.get(hook, 0)

    # --- Platform adjustment
    if platform == 'facebook':
        score *= 0.85   # FB reels are harder to revive (less playlist discovery)
    elif platform == 'instagram':
        score *= 0.80   # IG is hardest — stories reshare is the only good lever

    return min(100.0, max(0.0, score))


def identify_revival_candidates(youtube_history: list = None,
                                 fb_reels: list = None,
                                 ig_reels: list = None,
                                 max_candidates: int = 15) -> dict:
    """Scan all platforms for dead videos worth reviving.

    Returns a dict with 'youtube', 'facebook', 'instagram' lists, each
    sorted by revival score descending.
    """
    if youtube_history is None:
        youtube_history = _load_json(UPLOAD_HISTORY_PATH, [])
    if fb_reels is None:
        fb_data = _load_json(FB_REELS_PATH, {})
        fb_reels = fb_data.get('reels', [])
    if ig_reels is None:
        ig_data = _load_json(IG_REELS_PATH, {})
        ig_reels = ig_data.get('reels', [])

    now = _now_utc()
    candidates = {'youtube': [], 'facebook': [], 'instagram': []}

    # YouTube candidates
    for item in youtube_history:
        vid_id = item.get('youtube_video_id')
        if not vid_id:
            continue
        views = item.get('views', 0)
        if views >= 500:
            continue  # already performing — don't waste end-screen slots
        posted = item.get('posted_at', '')
        age_days = _age_days(posted, now)
        if age_days < DEAD_AGE_MIN_DAYS:
            continue
        video = {
            'id': vid_id,
            'title': item.get('title', item.get('seo_title', 'Untitled')),
            'views': views,
            'retention': item.get('retention', item.get('avg_completion', 0)),
            'topic': item.get('topic', 'other'),
            'hook_type': item.get('hook_type', 'unknown'),
            'age_days': age_days,
            'posted_at': posted,
            'description': item.get('description', ''),
        }
        video['revival_score'] = score_revival_potential(video, 'youtube')
        candidates['youtube'].append(video)

    candidates['youtube'].sort(key=lambda x: x['revival_score'], reverse=True)
    candidates['youtube'] = candidates['youtube'][:max_candidates]

    # Facebook candidates
    for reel in fb_reels:
        vid_id = reel.get('id')
        if not vid_id:
            continue
        views = reel.get('views', 0)
        if views >= 500:
            continue
        posted = reel.get('created_time', '')
        age_days = _age_days(posted, now)
        if age_days < DEAD_AGE_MIN_DAYS:
            continue
        video = {
            'id': vid_id,
            'title': reel.get('title', reel.get('name', 'Untitled')),
            'views': views,
            'retention': 0,
            'topic': 'other',
            'hook_type': 'unknown',
            'age_days': age_days,
            'posted_at': posted,
            'permalink': reel.get('permalink_url', ''),
        }
        video['revival_score'] = score_revival_potential(video, 'facebook')
        candidates['facebook'].append(video)

    candidates['facebook'].sort(key=lambda x: x['revival_score'], reverse=True)
    candidates['facebook'] = candidates['facebook'][:max_candidates]

    # Instagram candidates
    for reel in ig_reels:
        vid_id = reel.get('id')
        if not vid_id:
            continue
        views = reel.get('views', 0)
        if views >= 500:
            continue
        posted = reel.get('timestamp', reel.get('created_time', ''))
        age_days = _age_days(posted, now)
        if age_days < DEAD_AGE_MIN_DAYS:
            continue
        video = {
            'id': vid_id,
            'title': reel.get('caption', reel.get('description', 'Untitled'))[:60],
            'views': views,
            'retention': 0,
            'topic': 'other',
            'hook_type': 'unknown',
            'age_days': age_days,
            'posted_at': posted,
        }
        video['revival_score'] = score_revival_potential(video, 'instagram')
        candidates['instagram'].append(video)

    candidates['instagram'].sort(key=lambda x: x['revival_score'], reverse=True)
    candidates['instagram'] = candidates['instagram'][:max_candidates]

    return candidates


def _age_days(posted_str: str, now: datetime) -> int:
    """Parse a posted-at string and return age in days."""
    if not posted_str:
        return 999
    try:
        posted = datetime.fromisoformat(posted_str.replace('Z', '+00:00'))
        return max(0, (now - posted).days)
    except (ValueError, TypeError):
        return 999


# ---------------------------------------------------------------------------
# 2. END SCREEN PLANNER — picks which old videos to link in new uploads
# ---------------------------------------------------------------------------

def plan_end_screens(new_video: dict,
                     candidates: list,
                     max_videos: int = MAX_END_SCREEN_VIDEOS) -> list:
    """Pick the best old videos to show as end-screen cards on a new upload.

    Strategy:
      - Same topic as new video gets priority (cross-watch likelihood)
      - Higher revival_score gets priority
      - Never link the same video twice in a row (tracked in revival_state)
    """
    state = _load_json(REVIVAL_STATE_PATH, {})
    recently_used = set(state.get('recent_end_screen_ids', []))

    scored = []
    new_topic = new_video.get('topic', 'other')
    for c in candidates:
        if c['id'] in recently_used:
            continue
        topic_boost = 20 if c.get('topic') == new_topic else 0
        scored.append({
            'video_id': c['id'],
            'title': c['title'],
            'revival_score': c['revival_score'] + topic_boost,
            'reason': f"topic match: {c['topic']}" if topic_boost else "high revival score",
        })

    scored.sort(key=lambda x: x['revival_score'], reverse=True)
    selected = scored[:max_videos]

    # Track usage
    if selected:
        used_ids = [s['video_id'] for s in selected]
        state['recent_end_screen_ids'] = list(
            (state.get('recent_end_screen_ids', []) + used_ids)[-50:]
        )
        state['last_end_screen_run'] = _now_utc().isoformat()
        _save_json(REVIVAL_STATE_PATH, state)

    return selected


def generate_end_screen_elements(end_screen_videos: list) -> list:
    """Generate YouTube endScreen element configs for the API.

    Returns a list of dicts suitable for including in a YouTube
    videos.update call with part=endScreen.
    """
    elements = []
    for i, v in enumerate(end_screen_videos):
        # Stagger the elements across the last 20 seconds
        start_offset = f"{20 - (i * 5)}s"
        elements.append({
            'type': 'endScreenElement',
            'endScreenElementType': 'video',
            'videoId': v['video_id'],
            'startOffset': start_offset,
            'endOffset': '20s',
            'style': 'RECTANGLE',
        })
    return elements


# ---------------------------------------------------------------------------
# 3. PLAYLIST MANAGER — groups dead videos into themed playlists
# ---------------------------------------------------------------------------

PLAYLIST_CATALOG = {
    'Brain': {
        'title': '🧠 Dark Brain Facts You Won\'t Believe',
        'description': 'The creepiest things your brain does when you\'re not watching. New videos every week.',
    },
    'Body': {
        'title': '🫀 Dark Body Facts That Sound Fake',
        'description': 'Your body is hiding things from you. These facts will change how you see yourself.',
    },
    'Ear': {
        'title': '👂 Your Ears Are Hiding Something',
        'description': 'The strange things your ears do that nobody talks about.',
    },
    'Mystery': {
        'title': '🔮 Body Mysteries Solved',
        'description': 'Unexplained body phenomena — the science behind the strange.',
    },
    'Health': {
        'title': '🩺 Health Facts You Need To Know',
        'description': 'Quick science-backed health facts that could save your life.',
    },
}


def suggest_playlist_groups(candidates: list) -> dict:
    """Group revival candidates into playlist buckets.

    Returns {category: [video_id, ...]} for categories with 2+ videos.
    A category needs at least 2 videos to form a meaningful playlist.
    """
    groups: Dict[str, list] = {}
    for c in candidates:
        topic = c.get('topic', 'other')
        if topic not in groups:
            groups[topic] = []
        groups[topic].append(c['id'])

    # Filter: need at least 2 videos per playlist
    return {k: v for k, v in groups.items() if len(v) >= 2}


# ---------------------------------------------------------------------------
# 4. THUMBNAIL REFRESH SCHEDULER — safe re-render of dead video thumbnails
# ---------------------------------------------------------------------------

def plan_thumbnail_refreshes(candidates: list,
                              state: dict = None,
                              max_per_day: int = MAX_THUMBNAIL_REFRESHES_PER_DAY) -> list:
    """Select up to N videos for thumbnail refresh today.

    Safety rules:
      - Max 3/day (YouTube doesn't like rapid mass changes)
      - Only videos with 40%+ retention (good content, bad thumbnail)
      - Never refresh the same video twice within 14 days
    """
    if state is None:
        state = _load_json(REVIVAL_STATE_PATH, {})

    refreshed_today = state.get('thumbnails_refreshed_today', [])
    already_refreshed = set(state.get('thumbnail_refresh_history', []))
    today_str = _now_utc().strftime('%Y-%m-%d')

    if refreshed_today and refreshed_today[0].get('date') != today_str:
        refreshed_today = []

    remaining = max_per_day - len(refreshed_today)
    if remaining <= 0:
        return []

    plan = []
    for c in candidates:
        if len(plan) >= remaining:
            break
        if c['id'] in already_refreshed:
            continue
        retention = c.get('retention', 0)
        if retention < RETENTION_BONUS_THRESHOLD:
            continue
        plan.append({
            'video_id': c['id'],
            'title': c['title'],
            'revival_score': c['revival_score'],
            'current_retention': retention,
            'action': 'refresh_thumbnail',
        })

    return plan


def apply_thumbnail_refresh(video_id: str, state: dict = None):
    """Record that a thumbnail refresh was applied."""
    if state is None:
        state = _load_json(REVIVAL_STATE_PATH, {})

    today_str = _now_utc().strftime('%Y-%m-%d')
    refreshed_today = state.get('thumbnails_refreshed_today', [])
    if refreshed_today and refreshed_today[0].get('date') != today_str:
        refreshed_today = []

    refreshed_today.append({'video_id': video_id, 'date': today_str})
    state['thumbnails_refreshed_today'] = refreshed_today

    history = state.get('thumbnail_refresh_history', [])
    history.append(video_id)
    state['thumbnail_refresh_history'] = history[-100:]

    _save_json(REVIVAL_STATE_PATH, state)


# ---------------------------------------------------------------------------
# 5. DESCRIPTION CROSS-LINKS — embed old video links in new descriptions
# ---------------------------------------------------------------------------

def plan_description_cross_links(new_video: dict,
                                  candidates: list,
                                  max_links: int = MAX_DESCRIPTION_CROSS_LINKS) -> list:
    """Pick old videos to mention in a new video's description.

    YouTube allows clickable video links in descriptions. These drive
    5-15% of watch time on well-described videos.
    """
    new_topic = new_video.get('topic', 'other')
    scored = []
    for c in candidates:
        topic_boost = 15 if c.get('topic') == new_topic else 0
        scored.append({
            'video_id': c['id'],
            'title': c['title'],
            'revival_score': c['revival_score'] + topic_boost,
        })
    scored.sort(key=lambda x: x['revival_score'], reverse=True)
    return scored[:max_links]


def build_cross_link_text(links: list) -> str:
    """Build the cross-link paragraph for a YouTube description."""
    if not links:
        return ''
    lines = ['\n\n📺 Related videos you might like:\n']
    for link in links:
        url = f"https://www.youtube.com/shorts/{link['video_id']}"
        lines.append(f"→ {link['title']}: {url}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# 6. META STORIES RESHARE — push old FB/IG reels to Stories
# ---------------------------------------------------------------------------

def plan_meta_stories(ig_reels: list = None,
                      state: dict = None,
                      max_per_day: int = MAX_META_STORIES_PER_DAY) -> list:
    """Select old IG reels to reshare to Stories today.

    IG Stories don't count as "new posts" so the algorithm treats them
    separately — no feed suppression risk. Stories get 2-5x more reach
    than feed posts for accounts with <1000 followers.
    """
    if ig_reels is None:
        ig_data = _load_json(IG_REELS_PATH, {})
        ig_reels = ig_data.get('reels', [])

    if state is None:
        state = _load_json(REVIVAL_STATE_PATH, {})

    reshared_today = state.get('stories_reshared_today', [])
    today_str = _now_utc().strftime('%Y-%m-%d')
    if reshared_today and reshared_today[0].get('date') != today_str:
        reshared_today = []

    already_reshared = set(state.get('stories_reshare_history', []))
    remaining = max_per_day - len(reshared_today)
    if remaining <= 0:
        return []

    now = _now_utc()
    plan = []
    for reel in ig_reels:
        if len(plan) >= remaining:
            break
        vid_id = reel.get('id')
        if not vid_id or vid_id in already_reshared:
            continue
        posted = reel.get('timestamp', reel.get('created_time', ''))
        age_days = _age_days(posted, now)
        if age_days < DEAD_AGE_MIN_DAYS:
            continue
        plan.append({
            'reel_id': vid_id,
            'title': reel.get('caption', reel.get('description', ''))[:60],
            'views': reel.get('views', 0),
            'age_days': age_days,
            'action': 'share_to_story',
        })

    return plan


# ---------------------------------------------------------------------------
# 7. COMMUNITY POST GENERATOR — drafts YouTube Community tab posts
# ---------------------------------------------------------------------------

COMMUNITY_POST_TEMPLATES = [
    "🤔 Did you know? {fact}\n\nFull video: https://youtube.com/shorts/{video_id}\n\n#DarkFacts #BodyScience",
    "This blew my mind when I first learned it 👀\n\n{fact}\n\nWatch the full short → https://youtube.com/shorts/{video_id}",
    "Your body is doing this RIGHT NOW and you don't even know it 🧠\n\n{fact}\n\nMore facts in the video above ☝️",
    "Drop a 🔥 if this surprised you:\n\n{fact}\n\nFull video: https://youtube.com/shorts/{video_id}",
]


def plan_community_posts(candidates: list,
                          state: dict = None,
                          max_per_week: int = MAX_COMMUNITY_POSTS_PER_WEEK) -> list:
    """Draft YouTube Community tab posts for high-potential dead videos.

    Community posts appear in subscribers' feeds independently of the
    video algorithm. They drive 10-30% of watch time for channels with
    <10K subscribers.
    """
    if state is None:
        state = _load_json(REVIVAL_STATE_PATH, {})

    posts_this_week = state.get('community_posts_this_week', [])
    now = _now_utc()
    week_start = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
    posts_this_week = [p for p in posts_this_week if p.get('week', '') >= week_start]
    if len(posts_this_week) >= max_per_week:
        return []

    already_posted = set(state.get('community_post_history', []))

    drafts = []
    import random
    for c in candidates[:5]:
        if len(drafts) + len(posts_this_week) >= max_per_week:
            break
        if c['id'] in already_posted:
            continue
        template = random.choice(COMMUNITY_POST_TEMPLATES)
        fact = c.get('title', 'Something strange about your body')
        draft = template.format(fact=fact, video_id=c['id'])
        drafts.append({
            'video_id': c['id'],
            'title': c['title'],
            'revival_score': c['revival_score'],
            'draft_text': draft,
            'action': 'community_post_draft',
        })

    return drafts


# ---------------------------------------------------------------------------
# 8. MAIN REVIVAL RUNNER — called by the daily cron
# ---------------------------------------------------------------------------

def run_revival_cycle() -> dict:
    """Execute one full revival cycle. Called by the daily workflow.

    Returns a summary dict with actions taken and drafts generated.
    """
    logger.info("=== Starting revival cycle ===")
    candidates = identify_revival_candidates()
    state = _load_json(REVIVAL_STATE_PATH, {})

    result = {
        'timestamp': _now_utc().isoformat(),
        'candidates_found': {
            'youtube': len(candidates['youtube']),
            'facebook': len(candidates['facebook']),
            'instagram': len(candidates['instagram']),
        },
        'actions': [],
        'drafts': [],
    }

    # YouTube end screen pool
    top_yt = candidates['youtube'][:10]
    if top_yt:
        state['end_screen_pool'] = [
            {'video_id': c['id'], 'title': c['title'], 'score': c['revival_score']}
            for c in top_yt
        ]
        result['actions'].append({
            'type': 'end_screen_pool_refreshed',
            'count': len(top_yt),
        })

    # Thumbnail refreshes
    thumb_plan = plan_thumbnail_refreshes(candidates['youtube'], state)
    for t in thumb_plan:
        apply_thumbnail_refresh(t['video_id'], state)
        result['actions'].append({
            'type': 'thumbnail_refresh_queued',
            'video_id': t['video_id'],
            'title': t['title'],
            'score': t['revival_score'],
        })

    # Meta stories
    stories_plan = plan_meta_stories(state=state)
    for s in stories_plan:
        reshared_today = state.get('stories_reshared_today', [])
        today_str = _now_utc().strftime('%Y-%m-%d')
        if reshared_today and reshared_today[0].get('date') != today_str:
            reshared_today = []
        reshared_today.append({'reel_id': s['reel_id'], 'date': today_str})
        state['stories_reshared_today'] = reshared_today
        history = state.get('stories_reshare_history', [])
        history.append(s['reel_id'])
        state['stories_reshare_history'] = history[-100:]
        result['actions'].append({
            'type': 'meta_story_queued',
            'reel_id': s['reel_id'],
            'title': s['title'],
        })

    # Community posts (drafts only — need manual approval)
    drafts = plan_community_posts(candidates['youtube'], state)
    for d in drafts:
        posts_this_week = state.get('community_posts_this_week', [])
        week_start = (_now_utc() - timedelta(days=_now_utc().weekday())).strftime('%Y-%m-%d')
        posts_this_week = [p for p in posts_this_week if p.get('week', '') >= week_start]
        posts_this_week.append({
            'video_id': d['video_id'],
            'week': week_start,
        })
        state['community_posts_this_week'] = posts_this_week
        history = state.get('community_post_history', [])
        history.append(d['video_id'])
        state['community_post_history'] = history[-100:]
        result['drafts'].append(d)

    # Playlist suggestions
    all_yt_candidates = candidates['youtube']
    playlist_groups = suggest_playlist_groups(all_yt_candidates)
    if playlist_groups:
        result['actions'].append({
            'type': 'playlist_suggestions',
            'groups': {k: len(v) for k, v in playlist_groups.items()},
        })
    state['playlist_groups'] = playlist_groups

    # Cross-link pool for next upload
    top_cross_link = candidates['youtube'][:MAX_DESCRIPTION_CROSS_LINKS]
    if top_cross_link:
        state['cross_link_pool'] = [
            {'video_id': c['id'], 'title': c['title']}
            for c in top_cross_link
        ]
        result['actions'].append({
            'type': 'cross_link_pool_refreshed',
            'count': len(top_cross_link),
        })

    state['last_run'] = _now_utc().isoformat()
    _save_json(REVIVAL_STATE_PATH, state)

    # Save the full candidate list for reference
    _save_json(REVIVAL_QUEUE_PATH, candidates)

    logger.info(
        "Revival cycle complete: %d YT, %d FB, %d IG candidates; "
        "%d actions, %d drafts",
        result['candidates_found']['youtube'],
        result['candidates_found']['facebook'],
        result['candidates_found']['instagram'],
        len(result['actions']),
        len(result['drafts']),
    )
    return result


# ---------------------------------------------------------------------------
# 9. INTEGRATION HELPERS — called by uploader.py and seo_generator.py
# ---------------------------------------------------------------------------

def get_next_end_screens(new_video_topic: str = 'other') -> list:
    """Called by uploader.py before YouTube upload.

    Returns end-screen video IDs to include in the upload, or empty list.
    """
    state = _load_json(REVIVAL_STATE_PATH, {})
    pool = state.get('end_screen_pool', [])
    if not pool:
        return []

    topic_matches = [p for p in pool if p.get('topic') == new_video_topic]
    rest = [p for p in pool if p.get('topic') != new_video_topic]
    ordered = topic_matches + rest
    return [
        {'video_id': p['video_id'], 'title': p['title']}
        for p in ordered[:MAX_END_SCREEN_VIDEOS]
    ]


def get_cross_links(new_video_topic: str = 'other') -> list:
    """Called by seo_generator.py to build description cross-links."""
    state = _load_json(REVIVAL_STATE_PATH, {})
    pool = state.get('cross_link_pool', [])
    return [{'video_id': p['video_id'], 'title': p['title']} for p in pool[:MAX_DESCRIPTION_CROSS_LINKS]]


def get_playlist_suggestion(topic: str) -> str:
    """Called by seo_generator.py for playlist assignment."""
    state = _load_json(REVIVAL_STATE_PATH, {})
    groups = state.get('playlist_groups', {})
    if topic in groups:
        playlist_info = PLAYLIST_CATALOG.get(topic, {})
        return playlist_info.get('title', f'{topic} Facts')
    return ''


if __name__ == '__main__':
    result = run_revival_cycle()
    print(json.dumps(result, indent=2, default=str))
