# SKILLOR growth report

_Generated 2026-07-31 15:26 UTC · policy 2026.07-fix1 (verified 2026-07-31)_

This file is produced by `scripts/growth_report.py`. It reads real
numbers from all three platforms, compares each against that
platform's own 2026 distribution gate, and states one next action.

---

## Headline

Across **23 mature videos**, the channel is **under the bar** (retention index 0.98, where 1.00 = exactly the level at which each platform widens distribution).

- Best publish slot: **20:00 NY**
- Best-retaining topics: **other**
- Best opening frame: **—**
- Recommended cadence: **2 video(s)/day**

> Retention is 98% of the bar — close but under. Two uploads a day at the channel's two best-measured slots concentrates the quality budget where it converts.

## Needs attention

- 🟡 Slot 12:30 NY is under-performing across 3 videos — its weight has been reduced automatically.
- 🟡 Slot 21:30 NY is under-performing across 3 videos — its weight has been reduced automatically.

## Per platform

### 🟡 YouTube Shorts — below gate

- Videos measured: **21**
- Average completion: **49%** against a **50%** distribution gate (ratio 0.98)
- Average views: **280**

**Next action:** Averaging 49% against a 50% bar. Shorten the cut toward 27s and tighten the first 3 seconds — the gap is retention, not reach.

### ⚪ Facebook Reels — no data

No usable metrics yet. No metrics yet — publish and wait 24h, or connect this platform's analytics.

### ⚪ Instagram Reels — no data

No usable metrics yet. No metrics yet — publish and wait 24h, or connect this platform's analytics.

## Learned weights

Weights multiply how often a slot or topic pillar gets chosen.
1.00 is neutral; they are clamped to 0.35-2.00 so nothing is ever
permanently switched off and can always earn its way back.

| Slot (NY) | Weight | Videos |
|---|---|---|
| 20:00 | 1.21 | 5 |
| 00:00 | 1.00 | 1 |
| 05:00 | 1.00 | 2 |
| 11:00 | 1.00 | 1 |
| 15:30 | 1.00 | 1 |
| 04:30 | 1.00 | 1 |
| 14:30 | 1.00 | 2 |
| 18:30 | 1.00 | 1 |
| 01:00 | 1.00 | 1 |
| 12:30 | 0.86 | 3 |
| 21:30 | 0.80 | 3 |

| Topic pillar | Weight | Videos |
|---|---|---|
| other | 1.28 | 7 |
| gut | 1.00 | 1 |
| breath | 1.00 | 1 |
| ear | 0.89 | 5 |
| muscle | 0.83 | 3 |
| brain | 0.79 | 4 |

## The policy this is measured against

```
SKILLOR algorithm policy 2026.07-fix1 (verified 2026-07-31)

- YouTube Shorts: 27-40s (ideal 33s), hook <= 2.8s, 3-4 hashtags, gate 50% AVP
- Facebook Reels: 18-28s (ideal 24s), hook <= 2.5s, 2-3 hashtags, gate 72% AVP
- Instagram Reels: 16-27s (ideal 23s), hook <= 2.3s, 3-5 hashtags, gate 70% AVP

Script budget: 67-105 words at 2.62 w/s (hook 4-6 words).
Cadence ceiling: 3/day, >= 90 min apart.
```

Platform ranking behaviour changes every few months. Re-verify the
sources in `src/algorithm_policy.py` every 90 days
and update the constants there — every other module follows.
