# SKILLOR growth report

_Generated 2026-08-15 07:43 UTC · policy 2026.08-fix2 (verified 2026-08-14)_

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
SKILLOR algorithm policy 2026.08-fix2 (verified 2026-08-14)

- YouTube Shorts: 18-30s (ideal 24s), hook <= 2.8s, 3-4 hashtags, gate 65% AVP
- Facebook Reels: 12-22s (ideal 16s), hook <= 2.5s, 2-3 hashtags, gate 72% AVP
- Instagram Reels: 12-22s (ideal 15s), hook <= 2.3s, 3-5 hashtags, gate 70% AVP

Script budget: 45-79 words at 2.62 w/s (hook 4-6 words).
Cadence ceiling: 3/day, >= 90 min apart.
```

Platform ranking behaviour changes every few months. Re-verify the
sources in `src/algorithm_policy.py` every 90 days
and update the constants there — every other module follows.
