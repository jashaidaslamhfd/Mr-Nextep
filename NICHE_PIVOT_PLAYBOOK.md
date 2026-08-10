# NICHE PIVOT PLAYBOOK — From Saturated "Body Glitches" to "Dark Mystery / Mind-Bending Facts"

**Goal:** millions of US Shorts/Reels views.
**Decision made:** full pivot implemented (per operator request — "just want millions of views").

---

## 1. Why we pivoted (the data)

### 1.1 Your channel's REAL performance (from `data/growth_state.json`)
The current niche was not delivering millions — it was delivering hundreds, and
failing the completion gates that every 2026 feed grades on:

| Platform | Avg views | Completion | Gate | Verdict |
|---|---|---|---|---|
| YouTube Shorts | **321** | 47% | 50% | ⚠️ below gate |
| Facebook Reels | **61** | 19% | 72% | ❌ far below gate |
| Instagram Reels | **89** | 24% | 70% | ❌ far below gate |

Volume is not the problem; **completion/retention** is. Meta only widens
distribution at ~70–72% watch-through. At 19–24% the feed treats the channel as
low-quality and quietly stops showing it — so no amount of "more videos" fixes it.

### 1.2 Your own competitor research (`data/niche_intelligence.json`) says the niche is saturated
```
🧠 Brain Mysteries      gap=🔴 SATURATED
⚡ Body Reactions       gap=🔴 SATURATED
😴 Sleep & Body         gap=🔴 SATURATED
💓 Heart & Circulation  gap=🔴 SATURATED
```
Demand is high, but so is competition — exactly the "high-demand / high-competition"
trap. Only two sub-niches were open, and even those stay inside the same
body-facts format that was already failing retention on Meta.

### 1.3 2026 US Shorts research (multiple sources) — what actually goes viral faceless
Curiosity + tension + shareability are the strongest retention drivers, and the
Shorts space is **least saturated** in:
- **Psychology / dark psychology / human behavior** — "why people do what they do"
- **Unsolved mysteries / "history that sounds fake but isn't"** — Shorts space "almost completely open"
- **Horror / creepy / mind-bending facts** — tension = watch-to-end + share
- **Dark animal behavior** — "genuinely wide open"

These convert directly into the completion metric your channel was failing on.

---

## 2. The chosen pivot

> **Dark Psychology & Mind-Bending Facts** — framed as curiosity/mystery, not
> medical facts. Tension + an unanswered "why?" hook → viewer watches to the
> end → replays → share. This is the single biggest lever for the completion
> gate that was killing Meta reach.

**Why it reuses your entire infrastructure:**
- `assets/music/` already has **suspense + mystery** tracks (perfect for this).
- Your `dark_mystery_topics.json` already contained the style (sleep paralysis,
  delusions, sensory glitches).
- Voiceover + AI-visuals + Shorts pipeline is 100% unchanged; only the topic
  source and the writing tone changed.

---

## 3. What was implemented

| File | Change |
|---|---|
| `src/trend_fetcher.py` | Added `DARK_MYSTERY_CATALOGUE_PATH`, `get_dark_mystery_topics()` loader, and the `dark_mystery_series` strategy branch (mirrors the 500-topic body-glitch pattern). |
| `src/script_generator.py` | Added `dark_mystery_mode` + a `DARK MYSTERY & MIND-BENDING FACTS` ruleset (curiosity/tension hook, no gore, no fake cures, loop ending, calm narrator). |
| `data/dark_mystery_topics.json` | Expanded **20 → 500 unique topics** across sleep, delusions, perception, memory, body, psychology, unsolved mysteries, dark animal facts, statistics and space. |
| `scripts/generate_dark_mystery_topics.py` | NEW reproducible generator for the 500-topic catalogue. |
| `.github/workflows/main.yml` | `CONTENT_SERIES` `body_glitches → dark_mystery`, `TOPIC_STRATEGY` `viral_hijack → dark_mystery_series`. |
| `env.example` | Documented both launch series + the new defaults. |
| `tests/test_core.py` | +2 tests: 500-topic catalogue integrity & prompt-mode liveness. **172/172 tests pass.** |

---

## 4. Evidence it works (run on this machine)

```
TOPIC_STRATEGY=dark_mystery_series  selected:
  #218 The Monty Hall Problem
  #62  Livor Mortis
  #430 Why Crying Helps
  #456 Why Your Nose Runs in the Cold
  #36  Charles Bonnet Syndrome
```
Unique, episode-numbered, weighted-random — the series iterates cleanly through
500 topics.

---

## 5. Next actions to actually hit millions

1. **Deploy:** commit + push, let GitHub Actions run the new series for ~14 days.
2. **Keep the learning loop fed** — the daily analytics run re-weights slots,
   topics and cadence from real completion. Let it collect >=3 mature videos
   per bucket before judging.
3. **Watch completion, not raw views.** Target: YouTube ≥50%, FB ≥72%, IG ≥70%.
   That is the "millions" gate.
4. **If Meta still lags:** your own report already says it — the fix is the
   **hook/first frame**, not the niche. Rebuild frame-one payoff, promise in
   <3s. The dark-mystery format is chosen precisely because it makes this easy.
5. **A/B the visual style:** dark/cinematic AI visuals (already the default
   `DARK_STYLE_SUFFIX`) test against the old clean-documentary look.
6. **Re-verify in 90 days** — platform ranking behaviour drifts (noted in
   `src/algorithm_policy.py`).

---

## 6. Rollback (if ever needed)
- `main.yml`: set `CONTENT_SERIES=body_glitches`, `TOPIC_STRATEGY=body_glitch_series`.
- Nothing was deleted — `data/body_glitch_topics.json` (500 topics), the body
  glitch loader, and the `body_glitch_series` branch all still exist and pass tests.
