# ALL-PLATFORM METRICS AUDIT — Real Performance vs System Scores

*Collected from the channel's committed data (YouTube `video_history.json`,
Facebook `facebook_real_data.json`, Instagram `instagram_real_data.json`).*

---

## 1. THE CORE PROBLEM (proof)

The system assigned **high heuristic scores** to videos, but those scores have
**NO relationship to real performance** — often the OPPOSITE.

### Same scores → wildly different views (the smoking gun)

These 8 videos all got the **identical** score from the system
(`hook=85, ctr=6.8, seo=73`), yet their real YouTube views span **441x**:

| Real views | Topic |
|---|---|
| **882** | Tongue Burn |
| **730** | Ringing Ears |
| **658** | Gag Reflex |
| **344** | Muscle Cramp |
| **203** | Song Earworm |
| **133** | Time Compression |
| **103** | Morning Voice |
| **2** | Throat Lump |

→ The score is useless for predicting success. "Throat Lump" was scored as
good as "Tongue Burn" but got **2 views vs 882**.

### Score-vs-reality correlation (real data, n=22 scored videos)

| System score | Correlation with real views | Verdict |
|---|---|---|
| hook_score | **+0.06** (none) | DRIFTED |
| predicted_ctr | **-0.38** (inverse!) | DRIFTED |
| seo_score | **-0.32** (inverse!) | DRIFTED |
| predicted_retention | **-0.29** (inverse!) | DRIFTED |

Higher "quality" scores are earning FEWER views. This is why the channel is
stuck — it publishes what its (uncalibrated) gates call "good", which reality
rejects.

---

## 2. YOUTUBE — full scored list (real views)

| views | hook | ctr | seo | ret | topic |
|---|---|---|---|---|---|
| 1122 | – | – | – | – | Baby Memory Lost |
| 990 | – | – | – | – | Brain Freeze |
| 907 | – | – | – | – | Cold Hands |
| 882 | 85 | 6.8 | 73 | 0.68 | Tongue Burn |
| 875 | – | – | – | – | Cold Tip Nose |
| 830 | – | – | – | – | Gag Reflex |
| 829 | – | – | – | – | Body Freezes When Scared |
| 825 | 85 | 7.1 | 78 | 0.68 | Cracking Knees |
| 798 | 85 | 7.0 | 75 | 0.68 | Sleeping Foot |
| 794 | – | – | – | – | Dry Mouth |
| 730 | 85 | 6.8 | 73 | 0.68 | Ringing Ears |
| 728 | – | – | – | – | Cold Sweat |
| 700 | – | – | – | – | Yawn |
| 666 | 85 | 7.0 | 75 | 0.68 | Spreading Yawns |
| 658 | 85 | 6.8 | 73 | 0.68 | Gag Reflex |
| 570 | 85 | 7.0 | 75 | 0.68 | Dizzy Standing |
| 447 | 85 | 7.4 | 82 | 0.68 | Body Freeze |
| 349 | 70 | 7.8 | 88 | 0.62 | Sleep Jerk |
| 344 | 85 | 6.8 | 73 | 0.73 | Muscle Cramp |
| 344 | 90 | 7.1 | 78 | 0.76 | Heartbeat Sound |
| 241 | 85 | 6.6 | 70 | 0.68 | Deja Vu |
| 236 | 85 | 9.2 | 87 | 0.68 | Deja Vu Feels Familiar |
| 203 | 85 | 6.8 | 73 | 0.68 | Song Earworm |
| 195 | 85 | 7.1 | 78 | 0.73 | Wrinkled Hands |
| 192 | 70 | 8.0 | 92 | 0.62 | Fast Hunger |
| 133 | 85 | 6.8 | 73 | 0.68 | Time Compression |
| 103 | 85 | 6.8 | 73 | 0.68 | Morning Voice |
| 86 | 90 | 9.4 | 90 | 0.76 | Hear Heartbeat at Night |
| 2 | 85 | 6.8 | 73 | 0.68 | Throat Lump |

*`–` = system did not store a score for that row.*

**YouTube totals:** ~102 videos with analytics, ~28,364 views, avg **278**,
max **1122**, min **2**.

---

## 3. FACEBOOK — real reel views

| views | length | reel |
|---|---|---|
| 381 | 38.8s | (title not captured) |
| 372 | 55.0s | – |
| 370 | 44.9s | – |
| 333 | 49.1s | – |
| 297 | 56.0s | – |
| 290 | 28.8s | – |
| 287 | 35.6s | – |
| 285 | 41.8s | – |
| 271 | 55.0s | – |
| 258 | 41.1s | – |
| 253 | 41.8s | – |
| 252 | 55.0s | – |

**Facebook totals:** 50 reels, **6,650 views**, max **381**. Note the top
performers are LONG (49-56s) — the system now cuts Meta to 18s, which may be
leaving Facebook reach on the table (worth testing).

---

## 4. INSTAGRAM — real reach

| reach | avg watch | caption start |
|---|---|---|
| 164 | 7.4s | Your nose tip freezes |
| 158 | 5.0s | Your foot falls asleep |
| 106 | 6.6s | Your coffee kills taste |
| 103 | 4.5s | You suddenly shake awake |
| 103 | 7.5s | Your calf locks up |
| 102 | 4.8s | Your hands feel cold |
| 102 | 4.2s | You gag brushing back teeth |
| 102 | 7.1s | Your ears ring loudly |
| 98 | 3.6s | Your body twitches suddenly |
| 96 | 3.8s | Your body freezes suddenly |
| 76 | 2.4s | You're stuck on it |
| 50 | 3.6s | You see glowing spots |
| 45 | 3.0s | You Stop Breathing Normally |
| 32 | 2.8s | Your body freezes suddenly |
| 22 | 6.0s | You've lived this moment before |

**Instagram totals:** 20 reels, max reach **164**. Avg watch is only **2.4–7.5s**
— the hook is not landing on IG; completion is far below the 70% gate.

---

## 5. WHAT THIS MEANS (actionable)

1. **Heuristic scores are unreliable** — the reality-calibration engine
   (`src/calibration.py`, committed) now detects this drift and the pipeline
   warns when it happens. But the root fix needs REAL CTR data (see below).
2. **Facebook top performers are 49-56s** — the 18s Meta cut may be too short
   for FB. Consider a separate FB length from IG.
3. **Instagram avg watch 2.4-7.5s** — the hook still isn't landing on IG; the
   first-frame hook overlay helps but needs real IG data to confirm.
4. **Real CTR is 0 across all history** — no `actual_ctr`/`impressions` were
   ever collected, so CTR calibration can't happen until the analytics token
   grants `yt-analytics.readonly` and the analytics workflow runs.

*Full per-video audit: `data/metrics_audit.json` (generated by
`scripts/metrics_report.py`).*
