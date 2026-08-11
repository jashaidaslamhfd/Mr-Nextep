# Autonomous Strategy Engine — DS / ML / DL Intelligence Layer

The system is no longer just a scheduler. It now has a **self-deciding brain**
that reads its own results, learns what works, and picks the strategy for the
next run without a human re-tuning the workflow.

## Why this exists

The pipeline already had scattered ML (growth_engine weights, ml_brain, viral
intelligence) but nothing that **tied it into one decision** before every run.
That was the barrier: the learning loop ran, then generation ignored most of
what it learned. This layer closes that loop.

## Architecture

```
         real analytics (YouTube/FB/IG metrics)
                     │
      ┌──────────────▼──────────────┐
      │      Strategy Engine        │  src/strategy_engine.py
      │  ┌────────────────────────┐ │
      │  │ Barrier detection      │ │  which gate is failing?
      │  ├────────────────────────┤ │
      │  │ Series selection       │ │  dark_mystery / body_glitches / trend
      │  ├────────────────────────┤ │
      │  │ ML lever analysis      │ │  RandomForest → which feature drives views
      │  ├────────────────────────┤ │
      │  │ Adaptive quality gate  │ │  tighten/loosen based on completion
      │  └────────────────────────┘ │
      └──────────────┬──────────────┘
                     │ writes data/strategy_state.json
                     ▼
       generation pipeline (src/main.py) reads the decision
```

## What it decides (autonomously)

| Decision | Source | What it does |
|---|---|---|
| **Growth barrier** | platform_health + video features | Flags completion / CTR / scheduling / volume as the single binding constraint, with a concrete fix. |
| **Series to run** | real per-series completion | Picks the best-retaining series; **respects an operator pivot** (won't bounce a fresh series back to a saturated one just because the old one has more history). |
| **Cadence** | barrier type | 1/day when retention is broken (quality first), 3/day when healthy (reach). |
| **Adaptive quality gate** | measured completion | Raises the gate to 65 when completion is failing, lowers to 55 when healthy. |
| **Best slot** | learned slot weights | Reuses growth_engine's measured peak slot (e.g. 20:00). |
| **ML lever priority** | RandomForest on this channel's own videos | Tells you which lever (video length, retention, SEO, hook, CTR) actually drives views on THIS channel — not a guess. |

## Real run output

```
🤖 AUTONOMOUS STRATEGY DECISION
Series to run      : dark_mystery
Topic strategy     : dark_mystery_series
Growth barrier     : completion
  facebook_reels is at 27% of its completion gate. Rebuild the first-3-seconds
  hook and shorten the cut toward the platform ideal before adding volume.
Cadence            : 1 video(s)/day
Quality gate       : 60
Best slot          : 20:00
ML lever priority  :
  - video length  (34%)
  - predicted retention  (28%)
  - SEO / description+tags  (22%)
```

Note the ML insight: **video length and predicted retention drive views on this
channel more than SEO** — so tightening the cut toward the platform ideal
matters more than writing better descriptions.

## Files

| File | Purpose |
|---|---|
| `src/strategy_engine.py` | The engine. Pure `decide_from_state()` core + `StrategyEngine` class wrapper + `ml_lever_analysis()` (scikit-learn RandomForest). |
| `scripts/strategy_decision.py` | CLI: `--report` human summary, `--reset` clear, default prints JSON. |
| `data/strategy_state.json` | The persisted decision the pipeline reads. |
| `tests/test_strategy_engine.py` | 8 offline tests (barrier, cadence, slot, series weighting, ML lever training + fallbacks). |
| `env.example` | `STRATEGY_STATE_PATH` documented. |
| `requirements-optional.txt` | `pandas` for future feature engineering (core runs on numpy + scikit-learn already in requirements.txt). |

## Wiring

- **Learning loop** (`src/analytics_updater.py`): after it reads real metrics
  and runs growth_engine, it now calls the strategy engine and persists a fresh
  decision (Stage 3b).
- **Generation** (`src/main.py`): `_apply_strategy_decision()` runs before topic
  selection — it applies the recommended series, adaptive quality gate, and
  logs the barrier + ML insight. Fully wrapped so a bad decision file can never
  block a publish.

## How to use

```bash
# See the current autonomous decision (real data)
python scripts/strategy_decision.py --report

# Reset if you ever want a fresh decision
python scripts/strategy_decision.py --reset
```

## Deliberate design choices

1. **Pure core = testable.** `decide_from_state()` takes numbers and returns a
   decision — no disk, no network. Tests feed synthetic state directly.
2. **Graceful degradation.** No data → sensible policy defaults, never raises.
3. **Respects human pivots.** An operator's deliberate series choice is honored
   until the new series either proves out or fails.
4. **ML only where it helps.** RandomForest trains on real videos for lever
   importance; heuristic fallbacks keep decisions robust on cold start.
5. **Percentage→fraction normalisation.** `average_view_percentage` (0-100)
   is converted to a 0-1 fraction everywhere the engine reasons, so the
   adaptive gates and weights are correct.

## Test status

- **180/180 tests pass** (172 existing + 8 new strategy-engine tests).
- `pyflakes` clean across `src/`, `scripts/`, `tests/`.
- All modules compile.

---

## Advanced Intelligence Layer (new — `src/intelligence.py`)

The basic strategy engine now sits on top of a genuinely smarter model stack.
Where before there was a single RandomForest, the advanced layer provides:

1. **Cross-validated weighted ENSEMBLE** — RandomForest + GradientBoosting +
   ExtraTrees + Ridge each predict views/completion, blended by out-of-fold
   R² so the model that is actually best on THIS channel dominates.
2. **Stacking meta-learner (DL-inspired)** — treats each base model's
   out-of-fold prediction as a *feature* and fits a ridge meta-model to learn
   the optimal blend (which model to trust when). Learnt coefficients show
   exactly how much weight each base model should get.
3. **IsolationForest viral-outlier detection** — flags 1000+ view spikes so
   the model isn't skewed by anomalies, and so outliers can be studied.
4. **KMeans-on-PCA topic segments** — clusters videos by feature profile and
   recommends which content segment retains best.
5. **Feature importance with correlation fallback** — always returns a ranked
   lever list even when the best model is linear.
6. **Calibrated confidence** (low/medium/high) so the pipeline knows how much
   to trust each prediction.

Wired into `strategy_engine.decide()` as the `intelligence` field (non-blocking:
if the advanced stack fails, the basic lever analysis still runs).

### Test status
- **53 tests pass** (12 intelligence + 41 prior).
- `pyflakes` clean; all modules compile.
