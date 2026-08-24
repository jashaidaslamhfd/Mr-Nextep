# Product Requirements Document — MrNextep YouTube/Shorts Automation System
**Version:** 1.0 | **Date:** July 2026 | **Owner:** [Your Name] | **Dev:** [Developer Name]

## 0. Current Stack (as of existing repo)
- **Language/Runtime:** Python 3.10, orchestrated via GitHub Actions cron (3x/day)
- **Script Generation:** Groq API (`openai/gpt-oss-20b`)
- **Voice:** Kokoro TTS (local, open-source, American English)
- **Video Assembly:** MoviePy + PIL (Ken Burns effect, word-by-word captions)
- **Image Sourcing:** 8-provider fallback chain (Pollinations, HuggingFace, Gemini, DeepAI, Craiyon, ModelsLab, Replicate)
- **Publishing:** YouTube Data API v3 (OAuth), Facebook Graph API v19 (Reels 3-phase upload)
- **Storage:** Flat JSON file (`output/video_history.json`) — no database

This PRD is written against that stack. Each section below states **Status** so the developer knows what to build vs. extend.

---

## 1. AI Topic Research
**Status: ❌ Not built** (current: static 10-item hardcoded list in `niche_strategy.py`)

Requirements:
- Pull trending topics via YouTube Data API (`search.list` + `videos.list` with `chart=mostPopular` per niche category)
- Analyze YouTube autosuggest (unofficial endpoint or a suggestion-scraping library) for keyword demand
- Competitor channel scan (see Section 10) feeds topic candidates
- Score each topic 0-100 on: recency, search volume proxy, competition density, niche fit
- Maintain a rolling topic pool of 100+ so repeats don't happen inside a 30-day window

**Acceptance criteria:** System never repeats an exact topic within 30 days; topic pool auto-replenishes weekly.

## 2. AI SEO Generator
**Status: 🟡 Partial** — `niche_strategy.generate_seo_tags()` exists but is a static tag dictionary, not AI-generated per video. Description builder exists in `uploader.py`. No title A/B options, no chapters, no pinned comment.

Requirements:
- 10-20 AI-generated title candidates per video (LLM call, not template)
- SEO description auto-written per video (not just hook+CTA concatenation)
- Chapters (`00:00 Hook`, `00:08 Reveal`...) for videos >3 min
- Auto-generated pinned comment (engagement seed, factual — no bait)

**Acceptance criteria:** Every upload has unique title/description generated fresh from that video's script content, not from a shared template.

## 3. Thumbnail Generator
**Status: 🟡 Partial** — `generate_thumbnail()` in `video_editor.py` makes ONE thumbnail (image crop + title text). No variations, no A/B testing, no niche presets.

Requirements:
- 3-5 thumbnail concept variations per video
- Preset style templates per niche (Dark/Mystery, Finance, Motivation, etc.)
- Large mobile-safe text (test render at 120x90px preview size — must be legible)
- Manual override: allow picking a winning thumbnail after upload based on early CTR

## 4. Script Generator
**Status: 🟡 Partial, Shorts-only** — `script_generator.py` is hardcoded to 40-55 second scripts (110-150 words). No length options.

Requirements:
- Configurable target length: 8 min / 10 min / 15 min (long-form) in addition to existing Shorts mode
- Structure for long-form: hook → storytelling → real-world examples → transitions → CTA ending
- Scene count and pacing should scale with target length, not stay fixed at 6-8 scenes

**Note:** This is a meaningfully larger lift than it sounds — long-form scripting, TTS pacing, and video assembly (currently tuned for 40-55s) all need separate code paths from Shorts.

## 5. Retention Optimizer
**Status: ❌ Not built**

Requirements:
- LLM pass over generated script to flag/insert: curiosity gaps, pattern interrupts (visual or tonal shift every ~15s), suggested B-roll per scene
- Output should annotate the script (not just approve/reject like current `quality_checker.py`), giving the editor concrete suggestions

**Note:** `quality_checker.py` already scores hook/engagement/pacing/CTA — this is the natural place to extend into *suggestions* rather than just a pass/fail score.

## 6. Analytics Dashboard
**Status: ❌ Not built** — `video_history.json` only stores title/timestamp/upload success. No performance data pulled back from YouTube.

Requirements:
- Pull CTR, Average View Duration, Audience Retention curve, Returning Viewers, Subscribers-per-video via YouTube Analytics API (`youtubeAnalytics/v2`)
- Store in a proper database (flat JSON won't scale past a few hundred videos) — recommend SQLite to start
- Simple dashboard (even a generated HTML/Streamlit page is fine at this stage)
- Rule-based recommendations initially (e.g., "CTR <4% → flag thumbnail for revision"), AI-generated recommendations later

**Acceptance criteria:** Within 48h of upload, system pulls real performance metrics and logs them against that video's ID.

## 7. Multi-Platform Publishing
**Status: 🟡 Partial** — YouTube + Facebook Reels both work (`uploader.py`). No Instagram Reels, no TikTok.

Requirements:
- Instagram Reels via Graph API (needs Instagram Business Account linked to the FB Page — mostly reuses existing FB app credentials)
- TikTok via TikTok Content Posting API (separate app review/approval process — budget extra lead time)
- Auto aspect-ratio variants: current 1080x1920 (9:16) already correct for all three platforms, so this is mostly a metadata/caption-format difference, not a re-encode

## 8. Shorts Generator (from long-form)
**Status: ❌ Not built** — depends on Section 4 (long-form scripts) existing first.

Requirements:
- Given a long-form video + transcript, auto-identify 10-20 clip-worthy segments (highest information density / emotional peak per the retention optimizer's markers)
- Auto vertical crop (9:16) from 16:9 source
- Reuse existing caption/word-by-word rendering pipeline (`video_editor.py` already has this — good foundation)

## 9. AI Voice
**Status: 🟡 Partial** — Kokoro TTS gives multiple voices/accents (it ships several `am_*`/`af_*`/etc. voice presets) but code hardcodes one voice (`am_adam`) with no selection logic or emotion control.

Requirements:
- Expose voice selection (male/female/accent) as a per-niche or per-video config instead of hardcoded
- Emotion/tone control — Kokoro has limited native emotion support, so this may require prompt-level SSML-style text conditioning (e.g., punctuation/pacing tricks already partially done in `add_mystery_pauses()`) rather than true emotion parameters

## 10. Competitor Intelligence
**Status: ❌ Not built**

Requirements:
- Input: competitor channel URL/ID
- Pull via YouTube Data API: top videos by views, average views, upload frequency, title patterns, thumbnail styles (visual analysis via image model), common keywords/tags
- Feed results into Topic Research (Section 1) as candidate signals

## 11. Content Calendar
**Status: ❌ Not built** — currently topic selection is random-per-run with no forward planning.

Requirements:
- AI-suggested topics for next 30 days, each with priority score (from Topic Research scoring)
- Best upload date/time suggestions (extend existing `scheduler.py` — it already has solid EST peak-time logic, just needs the calendar layer on top)

## 12. AI Chat Assistant
**Status: ❌ Not built**

Requirements:
- Single prompt → full package: topic, title, thumbnail text, full script, description, tags, hashtags, pinned comment, Shorts ideas
- This is essentially an orchestration layer chaining Sections 2-5 + 8 into one LLM-driven flow — build this last, once the underlying generators exist independently

---

## Explicit Non-Goals / Guardrails
To keep this system compliant and sustainable long-term, it must **not**:
- Use engagement bait, fake views/watch-time, bot subscribers, or comment/like automation
- Bypass platform spam/duplicate-content detection (the existing `anti_spam.py` should stay a *quality gate*, not be weakened to push more uploads through)
- Republish near-duplicate content to inflate upload frequency

Growth strategy should rely on genuine topic variety, accurate SEO, and real audience-retention data — not volume or manipulation.

---

## Suggested Build Priority
| Phase | Sections | Why |
|---|---|---|
| P0 (foundation) | 1 (Topic Research), 6 (Analytics Dashboard) | Without real performance data + a real topic pipeline, every other feature is guessing |
| P1 | 2 (SEO), 3 (Thumbnails), 5 (Retention Optimizer) | Directly improve current Shorts pipeline's CTR/retention |
| P2 | 4 (Long-form scripts), 8 (Shorts-from-long-form), 7 (IG/TikTok) | New format/platform expansion |
| P3 | 10 (Competitor Intel), 11 (Content Calendar), 12 (Chat Assistant) | Orchestration/planning layer on top of P0-P2 |

---

## Open Questions for Developer Scoping
1. Analytics Dashboard: acceptable to start with SQLite + a simple generated report, or is a live web dashboard required from day one?
2. Long-form scripts (Section 4): confirm this is in scope now, or should Shorts-only be optimized first (per this PRD's own priority order)?
3. TikTok: app approval timelines can run 1-4 weeks — flag this early if Section 7 is a near-term priority.
