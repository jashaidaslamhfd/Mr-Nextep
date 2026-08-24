"""
src/viral_calibrator.py

THE REAL LEARNING LOOP. Replaces fake regex scores with data-driven weights.

How it works:
  1. After each video matures (>48h), we have REAL metrics:
     - views, completion rate, ctr, hook_score, seo_score, topic
  2. We compare what viral_optimizer PREDICTED vs what ACTUALLY happened
  3. We update scoring weights using exponential moving average (EMA)
  4. Future predictions use these REAL weights instead of guessed ones

Before this module:
  viral_optimizer said: "hook has 'you' → +6 points" (guessed)
After this module:
  viral_optimizer says: "hook has 'you' → +8.3 points (from 47 videos with 'you',
  avg completion was 52% vs 31% without — weighted by sample size)"

Every weight is grounded in real YouTube/Facebook/Instagram performance data.
No more guessing. No more self-congratulating.

Usage:
    # Called by analytics_updater after daily data collection
    from viral_calibrator import calibrate
    result = calibrate()
    # result = {'features_updated': 12, 'videos_used': 47, 'r2_score': 0.73}
"""

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
CALIBRATOR_STATE_PATH = os.path.join(DATA_DIR, 'viral_calibrator_state.json')
PLATFORM_METRICS_PATH = os.path.join(DATA_DIR, 'platform_metrics.json')
GROWTH_STATE_PATH = os.path.join(DATA_DIR, 'growth_state.json')
PREDICTION_LOG_PATH = os.path.join(DATA_DIR, 'viral_prediction_log.json')

# ---------------------------------------------------------------------------
# Calibration parameters
# ---------------------------------------------------------------------------
MIN_VIDEOS_FOR_CALIBRATION = 5     # need at least 5 videos to update weights
EMA_ALPHA = 0.3                    # exponential moving average factor (0-1)
                                   # 0.3 = each new video moves weights by 30%
MIN_SAMPLE_WEIGHT = 2              # videos with <2 samples keep default weights
MAX_WEIGHT = 2.0                   # no single feature can be worth >2x baseline
MIN_WEIGHT = 0.3                   # no feature can be worth <0.3x baseline

# ---------------------------------------------------------------------------
# Feature extraction — what we measure from each video
# ---------------------------------------------------------------------------

def _extract_features(record: dict) -> dict:
    """Extract measurable features from a video record.

    These are the features whose weights we learn from real data.
    """
    title = record.get('title', '') or record.get('name', '') or ''
    topic = record.get('topic', 'other')
    hook_score = record.get('hook_score') or 50
    seo_score = record.get('seo_score') or 50
    title_lower = title.lower()

    features = {}

    # --- Hook features ---
    features['hook_has_you'] = 1 if any(w in title_lower for w in ['your', 'you ']) else 0
    features['hook_is_statement'] = 1 if not title_lower.endswith('?') and not title_lower.startswith('why ') else 0
    features['hook_is_question'] = 1 if title_lower.endswith('?') else 0
    features['hook_is_why'] = 1 if title_lower.startswith('why ') else 0
    features['hook_has_number'] = 1 if any(c.isdigit() for c in title) else 0
    features['hook_has_body_part'] = 1 if any(p in title_lower for p in [
        'body', 'brain', 'heart', 'muscle', 'nerve', 'ear', 'eye',
        'bone', 'skin', 'blood', 'stomach', 'spine', 'lung'
    ]) else 0

    # --- Title features ---
    title_words = title.split()
    features['title_length'] = len(title_words)
    features['title_short'] = 1 if len(title_words) <= 6 else 0
    features['title_long'] = 1 if len(title_words) > 10 else 0
    features['title_has_capitals'] = 1 if any(w.isupper() and len(w) > 1 for w in title_words) else 0

    # --- Topic features ---
    features['topic_muscle'] = 1 if 'muscle' in topic.lower() else 0
    features['topic_brain'] = 1 if 'brain' in topic.lower() else 0
    features['topic_ear'] = 1 if 'ear' in topic.lower() else 0
    features['topic_body'] = 1 if 'body' in topic.lower() else 0
    features['topic_health'] = 1 if 'health' in topic.lower() else 0

    # --- Quality scores ---
    features['hook_score_raw'] = hook_score / 100.0
    features['seo_score_raw'] = seo_score / 100.0

    return features


def _extract_actual_performance(record: dict) -> dict:
    """Extract actual performance metrics from a mature video."""
    yt = record.get('youtube_shorts', {})
    fb = record.get('facebook_reels', {})
    ig = record.get('instagram_reels', {})

    # Use YouTube primary (most data), fall back to FB
    views = 0
    completion = 0.0
    ctr = None

    if isinstance(yt, dict):
        views = yt.get('views', 0) or 0
        completion = yt.get('completion', 0) or 0
        ctr = yt.get('ctr')

    if views == 0 and isinstance(fb, dict):
        views = fb.get('views', 0) or 0
        completion = fb.get('completion', 0) or 0

    return {
        'views': views,
        'completion': completion,        # 0-1 (watched fraction)
        'ctr': ctr,                      # None if unknown, else 0-1
        'has_data': views > 0,
    }


def _compute_actual_score(perf: dict) -> float:
    """Combine actual metrics into a single performance score (0-100).

    Weighted: completion (50%) + views (30%) + ctr (20%).
    Uses log scale for views because they vary wildly (2 → 5000+).
    """
    # Completion score (0-50)
    comp_score = min(50, (perf['completion'] or 0) * 50)

    # View score (0-30) — log scale
    views = perf['views'] or 0
    if views > 0:
        view_score = min(30, math.log10(max(views, 1)) * 6)  # 1 view = 0, 10 = 6, 100 = 12, 1000 = 18, 10000 = 24
    else:
        view_score = 0

    # CTR score (0-20) — if available
    ctr = perf.get('ctr')
    if ctr is not None:
        ctr_score = min(20, ctr * 100)  # 1% CTR = 20 points (rare for shorts)
    else:
        ctr_score = 10  # neutral if unknown

    return round(comp_score + view_score + ctr_score, 2)


# ---------------------------------------------------------------------------
# The actual calibration engine
# ---------------------------------------------------------------------------

def calibrate() -> dict:
    """Run the real learning calibration.

    Reads all mature videos from platform_metrics.json, extracts features
    and actual performance, then updates scoring weights.

    Returns summary dict with calibration results.
    """
    # Load data
    platform_metrics = _load_json(PLATFORM_METRICS_PATH, {})
    growth_state = _load_json(GROWTH_STATE_PATH, {})
    calibrator_state = _load_json(CALIBRATOR_STATE_PATH, {
        'feature_weights': {},    # learned weights per feature
        'feature_samples': {},    # sample count per feature
        'feature_performance': {},  # avg actual score per feature value
        'calibration_history': [],  # past calibration runs
        'total_videos_calibrated': 0,
        'prediction_accuracy': 0,  # r2 score of predictions vs actuals
        'last_run': None,
    })

    # Filter to mature videos with actual data
    mature_with_data = []
    for vid_id, record in platform_metrics.items():
        if not isinstance(record, dict):
            continue
        age_hours = record.get('age_hours', 0) or 0
        if age_hours < 48:
            continue  # too young
        perf = _extract_actual_performance(record)
        if not perf['has_data']:
            continue
        mature_with_data.append((vid_id, record, perf))

    if len(mature_with_data) < MIN_VIDEOS_FOR_CALIBRATION:
        logger.info("Not enough mature videos for calibration: %d/%d needed",
                     len(mature_with_data), MIN_VIDEOS_FOR_CALIBRATION)
        return {
            'status': 'insufficient_data',
            'videos_available': len(mature_with_data),
            'videos_needed': MIN_VIDEOS_FOR_CALIBRATION,
        }

    logger.info("Calibrating from %d mature videos with real data", len(mature_with_data))

    # --- Step 1: Extract features + actual performance for all videos ---
    video_data = []
    for vid_id, record, perf in mature_with_data:
        features = _extract_features(record)
        actual_score = _compute_actual_score(perf)
        video_data.append({
            'vid_id': vid_id,
            'features': features,
            'actual_score': actual_score,
            'views': perf['views'],
            'completion': perf['completion'],
        })

    # --- Step 2: For each feature, compute correlation with actual performance ---
    feature_weights = calibrator_state.get('feature_weights', {})
    feature_samples = calibrator_state.get('feature_samples', {})
    feature_perf = calibrator_state.get('feature_performance', {})

    for feature_name in video_data[0]['features'].keys():
        # Group videos by feature value
        with_feature = [v for v in video_data if v['features'][feature_name] == 1]
        without_feature = [v for v in video_data if v['features'][feature_name] == 0]

        # Skip numeric features (title_length, hook_score_raw, seo_score_raw)
        if feature_name in ('title_length', 'hook_score_raw', 'seo_score_raw'):
            # For numeric features, compute correlation
            if len(video_data) >= 10:
                values = [v['features'][feature_name] for v in video_data]
                scores = [v['actual_score'] for v in video_data]
                corr = _pearson_correlation(values, scores)
                # Map correlation (-1 to 1) to weight (0.5 to 1.5)
                new_weight = 1.0 + corr * 0.5
                new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
                # EMA update
                old_weight = feature_weights.get(feature_name, 1.0)
                samples = feature_samples.get(feature_name, 0)
                alpha = EMA_ALPHA if samples > 0 else 1.0
                updated_weight = old_weight * (1 - alpha) + new_weight * alpha
                feature_weights[feature_name] = round(updated_weight, 4)
                feature_samples[feature_name] = samples + len(video_data)
                continue

        if not with_feature or not without_feature:
            continue

        avg_with = sum(v['actual_score'] for v in with_feature) / len(with_feature)
        avg_without = sum(v['actual_score'] for v in without_feature) / len(without_feature)

        # Compute weight: ratio of with/without performance
        if avg_without > 0:
            raw_weight = avg_with / avg_without
        else:
            raw_weight = 1.0

        raw_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, raw_weight))

        # EMA update (blend old weight with new observation)
        old_weight = feature_weights.get(feature_name, 1.0)
        samples = feature_samples.get(feature_name, 0)
        alpha = EMA_ALPHA if samples > 0 else 1.0
        updated_weight = old_weight * (1 - alpha) + raw_weight * alpha
        updated_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, updated_weight))

        feature_weights[feature_name] = round(updated_weight, 4)
        feature_samples[feature_name] = samples + len(with_feature)

        # Track per-feature performance
        feature_perf[feature_name] = {
            'avg_with': round(avg_with, 2),
            'avg_without': round(avg_without, 2),
            'raw_weight': round(raw_weight, 4),
            'ema_weight': round(updated_weight, 4),
            'sample_count': feature_samples[feature_name],
        }

    # --- Step 3: Compute prediction accuracy ---
    predictions = []
    actuals = []
    for v in video_data:
        predicted = _predict_score(v['features'], feature_weights)
        predictions.append(predicted)
        actuals.append(v['actual_score'])

    r2 = _r_squared(predictions, actuals) if len(predictions) >= 3 else 0

    # --- Step 4: Log predictions vs actuals for debugging ---
    prediction_log = []
    for i, v in enumerate(video_data):
        prediction_log.append({
            'vid_id': v['vid_id'],
            'predicted': round(predictions[i], 2),
            'actual': v['actual_score'],
            'error': round(abs(predictions[i] - v['actual_score']), 2),
            'views': v['views'],
            'completion': v['completion'],
        })

    # --- Step 5: Save state ---
    calibrator_state['feature_weights'] = feature_weights
    calibrator_state['feature_samples'] = feature_samples
    calibrator_state['feature_performance'] = feature_perf
    calibrator_state['total_videos_calibrated'] = (
        calibrator_state.get('total_videos_calibrated', 0) + len(video_data)
    )
    calibrator_state['prediction_accuracy'] = round(r2, 4)
    calibrator_state['last_run'] = datetime.now(timezone.utc).isoformat()
    calibrator_state['last_calibration_size'] = len(video_data)

    # Keep history of last 10 calibrations
    history = calibrator_state.get('calibration_history', [])
    history.append({
        'date': datetime.now(timezone.utc).isoformat(),
        'videos': len(video_data),
        'r2': round(r2, 4),
        'top_features': sorted(
            feature_perf.items(),
            key=lambda x: abs(x[1]['ema_weight'] - 1.0),
            reverse=True
        )[:5],
    })
    calibrator_state['calibration_history'] = history[-10:]

    _save_json(CALIBRATOR_STATE_PATH, calibrator_state)
    _save_json(PREDICTION_LOG_PATH, prediction_log[-50:])  # keep last 50

    # --- Step 6: Log results ---
    top_movers = sorted(
        [(k, v) for k, v in feature_perf.items()],
        key=lambda x: abs(x[1]['ema_weight'] - 1.0),
        reverse=True
    )[:5]

    logger.info("Calibration complete: %d videos, R²=%.3f", len(video_data), r2)
    for name, data in top_movers:
        direction = "↑" if data['ema_weight'] > 1.0 else "↓"
        logger.info("  %s: %s %.2f (avg %.1f vs %.1f, n=%d)",
                     name, direction, data['ema_weight'],
                     data['avg_with'], data['avg_without'],
                     data['sample_count'])

    return {
        'status': 'success',
        'videos_used': len(video_data),
        'features_updated': len(feature_weights),
        'r2_score': round(r2, 4),
        'top_movers': [{
            'feature': name,
            'weight': data['ema_weight'],
            'avg_with': data['avg_with'],
            'avg_without': data['avg_without'],
            'samples': data['sample_count'],
        } for name, data in top_movers],
    }


# ---------------------------------------------------------------------------
# Prediction using learned weights
# ---------------------------------------------------------------------------

def _predict_score(features: dict, weights: dict) -> float:
    """Predict performance score using learned weights.

    Base score = 50 (neutral). Each active feature adds or subtracts
    based on its learned weight.
    """
    score = 50.0
    for feature_name, feature_value in features.items():
        if feature_name in ('title_length', 'hook_score_raw', 'seo_score_raw'):
            # Numeric features: use as-is scaled by weight
            w = weights.get(feature_name, 1.0)
            score += (feature_value - 0.5) * 20 * w  # ±10 from center
        elif feature_value == 1:
            w = weights.get(feature_name, 1.0)
            score += (w - 1.0) * 25  # ±25 max deviation
    return max(0, min(100, score))


def get_learned_weights() -> dict:
    """Get current learned weights for external use (viral_optimizer)."""
    state = _load_json(CALIBRATOR_STATE_PATH, {})
    return state.get('feature_weights', {})


def get_weight_for_feature(feature_name: str) -> float:
    """Get the learned weight for a specific feature. Returns 1.0 if unknown."""
    weights = get_learned_weights()
    return weights.get(feature_name, 1.0)


def get_calibration_summary() -> dict:
    """Get a human-readable summary of what the system learned."""
    state = _load_json(CALIBRATOR_STATE_PATH, {})
    weights = state.get('feature_weights', {})
    perf = state.get('feature_performance', {})

    improvements = []
    regressions = []
    for name, data in perf.items():
        if data['ema_weight'] > 1.05 and data['sample_count'] >= MIN_SAMPLE_WEIGHT:
            improvements.append(f"{name}: +{(data['ema_weight']-1)*100:.0f}% (n={data['sample_count']})")
        elif data['ema_weight'] < 0.95 and data['sample_count'] >= MIN_SAMPLE_WEIGHT:
            regressions.append(f"{name}: {(data['ema_weight']-1)*100:.0f}% (n={data['sample_count']})")

    return {
        'total_videos': state.get('total_videos_calibrated', 0),
        'prediction_accuracy': state.get('prediction_accuracy', 0),
        'improvements': improvements[:5],
        'regressions': regressions[:5],
        'last_run': state.get('last_run'),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pearson_correlation(x: list, y: list) -> float:
    """Compute Pearson correlation coefficient between two lists."""
    n = len(x)
    if n < 3:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if den_x == 0 or den_y == 0:
        return 0.0
    return max(-1.0, min(1.0, num / (den_x * den_y)))


def _r_squared(predicted: list, actual: list) -> float:
    """Compute R² (coefficient of determination) between predicted and actual."""
    n = len(predicted)
    if n < 3:
        return 0.0
    mean_actual = sum(actual) / n
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    ss_tot = sum((a - mean_actual) ** 2 for a in actual)
    if ss_tot == 0:
        return 0.0
    return max(0.0, 1.0 - ss_res / ss_tot)


def _load_json(path: str, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Running Calibration ===\n")
    result = calibrate()
    print(json.dumps(result, indent=2, default=str))

    print("\n=== Calibration Summary ===\n")
    summary = get_calibration_summary()
    print(f"Videos calibrated: {summary['total_videos']}")
    print(f"Prediction accuracy (R²): {summary['prediction_accuracy']}")
    print(f"\nWhat actually helps:")
    for imp in summary['improvements']:
        print(f"  ✅ {imp}")
    print(f"\nWhat actually hurts:")
    for reg in summary['regressions']:
        print(f"  ❌ {reg}")

    print("\n=== Learned Weights (vs default 1.0) ===\n")
    weights = get_learned_weights()
    for name, weight in sorted(weights.items(), key=lambda x: abs(x[1] - 1.0), reverse=True):
        direction = "↑" if weight > 1.0 else "↓" if weight < 1.0 else "="
        print(f"  {direction} {name:30s}: {weight:.3f}")
