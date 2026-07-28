# What changed, and why — 2026 multi-platform rebuild

A plain-language record of this release. For the reasoning behind each
platform rule see [`ALGORITHM_PLAYBOOK.md`](ALGORITHM_PLAYBOOK.md); for what
*you* need to do see [`../GROWTH_SETUP.md`](../GROWTH_SETUP.md).

---

## The core problem

The channel published **one 40-55 second file to three platforms** whose
completion curves are nothing alike, and the strategy behind that choice lived
in three places that disagreed with each other: prose in the playbook, magic
numbers in the Python, and env vars in the workflow YAML. When YouTube changed
Shorts ranking to watch-time-per-impression in late 2025, the docs were
updated and the code was not.

The channel's own data said exactly how much that cost. `meta_reach_diag.json`
recorded average watch times of **2.6s, 7.1s and 7.5s against a 47-second
clip** — 5% to 16% completion, against a bar around 70%. No hook rewrite fixes
a length mismatch that large.

---

## What was built

### 1. One source of truth — `src/algorithm_policy.py`
Durations, completion gates, hook budgets, hashtag limits, bait vocabulary and
the cadence ceiling for all three platforms, each with its sources and a review
date. The script writer, renderer, cuts, captions, validator and tests all
derive from it. Change the strategy in one reviewable file; everything follows.

### 2. Dual cut — `src/platform_cuts.py`
YouTube gets a ~36s master; Facebook and Instagram get a ~26s edit built from
the **same rendered scenes and audio** — one extra encode, zero extra
generation cost. Structural beats (hook, suspense, payoff, loop-back) are
protected; the lowest-information middle scenes are dropped. Scenes are
dropped rather than speeding the audio up, because rushed narration is exactly
the "machine-made" quality both platforms' 2026 policies penalise.

### 3. Loop ending instead of a spoken CTA
The outro scene spent ~8% of a short video's runtime asking instead of
delivering — on the exact signal all three platforms rank on. The follow ask
moved to the caption, where it costs nothing. `SPOKEN_CTA_MODE=cta` restores
the old behaviour for A/B testing.

### 4. Three captions written for three ranking systems — `src/platform_captions.py`
YouTube gets a keyword description for the Shorts search carousel; Facebook
gets a caption that names the topic plainly for Meta's true-interest model;
Instagram gets keyword-indexed text with a forwardable payoff, since sends are
its second-strongest signal. `#shorts` is stripped from Meta captions — it is
the visible tell of a cross-post.

### 5. The learning loop — `platform_metrics.py` → `growth_engine.py`
Normalises all three platforms into comparable completion-vs-gate ratios,
then re-weights publish slots, topic pillars, hook frames and cadence. The
scheduler, trend fetcher and script generator consume those weights on the
next run. `scripts/growth_report.py` writes a daily plain-language verdict.

Guardrails: no action under 3 mature samples, weights clamped to [0.35, 2.0]
so nothing is ever permanently written off, damped updates so one day cannot
swing the schedule, and cadence that can only be lowered — never raised past
3/day.

---

## Bugs found while building

Each of these was already costing reach; none were in the original brief.

| Bug | Impact |
|---|---|
| **Thumbnail text at 84-97% of frame height** | Rendered entirely behind every platform's caption block and CTA button. A thumbnail's only job is legibility at ~120x90 in a feed. |
| **Hook scorer could not rank hooks** | Gave "Hello everyone and welcome back" a 70 and "Scientists discovered something interesting" an 85 — the same band as a working hook. The workflow gated on this number. |
| **Hook gate was unreachable** | `MIN_HOOK_SCORE=85` was calibrated for the old scorer; under the new one only 3 of 21 published hooks would clear it. Most runs would have skipped their upload. |
| **Hook budget conflated two things** | "Viewers decide in 2-3s" was applied as "the sentence must END in 2s", allowing five words. The trimmer then chopped good openers into `"Your calf locks up in."` |
| **Trimmer shipped fragments** | Its docstring promised "regeneration is better than broken audio"; its last branch hard-cut mid-sentence anyway. |
| **Retries taught the model nothing** | The hook gate lived in `main.py`, which calls `generate_script` fresh each attempt — so a rejected hook started a new conversation and the model never learned what was wrong. |
| **Evening slot never got credit** | Publish times snapped to a 30-minute grid, so a 20:35 publish landed in a "20:30" bucket no slot uses. The 20:00 slot stayed at neutral weight forever. |
| **ffprobe absence discarded finished renders** | `imageio-ffmpeg` ships ffmpeg *without* ffprobe, so the fallback never worked. Now parses ffmpeg's own output. |
| **Two definitions of "winner"** | The report announced a best hook frame at weight ≥1.10 that the generator ignored for being under its own 1.15. |
| **Retired config could override the policy** | The deployed workflow still pins the old 40-55s targets; env vars beat code. `env_override()` now refuses exactly those values and says so. |

---

## Verification

- **151 offline tests**, 74 new. Every test names the failure it prevents.
- **End-to-end pipeline run** with mocked APIs: 33.9s master + 24.9s Meta cut,
  three distinct captions, loop ending, correct history fields.
- **Real renders measured**: thumbnails checked by measuring ink extents
  against the safe box across four title lengths.
- **Learning loop simulated** with 12 videos across three slots: weights
  separate correctly (12:30 → 1.18, 20:00 → 1.07, 18:30 → 0.71), the scheduler
  reorders, cadence drops to 2/day at 99% of gate, topic selection biases
  130/70 toward the retaining pillar.
- **Deployment safety**: pipeline run with the live workflow's exact env
  confirms all four retired values are ignored.

---

## What still needs a human

1. **Apply the workflow updates** in [`workflow_updates/`](workflow_updates/) —
   most importantly adding `growth_loop.yml`, without which nothing ever reads
   your performance data.
2. **Grant the three access permissions** in [`../GROWTH_SETUP.md`](../GROWTH_SETUP.md)
   section 2 (YouTube Analytics API, `yt-analytics.readonly` on the refresh
   token, Meta `read_insights`).
3. **Reply to comments in the first hour**, pin the generated comment, and
   watch one video a day yourself. Both platforms reward visible human
   presence and neither can be automated.
