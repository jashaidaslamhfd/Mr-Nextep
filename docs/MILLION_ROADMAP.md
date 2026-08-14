# Million-View Roadmap — MrNextep (2026-08-14)

This document turns the channel's own measured data into a staged path from the current ~30,000 total views to a seven-figure per-video outcome. Every stage below rests on evidence already in `data/video_history.json` and `data/platform_metrics.json`, not on generic advice.

## Where the channel stands today

| Metric | YouTube | Facebook | Instagram |
|---|---|---|---|
| Measured completion | 32% | 19% | 24% |
| Feed push gate | 50% | 72% | 70% |
| Average watch time | 10–14s | 2.6–7.5s | 2.6–7.5s |
| Median video views | ~156 | low | low |

The feed does not push videos whose viewers abandon them, and the old 33s master cut made the gate arithmetically unreachable: 12s of watch on a 33s video is 36% completion, which fails the 50% gate every time. The 2026-08-fix2 policy change (YouTube ideal 33s → 24s, emoji title template off, retention-first prompt) exists to make the gate reachable at the channel's measured watch time.

## Stage 1 — Reach the gates (weeks 1–4)

The immediate job is to make 50% YouTube completion routine. With the new 24s cut, the same 12s of watch becomes 50% — exactly the gate line. Because the ML lever analysis ranks `duration_seconds` (importance 0.343) far above every other lever, shorter cuts are the highest-leverage free change available.

Actions already shipped in code: YT duration policy (18–24–30s), `TITLE_EMOJI_OFF=true` (template demotion removed), retention-first LLM prompt with stakes in sentence one and a loop-back final scene, and niche consolidated on `dark_mystery` in both the workflow and the topic strategy.

What must still happen operationally: the next ~15 uploads are measured against the gates. If completion climbs toward 50%, the feed widens distribution automatically. If it does not, the fallback is an 18s cut (12s/18s = 67% completion at unchanged watch time).

## Stage 2 — Rebuild CTR with variety (weeks 4–8)

Completion gets a video pushed; click-through decides how wide. The channel's CTR loop collected zero usable records because the analytics scopes were missing. Meta scopes are now added on the user's side; the remaining item is adding `yt-analytics.readonly` to the Google Cloud OAuth consent screen (one-time, ~5 minutes; see `docs/GROWTH_SETUP.md`).

Title variety matters: titles with 5–8 word curiosity loops already earn 38+ views versus 2–38 on the plain 1–3 word labels. The top videos on the channel (Baby Memory Lost 1,122 · Brain Freeze 990 · Cold Hands 907) all follow the curiosity-loop shape, confirming the data.

## Stage 3 — The compounding zone (months 2–6)

Shorts that clear the gate accumulate views for weeks, not hours. Three behaviours compound here. First, keep one niche (dark body/mind facts) so the audience graph stays coherent — the previous drift between body glitches and dark mystery split the graph. Second, protect the first frame: burn the payoff into second one on the thumbnail and caption alike, because decision time is 2.2s on YouTube. Third, do not chase volume past three videos a day — the growth engine already throttles cadence on poor retention, and over-publishing losing formats is precisely what taught the feed to undervalue the channel.

## Stage 4 — Seven figures (months 6–12)

A single Short crossing a million views requires the full stack working at once: 50%+ completion, above-median CTR, a topic with a broad "everybody has felt this" anchor (the channel's own best performers are universal sensations — memory, cold hands, yawning — not obscure phenomena), and a launch window where Meta cross-posts amplify the YouTube short. The realistic mechanics: one breakout topic per ~30 uploads at this stage, each breakout retraining the hook-weight model (`data/growth_state.json`), which biases the next batch toward what is measurably holding viewers.

| Milestone | Trigger (from channel data) |
|---|---|
| Consistent 1K+ views/video | YouTube completion ≥ 50% for 2 consecutive weeks |
| First 10K video | Any video CTR above channel median AND completion ≥ 55% |
| First 100K video | A universal-sensation topic launched at a US peak slot |
| 1M+ video | Full stack: gate-cleared completion + breakout CTR + cross-post amplification |

## Anti-patterns this roadmap refuses to repeat

The channel's own history documents the failure modes: a machine template visible in 100+ titles (demotion), a metrics loop that recorded zero real views while workflows reported success (flying blind), and hardcoded 3-videos-a-day volume during a 19–32% completion era (teaching the feed that the format loses). None of these ship again; the policy engine (`src/algorithm_policy.py`, POLICY_VERSION 2026.08-fix2) now blocks them by construction.
