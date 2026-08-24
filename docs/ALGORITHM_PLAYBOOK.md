# MrNextep Algorithm Playbook — YouTube · Facebook · Instagram (2026)

> **Honest framing first.** Nobody outside Google and Meta can read the ranking
> model. What *is* knowable: statements from platform staff, documented product
> behaviour, large-cohort creator measurements, and this channel's own numbers.
> Every claim below is tagged with which of those it came from, and every one
> is wired to a specific line of code. Re-verify quarterly — feeds change.
>
> **This document does not configure anything.** `src/algorithm_policy.py` is
> the single source of truth; this file explains *why* those constants are
> what they are. If the two ever disagree, the code is right and this file is
> stale.

---

## 0. What changed in 2026, and what it cost this channel

Four confirmed platform changes broke the assumptions the pipeline was built on:

| Change | Confirmed by | What it broke here |
|---|---|---|
| YouTube **decoupled Shorts from long-form ranking** (late 2025) | YouTube / Rene Ritchie; corroborated across 2026 creator analyses | Shorts must now win entirely on their own signals — no borrowed channel authority |
| Shorts ranking moved to **watch-time-per-impression**, ~50% AVP gate for 30-60s and ~65% for sub-30s | Multiple independent 2026 cohort studies | The 40-55s cut needed 20-27 seconds of held attention to clear the same bar a 36s cut clears with 18 |
| Instagram's top signals are **watch time, then sends-per-reach**, sends worth 3-5x a like | Adam Mosseri, repeatedly | Nothing in this repo had ever read sends-per-reach. It was invisible. |
| Meta shipped **UTIS** — surveying viewers on whether a Reel matched their interests (Jan 2026) | Meta engineering announcement | Broad-appeal engagement optimisation lost value; sharp niche relevance gained it |

**What the channel's own data said.** `data/meta_reach_diag.json` recorded
average watch times of **2.6s, 7.1s and 7.5s against a 47-second clip** — 5% to
16% completion, against a bar around 70%. That is not a hook problem, a topic
problem, or a posting-time problem. It is a **length mismatch**: the same file
was being sent to three platforms with three different completion curves.

---

## 1. The policy, and where it lives

`src/algorithm_policy.py` declares one block per platform. Everything else
imports from it: the script word budget, the render targets, the caption
limits, the media validator, the learning thresholds and the tests.

| | YouTube Shorts | Facebook Reels | Instagram Reels |
|---|---|---|---|
| Cut length | 30-42s (ideal **36s**) | 20-32s (ideal **27s**) | 18-30s (ideal **26s**) |
| Completion gate | 50% (65% if under 30s) | ~72% | ~70% |
| Hook budget | 2.8s | 2.5s | **2.0s** ← binds all three |
| Hashtags | 3-4 | 2-3 | 3-5 |
| Spoken CTA | no | no | no |

The hook budget is the tightest of the *enabled* platforms, because one audio
track serves all of them (`shared_hook_seconds`). Turn Instagram off and the
budget relaxes to YouTube's automatically.

---

## 2. The five changes that actually move reach

### 2.1 Dual cut — one script, two edits
`src/platform_cuts.py`

YouTube receives the ~36s master. Facebook and Instagram receive a ~26s edit
built from **the same rendered scenes and audio** — one extra encode, zero
extra LLM or image calls.

Scene priority is fixed and enforced:

```
protected   scene 1     HOOK        the promise
protected   scene 2     SUSPENSE    the open question
protected   scene N-1   PAYOFF      the answer
protected   scene N     LOOP-BACK   the replay earner
droppable   the middle, lowest information density first
```

Two deliberate choices worth defending:

- **Drop scenes, never speed up the audio.** Rushed narration is exactly the
  "machine-made" quality both platforms' 2026 policies penalise, and every
  scene boundary is already a sentence boundary, so cutting one leaves clean
  speech.
- **Fill toward the target, not the ceiling.** Completion is a percentage:
  every second added raises the seconds a viewer must watch to clear the same
  gate. The ceiling is a limit, not a goal. (First implementation filled to the
  ceiling and produced 29.4s cuts against a 26s target — regression-tested now.)

### 2.2 Loop ending instead of a spoken CTA
`src/main.py` · `SPOKEN_CTA_MODE=loop`

The old pipeline appended a "follow for more" scene. On a 36s video that is
~8% of runtime spent asking instead of delivering — spent precisely on the
signal all three platforms rank on. Worse, Meta demotes engagement-bait audio.

Now the final scene echoes the hook so the video loops cleanly. **Replays count
as watch time everywhere.** The follow ask moved to the caption, where it costs
nothing. `SPOKEN_CTA_MODE=cta` restores the old behaviour for A/B testing.

### 2.3 Three captions, not one copied three ways
`src/platform_captions.py`

| Platform | What the caption is *for* | Consequence |
|---|---|---|
| YouTube | Shorts now appear in search with their own carousel | keyword-first description, `#Shorts` retained |
| Facebook | UTIS asks viewers "did this match your interests?" | topic named plainly in line 1, never teased |
| Instagram | captions are indexed for search; sends drive non-follower reach | keyword body, forwardable payoff, first line under the fold limit |

`#shorts` is stripped from Meta captions: it is the visible tell of a
cross-post, and Meta's originality checks look for exactly that.

**Bait rules are platform-specific.** Both families ban demanding a
like/comment/share/tag. Meta additionally treats "subscribe" as off-platform
promotion; YouTube does not. Treating them identically costs reach on one side
or a demotion on the other. A plain "Follow" is clean everywhere — and since
the spoken CTA is gone, every Meta caption carries it (test-enforced).

### 2.4 The learning loop
`src/platform_metrics.py` → `src/growth_engine.py` → the next run

Metrics from all three platforms are normalised to **completion as a fraction
of that platform's own gate**, which is the only way a 27s Reel and a 36s Short
can be compared fairly. The engine then re-weights publish slots, topic pillars
and hook frames, and recommends a cadence.

Four rules keep it from doing damage:

1. **No action on thin data** — a bucket needs 3+ mature videos before its
   weight can move. Small samples produce confident nonsense.
2. **No weight ever reaches zero** — clamped to `[0.35, 2.0]`, so a bad
   fortnight cannot permanently delete a slot or a topic area.
3. **Damped updates** — a single day shifts a weight by at most ~30% of the
   gap, so one outlier cannot flip the schedule.
4. **Cadence can only be lowered**, never raised past the policy ceiling.

### 2.5 Cadence follows retention
`src/growth_engine._recommend_cadence`

| Measured retention | Cadence | Reasoning |
|---|---|---|
| < 60% of gate | **1/day** | More uploads of a format that loses viewers teaches the feed to stop showing the channel |
| 60-100% of gate | **2/day** | Concentrate the quality budget on the two best-measured slots |
| ≥ 100%, 2+ platforms healthy | **3/day** | The format has earned the volume |

This is the direct answer to YouTube's inauthentic-content policy: volume is
only safe once quality is proven.

---

## 3. The 8-beat arc (enforced in code, not advisory)

`script_generator._validate_script` rejects a script that fails these:

1. **HOOK** — scene 1, 4-5 words, lands inside the shared hook budget
2. **SUSPENSE** — scene 2 must contain an open question (`?`) — enforced
3. **PROBLEM** — the relatable misconception
4-5. **EXPLANATION** — the mechanism, in plain steps
6. **NORMAL VS NOTE** — context without diagnosing
7. **PAYOFF** — one concrete, quotable fact (this is what makes a Reel
   *sendable*, and sends are Instagram's #2 signal)
8. **LOOP-BACK** — must share a concept word with the hook — enforced

---

## 4. Compliance guardrails (these protect monetisation — do not "optimise" them away)

- **AI disclosure always on** (`containsSyntheticMedia: true`). Disclosed AI
  ranks normally; undisclosed realistic AI is a suppression and demonetisation
  path.
- **Originality**: channel-wide media-hash ledger means no visual ever repeats;
  per-video metadata; rotating caption boilerplate. YouTube's July-2025
  inauthentic-content policy targets template output — AI or not.
- **No engagement bait, no fear bait**, medical-accuracy pass with auto
  disclaimer, `YT_MADE_FOR_KIDS=false`.
- **Topic variety is a compliance requirement**, which is why the learning loop
  biases topic selection rather than locking onto one winning pillar.
- **Human in the loop**: reply to first-hour comments, pin the generated
  comment. Automation cannot fake this and both platforms reward it.

---

## 5. Reading the results

Run `python scripts/growth_report.py` (or the daily **Growth Loop** workflow).
It writes `docs/GROWTH_REPORT.md` with a per-platform verdict and one next
action each. The status meanings:

- 🟢 **healthy** — clearing the gate. Scale what is working.
- 🟡 **below_gate** — watchable but not spreading. Shorten and tighten the open.
- 🔴 **critical** — losing viewers early. Fix the hook before anything else.
- ⚪ **no_data** — usually a missing permission; the report names it.

**Order of operations when something is wrong:** retention → hook → length →
topic → posting time → SEO. Tuning SEO while retention is red is wasted work,
and the report says so explicitly.

---

## 6. Re-verification

Platform behaviour shifts every few months. Every 90 days, re-check the sources
listed in `src/algorithm_policy.py` and update the constants there. Everything
downstream — writer, renderer, cuts, captions, validator, tests — follows from
that one file.
