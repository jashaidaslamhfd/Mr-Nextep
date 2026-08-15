# MrNextep — Autonomous AI YouTube Shorts Factory (US Audience)

Fully automated dark-science short-form factory for **YouTube, Facebook and
Instagram**, running on GitHub Actions and calibrated toward million-view
breakouts — the staged plan is in
[`docs/MILLION_ROADMAP.md`](docs/MILLION_ROADMAP.md).

```
Dark-mystery topic → Llama script (Groq) → AI images (9-provider fallback)
→ Kokoro voice (US English) → MoviePy render
→ DUAL CUT:  ~24s master  → YouTube Short       (50% completion gate target)
             ~14s edit    → Facebook + Instagram Reels (72% gate target)
→ per-platform captions → scheduled publish at measured peak slots
→ next morning: read all 3 platforms' real numbers and re-tune itself
```

**2026-08 retention-first release (`2026.08-fix2`)**: the YouTube master cut
moved from the old 36/33s toward 24s because the channel's measured 10–14s
watch time could never clear the 50% completion gate at the old length (median
completion was 32%). The emoji-title machine template was removed to escape
2026 template-detection demotion, the LLM prompt was rebuilt around
stakes-first hooks and loop-back endings, and the niche was consolidated on
dark-mystery in both the workflow and the topic strategy.

## What makes it a system rather than a scheduler

`src/algorithm_policy.py` holds the 2026 ranking rules for all three platforms
in one place — durations, completion gates, hook budgets, hashtag limits, bait
vocabulary — and **every other module derives from it**. Change the strategy in
one file and the writer, renderer, cuts, captions, validator and tests all
follow.

`src/growth_engine.py` closes the loop: it reads real completion data from
every platform, normalises it against each platform's own gate, and re-weights
publish slots, topic pillars, hook frames and cadence for the next run.

Full reasoning: [`docs/ALGORITHM_PLAYBOOK.md`](docs/ALGORITHM_PLAYBOOK.md) ·
Operator guide: [`GROWTH_SETUP.md`](GROWTH_SETUP.md)

## Production schedule (America/New_York)

| Run | Publishes | Purpose |
|---|---|---|
| 05:20 NY | — | **Learning run**: read all 3 platforms, re-tune today |
| 10:40 NY | 12:30 NY | lunch slot (best measured on this channel) |
| 16:40 NY | 18:30 NY | early evening |
| 18:10 NY | 20:00 NY | evening prime |

- The learning run happens **before** the day's first video, so each day's
  uploads use the previous day's lesson.
- Cadence is **retention-gated, and the gate is enforced**: 3/day only when at
  least two platforms clear their completion gates, 2/day while below gate,
  1/day when a platform is critical. Volume on a low-retention format teaches
  the feed to stop showing the channel (and is what YouTube's
  inauthentic-content policy targets). `DISABLE_CADENCE_3=true` restores raw
  operator control — not recommended while any platform is under its gate.
  Current status, the free growth plan and the million-view roadmap:
  [`docs/FREE_GROWTH_PLAN.md`](docs/FREE_GROWTH_PLAN.md) ·
  [`docs/MILLION_ROADMAP.md`](docs/MILLION_ROADMAP.md).
- Videos upload **private** with `publishAt`; YouTube flips them public at the
  slot, so there is a review window.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # core pipeline (CPU-safe)
cp env.example .env                     # fill in keys (see table below)
python -m unittest discover -s tests -v # offline regression tests
python src/main.py                      # run one video locally
```

Voice cloning (GPU only) and the screenshot fallback are **optional** extras:
`pip install -r requirements-optional.txt`.

## Required GitHub Secrets

| Secret | Why |
|---|---|
| `GROQ_API_KEY` | script generation (Llama 3.1) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `REFRESH_TOKEN` | YouTube OAuth upload. The refresh token also needs **`yt-analytics.readonly`** for the learning loop — see `GROWTH_SETUP.md` |
| `FACEBOOK_ACCESS_TOKEN` / `FACEBOOK_PAGE_ID` / `INSTAGRAM_USER_ID` | Reels publishing + insights. The page token needs `read_insights`, `pages_read_engagement`, `instagram_manage_insights` |
| Optional: `HF_API_KEY`, `GEMINI_API_KEY`, `DEEPAI_API_KEY`, `MODELSLAB_API_KEY`, `REPLICATE_API_TOKEN`, `AI_HORDE_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `YOUTUBE_API_KEY`, Reddit pair | more image providers / trend sources — system auto-skips missing ones |

The workflow **fails fast** (in seconds) if a required secret is missing,
instead of burning ~60 min of compute first. Get secrets via
`python scripts/get_refresh_token.py` (backup goes to `~/.skillor/`,
**never** into this repo — token files are git-ignored).

## Image generation — 9-provider fallback chain

`src/image_providers.py` `PROVIDER_REGISTRY` (order = fallback order):

1. AI-Horde (no key) · 2. Pollinations-flux (no key) · 3. Pollinations-turbo
(no key) · 4. Hugging Face · 5. Gemini · 6. DeepAI · 7. ModelsLab ·
8. Replicate · (9th reserved for your next free-tier key — copy any
`gen_*` function and add one registry line).

Honest note: free tiers change every few months. The registry pattern lets
you add any new free key in ~5 minutes instead of promising impossible
"50 always-free providers". A channel-wide media hash ledger
(`data/media_hash_history.json`) prevents any image/clip from ever repeating
across videos. Local pool: `python scripts/generate_fallback_images.py`
(the pool dir is git-ignored by design — it's regenerable on any machine).

## Config that actually works

Every variable in `env.example` is **read by code** — verified in CI tests.
Key US-audience settings: `TTS_ENGINE=kokoro`, `KOKORO_LANG_CODE=a`,
`KOKORO_VOICE=am_adam`, `TREND_REGION=US`, `CONTENT_SERIES=dark_mystery`,
`TITLE_EMOJI_OFF=true` (clean curiosity-question titles — the old emoji
template coincides with the channel's template-demotion period).

Video length and hook budgets are **not** env vars any more. They live in
`src/algorithm_policy.py`, derived from each platform's completion gate and the
measured speech rate. `TARGET_MIN_SECONDS` / `TARGET_MAX_SECONDS` still work as
a per-run override for experiments, but the workflow deliberately leaves them
unset so strategy lives in one reviewable Python file instead of in YAML.

New switches:

| Variable | Default | Effect |
|---|---|---|
| `META_CUT_ENABLED` | `true` | build the shorter Facebook/Instagram edit |
| `SPOKEN_CTA_MODE` | `loop` | `loop` = end on the loop-back line; `cta` = restore the spoken outro |
| `GROWTH_STATE_PATH` | `data/growth_state.json` | learned weights the pipeline reads |

## Repo layout

```
src/
  algorithm_policy.py   2026 ranking rules for all 3 platforms — the source of truth
  growth_engine.py      learns from real metrics; re-weights slots/topics/hooks/cadence
  platform_metrics.py   normalised YouTube + Facebook + Instagram performance
  platform_cuts.py      dual-cut editor (YouTube master vs. shorter Meta edit)
  platform_captions.py  one caption per platform, written for its own algorithm
  (script, images, voice, video, SEO, upload, analytics modules as before)
scripts/        maintenance, diagnostics, and scripts/growth_report.py
tests/          offline regression tests (117, run on every CI run)
docs/           ALGORITHM_PLAYBOOK.md (why) + GROWTH_REPORT.md (generated daily)
data/           durable channel state (committed by skillor-bot)
```

## Legal / policy

- `MIT` license — see `LICENSE`.
- Every upload sets `containsSyntheticMedia: true` (YouTube AI disclosure),
  `selfDeclaredMadeForKids: false`, and auto-generates a science disclaimer
  when the medical-accuracy check trips.
- Music in `assets/music/` — see `assets/music/ATTRIBUTION.md` and verify
  each track's license before monetizing.
- Never commit `assets/voice_reference.wav` or any OAuth/token file
  (git-ignored). Rotate anything that has ever been pushed by accident.


## Storage Optimization
- Diagnostic dumps and audit logs are retained as 90-day GitHub Actions artifacts instead of inflating git repository history.
