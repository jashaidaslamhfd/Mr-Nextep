# Workflow updates — APPLIED ✅

These changes are **already in the branch**. This folder is kept as the record
of what changed and why, plus a recovery copy if a workflow ever needs to be
restored by hand.

| File | Status |
|---|---|
| `.github/workflows/growth_loop.yml` | ✅ installed (copy here: [`growth_loop.yml`](growth_loop.yml)) |
| `.github/workflows/main.yml` | ✅ patched ([`main.yml.patch`](main.yml.patch)) |
| `.github/workflows/ci.yml` | ✅ patched ([`ci.yml.patch`](ci.yml.patch)) |

Six tests in `tests/test_algorithm_policy.py::DeploymentWiringTests` assert all
three stay applied, so a future revert fails CI instead of silently returning
the channel to the old strategy.

---

## 1. Growth Loop workflow — added

`.github/workflows/growth_loop.yml` runs daily at 09:20 UTC (05:20 New York),
**before** the day's first generation run at 14:40 UTC — so each day's videos
are made using the previous day's lesson rather than a day-old one.

It reads real numbers from YouTube, Facebook and Instagram, normalises them
into one comparable store, learns which slots / topic pillars / hook frames
actually retain viewers, and writes both the machine-readable weights the
pipeline consumes and `docs/GROWTH_REPORT.md` for you.

It is **read-only** against every platform: it cannot publish, edit or delete.

> Until the analytics permissions in [`../../GROWTH_SETUP.md`](../../GROWTH_SETUP.md)
> §2 are granted, this workflow runs successfully and reports ⚪ `no_data` per
> platform, naming the exact missing permission. It never fails loudly for a
> reason you cannot act on.

## 2. Generation workflow — patched

**Removed** (these pinned the strategy this release replaced):

```yaml
TARGET_MIN_SECONDS: "40"
TARGET_MAX_SECONDS: "55"
MIN_HOOK_SCORE: "85"
MAX_HOOK_SECONDS: "5.0"
```

**Added:**

```yaml
META_CUT_ENABLED: "true"
SPOKEN_CTA_MODE: "loop"
GROWTH_STATE_PATH: data/growth_state.json
PLATFORM_METRICS_PATH: data/platform_metrics.json
```

### Why each removed line had to go

| Removed | Why |
|---|---|
| `TARGET_MIN/MAX_SECONDS: 40/55` | Env vars beat code, so these silently overrode the policy — the exact drift `algorithm_policy` exists to end. YouTube grades a 30-60s Short on ~50% completion and Meta on ~72%; the 36s master and 26s Meta cut are sized against those gates. |
| `MIN_HOOK_SCORE: "85"` | **The dangerous one.** Calibrated for the previous hook scorer. Against the rewritten one only ~3 of this channel's 21 published hooks clear it — nearly every run would have exhausted its retries and skipped the upload. |
| `MAX_HOOK_SECONDS: "5.0"` | Three seconds of slack on the single most decisive moment of the video. The budget now comes from the tightest enabled platform. |

## 3. CI — patched

`branches: [main]` → `branches: ["**"]` plus `pull_request`, pip caching,
`tests/` added to the compile gate, and a step that prints the active policy
into the run log so a strategy change is visible in the CI diff.

Guarding only `main` meant a branch's first test signal arrived *after* merge —
by which point the scheduled pipeline already depended on it.

---

## Defence in depth: the code does not trust the workflow

`algorithm_policy.env_override()` recognises the four retired values above and
ignores them in favour of the policy, logging one warning per run:

```
WARNING - MIN_HOOK_SCORE=85 is a retired setting from the pre-2026.07 strategy
and is being IGNORED; using the policy value instead.
```

This stays in place even though the workflow is now fixed, because workflow
files get reverted, hand-edited and restored from old branches. Any *other*
value is honoured normally, so deliberate experiments still work:

```yaml
TARGET_MAX_SECONDS: "48"   # honoured — a real experiment
MIN_HOOK_SCORE: "90"       # honoured — a deliberately stricter gate
```

---

## Verifying

1. **Actions → SKILLOR — Growth Loop → Run workflow.** It should finish green
   and commit `docs/GROWTH_REPORT.md`. Any ⚪ `no_data` platform names its
   missing permission.
2. **Check a generation run's log** for the phrase `retired setting`. It should
   no longer appear.
