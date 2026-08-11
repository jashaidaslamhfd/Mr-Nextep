# MILLION-VIEWS STRATEGY — Data-Driven Plan (from real all-platform metrics)

*Generated from the channel's ACTUAL metrics across YouTube, Facebook and
Instagram. This is not a guess — every number below comes from the platform
data files committed in `data/`.*

---

## 1. Where the channel actually stands (real numbers)

| Platform | Videos | Total views | Avg/video | Best | Completion | Gate | Gate ratio |
|---|---|---|---|---|---|---|---|
| **YouTube** | 106 | 29,693 | 280 | 1,122 | 47% | 50% | 0.94 |
| **Facebook** | 50 | 6,650 | 133 | 381 | 19% | 72% | 0.27 |
| **Instagram** | 20 | ~1,400 | 71 | 164 | 24% | 70% | 0.34 |

Followers: YouTube (n/a) · Facebook **35** · Instagram **0**

### The honest truth
- **YouTube** is closest to working (47% vs 50% gate) but avg 280 views — the
  algorithm has not found a reason to push it wider.
- **Facebook + Instagram are the real problem.** Completion is 19-24% against a
  70-72% gate. A feed that sees under a quarter of the video watched treats the
  channel as low-quality and **stops showing it** — so views flatline at
  tens-to-hundreds no matter how many videos you publish.
- **Followers are near zero** (FB 35, IG 0). This channel is essentially new.

**Therefore: "millions of views" will NOT come from posting more.** It comes
from fixing the two signals that gate distribution:
  1. **Completion (retention)** — the dominant ranking signal on all 3 feeds.
  2. **Watch-time per impression** — a longer average watch earns more of the
     feed.

---

## 2. Diagnosis — why completion is failing

The metrics (avg watch time, completion, hook scores) plus the ML lever
analysis point to **the first 3 seconds and the cut length**:

- YouTube avg watch 10-14s on a 33s video = viewers leave early.
- Facebook/IG avg watch **2.6-7.5s** on a ~24s Reel = the hook is NOT landing.
- ML lever analysis (RandomForest on this channel's real videos) ranks
  **video length** and **predicted retention** as the two biggest drivers of
  views — above SEO and CTR.

**Root causes:**
1. **Hook lands too slow / too weak** — first-frame payoff missing, promise not
   in under 3 seconds.
2. **Cut still too long for Meta** — a 24s Reel is still ~3x the 7s avg watch.
3. **Repetitive template** (now fixed via the Humanizer, but the damage from
   earlier near-identical uploads is in the feed's memory).
4. **Duplicate uploads** (now deleted) had conditioned the feed to expect
   repeat content.

---

## 3. The Million-Views Strategy (what we're applying)

### A. Retention-first generation (DONE — this is now the default)
- **Barrier = completion** (strategy engine now detects this correctly).
- **Cadence = 1/day** while completion is below bar (quality over volume —
  flooding a low-retention format teaches the feed to stop showing the channel).
- **Series = dark_mystery** (tension + curiosity = highest-retention format,
  per research + this being an open niche).
- **Hook budget tightened** to each platform's 2026 gate (YT 2.8s, FB 2.5s,
  IG 2.3s).
- **Loop ending** (no spoken CTA) — replays count as watch time.

### B. Make the first 3 seconds unmissable (HIGHEST priority)
This is the single biggest lever. Implement:
1. **Frame-one visual payoff** — the "wow"/hook image in frame 1, not an intro.
2. **Promise in the first sentence** (<3s) — name the surprising outcome.
3. **Text overlay in frame one** with the hook line (helps silent-scroll).

### C. Meta-specific fix (Facebook + Instagram)
- **Shorten the Meta cut further** toward 18-20s until completion clears the
  70% gate. Short Reels that finish beat long Reels that get abandoned.
- **Rebuild the Meta hook specifically** (IG decides in ~2s).

### D. One clear topic/pillar to build an audience identity
The feed rewards a **consistent, recognizable** channel. Stick to the
dark-mystery series and let it build a fingerprint instead of mixing themes.

### E. Let the learning loop actually steer
- The analytics workflow now re-decides series/cadence/quality each day from
  real completion. Keep publishing so it has data, but at quality cadence.

---

## 4. What "do whatever is needed" meant (already done in this session)

1. **Deleted the duplicate scheduled video** that had the same title as a recent
   upload (duplicate content is an inauthentic-content risk + tanks retention).
2. **Deleted 9 more duplicate-title videos** (kept best performer per group).
3. **Added a duplicate-title guard** so no future upload can repeat a title.
4. **Added the Humanizer** so content reads as a consistent human creator, not
   a templated pipeline (2026 inauthentic-content policies demote the latter).
5. **Built the Autonomous Strategy Engine** so the system self-tunes toward
   whatever retains (barrier, cadence, quality gate, ML lever insight).
6. **Pivoted to dark_mystery** — the highest-retention, open-niche format.

---

## 5. Realistic expectations (important)

**"Millions of views" is a destination, not a switch.** No tool can guarantee
millions on day one — the platforms only push videos wider when retention +
watch-time clear their gates. What this plan does is give the system the best
possible chance by fixing the actual measured bottlenecks. If completion climbs
past the gates (YT ≥50%, FB ≥72%, IG ≥70%), the feed starts distributing wider,
and that is the mechanism by which a short can reach millions.

**Track the leading indicators daily** (the strategy engine now does):
- Average view percentage per platform (the #1 gate).
- Hook survival (first-3s completion).
- Watch-time per impression.

When those cross their gates, volume can be raised back to 3/day. Until then,
1 high-retention video/day + a rebuilt hook is the correct, data-backed play.

---

*Policy: 2026.07-fix1 (verified 2026-07-31). See `docs/ALGORITHM_PLAYBOOK.md` and
`src/algorithm_policy.py` for the underlying 2026 ranking rules.*
