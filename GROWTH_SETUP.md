# Growth Setup — Mr. Nextep / MrNextep

This is the operator's guide: what the system now does on its own, the three
access grants it needs from you, and how to read what it tells you.

For *why* each decision was made, see
[`docs/ALGORITHM_PLAYBOOK.md`](docs/ALGORITHM_PLAYBOOK.md).

---

## 1. What runs automatically now

| Every day | What happens |
|---|---|
| 05:20 NY | **Learning run** (the existing *YouTube Analytics Learning* workflow) — reads real numbers from YouTube + Facebook + Instagram, works out what is and isn't working, writes `docs/GROWTH_REPORT.md` and updates the weights the pipeline uses |
| 10:40 NY | Generation run → publishes 12:30 NY |
| 16:40 NY | Generation run → publishes 18:30 NY |
| 18:10 NY | Generation run → publishes 20:00 NY |

Each generation run now produces **two edits from one script**: a ~36s master
for YouTube and a ~26s cut for Facebook and Instagram, because those platforms
grade completion on a much stricter curve. Each platform also gets its own
caption, written for its own ranking system.

The learning loop runs *before* the day's first video, so today's uploads use
yesterday's lesson.

---

## 2. The two things only you can do

The system is fully automatic **except** for access it cannot grant itself.
Until these are in place the growth report will say `no_data` for the affected
platform and name the exact blocker.

### A. Enable the YouTube Analytics API  ← start here

This is almost certainly the *only* thing blocking YouTube data. The last
diagnostic (`data/seo_diag_20260725.json`) failed with:

```
403: YouTube Analytics API has not been used in project 559439687452
     before or it is disabled.
```

That is a Google Cloud project setting, not a token problem — no code change
can work around it.

1. Open <https://console.developers.google.com/apis/api/youtubeanalytics.googleapis.com/overview?project=559439687452>
2. Click **Enable**, wait ~2 minutes for it to propagate.
3. Run Actions → **MrNextep - YouTube Analytics Learning**.

### B. Regenerate the Meta page token with insights permissions

Currently Facebook returns `(#200) read_insights permission missing`, which is
why per-Reel Facebook data is unavailable.

1. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer).
2. Select your app and the **Mr. Nextep** page.
3. Add: `read_insights`, `pages_read_engagement`, `pages_show_list`,
   `instagram_basic`, `instagram_manage_insights`.
4. Generate a **Page Access Token** and save it as **`FACEBOOK_ACCESS_TOKEN`**
   (and `FB_ACCESS_TOKEN` if you keep that one separately).
5. Verify with Actions → **FB token probe** (prints labels and OK/NO only,
   never the token).

> Instagram insights use the same token. `INSTAGRAM_USER_ID` is already set.

**How to check it worked:** run Actions → **MrNextep - YouTube Analytics
Learning** manually. Every platform should move from ⚪ `no_data` to a real
status, and the run commits an updated `docs/GROWTH_REPORT.md`.

### What you do NOT need to do

**Re-issue the YouTube refresh token.** An earlier draft of this guide asked
for it; that was wrong. The evidence says the existing token already carries
`yt-analytics.readonly`:

- The Analytics failure is `403 API not enabled`, not a scope or permission
  error. A token missing the scope fails differently.
- `scripts/seo_diag.py` calls the Analytics API with this same
  `REFRESH_TOKEN` and reaches the API — it is stopped by the project setting,
  not by the token.

Note that `scripts/get_refresh_token.py` only requests `youtube.upload` and
`youtube.force-ssl`. If you ever *do* need to mint a fresh token, add
`https://www.googleapis.com/auth/yt-analytics.readonly` to its `SCOPES` list
first, or the new token will be less capable than the one you have now.

---

## 3. Reading the growth report

`docs/GROWTH_REPORT.md` is rewritten daily and committed, so you can read it
from your phone without opening Actions logs.

| Status | Meaning | What to do |
|---|---|---|
| 🟢 healthy | clearing the platform's distribution gate | nothing — scale what works |
| 🟡 below_gate | watchable, not spreading | shorten the cut, tighten the first 3s |
| 🔴 critical | viewers leaving early | rebuild the hook before touching anything else |
| ⚪ no_data | no readable metrics | the report names the blocking permission |

**The retention index** is the one number to watch. `1.00` means the channel is
exactly at the level where feeds widen distribution. Below `0.60`, the system
automatically cuts back to 1 video/day — more uploads of a format that loses
viewers actively teaches the feed to stop showing the channel.

**Order of operations when something is red:** retention → hook → length →
topic → posting time → SEO. Tuning SEO while retention is red is wasted effort.

---

## 4. What the system decides on its own

Once data is flowing, and only once there is enough of it (3+ mature videos
per bucket), it adjusts:

- **which time slots** get used, ranked by measured completion
- **which body-system pillars** get picked more often
- **which opening frame** ("Why…", "Your…", "What happens when…") the writer prefers
- **how many videos a day** to publish (1-3, retention-gated)

Safety rails, deliberately: no weight can reach zero, so nothing is ever
permanently written off; one good or bad day cannot swing the schedule; and
cadence can only be *lowered* by the engine, never raised past 3/day.

---

## 5. The part automation cannot do

Both platforms measurably reward visible human presence, and neither can be
faked:

1. **Reply to comments in the first hour** — the strongest early signal you
   personally control.
2. **Pin the generated comment** (the API can post it but cannot pin it).
3. **Watch one video a day yourself, all the way through.** If you get bored at
   second 12, so does everyone else — and no amount of tuning fixes that.

### Never
Do not buy views, subscribers or engagement. Detection is reliable, the
penalty is termination, and fake watch time cannot move a retention-based
ranking system anyway.

---

## 6. Monetisation targets

- **YouTube (YPP):** 1,000 subscribers + 4,000 watch-hours, **or** 10M Shorts
  views in 90 days.
- **Facebook:** ~10,000 followers plus watch-time criteria.
- **Instagram:** an engaged audience for bonuses and brand deals.

Every upload already declares synthetic media, keeps unique visuals via the
channel-wide hash ledger, and rotates its caption boilerplate — the three
things YouTube's inauthentic-content policy actually checks for. Those
guardrails are what keep a faceless AI channel monetisable; please do not
relax them to push more volume.
