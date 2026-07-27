# Growth Setup & Action Guide — Mr. Nextep / SKILLOR US

This guide covers (1) what was fixed in the pipeline, (2) the ONE thing you must
do to start **seeing your data**, and (3) the realistic growth path. Read it top
to bottom — step 2 is the current bottleneck.

---

## 1. Pipeline fixes applied in this branch

| Fix | File(s) | Why it matters |
|---|---|---|
| Voice generation `NameError` crash | `src/voice_generator.py` | The "all engines failed" error path referenced a deleted variable and crashed |
| Facebook permanent-failure crash | `src/uploader.py` | A failed FB Reel left state stuck at `"started"`, crashing the next run |
| Broken hashtags in YouTube description | `src/seo_generator.py` + `scripts/metadata_repair.py` | `#human body` was truncated at the space; now `#humanbody` |
| Stronger pinned/seed comment | `src/seo_generator.py` | Seeds the first reply — the biggest cold-start engagement lever |
| Curiosity / open-loop hook scoring | `src/shorts_enhancer.py` + `src/script_generator.py` | The publish gate now prefers strong curiosity hooks (retention lever) |
| Minor cleanups | `scripts/*.py` | unused imports / f-strings without placeholders |

Verified: `pyflakes` clean, offline test suite passes (23 tests).

---

## 2. DO THIS FIRST — unlock your data (the #1 blocker)

The pipeline is currently **flying blind**: it cannot read your retention/CTR
(YouTube) or your reel views (Facebook). You cannot improve what you cannot
measure. Fix these two:

### A. Enable the YouTube Analytics API (CTR / retention / traffic)
`scripts/seo_diag.py` fails with a 403 because the Analytics API is disabled in
your Google Cloud project. Enable it here:

```
https://console.developers.google.com/apis/api/youtubeanalytics.googleapis.com/overview?project=559439687452
```

Click **Enable**, wait ~1 minute, then re-run the **US SEO Diagnostic** workflow
(Actions → “US SEO Diagnostic (one-shot)”). It will then return daily
views / impressions / CTR / average view duration and traffic sources.

### B. Regenerate the Facebook PAGE token WITH `read_insights`
Your FB diagnostic shows `(#200) read_insights permission missing`. Your page
token can read AND write reels, but it lacks `read_insights`, so reel views
cannot be read.

1. Open **Graph API Explorer** (developers.facebook.com/tools/explorer).
2. Select your app + the **Mr. Nextep** page.
3. Add permissions: `read_insights`, `pages_read_engagement`, `pages_show_list`.
4. Generate a new **Page Access Token**.
5. Store it in the repo secret **`FB_ACCESS_TOKEN`** (used by analytics/diagnostics)
   and — if it is a separate secret — **`FACEBOOK_ACCESS_TOKEN`** (used for posting).
6. Verify: run Actions → **“FB token probe”**. Its output is safe to share (it
   prints only labels + OK/NO, never the token) and should read `read_insights=OK`.

---

## 3. Read & repair your existing videos

- **Diagnose:** Actions → “US SEO Diagnostic (one-shot)” (read-only) → writes
  `data/seo_diag_<date>.json`.
- **Repair old metadata (titles/tags/descriptions):** Actions → “Metadata Repair
  (one-shot)” → run with `apply=false` FIRST (preview report), then `apply=true`
  once you are happy with the before/after plan.

---

## 4. The realistic growth path (there is no magic button)

Growth = good content + consistency + time. The pipeline removes friction; the
algorithm still rewards genuine watch-time and engagement.

1. **See your data** (step 2), then fix whatever retention/CTR reveals.
2. **Win the first 3 seconds** — the hook decides whether viewers stay. The gate
   now prefers curiosity/open-loop hooks.
3. **Post consistently for months.** Don’t stop.
4. **Double down on winners** — make more like your best performer
   (“Why You Hear Your Heartbeat at Night”).
5. **Reply to every comment** — engagement tells the algorithm to push more.

### Monetization thresholds (so you know the target)
- **YouTube (YPP):** 1,000 subscribers + 4,000 watch-hours (12 mo) **or** 10M
  Shorts views (90 days). Currently ~22 subs — growth first.
- **Facebook:** ~10,000 followers + watch-time criteria for in-stream/Reels.
- **Instagram:** an engaged audience for bonuses / brand deals.

Earnings follow growth. Aim for the next milestone (33 → 1,000), not millions.

---

## 5. Never do this
Do **not** buy views/subscribers or use bots. Platforms detect this and
terminate or shadow-ban the channel. Fake engagement does not fool the algorithm
— real watch-time does.
