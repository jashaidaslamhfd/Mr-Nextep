# MrNextep update-only files

Copy/extract these files into the root of your existing `MrNextep` repository, preserving folders. Existing files in `src/`, `.github/workflows/main.yml`, and `env.example` should be overwritten. The following are new folders/files:

- `.github/workflows/analytics.yml`
- `data/video_history.json`
- `data/upload_state.json`
- `tests/test_core.py`

After copying:

```bash
git add .
git commit -m "Upgrade MrNextep production automation"
git push origin main
```

Required GitHub Secrets:

```text
GROQ_API_KEY
YOUTUBE_API_KEY
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
REFRESH_TOKEN
```

`REFRESH_TOKEN` also needs the `yt-analytics.readonly` scope for analytics workflow.
