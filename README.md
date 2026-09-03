# Mr-Nextep — Dark Science Shorts Factory

Mr-Nextep is a clean US-English YouTube Shorts automation pipeline for dark science, psychology, mystery, and human-behavior topics. It generates a 15–30 second vertical Short, uses fast visual beats with one-word captions, validates the output, and uploads it privately with an optional native YouTube publication time.

## Daily schedule

GitHub Actions runs twice daily at **16:40 UTC** and **22:10 UTC**. These are approximately **12:40 PM and 6:10 PM America/New_York**, with daylight-saving changes handled by the publication timestamp strategy. Each scheduled run selects a topic, renders one video, and schedules it approximately 15 minutes after upload. This review window can be changed in `src/youtube.py`.

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

The renderer produces 1080×1920 video at 30fps with narration audio, 8 short visual caption beats, one centered word at a time, no caption box, and a final duration between 15 and 30 seconds. A failed quality gate stops upload.

## Safety and state

The rebuild deletes old tracked source, documentation, generated models, and `data/` state, but preserves Git history, repository settings, GitHub Secrets, and GitHub Variables. New runtime state is written to `data/video_history.json`, while generated media remains in `output/`.

License: MIT.
