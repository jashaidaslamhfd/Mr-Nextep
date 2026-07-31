# SKILLOR growth report

_Generated 2026-07-31 18:54 UTC · policy 2026.07-fix1 (verified 2026-07-31)_

This file is produced by `scripts/growth_report.py`. It reads real
numbers from all three platforms, compares each against that
platform's own 2026 distribution gate, and states one next action.

---

## Headline

**No mature videos with readable metrics yet.**

This is expected on a fresh channel or when analytics access is
not connected. Every platform needs ~24-48h after publishing
before its numbers mean anything, and the learning loop waits for
at least 3 mature
videos per bucket before it will move any weight — small samples
produce confident nonsense.

## Per platform

### ⚪ YouTube Shorts — no data

No usable metrics yet. No metrics yet — publish and wait 24h, or connect this platform's analytics.

### ⚪ Facebook Reels — no data

No usable metrics yet. No metrics yet — publish and wait 24h, or connect this platform's analytics.

### ⚪ Instagram Reels — no data

No usable metrics yet. No metrics yet — publish and wait 24h, or connect this platform's analytics.

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
