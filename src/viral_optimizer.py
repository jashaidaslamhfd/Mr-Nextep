"""
src/viral_optimizer.py

The 100K-view engine. Current state: ~300 avg views, 32% retention, 69%
swipe-away. To reach 100K views/video we need:

  1. Retention 32% → 65%+ (the #1 gate — YouTube won't push below 50%)
  2. CTR 3% → 8%+ (thumbnail/title must make people CLICK)
  3. Shareability (IG DMs are the #2 ranking signal on that platform)
  4. Loop replay (each replay = 1x extra watch time)

This module sits BEFORE rendering and AFTER script generation. It:
  - Scores scripts for viral potential (0-100)
  - Predicts retention from script features
  - Recommends concrete rewrites when score < 80
  - Generates A/B thumbnail variants
  - Tracks what works and feeds it back

The pipeline calls it as:
    from viral_optimizer import ViralOptimizer
    opt = ViralOptimizer()
    result = opt.optimize_script(script_data)
    # result has: score, predicted_retention, rewrite_suggestions, thumbnails
"""

import json
import logging
import os
import re
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from viral_calibrator import get_learned_weights, get_weight_for_feature
    HAS_CALIBRATOR = True
except ImportError:
    HAS_CALIBRATOR = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
VIRAL_STATE_PATH = os.path.join(DATA_DIR, 'viral_optimizer_state.json')
VIRAL_HISTORY_PATH = os.path.join(DATA_DIR, 'viral_score_history.json')

# ---------------------------------------------------------------------------
# Thresholds — what "viral-ready" means
# ---------------------------------------------------------------------------
VIRAL_SCORE_GATE = 80           # scripts below this get rewrite suggestions
PREDICTED_RETENTION_GATE = 0.60 # below 60% predicted = needs work
MAX_REWRITE_ATTEMPTS = 3        # how many times to retry a script

# ---------------------------------------------------------------------------
# Pattern weights — data-driven from growth_state
# ---------------------------------------------------------------------------
# From growth_state.hook_weights:
#   statement: 1.037  (best — use direct statements)
#   why:       0.855  (worst — avoid "Why" question openers)
# From growth_state.topic_weights:
#   muscle:    1.076  (best performing topic)
#   other:     1.047
#   ear:       0.970
#   brain:     0.879  (worst — avoid brain topics until proven)

# DEFAULT weights — used ONLY when calibrator has no data yet.
# After calibration, these are REPLACED by real learned weights.
_DEFAULT_TOPIC_WEIGHTS = {'muscle': 1.08, 'ear': 0.97, 'brain': 0.88, 'other': 1.05}
_DEFAULT_HOOK_WEIGHTS = {'statement': 1.04, 'why': 0.86, 'question': 0.92, 'unknown': 0.96}


def _get_topic_weight(topic: str) -> float:
    """Get topic weight — learned from real data if calibrator has run."""
    if HAS_CALIBRATOR:
        key = f"topic_{topic}"
        w = get_weight_for_feature(key)
        if w != 1.0:  # calibrator returned a learned weight
            return w
    return _DEFAULT_TOPIC_WEIGHTS.get(topic, 1.05)


def _get_hook_weight(hook_type: str) -> float:
    """Get hook weight — learned from real data if calibrator has run."""
    if HAS_CALIBRATOR:
        key = f"hook_is_{hook_type}"
        w = get_weight_for_feature(key)
        if w != 1.0:
            return w
    return _DEFAULT_HOOK_WEIGHTS.get(hook_type, 0.96)

# ---------------------------------------------------------------------------
# Retention predictors — empirical weights from channel analytics
# ---------------------------------------------------------------------------

# Words the algorithm penalises (AI-slop markers reduce completion rate)
_AI_SLOP_WORDS = frozenset([
    'delve', 'explore', 'fascinating', 'incredible', 'journey',
    'mind-blowing', 'buckle up', 'crucial', 'testament', 'tapestry',
    'did you know', 'you won\'t believe', 'shocking', 'amazing',
    'in this digital age', 'let\'s dive', 'buckle up', 'turns out',
    'the truth is', 'what if i told you',
])

# Words that INCREASE completion (concrete, visceral, personal)
_RETENTION_BOOSTERS = frozenset([
    'your body', 'right now', 'tonight', 'tomorrow', 'this second',
    'listen', 'watch', 'look', 'wait', 'stop', 'hold on',
    'because', 'literally', 'actually', 'real', 'fact',
    'nervous system', 'brain', 'heart', 'muscle', 'nerve',
    '20 milliseconds', '0.3 seconds', 'twice', 'three times',
])

# Pattern interrupts — visual or conceptual shifts that reset the viewer's
# internal "should I swipe?" timer. Each one buys 2-3 more seconds.
_PATTERN_INTERRUPT_WORDS = frozenset([
    'but', 'however', 'except', 'until', 'before', 'after',
    'the problem is', 'here\'s the thing', 'but here\'s what',
    'but then', 'until suddenly', 'but watch this',
    'imagine', 'now picture', 'what happens', 'suddenly',
])


class ViralOptimizer:
    """Scores, predicts, and rewrites scripts for maximum viral potential."""

    def __init__(self):
        self.state = self._load_json(VIRAL_STATE_PATH, {
            'total_optimized': 0,
            'total_viral_ready': 0,
            'avg_score': 0,
            'best_topics': {},
            'best_hooks': {},
            'last_run': None,
        })

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize_script(self, script_data: Dict) -> Dict:
        """Full optimization pass on a generated script.

        Returns:
          {
            'viral_score': int (0-100),
            'predicted_retention': float (0-1),
            'predicted_ctr': float (0-1),
            'predicted_shares': float (0-1),
            'is_viral_ready': bool,
            'rewrite_suggestions': [str, ...],
            'enhanced_script': dict (script_data with improvements applied),
            'thumbnail_variants': [dict, ...],
            'topic_weight': float,
            'hook_weight': float,
          }
        """
        score = self._score_viral_potential(script_data)
        retention = self._predict_retention(script_data)
        ctr = self._predict_ctr(script_data)
        shares = self._predict_shareability(script_data)
        suggestions = self._generate_suggestions(script_data, score, retention, ctr)
        enhanced = self._apply_quick_fixes(script_data)
        thumbnails = self._generate_thumbnail_variants(script_data)

        topic = script_data.get('topic_category', script_data.get('topic', 'other'))
        hook_type = self._classify_hook(script_data.get('hook', ''))

        result = {
            'viral_score': score,
            'predicted_retention': round(retention, 4),
            'predicted_ctr': round(ctr, 4),
            'predicted_shares': round(shares, 4),
            'is_viral_ready': score >= VIRAL_SCORE_GATE and retention >= PREDICTED_RETENTION_GATE,
            'rewrite_suggestions': suggestions,
            'enhanced_script': enhanced,
            'thumbnail_variants': thumbnails,
            'topic_weight': TOPIC_WEIGHTS.get(topic, 1.0),
            'hook_weight': HOOK_WEIGHTS.get(hook_type, 0.96),
        }

        # Track stats
        self.state['total_optimized'] = self.state.get('total_optimized', 0) + 1
        if result['is_viral_ready']:
            self.state['total_viral_ready'] = self.state.get('total_viral_ready', 0) + 1
        n = self.state['total_optimized']
        self.state['avg_score'] = (
            (self.state.get('avg_score', 50) * (n - 1) + score) / n
        )
        self.state['last_run'] = datetime.now(timezone.utc).isoformat()

        # Track topic performance
        if topic not in self.state.get('best_topics', {}):
            self.state.setdefault('best_topics', {})[topic] = []
        self.state['best_topics'][topic].append(score)

        self._save_json(VIRAL_STATE_PATH, self.state)

        return result

    def get_rewrite_prompt_addendum(self, suggestions: List[str],
                                    current_score: int) -> str:
        """Build a prompt addendum for the LLM retry loop.

        Called by script_generator when the viral score is below gate.
        The addendum is injected into the retry prompt to steer the LLM
        toward fixes that actually move the needle.
        """
        if not suggestions:
            return ''

        lines = [
            f"\nVIRAL OPTIMIZATION (current score: {current_score}/100, "
            f"need {VIRAL_SCORE_GATE}):",
            "The previous script was rejected for these specific issues:",
        ]
        for i, s in enumerate(suggestions[:5], 1):
            lines.append(f"  {i}. {s}")

        lines.append("")
        lines.append("FIX THESE — the video will not reach 100K views without them:")
        lines.append("- Hook must deliver a CONTRADICTION or MECHANISM in the first sentence")
        lines.append("- Every scene must have a visual that is ALREADY IN MOTION (no setup)")
        lines.append("- The payoff scene must contain ONE quotable fact with a number or contrast")
        lines.append("- The ending must loop back to the hook so replays feel intentional")
        lines.append("- Cut every filler word. If a word doesn't add information, delete it.")
        lines.append("- DO NOT repeat the hook or pad length. Every word must earn its place.")

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Scoring engine
    # ------------------------------------------------------------------

    def _score_viral_potential(self, script: Dict) -> int:
        """Score 0-100 based on what actually drives views."""

        hook = (script.get('hook', '') or '').strip()
        scenes = script.get('scenes', [])
        title = script.get('title', '')
        description = script.get('description', '')
        all_text = ' '.join(s.get('caption', '') for s in scenes)
        hook_lower = hook.lower()
        title_lower = title.lower()
        all_lower = all_text.lower() + ' ' + hook_lower + ' ' + title_lower

        score = 0

        # --- 1. HOOK QUALITY (30 points max) ---
        hook_words = hook.split()
        hook_len = len(hook_words)

        # Length: 4-9 words = optimal for 2-second budget
        if 4 <= hook_len <= 9:
            score += 8
        elif hook_len < 4:
            score += 2
        elif hook_len > 12:
            score += 0

        # Direct address ("you/your")
        if re.search(r'\b(you|your|you\'re)\b', hook_lower):
            score += 6

        # Concrete subject (body part or phenomenon)
        concrete = [
            'heart', 'brain', 'muscle', 'nerve', 'bone', 'eye', 'ear',
            'skin', 'blood', 'lung', 'stomach', 'finger', 'tooth', 'spine',
            'cramp', 'twitch', 'pulse', 'breathe', 'yawn', 'sneeze',
            'voice', 'sleep', 'dream', 'shiver', 'freeze', 'jolt',
            'goosebump', 'itch', 'sweat', 'blush', 'choke', 'gag',
            'heartbeat', 'adrenaline', 'cortisol', 'dopamine',
        ]
        if any(c in hook_lower for c in concrete):
            score += 8

        # Curiosity loop (question, timing word, or unresolved reference)
        if (hook.rstrip().endswith('?')
                or re.search(r'\b(before|until|right after|the moment|seconds? before)\b', hook_lower)
                or re.search(r'\b(here\'s|that\'s)\s+(why|how|what)\b', hook_lower)):
            score += 5

        # Hook type bonus (statement > question)
        hook_type = self._classify_hook(hook)
        score += int(HOOK_WEIGHTS.get(hook_type, 0.96) * 3)

        # --- 2. COLD OPEN PENALTY (-40 max) ---
        cold_patterns = [
            r'^(hi|hey|hello|welcome|what\'?s up)\b',
            r'\bwelcome back\b',
            r'\bin (this|today\'?s)\s+(video|short|one)\b',
            r'^(let\'?s|lets)\s+(talk|discuss|look|dive|get into)',
            r'\bbefore we (start|begin)\b',
            r'\bsubscribe\b',
        ]
        if any(re.search(p, hook_lower) for p in cold_patterns):
            score -= 40

        # --- 3. VAGUE AUTHORITY PENALTY (-35 max) ---
        vague_patterns = [
            r'\bsomething\s+(interesting|amazing|weird|strange)\b',
            r'\bscientists?\s+(say|found|discovered)\b',
            r'\bfun fact\b',
            r'\bdid you know\b',
        ]
        if any(re.search(p, hook_lower) for p in vague_patterns):
            score -= 35

        # --- 4. AI-SLOP PENALTY (-15 per word, max -45) ---
        slop_count = sum(1 for w in _AI_SLOP_WORDS if w in all_lower)
        score -= min(45, slop_count * 15)

        # --- 5. SCENE PACING (15 points max) ---
        if scenes:
            total_captions = ' '.join(s.get('caption', '') for s in scenes)
            word_count = len(total_captions.split())
            scene_count = len(scenes)

            # Ideal: 5-8 words per scene for 25-28s video
            avg_words = word_count / max(scene_count, 1)
            if 4 <= avg_words <= 10:
                score += 8
            elif avg_words < 4:
                score += 3
            elif avg_words > 15:
                score += 0

            # Pattern interrupts: words that reset the swipe timer
            interrupt_count = sum(
                1 for w in _PATTERN_INTERRUPT_WORDS
                if w in total_captions.lower()
            )
            # 1-3 is ideal; more than 5 means too many direction changes
            if 1 <= interrupt_count <= 3:
                score += 7
            elif interrupt_count > 5:
                score += 2

        # --- 6. RETENTION BOOSTERS (10 points max) ---
        booster_count = sum(1 for b in _RETENTION_BOOSTERS if b in all_lower)
        score += min(10, booster_count * 2)

        # --- 7. TITLE CTR (10 points max) ---
        title_words = title.split()
        if 4 <= len(title_words) <= 8:
            score += 3
        if re.search(r'\b(your|you|why|what happens)\b', title_lower):
            score += 4
        if re.search(r'\b(happens|feel|really|actually|secret)\b', title_lower):
            score += 3

        # --- 8. LOOP-BACK ENDING (5 points) ---
        if scenes and len(scenes) >= 7:
            last_caption = scenes[-1].get('caption', '').lower()
            first_caption = scenes[0].get('caption', '').lower()
            # Check if ending references the hook concept
            hook_words_set = set(hook_lower.split()) - {'your', 'you', 'the', 'a', 'is', 'does', 'do', 'it', 'and', 'or', 'but', 'of', 'in', 'to', 'for', 'at', 'on'}
            last_words = set(last_caption.split())
            if hook_words_set & last_words:
                score += 5

        # --- 9. SHAREABILITY FACTOR (5 points) ---
        # IG DM signal: the payoff fact must be quotable
        if scenes and len(scenes) >= 7:
            payoff = scenes[6].get('caption', '') if len(scenes) > 6 else ''
            payoff_words = payoff.split()
            # Quotable = short (under 15 words), specific (has a number)
            if len(payoff_words) <= 15 and re.search(r'\d', payoff):
                score += 3
            # Emotional reaction word
            if any(w in payoff.lower() for w in ['actually', 'literally', 'never', 'always', 'every']):
                score += 2

        # --- 10. TOPIC WEIGHT ---
        topic = script.get('topic_category', script.get('topic', 'other'))
        tw = TOPIC_WEIGHTS.get(topic, 1.0)
        if tw < 1.0:
            score -= 3  # below-average topic gets a small penalty

        return max(0, min(100, score))

    def _predict_retention(self, script: Dict) -> float:
        """Predict average completion rate (0-1).

        Based on empirical channel data:
          - Current avg: 32% (301.9 views, below 50% gate)
          - Target: 65%+ for algorithmic push
          - Main drivers: hook strength, pacing, visual variety, length
        """
        hook = (script.get('hook', '') or '').lower()
        scenes = script.get('scenes', [])
        if not scenes:
            return 0.25

        base = 0.32  # channel baseline

        # Hook quality impact (0-0.15)
        hook_score = self._score_hook_retention_impact(hook)
        base += hook_score * 0.15

        # Scene pacing (0-0.10)
        total_words = sum(len(s.get('caption', '').split()) for s in scenes)
        ideal_words = 90  # ~28s at 3.2 words/sec
        word_deviation = abs(total_words - ideal_words) / ideal_words
        pacing_bonus = max(0, 0.10 * (1 - word_deviation))
        base += pacing_bonus

        # Visual variety (0-0.08) — each unique visual description = +0.01
        visuals = set(s.get('visual', '').lower()[:30] for s in scenes)
        variety_bonus = min(0.08, len(visuals) * 0.01)
        base += variety_bonus

        # Pattern interrupts reset swipe timer (0-0.06)
        all_captions = ' '.join(s.get('caption', '') for s in scenes).lower()
        interrupt_count = sum(1 for w in _PATTERN_INTERRUPT_WORDS if w in all_captions)
        interrupt_bonus = min(0.06, interrupt_count * 0.02)
        base += interrupt_bonus

        # AI-slop penalty (-0.15 max)
        slop_count = sum(1 for w in _AI_SLOP_WORDS if w in all_captions)
        slop_penalty = min(0.15, slop_count * 0.05)
        base -= slop_penalty

        # Retention boosters (+0.05)
        booster_count = sum(1 for b in _RETENTION_BOOSTERS if b in all_captions)
        base += min(0.05, booster_count * 0.01)

        # "You/your" language throughout (+0.04)
        you_count = len(re.findall(r'\b(you|your|you\'re)\b', all_captions))
        base += min(0.04, you_count * 0.005)

        # Loop-back ending (+0.03)
        if scenes and len(scenes) >= 7:
            last = scenes[-1].get('caption', '').lower()
            first = scenes[0].get('caption', '').lower()
            hook_words = set(first.split()) - {'your', 'you', 'the', 'a', 'is'}
            if hook_words & set(last.split()):
                base += 0.03

        return max(0.10, min(0.85, base))

    def _predict_ctr(self, script: Dict) -> float:
        """Predict click-through rate on thumbnail/title (0-1)."""
        title = (script.get('title', '') or '').lower()
        thumb = (script.get('thumbnail_text', '') or '').lower()
        hook = (script.get('hook', '') or '').lower()

        base = 0.03  # channel baseline (~3%)

        # Title curiosity loop
        if re.search(r'\b(your|you|why|what happens)\b', title):
            base += 0.02
        title_words = title.split()
        if 4 <= len(title_words) <= 8:
            base += 0.01

        # Thumbnail text is punchy (2-4 words)
        thumb_words = thumb.split()
        if 2 <= len(thumb_words) <= 4:
            base += 0.01

        # Title + thumbnail complement (don't repeat same words)
        title_set = set(title.split())
        thumb_set = set(thumb.split())
        overlap = title_set & thumb_set
        if not overlap:
            base += 0.01  # complementary text = higher CTR

        # Numbers in title
        if re.search(r'\d', title):
            base += 0.005

        return min(0.12, base)

    def _predict_shareability(self, script: Dict) -> float:
        """Predict IG DM share rate (0-1)."""
        scenes = script.get('scenes', [])
        if not scenes:
            return 0.001

        base = 0.00063  # channel baseline (from growth_state)

        # Payoff scene has a quotable fact
        if len(scenes) >= 7:
            payoff = scenes[6].get('caption', '')
            payoff_words = payoff.split()
            if len(payoff_words) <= 15 and re.search(r'\d', payoff):
                base *= 3  # quotable facts get shared 3x more

        # Overall tone: calm + specific > excited + vague
        all_captions = ' '.join(s.get('caption', '') for s in scenes).lower()
        if 'literally' in all_captions or 'actually' in all_captions:
            base *= 1.5

        return min(0.05, base)

    # ------------------------------------------------------------------
    # Suggestion engine
    # ------------------------------------------------------------------

    def _generate_suggestions(self, script: Dict, score: int,
                               retention: float, ctr: float) -> List[str]:
        """Generate concrete rewrite suggestions when score is below gate."""
        suggestions = []
        hook = (script.get('hook', '') or '').lower()
        scenes = script.get('scenes', [])

        if score >= VIRAL_SCORE_GATE:
            return []

        # Hook issues
        hook_words = (script.get('hook', '') or '').split()
        if len(hook_words) < 4:
            suggestions.append(
                f"Hook is only {len(hook_words)} words — too short to create "
                "a curiosity loop. Add the 'why it matters' in 4-9 words."
            )
        if len(hook_words) > 12:
            suggestions.append(
                f"Hook is {len(hook_words)} words — too long for the 2-second "
                "budget. Cut to 4-9 words."
            )

        if any(re.search(p, hook) for p in [
            r'^(hi|hey|hello|welcome)\b', r'\bwelcome back\b',
            r'\bin (this|today)\b', r'\bbefore we (start|begin)\b',
        ]):
            suggestions.append(
                "Hook is a COLD OPEN (greeting/filler). Replace with a "
                "direct statement that names the phenomenon: 'Your [body part] "
                "[does X] [when Y]' — no greeting, no intro."
            )

        if any(re.search(p, hook) for p in [
            r'\bsomething\s+(interesting|amazing|weird)\b',
            r'\bscientists?\s+(say|found|discovered)\b',
            r'\bdid you know\b', r'\bfun fact\b',
        ]):
            suggestions.append(
                "Hook uses VAGUE AUTHORITY ('scientists found something'). "
                "Replace with the SPECIFIC mechanism: what happens, to what, "
                "and why it matters to the viewer."
            )

        if hook.startswith('why '):
            suggestions.append(
                "Hook starts with 'Why' — question openers perform 17% worse "
                "on this channel (growth_data). Convert to a statement: "
                "'Your [X] does [Y] — here's why' instead of 'Why does [X]?'"
            )

        # Scene pacing
        if scenes:
            total_words = sum(len(s.get('caption', '').split()) for s in scenes)
            if total_words > 130:
                suggestions.append(
                    f"Script is {total_words} words — too long. Cut to 80-110 "
                    "words. Every extra word past 100 loses ~2% completion rate."
                )
            if total_words < 50:
                suggestions.append(
                    f"Script is only {total_words} words — too sparse. "
                    "Add concrete details to 80-100 words."
                )

        # AI slop
        all_captions = ' '.join(s.get('caption', '') for s in scenes).lower()
        slop_found = [w for w in _AI_SLOP_WORDS if w in all_captions]
        if slop_found:
            suggestions.append(
                f"AI-slop words detected: {', '.join(slop_found[:3])}. "
                "These kill completion rate. Replace with concrete specifics."
            )

        # Payoff quality
        if len(scenes) >= 7:
            payoff = scenes[6].get('caption', '')
            payoff_words = payoff.split()
            if len(payoff_words) > 20:
                suggestions.append(
                    "Payoff scene is too wordy. The 'quotable fact' must be "
                    "under 15 words — something a viewer would type into a "
                    "group chat."
                )
            if not re.search(r'\d', payoff):
                suggestions.append(
                    "Payoff fact has no number. Specific numbers (20ms, 40,000 "
                    "neurons, 3am) make facts shareable. Add one."
                )

        # Loop-back
        if scenes and len(scenes) >= 8:
            last = scenes[-1].get('caption', '').lower()
            first = scenes[0].get('caption', '').lower()
            if not any(w in last for w in first.split() if len(w) > 3):
                suggestions.append(
                    "Ending doesn't loop back to the hook. The last line should "
                    "reference the opening moment so replay feels intentional."
                )

        # Low CTR
        if ctr < 0.05:
            title = script.get('title', '')
            if len(title.split()) < 4:
                suggestions.append(
                    "Title is too short for CTR. Use 4-8 words with a "
                    "'What happens when...' or 'Your X does Y...' frame."
                )

        # Missing "you/your"
        all_text = all_captions + ' ' + hook
        if not re.search(r'\b(you|your)\b', all_text):
            suggestions.append(
                "No 'you/your' language anywhere. Direct viewer address is "
                "the single strongest retention driver on this channel."
            )

        return suggestions[:6]  # max 6 suggestions per script

    # ------------------------------------------------------------------
    # Quick-fix engine — applies safe edits to improve score
    # ------------------------------------------------------------------

    def _apply_quick_fixes(self, script: Dict) -> Dict:
        """Apply safe, reversible improvements to the script.

        These are edits that ALWAYS help and never change the meaning:
        - Strip AI-slop words
        - Ensure 'you/your' in the hook
        - Ensure the payoff has a number
        """
        import copy
        enhanced = copy.deepcopy(script)
        scenes = enhanced.get('scenes', [])

        # Fix 1: Strip AI-slop from captions
        for scene in scenes:
            caption = scene.get('caption', '')
            for slop in _AI_SLOP_WORDS:
                caption = re.sub(
                    r'\b' + re.escape(slop) + r'\b',
                    '', caption, flags=re.IGNORECASE
                )
            caption = re.sub(r'\s+', ' ', caption).strip()
            scene['caption'] = caption

        # Fix 2: Ensure hook addresses viewer
        hook = enhanced.get('hook', '')
        if hook and not re.search(r'\b(you|your)\b', hook, re.IGNORECASE):
            # Try to prepend "Your" if the first word is a body part
            body_parts = ['heart', 'brain', 'muscle', 'nerve', 'bone', 'eye',
                         'ear', 'skin', 'blood', 'voice', 'body']
            hook_lower = hook.lower()
            for part in body_parts:
                if hook_lower.startswith(part + ' '):
                    enhanced['hook'] = 'Your ' + hook[0].lower() + hook[1:]
                    break

        # Fix 3: Ensure payoff fact has a number
        if scenes and len(scenes) >= 7:
            payoff = scenes[6].get('caption', '')
            if not re.search(r'\d', payoff) and len(payoff.split()) > 8:
                # Append "— fact." placeholder if missing
                pass  # don't auto-add numbers, that's dishonest

        enhanced['viral_optimizer_applied'] = True
        return enhanced

    # ------------------------------------------------------------------
    # A/B Thumbnail variants
    # ------------------------------------------------------------------

    def _generate_thumbnail_variants(self, script: Dict) -> List[Dict]:
        """Generate 3 thumbnail text variants for A/B testing.

        YouTube supports uploading 3 thumbnails and auto-selects the
        best performer. We generate 3 variants that:
        1. Original thumbnail_text from the script
        2. A "question" variant (creates curiosity gap)
        3. A "number/shock" variant (specificity stops the scroll)
        """
        original_text = script.get('thumbnail_text', '')
        hook = script.get('hook', '')
        title = script.get('title', '')
        scenes = script.get('scenes', [])

        variants = [{'text': original_text, 'type': 'original', 'strategy': 'baseline'}]

        # Variant 2: Question frame
        if scenes and len(scenes) >= 7:
            payoff = scenes[6].get('caption', '')
            # Extract a key phrase from the payoff
            payoff_words = payoff.split()
            if len(payoff_words) >= 4:
                # Take the most impactful 3-4 words
                key_phrase = ' '.join(payoff_words[:4])
                variants.append({
                    'text': f"Why {key_phrase}?",
                    'type': 'question',
                    'strategy': 'curiosity_gap',
                })

        # Variant 3: Number/shock frame
        if re.search(r'\d', hook) or re.search(r'\d', title):
            # Extract the number
            nums = re.findall(r'\d+', hook + ' ' + title)
            if nums:
                # Find the most interesting number
                biggest = max(nums, key=int)
                variants.append({
                    'text': f"{biggest}× More Than You Think",
                    'type': 'number_shock',
                    'strategy': 'specificity_stop_scroll',
                })

        # Variant 3 fallback: "WAIT" pattern
        if len(variants) < 3:
            # Find the surprise word in the script
            surprise_words = ['actually', 'literally', 'never', 'always',
                            'suddenly', 'stops', 'freezes', 'explodes']
            all_text = ' '.join(s.get('caption', '') for s in scenes).lower()
            for sw in surprise_words:
                if sw in all_text:
                    variants.append({
                        'text': sw.upper() + "!",
                        'type': 'exclamation',
                        'strategy': 'pattern_interrupt',
                    })
                    break

        if len(variants) < 3:
            variants.append({
                'text': original_text,
                'type': 'duplicate',
                'strategy': 'safe_fallback',
            })

        return variants[:3]

    # ------------------------------------------------------------------
    # Hook classification
    # ------------------------------------------------------------------

    def _classify_hook(self, hook: str) -> str:
        """Classify hook into statement/question/why/unknown."""
        hook_lower = (hook or '').lower().strip()
        if not hook_lower:
            return 'unknown'
        if hook_lower.startswith('why '):
            return 'why'
        if hook_lower.endswith('?'):
            return 'question'
        return 'statement'

    def _score_hook_retention_impact(self, hook: str) -> float:
        """Score hook's impact on retention (0-1)."""
        hook_lower = hook.lower().strip()
        if not hook_lower:
            return 0.0

        score = 0.5  # baseline

        # Direct address
        if re.search(r'\b(you|your)\b', hook_lower):
            score += 0.15

        # Concrete body reference
        body_words = ['heart', 'brain', 'muscle', 'nerve', 'bone', 'eye',
                     'ear', 'skin', 'blood', 'voice', 'body', 'sleep',
                     'cramp', 'twitch', 'pulse', 'finger', 'stomach']
        if any(w in hook_lower for w in body_words):
            score += 0.15

        # Cold open penalty
        cold = ['hi', 'hey', 'hello', 'welcome', "what's up", 'let\'s talk',
                'in this video', 'today we']
        if any(hook_lower.startswith(c) for c in cold):
            score -= 0.4

        # Vague penalty
        vague = ['something', 'did you know', 'fun fact', 'amazing']
        if any(v in hook_lower for v in vague):
            score -= 0.3

        # "Why" penalty
        if hook_lower.startswith('why '):
            score -= 0.1

        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_json(self, path, default):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return default

    def _save_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    opt = ViralOptimizer()

    # Test with a sample script
    test_script = {
        'title': 'Why Your Body Freezes When Scared',
        'thumbnail_text': 'YOUR BODY FREEZES',
        'hook': 'Your body freezes before you hear the scary sound.',
        'topic_category': 'muscle',
        'scenes': [
            {'visual': 'person freezing mid-step', 'caption': 'Your body freezes before you hear the scary sound.'},
            {'visual': 'brain scan close-up', 'caption': 'The moment your brain detects danger, it floods your muscles with a signal that locks them in place.'},
            {'visual': 'nervous system diagram', 'caption': 'This is called the freeze response, and it happens in less than 200 milliseconds.'},
            {'visual': 'evolution comparison', 'caption': 'Evolution wired this in because for our ancestors, freezing meant survival.'},
            {'visual': 'modern human context', 'caption': 'But today, that same mechanism kicks in during a car honk or a loud noise at night.'},
            {'visual': 'comparison normal vs freeze', 'caption': 'Your muscles tense before your conscious brain even processes what happened.'},
            {'visual': 'science reveal', 'caption': 'Your brain sends the freeze signal 20 milliseconds before the fear center activates.'},
            {'visual': 'loop back opening frame', 'caption': 'So next time your body locks up, remember — it already saved you.'},
        ],
        'cta': 'Follow for more body facts',
        'description': 'Why does your body freeze when you get scared? The answer is in your brain stem.',
    }

    result = opt.optimize_script(test_script)
    print(json.dumps({k: v for k, v in result.items() if k != 'enhanced_script'}, indent=2, default=str))
    print(f"\nViral ready: {result['is_viral_ready']}")
    print(f"Score: {result['viral_score']}/100")
    print(f"Predicted retention: {result['predicted_retention']*100:.1f}%")
    print(f"Predicted CTR: {result['predicted_ctr']*100:.1f}%")
    print(f"\nSuggestions ({len(result['rewrite_suggestions'])}):")
    for s in result['rewrite_suggestions']:
        print(f"  → {s}")
    print(f"\nThumbnail variants:")
    for t in result['thumbnail_variants']:
        print(f"  [{t['type']}] {t['text']}")
