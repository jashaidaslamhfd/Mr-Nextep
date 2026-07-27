# SKILLOR — Usage Guide (US Body-Science Shorts)

Fully automated body-science YouTube Shorts pipeline. Generates a hook-driven
script (Groq/Llama) → AI images (multi-provider fallback) → US-English voice →
MoviePy render → SEO package → uploads to YouTube (private + auto-publish at a
US peak slot), with optional Facebook/Instagram Reels cross-posting.

> For the **growth/data checklist** (enabling analytics, fixing the Facebook
> token, the realistic growth path), see [`GROWTH_SETUP.md`](GROWTH_SETUP.md).

---

## 1. Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # core pipeline (CPU-safe)
cp env.example .env                       # then fill in your keys
python -m unittest discover -s tests -v   # offline regression tests
```

Optional heavy extras (voice cloning on GPU, screenshot fallback):
`pip install -r requirements-optional.txt`.

## 2. Configure secrets / `.env`

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | ✅ | script generation (Llama) |
| `GOOGLE_CLIENT_ID` | ✅ | YouTube OAuth |
| `GOOGLE_CLIENT_SECRET` | ✅ | YouTube OAuth |
| `REFRESH_TOKEN` | ✅ | YouTube upload (OAuth **user** token) |
| `HF_API_KEY`, `GEMINI_API_KEY`, `DEEPAI_API_KEY`, `MODELSLAB_API_KEY`, `REPLICATE_API_TOKEN`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `AI_HORDE_API_KEY` | optional | more image providers (missing ones are auto-skipped) |
| `FB_ACCESS_TOKEN`, `FB_PAGE_ID`, `FB_UPLOAD_ENABLED=true` | optional | Facebook Reels cross-post (off by default) |
| `INSTAGRAM_USER_ID`, `IG_ACCESS_TOKEN`, `IG_UPLOAD_ENABLED=true` | optional | Instagram Reel cross-post |

> ⚠️ **YouTube needs OAuth USER credentials, NOT a service account** — service
> accounts cannot upload to a normal channel. Get the three Google values with:
> ```bash
> python scripts/get_refresh_token.py
> ```
> The backup is written to `~/.skillor/` (git-ignored), **never** into the repo.

Key US-audience settings already defaulted in `env.example`:
`CONTENT_SERIES=body_glitches`, `TTS_ENGINE=kokoro`, `KOKORO_LANG_CODE=a`,
`KOKORO_VOICE=am_adam`, `YT_PRIVACY_STATUS=private`, `YT_SCHEDULE_PUBLISH=true`,
`QUALITY_APPROVAL_THRESHOLD=60`, `YT_MADE_FOR_KIDS=false`.

## 3. Run the pipeline

`src/main.py` is driven by **environment variables** (no CLI flags):

```bash
# One video (auto-selected body-glitch topic)
python src/main.py

# One video on a specific topic
VIDEO_TOPIC="Why You Hear Your Heartbeat at Night" python src/main.py

# Batch of N videos
BATCH_MODE=true BATCH_COUNT=3 python src/main.py
```

In production this runs on **GitHub Actions** (`.github/workflows/main.yml`),
3×/day, gated to the New York hours `04|11|18` so DST skips don't double-post.

## 4. Publishing schedule (America/New_York)

| Generation run | Auto-publishes (`publishAt`) |
|---|---|
| 04:30 NY | 06:00 NY |
| 11:00 NY | 12:30 NY |
| 18:30 NY | 20:00 NY |

Videos upload **private** with a `publishAt` timestamp; YouTube itself flips
them public at the slot (peak slots used: 12:30 / 20:00 / 21:30 NY). You can
review or delete during the private window. `ENFORCE_POSTING_GAP=true` refuses
runs closer than 2 h to the last post.

## 5. Pipeline phases

1. **Script** — body-glitch topic → Groq/Llama generates an 8-scene,
   hook→suspense→…→payoff→loop-back script; validated (word count, hook,
   arc) and quality-gated.
2. **Images** — 9-provider fallback chain (order = fallback order):
   AI-Horde → Pollinations-flux → Pollinations-turbo → Hugging Face → Gemini →
   DeepAI → ModelsLab → Replicate (missing keys auto-skipped). A channel-wide
   media-hash ledger (`data/media_hash_history.json`) prevents repeats.
3. **Voice** — Chatterbox clone (primary, GPU) with **Kokoro** US-English
   fallback (`TTS_ENGINE=kokoro` on CPU runners); emergency cloud TTS as a last
   resort. Validates output (no empty/NaN/too-short audio).
4. **Video** — MoviePy 1080×1920 render, word-by-word captions, zoom effects,
   optional royalty-free music with voice ducking (`assets/music/`).
5. **Thumbnail + SEO** — 9:16 thumbnail, topic-aware title/tags/description,
   hashtags, pinned-comment seed, SEO score.
6. **Upload** — YouTube (primary, private + `publishAt`), then optional
   Facebook Reels and Instagram Reel (each with its own platform-native caption
   and duplicate-prevention).

## 6. Maintenance & repair tools (`scripts/`)

| Script / Workflow | Purpose |
|---|---|
| `get_refresh_token.py` | obtain YouTube OAuth `REFRESH_TOKEN` |
| `seo_diag.py` (`US SEO Diagnostic`) | read-only channel CTR/AVD/traffic report → `data/seo_diag_<date>.json` |
| `metadata_repair.py` (`Metadata Repair`) | heal titles/tags/descriptions of old uploads (dry-run by default) |
| `fb_token_probe.py` (`FB token probe`) | check which FB token secret has which permissions (read-only) |
| `fb_page_audit.py` / `fb_page_diag.py` / `fb_repair.py` / `fb_page_tuneup.py` | Facebook Page audit & one-shot repairs |
| `channel_audit.py`, `video_audit.py`, `video_repair_us.py`, `yt_dead_cleanup.py` | YouTube channel audits/cleanup |
| `generate_fallback_images.py` | build a local fallback image pool |

## 7. Output files

```
output/
├── final_video.mp4     # rendered Short
├── thumbnail.jpg       # 9:16 thumbnail
├── captions.srt        # closed-caption track (uploaded best-effort)
└── segments/seg_*.wav  # per-scene voiceover
```
Durable channel state lives in `data/` (committed by the bot):
`video_history.json`, `upload_state.json`, `media_hash_history.json`, etc.

## 8. Troubleshooting

- **YouTube upload fails / missing secrets** — confirm `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `REFRESH_TOKEN` are set, and that the refresh token was
  issued for a **user** account with `youtube.upload` (and `youtube.force-ssl`
  for captions/seed-comment). Regenerate with `python scripts/get_refresh_token.py`.
- **Can't see CTR / retention** — the YouTube **Analytics API** must be enabled
  in your Google Cloud project, then run `US SEO Diagnostic`. See `GROWTH_SETUP.md`.
- **Facebook reel views show as unavailable** — your page token needs
  `read_insights` (+ `pages_read_engagement`, `pages_show_list`). Regenerate the
  page token and verify with `FB token probe`. See `GROWTH_SETUP.md`.
- **Image generation fails** — add at least one image-provider key; AI-Horde,
  Pollinations work keyless. A local pool via `generate_fallback_images.py` is
  the last resort.
- **Script rejected / retried** — the quality gate (`QUALITY_APPROVAL_THRESHOLD`,
  default 60) retries weak scripts; check the hook/arc suggestions in the logs.

## 9. Legal / policy

- MIT license. Every upload sets `containsSyntheticMedia: true` (AI disclosure)
  and `selfDeclaredMadeForKids: false`; a science disclaimer is auto-added when
  the medical-accuracy check trips.
- Never commit `assets/voice_reference.wav` or any OAuth/token file (git-ignored).

## 10. Support

1. `README.md` (overview + secret table) · 2. `GROWTH_SETUP.md` (growth/data
   checklist) · 3. `AUTOMATION_REQUIREMENTS.md` · 4. logs in `output/` ·
   5. <https://github.com/jashaidaslamhfd/SKILLOR/issues>

---

**US audience · Body-science Shorts · 3× daily · private + auto-publish at US peak slots**
