# MrNextep Shorts Reliability Patch

## Replaced/changed
- `src/script_generator.py` — 90–115 words and 6–8 scenes.
- `src/voice_generator.py` — natural 0.98 tempo and configurable private reference path.
- `src/image_generator.py` — decoded-image checks, black/blank rejection, duplicate rejection, screenshot fallback disabled by default.
- `src/video_editor.py` — removed broken flash timeline, strict 55-second gate, 1080×1920/yuv420p output.
- `src/main.py` — narration and rendered-video quality gates; failed uploads are not recorded as posted.
- `.github/workflows/main.yml` — pip cache, missing provider secrets, diagnostic artifacts.
- `env.example` — correct OAuth and Shorts settings.
- `.gitignore` — prevents committing private voice reference and generated output.

## Added
- `src/media_validator.py` — validates images and final video with Pillow/ffprobe.

## Important setup
1. Copy `env.example` to `.env` locally or configure matching GitHub Secrets.
2. Put your consented voice file at `assets/voice_reference.wav` locally. It is deliberately excluded from this package/repository.
3. Keep `ENABLE_SCREENSHOT_FALLBACK=false` to avoid irrelevant/copyright-risk webpage screenshots.
4. GitHub's standard runner is CPU-only. Chatterbox may fall back to Kokoro or time out; a GPU runner is recommended for dependable cloning.
5. This patch improves originality and quality but does not guarantee views or monetization. Follow YouTube altered/synthetic-content disclosure rules where applicable.
