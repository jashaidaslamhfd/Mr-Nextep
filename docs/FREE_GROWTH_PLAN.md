# SKILLOR — Free Growth Plan (YouTube + Facebook + Instagram)

**Goal:** scale all three platforms toward millions of views.
**Constraint:** zero paid services. Every lever below is free.
**Written:** 2026-08-13 · re-check weekly against `docs/GROWTH_REPORT.md`

---

## 1. Where the channel actually stands

Measured from committed channel state (`data/video_history.json`, `data/growth_state.json`):

| Signal | Now | Needed | Verdict |
|---|---|---|---|
| Videos published | 118 | — | volume is not the problem |
| Total views (all time) | ~29,700 | — | median video: **156 views** |
| YouTube completion (median) | **32%** | ≥ 50% | 🔴 0.63× the gate |
| Facebook Reels completion | **19%** | ~72% | 🔴 critical |
| Instagram Reels completion | **24%** | ~70% | 🔴 critical |
| Instagram followers | 0–35 | — | no distribution base yet |

> **Corrected 2026-08-14.** These numbers used to read "47% completion, 0.94× the
> gate". That was wrong. Two entries in the channel's own history —
> `averageViewPercentage = 293.6%` (a 195-view video whose replays counted) and
> `114.6%` (a video with **two** views) — were averaged in unweighted, which
> overstated the channel by ~50%. The learning loop now discards completion
> measured on almost no traffic, caps any single video's score, and uses the
> **median**. Honest retention index: **0.634** (was 0.937).

**The one-line diagnosis:** the pipeline ships reliably, but **almost nobody
finishes the videos**. Every 2026 feed (YT Shorts, FB Reels, IG Reels) decides
how wide to push a video mainly on *completion rate*. Below the gate, extra
uploads do not buy reach — they teach the feed the format loses viewers.

**So there is exactly one road to millions of views: clear the completion gates
first, then scale volume.** Nothing else in this document matters as much.

---

## 2. What the channel's own data just proved

With the metrics loop repaired (see §3), the ML lever analysis trained on 22
real videos for the first time. Ranked importance for predicting performance:

| Lever | Importance | Meaning |
|---|---|---|
| `duration_seconds` | **0.343** | video LENGTH is the strongest driver |
| `predicted_retention` | 0.284 | retention modelling helps |
| `seo_score` | 0.216 | metadata matters moderately |
| `predicted_ctr` | 0.148 | weak |
| `hook_score` | **0.009** | the gate we were blocking on is ~useless here |

Two hard conclusions:

1. **Shorter videos are the biggest free win available.** Completion =
   watch-time ÷ length. Measured watch time is 2.6–7.5s on Meta and 10–14s on
   YouTube. That is arithmetic, not opinion:

   | Cut length | Completion at 7.5s watch | Meta gate 72% |
   |---|---|---|
   | 24s | 31% | ❌ |
   | 18s | 42% | ❌ |
   | **14s** | **54%** | closer |
   | 12s | 63% | within reach |

2. **`hook_score` should stop being treated as a quality proxy.** It has
   essentially no relationship to real outcomes on this channel. Keep it as a
   sanity filter, never as the thing to optimise.

---

## 3. What was changed in code (already done, free)

| Fix | Why it matters for growth |
|---|---|
| **Cadence is now retention-gated** (`src/continuity.py`) | `clamp_cadence_3()` was a hardcoded `return 3`. It silently overrode the retention-aware decision and forced 3 uploads/day while Meta sat at 19% completion. That is the single most damaging behaviour a struggling channel can have — and it is what YouTube's inauthentic-content policy targets. Cadence is now **earned**: 3/day only when ≥2 platforms clear their gates, 2/day below gate, 1/day when critical. |
| **Metrics loop un-blinded** (`src/platform_metrics.py`) | `data/platform_metrics.json` was `{}`, so every decision was made with **zero** evidence. Measured YouTube numbers already sat in `video_history.json` and were being thrown away. They are now recovered offline (no API call, no cost): **0 → 22 records**. This alone switched the ML from `trained: false, n=0` to `trained: true, n=22`, and the adaptive quality gate from 60 → **70**. |
| **Barrier detection made honest** (`src/strategy_engine.py`) | A platform at 94% of its gate was labelled a *volume* problem ("increase cadence for reach"). Being under the gate is a *retention* problem. Also: a missing `gate_ratio` used to default to "perfectly healthy", so a critical platform read as fine. |
| **Meta cut can finally get short** (`algorithm_policy.py`, `platform_cuts.py`) | The Meta floor was 18s and `META_TARGET_SECONDS=18` was pinned *at* that floor — the lever did nothing. Floor is now 12s, target **14s**, and the cut editor can drop the setup beat so `hook → payoff → loop` fits. |
| **Outlier defence in the learning loop** (`src/growth_engine.py`) | The retention index — the number that sets cadence and the quality gate — was an unweighted mean. Two entries (293.6% on a 195-view video, 114.6% on a **2-view** video) overstated the channel by ~50%: it reported **0.937×** the gate when the honest figure is **0.634×**. Completion measured on almost no traffic is now discarded, any single video's score is capped, and channel health uses the **median**. |
| **Analytics job fails loudly** (`.github/workflows/analytics.yml`) | It ended in `|| echo "::warning::"`, so an expired token produced a **green** run while learning was dead. |
| **Fake repair reports removed** | `auto_repair_engine` / `us_audience_full_repair` invented numbers ("18 candidates found", 23 fake videos). They now report `implemented: false`. |

Tests: **305 passed, 2 skipped** (31 new regression tests lock these in).

---

## 4. What CANNOT be built yet (and why I did not fake it)

**Measured click-through rate does not exist for this channel.**

`src/seo_analytics.py` already requests `impressions` and
`impressionsClickThroughRate` from the YouTube Analytics API, with a
self-healing retry that drops unsupported metrics. YouTube does not serve those
two for this channel, so:

| Field | Entries in `video_history.json` |
|---|---|
| `views` | 108 |
| `average_view_percentage` | 22 |
| `likes` / `comments` | 103 |
| **`actual_ctr`** | **0** |
| **`impressions`** | **0** |

So a "real-CTR title ranker" is not buildable today. Building one anyway would
mean ranking titles on `predicted_ctr` — a heuristic the lever analysis scored
at **0.148**, and which an earlier audit measured as *negatively* correlated
with real views — while calling it measured data. That is precisely the
fabrication that was just removed from the repair stubs, so it was not built.

`tests/test_retention_first.py::RealCtrIsUnavailableTests` documents this: the
CTR request stays in the code so data can start arriving, and the test fails
the moment real CTR appears — which is the signal that a measured-CTR ranker
has become honest to build.

**What to use instead, today:** length and hook. Those are the levers the data
actually supports (`duration_seconds` 0.343), and both are free.

---

## 5. Your action list — free, ranked by impact

### 🔴 P0 — do this week

1. **Fix the Meta token scopes.** `data/facebook_analytics.json` is full of
   `insights_unavailable: grant read_insights and pages_read_engagement`.
   Two of three platforms are invisible to the learning loop, so the system is
   optimising half-blind. Free, ~10 minutes in Meta Business settings:
   `read_insights`, `pages_read_engagement`, `instagram_manage_insights`.
2. **Let cadence stay at 2/day.** Do **not** set `DISABLE_CADENCE_3=true` to
   force 3/day back. The channel earns 3/day automatically the moment two
   platforms clear their gates.
3. **Pick ONE niche and stop switching.** README says *body glitches*, the
   workflow runs *dark_mystery*, the Instagram bio still says body science.
   Mixed signals wreck the "who is this for?" model every feed builds. One
   niche, one bio, one series.

### 🟠 P1 — next two weeks (retention rebuild)

4. **First frame must pay off instantly.** No logo, no title card, no fade.
   Frame 1 = the most visually strange image in the video + 3–5 words of
   on-screen text. The viewer decides in under 1 second.
5. **First spoken line under 2.5s, and it must be a question with stakes.**
   Not "Your body does weird things." → "Your eye twitches *because* your brain
   is misfiring."
6. **Kill every truncated sentence in the narration.** Old videos literally
   say *"Ever felt like you're paralyzed with fear, unable."* A broken sentence
   in the first 3 seconds destroys the exact moment you need to win.
7. **Loop the ending into the opening.** Last line should make frame 1 make new
   sense, so replays happen. Replays are counted as watch time.
8. **Stop the emoji-suffix title template.** `Why Your X 🫀` on 100+ videos is a
   machine pattern; feeds demote template output and YouTube's
   inauthentic-content policy names it explicitly.

### 🟡 P2 — once retention clears the gate

9. **Scale volume only then.** 3/day at the two best-measured slots
   (currently 20:00 NY strongest; 12:30 and 21:30 measurably weak).
10. **Instagram: optimise for sends, not likes.** Sends-per-reach is IG's #2
    ranking signal and worth several likes. The caption should end on a
    concrete, forwardable fact — not "follow for more".
11. **Facebook: match one true interest.** Meta's UTIS model asks viewers if
    content matched their interests. Narrow, honest topic naming beats broad
    bait.
12. **Re-cut your own winners.** Top videos (882 / 730 / 658 views) are proven
    topics. Re-shoot them at 14s with the new hook. Free, and the highest
    expected-value content you can make.
13. **Free engagement signals:** pinned comment on every upload, reply to every
    comment in the first hour, playlists per pillar, YouTube Community posts.

---

## 6. Honest expectation setting

I am not going to pretend a code change produces millions of views. Here is the
realistic ladder, based on your own numbers:

| Stage | Trigger | Expected result |
|---|---|---|
| **Now** | 47% YT / 19% FB / 24% IG completion | median 156 views/video |
| **Stage 1** (2–4 weeks) | YT ≥ 50%, Meta ≥ 45% at 14s cuts | distribution unlocks; median plausibly **500–1,500** |
| **Stage 2** (1–3 months) | gates held + 2–3/day + real-CTR titles | outliers start appearing: **10k–50k** on 1 in ~20 |
| **Stage 3** (6+ months) | consistent outliers + audience base | cumulative **millions**, driven by a few breakout videos |

**Millions of views is an outlier-driven outcome, not a volume-driven one.**
No automation guarantees a breakout. What automation *can* guarantee is many
well-made shots at the target with the gates cleared — and that is exactly what
was broken before this pass: the system was taking 3 shots a day at a target it
could not arithmetically hit, and learning nothing from the misses.

**Biggest remaining risk:** 100+ near-identical template videos on a faceless
AI channel is monetisation-policy exposure. Retention-first, fewer-and-better is
also the safer path.

---

## 7. How to verify progress

```bash
python scripts/growth_report.py --no-fetch   # verdict + per-platform gates
python -m pytest tests/ -q                  # 305 tests
```

Watch exactly three numbers in `docs/GROWTH_REPORT.md`:

1. YouTube completion vs 50% gate
2. Facebook / Instagram completion vs ~70% gate
3. Recommended cadence — when it rises to 3/day on its own, the format has
   genuinely earned volume.
