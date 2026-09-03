# Mr-Nextep — Dark Science Shorts Factory

Mr-Nextep is a clean US-English YouTube Shorts automation pipeline for dark science, psychology, mystery, and human-behavior topics. It generates a 15–30 second vertical Short, uses fast visual beats with one-word captions, validates the output, rejects duplicate content, and uploads it privately with an optional native YouTube publication time.

When Meta credentials are available, the same video is posted to Facebook first and Instagram after a **10-minute gap**. Instagram requires a publicly reachable HTTPS video URL (`PUBLIC_VIDEO_URL`); if it is unavailable, the pipeline records a safe skip instead of reporting a false post. Facebook and Instagram keep the same US-English content and duration policy as YouTube.

Metadata is now platform-specific: YouTube receives a search-oriented title, tags, and Shorts hashtags; Facebook receives a discussion-oriented title and description; Instagram receives a concise Reels caption with a separate hashtag set. The video itself is shared, but SEO text is not copied across platforms.

## Retention and originality gates

The system cannot honestly guarantee that viewers will watch 70% of every video; actual retention is determined by the audience and YouTube distribution. It does enforce a **70%+ pre-publication retention proxy** based on short length, eight-scene structure, and hook shape. After publication, real YouTube retention is used for strategy decisions. Exact and near-duplicate scripts are rejected with a persistent content fingerprint and token-similarity check.

## Daily schedule

GitHub Actions runs twice daily in the supplied heatmap's peak band. Sunday/Saturday publish at **19:00 and 21:00 PKT**, Monday–Thursday at **20:00 and 22:00 PKT**, and Friday at **21:00 and 23:00 PKT**. Each run starts about one hour before its target, selects a topic, renders one video, and sets the exact YouTube `publishAt` time. The screenshot's PKT display is used as the scheduling reference; the channel target remains US viewers.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp env.example .env
PYTHONPATH=src DRY_RUN=true python src/main.py
```

## Required GitHub Secrets

`GROQ_API_KEY` or `OPENROUTER_API_KEY` may be retained for future LLM script adapters. YouTube upload requires `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `REFRESH_TOKEN`. Existing repository Secrets and Variables are intentionally not modified by this rebuild.

## Output standards

The renderer produces 1080×1920 video at 30fps with narration audio, 8 short visual caption beats, one word at a time, no caption box, and a final duration between 15 and 30 seconds. A failed quality gate stops upload.

## Safety and state

The rebuild deletes old tracked source, documentation, generated models, and `data/` state, but preserves Git history, repository settings, GitHub Secrets, and GitHub Variables. New runtime state is written to `data/content_history.json` and `data/video_history.json`, while generated media remains in `output/`.

License: MIT.
