# Mr-Nextep — Dark Science Shorts Factory

Mr-Nextep is a US-English YouTube Shorts automation pipeline for dark science, psychology, mystery, AI, and human behavior. It generates a vertical video, validates content and media, checks for duplicate content, and publishes according to the GitHub Actions workflow.

## Publishing behavior

The scheduled production workflow has three UTC slots: **17:00, 22:00, and 01:00 UTC**. These correspond to **10:00 PM, 3:00 AM, and 6:00 AM Pakistan Standard Time (PKT)** respectively; the last slot falls on the following PKT calendar day. US Eastern time shifts with daylight saving time, so use the UTC cron as the source of truth.

The workflow currently sets `YT_PRIVACY_STATUS=public` and `YT_SCHEDULE_PUBLISH=false`. Therefore, a successful scheduled run makes the YouTube upload public immediately; it does **not** create a private upload with a future `publishAt` time. The minimum-publish-gap guard is configured to 3 hours, and production workflow runs are serialized to reduce concurrent state-write races. A manual run can use `dry_run=true` to render/check without publishing.

## Meta publishing

When Meta credentials are configured, the pipeline can publish to Facebook and Instagram. Instagram publishing requires a publicly reachable HTTPS video URL in `PUBLIC_VIDEO_URL`; if required inputs are unavailable, the integration should report a skip/failure rather than claim a successful post. The configured Meta post gap and Instagram processing timeout are workflow settings; verify them against the platform's current API requirements before changing them.

## Retention and originality

The pipeline cannot guarantee views, click-through rate, or audience retention. The agent's script-structure and hook scores are **heuristics only**, not forecasts of actual CTR or retention. Real YouTube Analytics is the source of truth when enough historical data exists. The generator is instructed to use a concrete first-second hook, new information in each scene, a mid-video re-hook, a clear payoff, and a natural loop; caption rendering automatically shrinks long words to fit the mobile-safe width. When the analytics baseline is missing, retention is marked as ungrounded rather than presented as a measured score. Exact and near-duplicate scripts are checked using persistent content history and similarity rules.

The manual `VIDEO_TOPIC` input is a topic brief, not narration: the generated opening hook is preserved instead of being overwritten with a potentially long raw topic headline. Actual performance still depends on the audience, topic fit, delivery, and platform distribution.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp env.example .env
DRY_RUN=true python scripts/preflight.py
DRY_RUN=true python -m src.main
```

Install FFmpeg and ffprobe before running the media pipeline. Keep secrets in environment variables or GitHub Actions Secrets; do not commit `.env` files or API keys.

## Required GitHub Secrets

For production YouTube publishing, configure `GROQ_API_KEY` or `OPENROUTER_API_KEY`, plus `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `REFRESH_TOKEN` (the supported `YT_*` aliases are also accepted for OAuth). Meta secrets are optional unless you intend to publish to those platforms. Never paste secrets into issues, logs, or chat.

## Growth system

The production run ranks the current US trend queue using its source score, real retention from similar past video titles when a sufficient Analytics baseline exists, and novelty against the published history. The resulting `growth_score` is a **ranking heuristic, not a virality prediction**. If the trend queue is unavailable, the existing topic rotation remains the fallback.

Hook styles are assigned as a counterbalanced **between-video experiment** within broad topic clusters: concrete observation, counterintuitive-but-defensible framing, and a specific question. Each upload's experiment metadata is saved with video history so later runs can compare the variants against measured results. This is not a same-video randomized A/B test; topics and distribution can still confound results.

Before rendering, the pipeline checks for duplicate/near-duplicate scripts and requires source URLs when the draft contains numeric or study-attributed claims. A source URL is **not proof that the claim is true**: source content still needs review, and the script must never invent citations. Structural hook scores are not CTR estimates. Real performance is read from the YouTube Analytics API; the existing workflow refreshes the performance cache before generation and warns if that refresh fails.

## Enable YouTube Analytics OAuth

The Analytics API needs a user-authorized refresh token with the read-only Analytics scope. The local helper requests the scopes needed for both uploads and read-only analytics/title lookup. **Do not send OAuth tokens or client secrets in chat, issues, commits, or logs.**

1. In [Google Cloud Console](https://console.cloud.google.com/), select the project used by Mr-Nextep (or create one).
2. Enable **YouTube Analytics API** and **YouTube Data API v3**.
3. Configure the OAuth consent screen. If the app is in Testing mode, add the Google account that owns the channel as a test user.
4. Create an OAuth client ID with application type **Desktop app**. Use the same client ID and client secret already configured for the production workflow, if available.
5. In a local, private checkout, place `GOOGLE_CLIENT_ID=...` and `GOOGLE_CLIENT_SECRET=...` in the ignored `.env` file. Do not commit it.
6. Install dependencies and run:
   ```bash
   python -m pip install -r requirements.txt
   python scripts/authorize_analytics.py
   ```
7. Sign in to the Google account that owns the intended YouTube channel and approve the requested permissions. The helper saves credentials to `.secrets/youtube-oauth.json` with restrictive local permissions; `.secrets/` is ignored by Git.
8. Open that local file and copy **only** its `refresh_token` value into GitHub: repository **Settings → Secrets and variables → Actions → REFRESH_TOKEN**. Keep `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in their existing secrets. Do not paste the token into this conversation.
9. Run the workflow manually and inspect the “Refresh YouTube performance feedback” step. Successful output should report the number of videos with data and the measured median retention when at least eight videos have usable data.
10. Delete the local `.secrets/youtube-oauth.json` after the GitHub secret is updated.

The refresh token must belong to the channel owner and include the requested scopes. If Google reports a 403 or `MissingAnalyticsScope`, repeat the consent flow and update `REFRESH_TOKEN`. OAuth apps left in Testing mode may issue refresh tokens that expire after seven days; check the consent-screen publishing status if the connection stops working.

## Output

The workflow is configured for 1080×1920, 30 fps vertical video, with a target duration of approximately 17.5–23 seconds and eight visual/narration scenes. A failed quality gate should stop publication. Actual output dimensions and duration should be verified from the rendered file in CI.

## Operational security and state

A previously committed `config/.env` reportedly contained a Pixabay API key. Deleting the file does not remove it from Git history. **Revoke/rotate that key and update the GitHub Actions secret**; history cleanup is a separate, coordinated operation because rewriting history changes commit IDs. Runtime state is currently persisted to the repository by the production pipeline; this is operationally simple but adds noisy commits and should eventually move to external storage or a dedicated state branch.

License: MIT.
