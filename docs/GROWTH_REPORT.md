# SKILLOR growth report

_Generated 2026-08-04 10:39 UTC · policy 2026.07-fix1 (verified 2026-07-31)_

This file is produced by `scripts/growth_report.py`. It reads real
numbers from all three platforms, compares each against that
platform's own 2026 distribution gate, and states one next action.

---

## Headline

Across **113 mature videos**, the channel is **under the bar** (retention index 0.66, where 1.00 = exactly the level at which each platform widens distribution).

- Best publish slot: **20:00 NY**
- Best-retaining topics: **other**
- Best opening frame: **statement**
- Recommended cadence: **2 video(s)/day**

> Retention is 66% of the bar — close but under. Two uploads a day at the channel's two best-measured slots concentrates the quality budget where it converts.

## Needs attention

- 🔴 Facebook Reels: Only 19% of a 72% bar. The format itself is losing viewers early: rebuild the hook (visual payoff in frame one, promise in under 3 seconds) before changing anything else.
- 🔴 Instagram Reels: Only 24% of a 70% bar. The format itself is losing viewers early: rebuild the hook (visual payoff in frame one, promise in under 3 seconds) before changing anything else.
- 🟡 Slot 12:30 NY is under-performing across 9 videos — its weight has been reduced automatically.
- 🟡 Slot 20:00 NY is under-performing across 7 videos — its weight has been reduced automatically.
- 🟡 Slot 21:30 NY is under-performing across 3 videos — its weight has been reduced automatically.
- 🟡 Almost nobody DMs these Reels. Sends are Instagram's strongest non-follower signal: end on one surprising, quotable fact a viewer would send to a specific friend, not a generic wrap-up line.

## Per platform

### 🟡 YouTube Shorts — below gate

- Videos measured: **22**
- Average completion: **47%** against a **50%** distribution gate (ratio 0.94)
- Average views: **321**

**Next action:** Averaging 47% against a 50% bar. Shorten the cut toward 27s and tighten the first 3 seconds — the gap is retention, not reach.

### 🔴 Facebook Reels — critical

- Videos measured: **19**
- Average completion: **19%** against a **72%** distribution gate (ratio 0.27)
- Average views: **61**

**Next action:** Only 19% of a 72% bar. The format itself is losing viewers early: rebuild the hook (visual payoff in frame one, promise in under 3 seconds) before changing anything else.

### 🔴 Instagram Reels — critical

- Videos measured: **9**
- Average completion: **24%** against a **70%** distribution gate (ratio 0.34)
- Average views: **89**

**Next action:** Only 24% of a 70% bar. The format itself is losing viewers early: rebuild the hook (visual payoff in frame one, promise in under 3 seconds) before changing anything else.

### 🟡 Instagram sends (DM shares)

- Sends per reach: **0.07%** across 9 Reels

Sends are Instagram's strongest signal for reaching people who do
not already follow the account — weighted several times higher
than a like. It is the metric nothing else in this repo reports.

**Next action:** Almost nobody DMs these Reels. Sends are Instagram's strongest non-follower signal: end on one surprising, quotable fact a viewer would send to a specific friend, not a generic wrap-up line.

## Learned weights

Weights multiply how often a slot or topic pillar gets chosen.
1.00 is neutral; they are clamped to 0.35-2.00 so nothing is ever
permanently switched off and can always earn its way back.

| Slot (NY) | Weight | Videos |
|---|---|---|
| 20:00 | 1.27 | 7 |
| 01:00 | 1.00 | 2 |
| 03:30 | 1.00 | 1 |
| 00:00 | 1.00 | 1 |
| 15:30 | 1.00 | 1 |
| 21:00 | 1.00 | 1 |
| 14:30 | 1.00 | 2 |
| 18:30 | 1.00 | 2 |
| 04:30 | 1.00 | 1 |
| 05:00 | 1.00 | 2 |
| 11:00 | 1.00 | 1 |
| 12:30 | 0.84 | 9 |
| 21:30 | 0.76 | 3 |

| Topic pillar | Weight | Videos |
|---|---|---|
| other | 1.45 | 11 |
| breath | 1.00 | 1 |
| gut | 1.00 | 1 |
| ear | 0.80 | 7 |
| muscle | 0.74 | 4 |
| brain | 0.65 | 9 |

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
