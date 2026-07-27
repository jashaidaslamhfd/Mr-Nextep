# SKILLOR — Automated YouTube Shorts Pipeline (US Audience)

Fully automated body-science YouTube Shorts factory, running 3×/day on
GitHub Actions:

```
Body Glitch topic → Llama script (Groq) → AI images (9-provider fallback)
→ Kokoro voice (US English) → MoviePy render → SEO package
→ YouTube upload (private → auto-publishes at next US peak slot)
```

## Production schedule (America/New_York)

Slots were re-tuned on 2026-07-26 from an 87-video time-vs-views analysis.
The single source of truth is `_PUBLISH_SLOTS` in `src/uploader.py`
(mirrored by `PublishScheduler.PEAK_TIMES` in `src/scheduler.py`); the crons
in `.github/workflows/main.yml` simply start generation ~2 h earlier.

| Cron (UTC) | Generation starts (NY) | Auto-publishes (publishAt) | Why |
|---|---|---|---|
| `30 14 * * *` | ~10:30 NY | **12:30 NY** — Lunch Time | avg 231 views, best slot |
| `0 22 * * *` | ~18:00 NY | **20:00 NY** — Evening Prime | avg 261 views (n=11) |
| `30 23 * * *` | ~19:30 NY | **21:30 NY** — Wind-down | experiment (21:00 pair avg 218) |

- **3 runs/day.** Crons are UTC, so during US winter time (EST) the NY-local
  generation times shift one hour earlier; the publish slot itself is always
  computed in `America/New_York`, so the published time never drifts.
- Each upload needs a ≥30 min lead before its `publishAt`; the ~2 h head start
  leaves a comfortable margin.
- If a run slips past its slot, the one-video-per-slot lock in `uploader.py`
  (process set + history ledger + live channel queue) moves it to the **next
  free slot** — two videos can never publish at the same minute.
- Videos upload **private** with YouTube `publishAt`; YouTube itself flips
  them public at the slot — you can review/delete during the private window.
- `ENFORCE_POSTING_GAP=true` refuses runs closer than 2 h to the last post.

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

## What lives in `data/`

| Path | Committed? | What it is |
|---|---|---|
| `data/*.json` | **yes** | durable state the pipeline reads on every run — `upload_state.json`, `video_history.json`, `media_hash_history.json`, `*_done.json` ledgers |
| `data/reports/` | **no** (git-ignored) | dated one-off dumps from `fb_page_audit` / `fb_page_diag` / `fb_page_tuneup` / `seo_diag` / `video_audit`. Nothing reads them back; the workflows upload them as **build artifacts** (90-day retention) instead of committing them, so the repo does not grow forever |

## Required GitHub Secrets

| Secret | Why |
|---|---|
| `GROQ_API_KEY` | script generation (Llama 3.1) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `REFRESH_TOKEN` | YouTube OAuth upload |
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
`KOKORO_VOICE=am_adam`, `TREND_REGION=US`, `CONTENT_SERIES=body_glitches`.
(Anything previously decorative — e.g. `YT_SCHEDULE_PUBLISH` — is now wired
or removed; see `docs/archive/` for the old patch notes.)

## Repo layout

```
src/            pipeline modules (script, images, voice, video, SEO, upload, analytics)
scripts/        maintenance & local tooling
tests/          offline regression tests (run on every CI run)
docs/archive/   historical patch notes
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
