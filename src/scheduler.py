import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pytz

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class USAPeakTimeScheduler:
    """
    Intelligent scheduler for posting at USA peak times.
    Tuned for general adult short-form video audience behavior.
    """
    PEAK_TIMES = [
        {'hour': 19, 'minute': 0, 'zone': 'ET', 'name': 'US Evening Prime'},   # 7:00 PM ET — US prime time
    ]
    
    # IANA zones keep the policy correct across EST/EDT daylight-saving changes.
    TIMEZONE_MAP = {
        'ET': 'America/New_York',
        'CT': 'America/Chicago',
        'MT': 'America/Denver',
        'PT': 'America/Los_Angeles',
    }
    
    def __init__(self):
        self.est_tz = pytz.timezone(self.TIMEZONE_MAP['ET'])
        self.utc_tz = pytz.UTC
    
    @staticmethod
    def _learned_slot_weights() -> Dict[str, float]:
        """Measured performance per slot, from the growth engine.

        Returns an empty dict whenever the learning loop has no verdict yet,
        which keeps the scheduler fully functional on a cold start — this
        module must never depend on analytics being connected.
        """
        try:
            from growth_engine import get_slot_weights
            return get_slot_weights() or {}
        except Exception:  # noqa: BLE001 - scheduling must never break
            return {}

    def ranked_peak_times(self) -> List[Dict]:
        """Peak slots ordered by measured performance, best first.

        The production policy currently contains one heatmap-calibrated daily
        slot. Learned weights may still annotate it, but cannot move routine
        production into an unverified off-peak window.

        Weights come from data/growth_state.json and default to 1.0, so an
        unmeasured slot keeps its natural position instead of being buried.
        """
        weights = type(self)._learned_slot_weights()
        annotated = []
        for peak in self.PEAK_TIMES:
            key = f"{peak['hour']:02d}:{peak['minute'] // 30 * 30:02d}"
            annotated.append({**peak, "weight": float(weights.get(key, 1.0))})
        # Stable sort: equal weights keep chronological order, so an
        # unmeasured channel behaves exactly as it did before.
        return sorted(annotated, key=lambda p: -p["weight"])

    def get_next_posting_times(self, num_posts: int = 3, prioritise: bool = True) -> List[Dict]:
        """
        Get next optimal posting times for videos.

        Args:
            num_posts:  how many slots to return
            prioritise: order by measured performance (default) instead of by
                        clock order. Set False for a purely chronological view.

        Returns:
            List of optimal posting times with timezone info, always sorted
            chronologically in the OUTPUT (callers rely on that for "next
            slot" logic) but SELECTED by performance when prioritise=True.
        """
        source = self.ranked_peak_times() if prioritise else list(self.PEAK_TIMES)
        chosen = source[:max(0, num_posts)]

        posting_schedule = []
        for peak_time in chosen:
            next_post_time = self._get_next_occurrence(
                peak_time['hour'], peak_time['minute']
            )
            entry = {
                'time': next_post_time,
                'time_est': next_post_time.strftime('%Y-%m-%d %H:%M:%S EST'),
                'time_utc': next_post_time.astimezone(self.utc_tz).strftime('%Y-%m-%d %H:%M:%S UTC'),
                'peak_name': peak_time['name'],
                'reason': self._get_posting_reason(peak_time['name']),
            }
            if 'weight' in peak_time:
                entry['measured_weight'] = round(peak_time['weight'], 3)
            posting_schedule.append(entry)

        posting_schedule.sort(key=lambda item: item['time'])
        return posting_schedule
    
    def _get_next_occurrence(self, hour: int, minute: int) -> datetime:
        """
        Get next occurrence of a specific time in EST.
        """
        now = datetime.now(self.est_tz)
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If time has passed today, schedule for tomorrow
        if next_time <= now:
            next_time += timedelta(days=1)
        
        return next_time
    
    def _get_posting_reason(self, peak_name: str) -> str:
        """
        Get reason why this is a peak time for this content.
        """
        reasons = {
            'Early Morning': 'Commute/coffee scrolling before work',
            'Lunch Time': 'Lunch break browsing — best measured slot (avg 719 views)',
            'Early Evening': 'Start of the 6-9 PM consensus window (new slot, replaces 21:30)',
            'Evening Prime': 'Prime-time scroll — proven second best (avg 519 views)',
            'US Evening Prime': 'US prime time (7 PM ET) — maximum viewers online, peak Shorts algorithm push',
        }
        return reasons.get(peak_name, 'Peak engagement time')
    
    def get_publishing_metadata(self, posting_time: datetime) -> Dict:
        """
        Get YouTube API compatible publishing metadata.
        """
        # Convert to UTC for YouTube API
        utc_time = posting_time.astimezone(self.utc_tz)
        
        return {
            'publishAt': utc_time.isoformat(),
            'privacyStatus': 'private',  # review mode; uploader controls final visibility
            'releaseTime': utc_time.isoformat(),
            'timezone': 'America/New_York',
            'localTime': posting_time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    
    def validate_posting_interval(self, last_post_time: datetime) -> bool:
        """
        Validate minimum 2-hour interval between posts to avoid spam flagging.
        Accepts either a naive or timezone-aware datetime - naive datetimes
        are assumed to already be UTC (matches how video_history.json stores
        them) and are localized before comparing, so this never crashes with
        a "can't subtract offset-naive and offset-aware datetimes" error.
        """
        if last_post_time.tzinfo is None:
            last_post_time = last_post_time.replace(tzinfo=pytz.UTC)

        now = datetime.now(self.est_tz)
        time_since_last = (now - last_post_time).total_seconds() / 3600

        if time_since_last < 2:
            logger.warning(f"⚠️ Only {time_since_last:.1f} hours since last post")
            return False

        return True

    def get_daily_schedule(self) -> str:
        """
        Get formatted daily schedule.
        """
        schedule = self.get_next_posting_times(3)
        
        formatted = "📅 Daily Posting Schedule (EST)\n"
        formatted += "=" * 50 + "\n"
        
        for i, post in enumerate(schedule, 1):
            formatted += f"\nPost {i}: {post['time_est']}\n"
            formatted += f"  Peak: {post['peak_name']}\n"
            formatted += f"  Reason: {post['reason']}\n"
            formatted += f"  UTC: {post['time_utc']}\n"
        
        return formatted
    
    def get_timezone_conversion(self, est_time: datetime) -> Dict[str, str]:
        """
        Convert EST time to all major US timezones.
        """
        conversions = {}
        
        for zone_name, zone_path in self.TIMEZONE_MAP.items():
            tz = pytz.timezone(zone_path)
            converted = est_time.astimezone(tz)
            conversions[zone_name] = converted.strftime('%H:%M:%S')
        
        return conversions
    
    def suggest_optimal_schedule(self) -> List[Dict]:
        """
        Suggest optimal posting schedule based on engagement patterns.

        For this niche (dark/mystery body-science facts, general adult
        audience), the US evening prime time window (7-10 PM ET) has the
        highest viewer density. Target 7:00 PM ET so the Shorts algorithm
        pushes the video during peak scroll hours across all US time zones.
        """
        recommendations = [
            {
                'slot': 1,
                'time': '7:00 PM ET',
                'audience': 'US evening prime time — peak viewership across all US time zones',
                'expected_engagement': 'Maximum algorithm push during 7-10 PM US scroll window',
                'reason': '7 PM ET = 4:00 AM PKT next day — video processed and pushed by US peak'
            }
        ]
        return recommendations


if __name__ == "__main__":
    scheduler = USAPeakTimeScheduler()
    
    print(scheduler.get_daily_schedule())
    print("\n" + "="*50)
    print("\n📊 Optimal Schedule Recommendations:\n")
    
    for rec in scheduler.suggest_optimal_schedule():
        print(f"Slot {rec['slot']}: {rec['time']}")
        print(f"  Audience: {rec['audience']}")
        print(f"  Expected Engagement: {rec['expected_engagement']}")
        print(f"  Reason: {rec['reason']}\n")
