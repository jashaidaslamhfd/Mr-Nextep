# Workflow updates — apply these by hand

The automation that pushed this branch does not hold GitHub's `workflows`
permission, so it cannot create or edit anything under `.github/workflows/`.
The code changes are pushed; these three workflow changes are not.

**Nothing here is urgent.** The code was written to work correctly against the
*current* workflow — `src/algorithm_policy.py` detects the retired settings the
existing `main.yml` pins and ignores them, logging a warning per run. Applying
these updates removes the warnings and turns on the daily learning loop.

Do them in this order.

---

## 1. Add the Growth Loop workflow (the one that matters)

Without this, nothing ever reads your real performance data, so the system
cannot tune itself — it will keep publishing on its default settings forever.

Create `.github/workflows/growth_loop.yml` with the contents of
[`growth_loop.yml`](growth_loop.yml) in this folder.

Via the GitHub web UI: **Add file → Create new file**, name it
`.github/workflows/growth_loop.yml`, paste, commit.

It runs daily at 09:20 UTC (05:20 New York) — before the day's first
generation run, so each day's videos use the previous day's lesson. It is
read-only against every platform: it cannot publish, edit or delete anything.

---

## 2. Update the generation workflow

Apply [`main.yml.patch`](main.yml.patch), or make these edits by hand in
`.github/workflows/main.yml`:

**Remove these four lines** (they pin the strategy this release replaced):

```yaml
TARGET_MIN_SECONDS: "40"
TARGET_MAX_SECONDS: "55"
MIN_HOOK_SCORE: "85"
MAX_HOOK_SECONDS: "5.0"
```

**Add these four** in the same env block:

```yaml
META_CUT_ENABLED: "true"
SPOKEN_CTA_MODE: "loop"
GROWTH_STATE_PATH: data/growth_state.json
PLATFORM_METRICS_PATH: data/platform_metrics.json
```

### Why each removed line has to go

| Removed | Why |
|---|---|
| `TARGET_MIN/MAX_SECONDS: 40/55` | Targets the old length strategy. YouTube grades a 30-60s Short on ~50% completion and Meta on ~72%; the policy's 36s master and 26s Meta cut are sized against those gates. |
| `MIN_HOOK_SCORE: "85"` | **The dangerous one.** It was calibrated for the previous hook scorer. Against the rewritten one, only ~3 of this channel's 21 published hooks would clear it — nearly every run would exhaust its retries and skip the upload. |
| `MAX_HOOK_SECONDS: "5.0"` | Three seconds of slack on the single most decisive moment of the video. The budget now comes from the tightest enabled platform. |

Until you remove them the pipeline still behaves correctly — the guard in
`algorithm_policy.env_override()` ignores exactly these values and logs:

```
WARNING - MIN_HOOK_SCORE=85 is a retired setting from the pre-2026.07 strategy
and is being IGNORED; using the policy value instead.
```

Any *other* value is still honoured, so deliberate experiments (say
`TARGET_MAX_SECONDS: "48"`) work normally.

---

## 3. Widen CI

Apply [`ci.yml.patch`](ci.yml.patch). It changes `branches: [main]` to
`branches: ["**"]` plus `pull_request`, caches pip, compiles `tests/` too, and
prints the active policy into the run log.

Guarding only `main` meant a branch's first test signal arrived *after* merge —
by which point the scheduled pipeline already depended on it.

---

## Verifying it worked

Run **Actions → SKILLOR — Growth Loop** manually. On a healthy setup it writes
`docs/GROWTH_REPORT.md` and commits it. If a platform shows ⚪ `no_data`, the
report names the exact missing permission — see [`../../GROWTH_SETUP.md`](../../GROWTH_SETUP.md)
section 2.

Then check any generation run's log for the phrase `retired setting`. Once it
no longer appears, step 2 is complete.
