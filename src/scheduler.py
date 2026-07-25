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
    
    # USA peak times for short-form video engagement (EST)
    PEAK_TIMES = [
        {'hour': 12, 'minute': 30, 'zone': 'EST', 'name': 'Lunch Time'},     # 12:30 PM EST
        {'hour': 16, 'minute': 30, 'zone': 'EST', 'name': 'After School/Work'},  # 4:30 PM EST (replaces dead 6:00 AM slot)
        {'hour': 20, 'minute': 0, 'zone': 'EST', 'name': 'Evening'},         # 8:00 PM EST
    ]
    
    # Timezone mapping
    TIMEZONE_MAP = {
        'EST': 'America/New_York',
        'CST': 'America/Chicago',
        'MST': 'America/Denver',
        'PST': 'America/Los_Angeles',
    }
    
    def __init__(self):
        self.est_tz = pytz.timezone(self.TIMEZONE_MAP['EST'])
        self.utc_tz = pytz.UTC
    
    def get_next_posting_times(self, num_posts: int = 3) -> List[Dict]:
        """
        Get next optimal posting times for videos.
        
        Args:
            num_posts: Number of daily posts (default 3)
        
        Returns:
            List of optimal posting times with timezone info
        """
        posting_schedule = []
        
        for i in range(num_posts):
            if i < len(self.PEAK_TIMES):
                peak_time = self.PEAK_TIMES[i]
                next_post_time = self._get_next_occurrence(
                    peak_time['hour'],
                    peak_time['minute']
                )
                
                posting_schedule.append({
                    'time': next_post_time,
                    'time_est': next_post_time.strftime('%Y-%m-%d %H:%M:%S EST'),
                    'time_utc': next_post_time.astimezone(self.utc_tz).strftime('%Y-%m-%d %H:%M:%S UTC'),
                    'peak_name': peak_time['name'],
                    'reason': self._get_posting_reason(peak_time['name'])
                })
        
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
            'Lunch Time': 'Lunch break browsing',
            'Evening': 'Wind-down scrolling before bed',
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
        audience):
        - Early morning: commute/coffee scrolling
        - Lunch: work-break browsing
        - Evening: wind-down scrolling before bed
        """
        recommendations = [
            {
                'slot': 1,
                'time': '6:00 AM EST',
                'audience': 'Morning commute/coffee scrolling',
                'expected_engagement': 'High (time-sensitive content)',
                'reason': 'Catching people during their morning scroll before work'
            },
            {
                'slot': 2,
                'time': '12:30 PM EST',
                'audience': 'Lunch break browsers',
                'expected_engagement': 'Very High (widest audience online)',
                'reason': 'Work break viewing, likely to share/comment'
            },
            {
                'slot': 3,
                'time': '8:00 PM EST',
                'audience': 'Evening wind-down scrolling',
                'expected_engagement': 'High (relaxed, receptive to longer content)',
                'reason': 'Prime-time scrolling before bed'
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
