# Workflow updates — optional polish

**The system is fully working without any of this.** The daily learning loop
runs from the already-deployed `analytics.yml`, and every new behaviour is on
by default. This folder holds three optional improvements plus the reasoning
behind them.

## Why these are separate

GitHub blocks apps without the `workflows` permission from creating or editing
anything under `.github/workflows/`. The automation maintaining this repo does
not hold that permission — this is a GitHub security rule, not a missing token,
and it cannot be worked around from inside a commit.

So rather than leave the most valuable part of the release behind a manual
step it might never get, **the learning loop was wired into a workflow that is
already deployed**:

```
.github/workflows/analytics.yml   (already live, daily at 09:20 UTC)
        └── runs src/analytics_updater.py
                ├── stage 1  YouTube history      (its original job)
                ├── stage 2  all 3 platforms  →  data/platform_metrics.json
                └── stage 3  learn            →  data/growth_state.json
                                              →  docs/GROWTH_REPORT.md
```

That workflow already had the right schedule (before the day's first
generation run at 14:40 UTC), the right secrets, and a `git add data/` step.
Six tests in `DeploymentWiringTests` pin this arrangement so it cannot be
quietly undone.

---

## What is still worth applying by hand

| # | Change | Value |
|---|---|---|
| 1 | [`main.yml.patch`](main.yml.patch) | Removes four retired env vars. **Cosmetic only** — the code already ignores them, but each run currently logs four warnings. |
| 2 | [`ci.yml.patch`](ci.yml.patch) | Runs tests on every branch and PR, not just `main`. |
| 3 | [`growth_loop.yml`](growth_loop.yml) | A dedicated learning workflow. **Not needed** — only useful if you later want learning on a different schedule from analytics. |

### 1. Generation workflow (recommended)

In `.github/workflows/main.yml`, delete these four lines:

```yaml
TARGET_MIN_SECONDS: "40"
TARGET_MAX_SECONDS: "55"
MIN_HOOK_SCORE: "85"
MAX_HOOK_SECONDS: "5.0"
```

and add:

```yaml
META_CUT_ENABLED: "true"
SPOKEN_CTA_MODE: "loop"
GROWTH_STATE_PATH: data/growth_state.json
PLATFORM_METRICS_PATH: data/platform_metrics.json
```

The four additions only make the defaults explicit — `main.py` already uses
these values when the variables are absent.

**Why the deletions matter.** Env vars beat code, and these belong to the
strategy this release replaced:

| Variable | Problem |
|---|---|
| `TARGET_MIN/MAX_SECONDS: 40/55` | Would override the 30-42s policy — the exact drift `algorithm_policy` exists to prevent. |
| `MIN_HOOK_SCORE: "85"` | Calibrated for the previous hook scorer. Against the rewritten one only ~3 of this channel's 21 published hooks clear it, so nearly every run would exhaust its retries and skip the upload. |
| `MAX_HOOK_SECONDS: "5.0"` | Three seconds of slack on the most decisive moment of the video. |

Until they are removed, `algorithm_policy.env_override()` refuses these exact
values and logs once per run:

```
WARNING - MIN_HOOK_SCORE=85 is a retired setting from the pre-2026.07 strategy
and is being IGNORED; using the policy value instead.
```

That guard stays permanently, even after you apply the patch — workflow files
get reverted, hand-edited, and restored from old branches. Any *other* value is
honoured, so real experiments still work:

```yaml
TARGET_MAX_SECONDS: "48"   # honoured
MIN_HOOK_SCORE: "90"       # honoured
```

### 2. CI (recommended)

`branches: [main]` → `branches: ["**"]` plus `pull_request`. Guarding only
`main` meant a branch's first test signal arrived *after* merge, when the
scheduled pipeline already depended on it.

### 3. Dedicated learning workflow (skip unless needed)

Only add [`growth_loop.yml`](growth_loop.yml) if you want the learning loop on
a different schedule from the analytics run. Doing so would run the same work
twice a day, harmlessly but pointlessly.

---

## How to apply

Easiest is the GitHub web UI: open the file, click the pencil, make the edit,
commit. Or locally:

```bash
git apply docs/workflow_updates/main.yml.patch
git apply docs/workflow_updates/ci.yml.patch
```

## Verifying

1. **Actions → MrNextep - YouTube Analytics Learning → Run workflow.** It
   should finish green and commit `docs/GROWTH_REPORT.md`. Any ⚪ `no_data`
   platform names its own missing permission — see
   [`../../GROWTH_SETUP.md`](../../GROWTH_SETUP.md) §2.
2. **Check a generation run's log** for `retired setting`. Once patch 1 is
   applied, it stops appearing.
