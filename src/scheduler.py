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
    
    # USA peak times for short-form video engagement (America/New_York).
    #
    # Set 2026-07-27 from TWO sources that agree:
    #
    # 1. THIS CHANNEL'S OWN DATA (mature videos, >=2 days old, current views)
    #      12:30  n=3  avg 719   [830, 988, 339]   <- best slot on the channel
    #      20:00  n=3  avg 519   [664, 795, 98]    <- second best
    #      06:00  n=3  avg 308   [133, 139, 652]   <- one outlier carries it
    #      21:00+ n=2  avg 117   [107, 127]        <- weakest evening band
    #      14:00  n=2  avg  95   [103, 87]
    #      17:58  n=1      77
    #
    # 2. INDUSTRY CONSENSUS for US Shorts, five independent 2026 sources
    #    (iqfluence 325-campaign study, miraflow, socialrails, mediamister,
    #    sellerpic). Every one of them lands on the same two windows:
    #      12–2 PM ET   and   6–9 PM ET
    #
    # 21:30 was RETIRED. It sits outside the 6-9 PM window in all five
    # sources, this channel's own 21:00 band is its weakest evening data
    # (107, 127), and being only 90 minutes after the 20:00 slot it competes
    # with the strongest upload of the day for the same evening audience.
    #
    # Replaced with 18:30 — inside the 6-9 PM consensus core, 5.5h clear of
    # lunch and 1.5h before prime, so the three uploads no longer overlap.
    # This is a deliberate experiment: the 17:58 sample (77 views, n=1) is
    # the only nearby datapoint and is too thin to trust either way, so the
    # slot is chosen on consensus and will be re-checked once it has data.
    PEAK_TIMES = [
        {'hour': 12, 'minute': 30, 'zone': 'EST', 'name': 'Lunch Time'},     # 12:30 PM ET
        {'hour': 18, 'minute': 30, 'zone': 'EST', 'name': 'Early Evening'},  # 6:30 PM ET
        {'hour': 20, 'minute': 0, 'zone': 'EST', 'name': 'Evening Prime'},   # 8:00 PM ET
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
            'Lunch Time': 'Lunch break browsing — best measured slot (avg 719 views)',
            'Early Evening': 'Start of the 6-9 PM consensus window (new slot, replaces 21:30)',
            'Evening Prime': 'Prime-time scroll — proven second best (avg 519 views)',
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
                'time': '12:30 PM ET',
                'audience': 'Lunch break browsers',
                'expected_engagement': 'Best measured slot — avg 719 views (830/988/339)',
                'reason': 'Inside the 12-2 PM window all five 2026 US-Shorts studies agree on'
            },
            {
                'slot': 2,
                'time': '6:30 PM ET',
                'audience': 'Commute / post-work scroll',
                'expected_engagement': 'New slot — replaces the retired 21:30 experiment',
                'reason': 'Start of the 6-9 PM consensus window; 1.5h clear of prime so it '
                          'does not compete with the strongest upload'
            },
            {
                'slot': 3,
                'time': '8:00 PM ET',
                'audience': 'Evening prime-time scrolling',
                'expected_engagement': 'Proven — avg 519 views (664/795)',
                'reason': 'Peak of the 6-9 PM window, widest relaxed audience'
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
