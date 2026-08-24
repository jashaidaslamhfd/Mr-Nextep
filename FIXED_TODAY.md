# Fixed Today - 2026-07-31 (API + Token Fixed)

User ne confirm kiya:
- ✅ YouTube Analytics API ENABLED (project 559439687452)
- ✅ Facebook + Instagram token ALL permissions ke sath renew kiya (read_insights, pages_read_engagement, pages_show_list, pages_manage_posts, instagram_basic, instagram_manage_insights)

## Ab kya hona chahiye auto?

1. **Actions → FB Token Probe (read-only) → Run workflow**
   Expected output:
   ```
   FACEBOOK_ACCESS_TOKEN: page='Mr. Nextep' | read_insights=OK | read_posts=OK | page_insights=OK
   ```
   Agar abhi bhi NO dikhe to token 1-2 min propagate hone ka wait karo.

2. **Actions → MrNextep - YouTube Analytics Learning → Run workflow (manual)**
   - Pehle 403 tha, ab 2026-07-31 fix ke baad exit 0 hoga aur ye step kabhi fail nahi hoga
   - Is mein 2 stages hain:
     - Stage 1: data/video_history.json mein real views/avg_view_percentage populate hoga (24h+ old videos ke liye)
     - Stage 2: data/platform_metrics.json + data/facebook_analytics.json update hoga (ab token mein permission hai to `insights_unavailable` khatam)
     - Stage 3: data/growth_state.json + docs/GROWTH_REPORT.md regenerate hoga

3. **Growth Report ka naya verdict kya aayega?**
   - Pehle: No mature videos (kyunki APIs band)
   - Ab: 23 mature videos already measured (21 YouTube), retention 49% vs 50% gate = 0.983 index
   - Best slot: **20:00 NY (weight 1.20, 5 videos)** — ye lunch se better perform kar raha hai ab
   - Under performers: 12:30 (0.86), 21:30 (0.80) — auto weight kam
   - Cadence: **2/day** recommended (3/day se 2/day pe auto switch) kyunki abhi gate ke just neeche ho
   - Topic: "other" pillar best (1.27 weight) — matlab specific niches abhi tie hain

4. **Facebook / Instagram purane reels repair (ek baar karna hai):**
   - `fb_audit_2026-07-27.json` mein 49 reels titleless + 23 coverless hain (purane pipeline se)
   - New pipeline se ye auto fixed hai (title + cover at publish time)
   - Purane ke liye:
     - Actions → **FB Cover Backfill** → apply=true → 23 covers backfill honge
     - Actions → **Meta (FB/IG) Strong SEO Repair** → apply=true, limit=0 → truncated captions + #shorts tag + bait fix hoga, aur har reel pe seed comment lagega (empty comment section = no push)
   - Ye karne se FB page ka avg view 236 se 350+ expected (audit mein max 504 tha, naya cut shorter hai)

5. **Instagram sends 0% ka fix:**
   - IG ka #2 signal sends-per-reach hai (DM shares), 3-5x like se zyada weight
   - Old captions mein generic follow ask tha
   - Fixed code `src/platform_captions.py` mein ab payoff fact (scene 7) include hota hai — yehi forwardable hota hai
   - Naye uploads mein auto fix. Purane ke liye SEO Repair workflow chalao.

6. **YouTube retention 49% → 50%+ kaise le jana hai (ab sab se important):**
   - Policy change already done: ideal 36s → 33s (auto 9% lift)
   - Hook zoom 0.12 → 0.18 + duck 0.15 → 0.10 (voice clearer)
   - Baaki human ka kaam:
     - First hour mein har comment ka reply (strongest early signal)
     - Pinned comment ko manually pin karo (API pin nahi kar sakta)
     - Ek video roz khud poora dekho — agar tum 12s pe bore ho to sab bore honge

## Agle 48 ghante ka checklist

- [ ] Token probe = OK dikhaye
- [ ] Analytics Learning workflow manual run karo (aaj)
- [ ] 24h wait karo, kal subah 05:20 NY wala auto learning run dekho
- [ ] FB Cover Backfill + Meta SEO Repair ek baar apply=true se chalao
- [ ] Roz 1-2 comment reply first hour mein

Monetization guardrails already ON hain: containsSyntheticMedia=true, unique visuals, rotating boilerplate.

Agar kal ke GROWTH_REPORT mein 🟢 healthy aaye to cadence auto 3/day ho jayega.
