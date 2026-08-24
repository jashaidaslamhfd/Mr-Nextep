# Deep Repair 2026 — All Platforms, High-CTR, Per-Platform Algorithm

Repairs **every already-uploaded video** on YouTube, Facebook and Instagram
against each platform's 2026 algorithm, with a hard focus on **high CTR**
(click-through), and ensures **every future upload** goes out the same way.

---

## Why this exists

Uploaded videos carry older, flat metadata (label-style titles, engagement
bait, cross-posted hashtags). Every 2026 feed ranks on *completion* and
*distribution* signals, and CTR decides whether a Short even gets shown. This
system goes back over the whole catalog and fixes three platform-specific gaps:

| Platform | 2026 algorithm need | What repair applies |
|---|---|---|
| **YouTube** | Hook-driven, curiosity CTR titles; keyword descriptions; no bait | New curiosity titles (`Why Your X — The Real Reason 🤯`), keyword-backed descriptions, bait stripped |
| **Facebook** | UTIS true-interest match, plain topic naming, no cross-posted tags | UTIS-friendly captions, `#shorts`/`#youtube`/`#viral` stripped, watch-through bait removed |
| **Instagram** | Forwardable payoff + niche hashtag clusters, DM-worthy captions | Payoff captions, 3-5 niche hashtags, DM-worthy format |

---

## High-CTR engine (`src/ctr_engine.py`)

A pure, offline module that generates CTR-optimised titles and hook lines:

- **Curiosity gap, not clickbait** — a question the video answers (`Why ... Happens`, `The Real Reason ...`).
- **Power words** (why / real / hidden / secret / actually / every) that lift click-through.
- **One emoji** for visual contrast in the feed (`🧠 ⚡ 🫀 👁️ ...`).
- **Keyword-backed** so search/recommendation still match.
- **Bait-free** — `subscribe`, `smash like`, `tag someone` are stripped (they hurt 2026 completion).
- **Grammar-safe** — avoids "Why Your Your X" duplicates and dangling openings.
- **Mobile budget** — titles capped so they never truncate in the feed.

It also powers **future uploads**: `src/main.py` now builds a high-CTR title in
the SEO phase and keeps it if it passes the CTR health gate — so new videos
never go out with a flat label again.

---

## The repair engine (`scripts/deep_repair_2026.py`)

```
Usage:
  python scripts/deep_repair_2026.py                 # preview (dry run)
  python scripts/deep_repair_2026.py --apply         # apply to ALL videos
  python scripts/deep_repair_2026.py --apply --limit 10
  python scripts/deep_repair_2026.py --apply --youtube-only
  python scripts/deep_repair_2026.py --apply --force  # ignore ledger
```

- Scans `data/video_history.json` for every uploaded video on all 3 platforms.
- Only repairs weak titles (via `validate_title`) or captions with bait —
  already-modern videos are skipped.
- Writes a **repair ledger** (`data/deep_repair_ledger.json`) so we never
  re-touch a video we already fixed (unless `--force`).
- Saves a timestamped report (`data/deep_repair_<ts>.json`).

### GitHub Actions workflow (`.github/workflows/deep_repair_2026.yml`)
- **Manual dispatch** → choose `apply` (edit live) vs default dry-run, `limit`, `force`.
- Runs a **dry-run preview first (always)**, then applies only when you set
  `apply=true`.
- Persists the ledger + report back to the repo.

---

## Wiring

| File | Role |
|---|---|
| `src/ctr_engine.py` | High-CTR title/hook generation + validation (pure, testable). |
| `src/main.py` | Future uploads: applies high-CTR title in the SEO phase. |
| `scripts/deep_repair_2026.py` | Repairs the existing catalog on all 3 platforms. |
| `.github/workflows/deep_repair_2026.yml` | Run repairs in CI. |
| `tests/test_ctr_engine.py` | 9 offline tests. |
| `env.example` | `DEEP_REPAIR_LEDGER_PATH` documented. |

---

## Test status

- **189/189 tests pass** (172 prior + 9 CTR + 8 strategy-engine).
- `pyflakes` clean; all modules compile.

---

## To run the deep repair now

**Local preview (no changes):**
```bash
python scripts/deep_repair_2026.py --limit 5
```

**Apply to everything** (needs real credentials in env):
```bash
python scripts/deep_repair_2026.py --apply
```

**Or from GitHub:** Actions → "MrNextep - Deep Repair 2026" → Run workflow →
set **apply** to `true`.
