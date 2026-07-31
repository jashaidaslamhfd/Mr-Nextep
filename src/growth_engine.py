"""
src/growth_engine.py — the feedback loop that closes the system.

WHAT WAS MISSING
----------------
The pipeline could generate, score and publish, but it could not LEARN. Every
run started from the same fixed assumptions: same three time slots, same topic
pool weighting, same hook style, same cadence — regardless of what the last
fifty videos actually did. docs/ALGORITHM_PLAYBOOK.md even listed the feedback
loop as a manual "day 8-14" chore for a human with a spreadsheet.

This module reads the normalised cross-platform metrics written by
src/platform_metrics.py and produces machine-readable decisions the pipeline
consumes on the very next run:

  * slot_weights      - which publish slots actually earn completion
  * topic_weights     - which content pillars hold viewers
  * hook_patterns     - which opening frames survive the first 3 seconds
  * cadence           - how many uploads/day the data supports
  * platform_health   - per-platform verdict + the ONE next action
  * alerts            - things a human must look at

DESIGN RULES (learned from how this kind of loop usually goes wrong)
--------------------------------------------------------------------
1. Never act on thin data. Every bucket needs HEALTH_THRESHOLDS
   ["min_samples_per_slot"] mature videos before it can move a weight. Small
   samples produce confident nonsense.
2. Never let a weight collapse to zero. A slot/topic that had two bad days
   would otherwise be permanently unreachable and could never prove itself
   again. Weights are clamped to [0.35, 2.0].
3. Compare against the PLATFORM'S OWN retention gate, not a global number.
   A 27s Reel and a 36s Short are graded on different curves (see
   algorithm_policy.retention_gate).
4. Recommend, never silently override safety. Cadence can be lowered by the
   engine; raising it past the policy ceiling is impossible by construction.
5. Every decision carries its evidence, so a human can disagree with it.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Dict, List, Optional, Tuple

import pytz

from algorithm_policy import (
    FACEBOOK,
    HEALTH_THRESHOLDS,
    INSTAGRAM,
    PLATFORMS,
    YOUTUBE,
    clamp_cadence,
    duration_policy,
    get_policy,
    retention_gate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GROWTH_STATE_PATH = os.environ.get("GROWTH_STATE_PATH", "data/growth_state.json")
VIDEO_HISTORY_PATH = os.environ.get("VIDEO_HISTORY_PATH", "data/video_history.json")

NY = pytz.timezone("America/New_York")

# Weight bounds. 0.35 keeps an under-performing option alive with a real (if
# small) chance to recover; 2.0 stops one lucky video from monopolising the
# schedule. Both were chosen so a bucket can climb back from the floor within
# roughly two weeks of good performance rather than being written off.
WEIGHT_FLOOR = 0.35
WEIGHT_CEILING = 2.0
# How fast weights move toward the newest evidence. 0.3 means a single day of
# data can shift a weight by at most ~30% of the gap — fast enough to react
# inside a week, slow enough that one outlier cannot flip the schedule.
LEARNING_RATE = 0.3
# How far above neutral a bucket must sit before it is declared a winner and
# actually influences generation. One constant, used by both the report and
# the consumers — see _best_of().
WINNER_MARGIN = 0.10


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
    return default


def _save_json_atomic(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _clamp(value: float, low: float = WEIGHT_FLOOR, high: float = WEIGHT_CEILING) -> float:
    return round(max(low, min(float(value), high)), 3)


def _configured_slots() -> List[str]:
    """The publish slots the scheduler actually targets, as "HH:MM" strings."""
    try:
        from scheduler import USAPeakTimeScheduler
        return [f"{p['hour']:02d}:{p['minute']:02d}"
                for p in USAPeakTimeScheduler.PEAK_TIMES]
    except Exception:  # noqa: BLE001 - learning must not depend on the scheduler
        return []


# How far a publish time may drift from its intended slot and still count as
# that slot. GitHub cron routinely fires late, Instagram publishes when its
# hold expires, and YouTube's publishAt lands on the minute — so a 45-minute
# window comfortably absorbs real-world jitter while staying well inside the
# 90-minute minimum gap between slots.
_SLOT_MATCH_MINUTES = 45


def _slot_key(record: Dict) -> Optional[str]:
    """Which publish slot a video belongs to, in New York local time.

    Two details that were quietly corrupting the data:

    1. publish_at beats posted_at. posted_at is when the RUNNER finished,
       which on this repo is up to two hours before the video is visible.
       Bucketing by upload time attributed videos to the wrong slot entirely.

    2. Snap to the nearest CONFIGURED slot rather than to a fixed 30-minute
       grid. A video that went live at 20:35 (a late cron, or an Instagram
       hold expiring) landed in a "20:30" bucket that no scheduler slot uses,
       so the 20:00 slot never received credit for its own videos and stayed
       permanently at neutral weight no matter how well it performed.
    """
    stamp = record.get("publish_at") or record.get("posted_at")
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    local = parsed.astimezone(NY)
    minutes = local.hour * 60 + local.minute

    best, best_gap = None, None
    for slot in _configured_slots():
        hour, minute = (int(part) for part in slot.split(":"))
        gap = abs(minutes - (hour * 60 + minute))
        if gap <= _SLOT_MATCH_MINUTES and (best_gap is None or gap < best_gap):
            best, best_gap = slot, gap
    if best:
        return best

    # Published outside every configured slot (a manual dispatch, or a slot
    # that has since been retired). Keep it in its own half-hour bucket so the
    # data is not lost, but it will never be confused with a real slot.
    return f"{local.hour:02d}:{local.minute // 30 * 30:02d}"


_TOPIC_PILLARS = {
    "eye": ("eye", "vision", "blink", "pupil", "sight", "tears"),
    "ear": ("ear", "hearing", "ringing", "tinnitus", "sound"),
    "brain": ("brain", "memory", "dream", "sleep", "focus", "thought", "deja"),
    "heart": ("heart", "pulse", "blood", "circulation", "beat"),
    "muscle": ("muscle", "cramp", "twitch", "spasm", "joint", "knee", "back"),
    "gut": ("stomach", "gut", "hunger", "digest", "nausea", "throat"),
    "skin": ("skin", "goosebump", "itch", "sweat", "blush", "hair"),
    "breath": ("breath", "yawn", "hiccup", "sneeze", "cough", "lung"),
    "nerve": ("nerve", "tingle", "numb", "shiver", "chill", "pain"),
}


def topic_pillar(topic: str) -> str:
    """Group topics into pillars so learning has enough samples per bucket.

    500 individual topics would each have a sample size of one, which teaches
    nothing. Nine body-system pillars reach statistical usefulness within a
    couple of weeks at 2-3 uploads a day.
    """
    text = (topic or "").lower()
    for pillar, keywords in _TOPIC_PILLARS.items():
        if any(keyword in text for keyword in keywords):
            return pillar
    return "other"


def hook_frame(title_or_hook: str) -> str:
    """Classify the opening frame so we can learn which one survives.

    These are the frames the script generator can actually be told to produce,
    which is what makes the finding actionable rather than merely interesting.
    """
    text = (title_or_hook or "").strip().lower()
    if not text:
        return "unknown"
    if text.startswith("why"):
        return "why"
    if text.startswith(("what happens", "what your", "what")):
        return "what"
    if text.startswith(("how", "here's how")):
        return "how"
    if text.startswith("your") or re.match(r"^you'?r?e?\b", text):
        return "second_person"
    if "?" in text:
        return "question"
    return "statement"


# ---------------------------------------------------------------------------
# core scoring
# ---------------------------------------------------------------------------

def _platform_score(record: Dict, platform: str) -> Optional[float]:
    """How well one video did on one platform, as a 0..~2 ratio of the
    platform's own retention gate.

    1.0 means "exactly cleared the bar the feed uses to widen distribution".
    Using a RATIO instead of raw completion is what makes YouTube, Facebook
    and Instagram numbers comparable, and it automatically re-baselines if a
    platform's gate is updated in algorithm_policy.
    """
    data = record.get(platform) or {}
    if not isinstance(data, dict) or "error" in data:
        return None
    completion = data.get("completion")
    if completion is None:
        return None
    from platform_metrics import _clip_seconds

    seconds = _clip_seconds(record, platform)
    gate = retention_gate(platform, seconds)
    if gate <= 0:
        return None
    return float(completion) / gate


def _combined_score(record: Dict) -> Optional[float]:
    """One number per video across every platform that reported.

    YouTube is weighted highest because it is the monetisation target and the
    only platform where the channel owns the audience relationship; Meta
    platforms still count because they are the reach multiplier.
    """
    weights = {YOUTUBE: 0.5, INSTAGRAM: 0.3, FACEBOOK: 0.2}
    total, weight_sum = 0.0, 0.0
    for platform, weight in weights.items():
        score = _platform_score(record, platform)
        if score is not None:
            total += score * weight
            weight_sum += weight
    return round(total / weight_sum, 4) if weight_sum else None


def _bucket_weights(buckets: Dict[str, List[float]], previous: Dict[str, float]) -> Dict[str, float]:
    """Turn per-bucket scores into damped weights around the global mean.

    A bucket scoring exactly the channel average keeps weight 1.0. Buckets are
    only allowed to move if they have enough samples, and they move by
    LEARNING_RATE toward the target so the schedule cannot thrash.
    """
    min_samples = HEALTH_THRESHOLDS["min_samples_per_slot"]
    eligible = {k: v for k, v in buckets.items() if len(v) >= min_samples}
    if not eligible:
        # Not enough evidence anywhere yet. Still emit a neutral weight for
        # every bucket we have OBSERVED, so the report can show "we are
        # watching this slot, it just has 2 videos" instead of silently
        # showing nothing — an empty table reads like a broken feature.
        observed = {key: 1.0 for key in buckets}
        return {**observed, **{k: _clamp(v) for k, v in previous.items()}}

    global_mean = mean([score for values in eligible.values() for score in values]) or 1.0
    weights: Dict[str, float] = {}
    for key, values in buckets.items():
        prior = float(previous.get(key, 1.0))
        if len(values) < min_samples:
            # Not enough evidence: drift gently back toward neutral instead of
            # freezing an old verdict forever.
            weights[key] = _clamp(prior + (1.0 - prior) * 0.2)
            continue
        target = _clamp(mean(values) / global_mean if global_mean else 1.0)
        weights[key] = _clamp(prior + (target - prior) * LEARNING_RATE)
    return weights


# ---------------------------------------------------------------------------
# platform health
# ---------------------------------------------------------------------------

def _platform_health(records: List[Dict], platform: str) -> Dict:
    """Verdict + the single most useful next action for one platform."""
    scores, completions, views = [], [], []
    errors: Dict[str, int] = defaultdict(int)

    for record in records:
        data = record.get(platform) or {}
        if isinstance(data, dict) and "error" in data:
            errors[str(data.get("detail") or data["error"])[:120]] += 1
            continue
        score = _platform_score(record, platform)
        if score is not None:
            scores.append(score)
        if isinstance(data, dict):
            if data.get("completion") is not None:
                completions.append(float(data["completion"]))
            if data.get("views") is not None:
                views.append(float(data["views"]))

    policy = get_policy(platform)
    ideal = duration_policy(platform)[1]
    gate = retention_gate(platform, ideal)

    if not scores:
        top_error = max(errors.items(), key=lambda kv: kv[1])[0] if errors else None
        return {
            "platform": platform,
            "label": policy["label"],
            "status": "no_data",
            "samples": 0,
            "gate": gate,
            "blocking_error": top_error,
            "action": (
                f"No readable metrics. {top_error}" if top_error else
                "No metrics yet — publish and wait 24h, or connect this platform's analytics."
            ),
        }

    avg_score = mean(scores)
    avg_completion = mean(completions) if completions else None
    critical = HEALTH_THRESHOLDS["critical_retention_ratio"]

    if avg_score >= 1.0:
        status, action = "healthy", (
            f"Clearing the {gate:.0%} bar (avg {avg_completion:.0%} completion). "
            "Keep the current format; scale topics that score above average."
        )
    elif avg_score >= critical:
        status, action = "below_gate", (
            f"Averaging {avg_completion:.0%} against a {gate:.0%} bar. "
            f"Shorten the cut toward {duration_policy(platform)[0]:.0f}s and tighten the "
            "first 3 seconds — the gap is retention, not reach."
        )
    else:
        status, action = "critical", (
            f"Only {avg_completion:.0%} of a {gate:.0%} bar. The format itself is losing "
            "viewers early: rebuild the hook (visual payoff in frame one, promise in "
            "under 3 seconds) before changing anything else."
        )

    return {
        "platform": platform,
        "label": policy["label"],
        "status": status,
        "samples": len(scores),
        "gate": gate,
        "avg_completion": round(avg_completion, 4) if avg_completion is not None else None,
        "gate_ratio": round(avg_score, 3),
        "avg_views": round(mean(views), 1) if views else None,
        "action": action,
    }


def _instagram_share_health(records: List[Dict]) -> Optional[Dict]:
    """Instagram's #2 ranking signal is sends-per-reach (DM shares), which is
    invisible in every other report we have. A near-zero rate means the
    content is watchable but not *sendable* — a content problem with a
    specific fix (make the payoff a fact worth forwarding), not a reach bug."""
    rates = [
        r[INSTAGRAM]["sends_per_reach"]
        for r in records
        if isinstance(r.get(INSTAGRAM), dict)
        and r[INSTAGRAM].get("sends_per_reach") is not None
    ]
    if not rates:
        return None
    average = mean(rates)
    # 0.5% of reach sending a Reel is a reasonable working floor for a small
    # account; below that the send signal is effectively absent.
    healthy = average >= 0.005
    return {
        "avg_sends_per_reach": round(average, 5),
        "samples": len(rates),
        "healthy": healthy,
        "action": (
            "Send rate is fine — keep payoffs concrete and forwardable."
            if healthy else
            "Almost nobody DMs these Reels. Sends are Instagram's strongest "
            "non-follower signal: end on one surprising, quotable fact a viewer "
            "would send to a specific friend, not a generic wrap-up line."
        ),
    }


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def analyse(min_age_hours: Optional[int] = None) -> Dict:
    """Read metrics, learn, and write data/growth_state.json.

    Only videos older than the maturity window are used: a video still inside
    its distribution ramp has a completion rate that says more about how long
    it has been live than about how good it is.
    """
    from platform_metrics import load_metrics

    maturity = min_age_hours if min_age_hours is not None else HEALTH_THRESHOLDS["maturity_hours"]
    metrics = load_metrics()
    previous = _load_json(GROWTH_STATE_PATH, {}) or {}

    mature = [
        record for record in metrics.values()
        if isinstance(record, dict) and float(record.get("age_hours") or 0) >= maturity
    ]

    slot_buckets: Dict[str, List[float]] = defaultdict(list)
    topic_buckets: Dict[str, List[float]] = defaultdict(list)
    hook_buckets: Dict[str, List[float]] = defaultdict(list)

    for record in mature:
        score = _combined_score(record)
        if score is None:
            continue
        slot = _slot_key(record)
        if slot:
            slot_buckets[slot].append(score)
        topic_buckets[topic_pillar(record.get("topic") or "")].append(score)
        hook_buckets[hook_frame(record.get("title") or "")].append(score)

    slot_weights = _bucket_weights(slot_buckets, previous.get("slot_weights", {}))
    topic_weights = _bucket_weights(topic_buckets, previous.get("topic_weights", {}))
    hook_weights = _bucket_weights(hook_buckets, previous.get("hook_weights", {}))

    health = {platform: _platform_health(mature, platform) for platform in PLATFORMS}
    scored = [s for s in (_combined_score(r) for r in mature) if s is not None]

    cadence, cadence_reason = _recommend_cadence(scored, health)
    alerts = _build_alerts(health, slot_buckets, scored)
    ig_shares = _instagram_share_health(mature)
    if ig_shares and not ig_shares["healthy"]:
        alerts.append({"level": "warn", "message": ig_shares["action"]})

    state = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(mature),
        "scored_videos": len(scored),
        "channel_gate_ratio": round(mean(scored), 3) if scored else None,
        "slot_weights": slot_weights,
        "topic_weights": topic_weights,
        "hook_weights": hook_weights,
        "slot_samples": {k: len(v) for k, v in slot_buckets.items()},
        "topic_samples": {k: len(v) for k, v in topic_buckets.items()},
        "hook_samples": {k: len(v) for k, v in hook_buckets.items()},
        "platform_health": health,
        "instagram_sends": ig_shares,
        "recommended_cadence": cadence,
        "cadence_reason": cadence_reason,
        "alerts": alerts,
        # "Best" is only reported when the data has actually separated the
        # options. Before this guard, a channel where every bucket sat at the
        # neutral 1.0 still printed a confident "best slot: 08:30" — a
        # recommendation with no evidence behind it, which is worse than
        # printing nothing because people act on it.
        "best_slot": _best_of(slot_weights),
        "best_topics": _best_of(topic_weights, count=3) or [],
        "best_hook_frame": _best_of(hook_weights),
    }
    _save_json_atomic(GROWTH_STATE_PATH, state)
    logger.info(
        "Growth state: %d mature videos, cadence=%d, best slot=%s",
        len(mature), cadence, state["best_slot"],
    )
    return state


def _best_of(weights: Dict[str, float], count: int = 1, margin: float = None):
    """Top bucket(s), but only when the weights have genuinely separated.

    `margin` is the minimum distance above neutral (1.0) a bucket must reach
    before it is called a winner. Without it, a set of untouched 1.0 weights
    would still produce a "best" by arbitrary dict ordering, and the report
    would state a preference the data never expressed.

    Defaults to WINNER_MARGIN so the report and the consumers agree. They
    previously used 0.10 and 0.15 independently, which produced the confusing
    state of a report announcing 'best hook frame: why' at weight 1.147 while
    the script generator silently ignored it for being under 1.15.
    """
    margin = WINNER_MARGIN if margin is None else margin
    if not weights:
        return None if count == 1 else []
    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    winners = [key for key, value in ranked if value >= 1.0 + margin][:count]
    if count == 1:
        return winners[0] if winners else None
    return winners


def _recommend_cadence(scores: List[float], health: Dict) -> Tuple[int, str]:
    """Let the data pick 1-3 uploads/day.

    The logic is deliberately conservative in one direction only: it will
    happily cut volume, but it can never raise it above the policy ceiling.
    On a faceless AI channel, volume is the exact behaviour YouTube's
    inauthentic-content policy penalises, so extra uploads are only earned by
    proving the current ones clear their retention gates.
    """
    if len(scores) < HEALTH_THRESHOLDS["min_samples_per_slot"]:
        # FIXED 2026-07-31: Was 3/day on no_data — this channel's own metrics show
        # retention 27-44% vs 50% gate (critical/below_gate). Shipping 3 low-retention
        # videos/day teaches the feed to stop showing the channel. Hold 2/day while
        # data accumulates, drop to 1 if critical.
        return clamp_cadence(2), (
            "Not enough mature videos to judge yet — holding a conservative 2/day "
            "while data accumulates to avoid teaching the feed that this format loses viewers."
        )

    average = mean(scores)
    critical = HEALTH_THRESHOLDS["critical_retention_ratio"]
    if average < critical:
        return clamp_cadence(1), (
            f"Average retention is {average:.0%} of the required bar. More uploads "
            "of a format that loses viewers early just teaches the feed to stop "
            "showing the channel. Ship one strong video a day until retention "
            "clears the gate."
        )
    if average < 1.0:
        return clamp_cadence(2), (
            f"Retention is {average:.0%} of the bar — close but under. Two uploads a "
            "day at the channel's two best-measured slots concentrates the quality "
            "budget where it converts."
        )
    healthy = sum(1 for h in health.values() if h.get("status") == "healthy")
    if healthy >= 2:
        return clamp_cadence(3), (
            f"Retention is {average:.0%} of the bar and {healthy} platforms are healthy — "
            "the format has earned the full 3/day cadence."
        )
    return clamp_cadence(2), (
        f"Retention clears the bar ({average:.0%}) but only {healthy} platform is healthy. "
        "Holding 2/day until a second platform stabilises."
    )


def _build_alerts(health: Dict, slot_buckets: Dict, scores: List[float]) -> List[Dict]:
    """Things a human genuinely needs to see, phrased as actions."""
    alerts: List[Dict] = []

    for platform, info in health.items():
        if info["status"] == "no_data" and info.get("blocking_error"):
            alerts.append({
                "level": "error",
                "message": f"{info['label']}: {info['blocking_error']} — analytics are blind here.",
            })
        elif info["status"] == "critical":
            alerts.append({"level": "error", "message": f"{info['label']}: {info['action']}"})

    if scores and mean(scores) < HEALTH_THRESHOLDS["critical_retention_ratio"]:
        alerts.append({
            "level": "error",
            "message": (
                "Channel-wide retention is far below every platform's gate. Stop tuning "
                "SEO and posting times — those only matter after the video holds viewers."
            ),
        })

    weak = [
        slot for slot, values in slot_buckets.items()
        if len(values) >= HEALTH_THRESHOLDS["min_samples_per_slot"] and mean(values) < 0.7
    ]
    for slot in weak:
        alerts.append({
            "level": "warn",
            "message": f"Slot {slot} NY is under-performing across {len(slot_buckets[slot])} videos "
                       "— its weight has been reduced automatically.",
        })
    return alerts


# ---------------------------------------------------------------------------
# consumers — the pipeline reads these, never the raw file
# ---------------------------------------------------------------------------

def load_state() -> Dict:
    return _load_json(GROWTH_STATE_PATH, {}) or {}


def get_topic_weights() -> Dict[str, float]:
    """Pillar weights used by trend_fetcher to bias topic selection."""
    return load_state().get("topic_weights", {}) or {}


def get_slot_weights() -> Dict[str, float]:
    return load_state().get("slot_weights", {}) or {}


def get_recommended_cadence() -> int:
    state = load_state()
    return clamp_cadence(int(state.get("recommended_cadence") or 3))


def get_preferred_hook_frame() -> Optional[str]:
    """The opening frame with the best measured survival, if one has earned it.

    Returned only when it is meaningfully better than neutral — otherwise the
    script generator keeps its own variety, which matters for the originality
    policy.
    """
    state = load_state()
    frame = state.get("best_hook_frame")
    weights = state.get("hook_weights", {})
    samples = state.get("hook_samples", {})
    if not frame or weights.get(frame, 0) < 1.0 + WINNER_MARGIN:
        return None
    if samples.get(frame, 0) < HEALTH_THRESHOLDS["min_samples_per_slot"]:
        return None
    return frame


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    print(json.dumps(analyse(), indent=2))
