#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MrNextep ML BRAIN — Multi-Platform Viral Growth Engine v2.0               ║
║  ────────────────────────────────────────────────────────────────────────  ║
║  Trained on real channel data. Learns:                                    ║
║    • Which topics go viral (regression + classification)                  ║
║    • Optimal hook patterns per view-count bucket                          ║
║    • Best publish slots from actual performance                          ║
║    • Cross-platform content transfer strategy                            ║
║    • Retention prediction & improvement suggestions                      ║
║    • Topic-to-virality scoring with confidence intervals                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

Run:  python scripts/ml_brain.py                    # train + report
      python scripts/ml_brain.py --predict TOPIC     # score a topic
      python scripts/ml_brain.py --serve              # interactive mode
"""

import json
import os
import re
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("MrNextep_DATA_DIR", "data"))
VIDEO_HISTORY = DATA_DIR / "video_history.json"
PLATFORM_METRICS = DATA_DIR / "platform_metrics.json"
GROWTH_STATE = DATA_DIR / "growth_state.json"
RETENTION_DATA = DATA_DIR / "retention_analysis.json"
FB_AUDIT_PREFIX = "fb_audit_"
ML_BRAIN_STATE = DATA_DIR / "ml_brain_state.json"

# ---------------------------------------------------------------------------
# Viral threshold: views above this percentile count as "viral"
# ---------------------------------------------------------------------------
VIRAL_PERCENTILE = 75
MIN_VIEWS_FOR_TRAINING = 10


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  FEATURE ENGINEERING                                                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class FeatureExtractor:
    """Extract ML features from raw video/topic data."""

    # Body-science keyword clusters (semantic pillars)
    PILLARS = {
        "neurological": [
            "brain", "nerve", "neuron", "memory", "deja", "conscious", "sleep",
            "dream", "falling asleep", "ringing", "ear", "tinnitus", "hearing",
            "song", "loop", "stuck", "freezing", "scared", "fear",
        ],
        "muscular": [
            "muscle", "cramp", "charley horse", "calf", "twitch", "spasm",
            "knee", "crack", "joint", "foot", "numb", "jerking",
        ],
        "circulatory": [
            "heart", "blood", "pulse", "standing up", "lightheaded", "pressure",
            "cold", "freeze", "warm", "beat", "heartbeat",
        ],
        "sensory": [
            "taste", "sight", "smell", "hear", "touch", "numb", "tingling",
            "spot", "glowing", "wrinkling", "gag", "sensitive",
        ],
        "behavioral": [
            "yawn", "hungry", "craving", "habit", "lump", "throat", "sad",
            "voice", "deeper", "waking", "coffee", "hot", "losing taste",
        ],
        "temporal": [
            "time", "hours", "minutes", "daily", "night", "morning", "moment",
            "lived before", "deja vu", "familiar",
        ],
    }

    # Hook pattern templates
    HOOK_PATTERNS = [
        ("your_", r"\byour\b"),           # "your foot falling asleep"
        ("why_", r"\bwhy\b"),             # "Why your body freezes"
        ("a_", r"\ba\b"),                 # "a sudden charley horse"
        ("the_", r"\bthe\b"),
        ("feeling_", r"\bfeeling\b"),     # "feeling like you've lived"
        ("gerund", r"\b\w+ing\b"),        # gerund: "falling", "ringing", etc.
        ("when_", r"\bwhen\b"),
        ("question", r"\?"),
    ]

    # Word categories for richness scoring
    POWER_WORDS = {
        "mystery", "secret", "strange", "weird", "bizarre", "unexplained",
        "hidden", "unknown", "surprising", "shocking", "sudden", "instantly",
        "exact", "never", "nobody", "every", "always",
    }
    BODY_WORDS = {
        "body", "brain", "muscle", "nerve", "blood", "heart", "skin", "ear",
        "eye", "foot", "hand", "leg", "arm", "head", "throat", "voice",
        "knee", "calf", "tongue", "taste",
    }

    def __init__(self):
        pass

    def extract_from_topic(self, topic: str) -> np.ndarray:
        """Convert a topic string to a feature vector (37 dimensions)."""
        topic_lower = topic.lower() if topic else ""
        words = re.findall(r"[a-z]+", topic_lower)
        word_set = set(words)

        features = []

        # 1-6: Pillar match scores (0 or 1)
        for pillar, keywords in self.PILLARS.items():
            score = sum(1 for kw in keywords if kw in topic_lower)
            features.append(min(score, 3) / 3.0)

        # 7-13: Hook pattern matches
        for pattern_name, pattern_re in self.HOOK_PATTERNS:
            match = 1.0 if re.search(pattern_re, topic_lower) else 0.0
            features.append(match)

        # 14: Word count
        features.append(min(len(words), 20) / 20.0)

        # 15: Average word length
        avg_len = np.mean([len(w) for w in words]) if words else 0
        features.append(min(avg_len, 12) / 12.0)

        # 16: First word is "why" (curiosity hook)
        features.append(1.0 if words and words[0] == "why" else 0.0)

        # 17: First word is "your" (personalization)
        features.append(1.0 if words and words[0] == "your" else 0.0)

        # 18: Contains a body part
        features.append(
            sum(1 for bw in self.BODY_WORDS if bw in word_set) / max(len(self.BODY_WORDS) / 3, 1)
        )

        # 19: Power word density
        pw_count = sum(1 for pw in self.POWER_WORDS if pw in topic_lower)
        features.append(min(pw_count, 5) / 5.0)

        # 20: Question mark present (engagement bait?)
        features.append(1.0 if "?" in topic else 0.0)

        # 21: Topic length (characters)
        features.append(min(len(topic), 100) / 100.0)

        # 22-37: N-gram hash features (captures topic specificity)
        bigrams = ["".join(words[i : i + 2]) for i in range(len(words) - 1)]
        for i in range(16):
            if i < len(bigrams):
                h = int(hashlib.md5(bigrams[i].encode()).hexdigest()[:4], 16) % 1000
                features.append(h / 1000.0)
            else:
                features.append(0.0)

        return np.array(features, dtype=np.float64)

    def extract_all(self, topics: List[str]) -> np.ndarray:
        """Batch feature extraction."""
        return np.array([self.extract_from_topic(t) for t in topics], dtype=np.float64)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ML MODELS (Pure NumPy — no sklearn dependency)                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


class RidgeRegression:
    """L2-regularized linear regression with closed-form solution."""

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0
        self.feature_importances: Optional[np.ndarray] = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        n, d = X.shape
        # Normalize targets
        self.y_mean = float(np.mean(y))
        self.y_std = float(np.std(y)) or 1.0
        y_norm = (y - self.y_mean) / self.y_std

        # Closed-form: (X^T X + alpha I)^(-1) X^T y
        I = np.eye(d, dtype=np.float64)
        XtX = X.T @ X
        ridge = XtX + self.alpha * n * I
        try:
            self.weights = np.linalg.solve(ridge, X.T @ y_norm)
        except np.linalg.LinAlgError:
            self.weights = np.linalg.lstsq(ridge, X.T @ y_norm, rcond=None)[0]

        self.bias = self.y_mean - np.mean(X @ self.weights) * self.y_std
        self.feature_importances = np.abs(self.weights) / (np.sum(np.abs(self.weights)) + 1e-10)

    def predict(self, X: np.ndarray) -> np.ndarray:
        raw = X @ self.weights * self.y_std + self.bias
        return np.maximum(raw, 1)  # min 1 view

    def score(self, X: np.ndarray, y: np.ndarray) -> float:
        """R² score."""
        pred = self.predict(X)
        ss_res = np.sum((y - pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2) or 1e-10
        return float(1 - ss_res / ss_tot)


class LogisticClassifier:
    """Logistic regression for viral/not-viral classification."""

    def __init__(self, lr: float = 0.1, epochs: int = 500):
        self.lr = lr
        self.epochs = epochs
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))

    def fit(self, X: np.ndarray, y: np.ndarray):
        n, d = X.shape
        self.weights = np.zeros(d, dtype=np.float64)
        self.bias = 0.0

        for epoch in range(self.epochs):
            z = X @ self.weights + self.bias
            preds = self._sigmoid(z)
            error = preds - y

            # Gradient
            dw = (X.T @ error) / n + 0.01 * self.weights  # L2 reg
            db = np.mean(error)

            self.weights -= self.lr * dw
            self.bias -= self.lr * db

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._sigmoid(X @ self.weights + self.bias)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X) >= 0.5).astype(int)


class TopicClusterer:
    """K-means style clustering for topic grouping."""

    def __init__(self, n_clusters: int = 4):
        self.n_clusters = n_clusters
        self.centroids: Optional[np.ndarray] = None
        self.labels_: Optional[np.ndarray] = None

    def fit(self, X: np.ndarray, max_iters: int = 100):
        n, d = X.shape
        # K-means++ init
        centroids = [X[np.random.randint(n)]]
        for _ in range(1, self.n_clusters):
            dists = np.min([np.sum((X - c) ** 2, axis=1) for c in centroids], axis=0)
            probs = dists / dists.sum()
            centroids.append(X[np.random.choice(n, p=probs)])
        centroids = np.array(centroids)

        for _ in range(max_iters):
            # Assign
            dists = np.array([np.sum((X - c) ** 2, axis=1) for c in centroids])
            labels = np.argmin(dists, axis=0)

            # Update
            new_centroids = np.array([
                X[labels == k].mean(axis=0) if np.sum(labels == k) > 0 else centroids[k]
                for k in range(self.n_clusters)
            ])

            if np.allclose(centroids, new_centroids, rtol=1e-4):
                break
            centroids = new_centroids

        self.centroids = centroids
        self.labels_ = labels


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ML BRAIN — Main Class                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


class MLBrain:
    """
    The learning system that reads everything the channel knows and produces
    predictions the pipeline can act on.
    """

    def __init__(self):
        self.extractor = FeatureExtractor()
        self.views_model: Optional[RidgeRegression] = None
        self.viral_model: Optional[LogisticClassifier] = None
        self.clusterer: Optional[TopicClusterer] = None

        # Learned patterns
        self.topic_clusters: Dict[int, List[str]] = {}
        self.slot_performance: Dict[str, float] = {}
        self.hook_pattern_weights: Dict[str, float] = {}
        self.pillar_performance: Dict[str, Dict] = {}
        self.word_impact: Dict[str, float] = {}
        self.best_word_patterns: List[Tuple[str, float]] = []

        # Stats
        self.trained = False
        self.n_samples = 0
        self.views_r2 = 0.0
        self.viral_accuracy = 0.0

    # ── DATA LOADING ────────────────────────────────────────────────────

    def load_all_data(self) -> Tuple[List[str], List[float], List[float], List[int]]:
        """Load and clean all training data. Returns (topics, views, retention, hook_scores)."""
        if not VIDEO_HISTORY.exists():
            logger.error("No video_history.json found!")
            return [], [], [], []

        with open(VIDEO_HISTORY) as f:
            history = json.load(f)

        topics, views, retention, hook_scores = [], [], [], []
        for v in history:
            topic = v.get("topic", "")
            view_count = v.get("views")
            avp = v.get("average_view_percentage")
            hs = v.get("hook_score")

            if not topic:
                continue
            topics.append(topic)
            views.append(float(view_count) if view_count is not None else 0.0)
            retention.append(float(avp) if avp is not None else 0.0)
            hook_scores.append(int(hs) if hs is not None else 0)

        self.n_samples = len(topics)
        logger.info("Loaded %d videos for training", self.n_samples)
        return topics, views, retention, hook_scores

    def load_slot_data(self) -> Dict[str, float]:
        """Load slot weights from growth_state."""
        if GROWTH_STATE.exists():
            with open(GROWTH_STATE) as f:
                gs = json.load(f)
            self.slot_performance = gs.get("slot_weights", {})
        return self.slot_performance

    def load_topic_catalog(self) -> List[str]:
        """Load the full topic catalog for scoring."""
        catalog_path = DATA_DIR / "body_glitch_topics.json"
        if catalog_path.exists():
            with open(catalog_path) as f:
                data = json.load(f)
            if isinstance(data, list):
                topics = []
                for item in data:
                    if isinstance(item, str):
                        topics.append(item)
                    elif isinstance(item, dict):
                        topics.append(str(item.get("topic", item.get("title", str(item)))))
                    else:
                        topics.append(str(item))
                return topics
            if isinstance(data, dict):
                topics = []
                
                for v in data.values():
                    if isinstance(v, str):
                        topics.append(v)
                    elif isinstance(v, list):
                        topics.extend([t if isinstance(t, str) else str(t) for t in v])
                return topics
        return []

    # ── TRAINING ────────────────────────────────────────────────────────

    def train(self) -> "MLBrain":
        """Full training pipeline."""
        logger.info("=" * 60)
        logger.info("  ML BRAIN TRAINING — Multi-Platform Viral Engine")
        logger.info("=" * 60)

        # 1. Load data
        topics, views, retention, hook_scores = self.load_all_data()
        if len(topics) < 5:
            logger.error(
                "Need at least 5 videos to train. Currently have %d.", len(topics)
            )
            return self

        # 2. Feature extraction
        X = self.extractor.extract_all(topics)
        y_views = np.array(views, dtype=np.float64)
        _ = np.array(retention, dtype=np.float64)  # reserved for future retention model

        # Log-transform views (long-tailed distribution)
        y_views_log = np.log1p(y_views)

        # 3. Train views predictor (Ridge Regression)
        logger.info("\n── Training Views Predictor (Ridge) ──")
        self.views_model = RidgeRegression(alpha=0.5)
        self.views_model.fit(X, y_views_log)
        _ = self.views_model.predict(X)  # used to report residuals if needed
        self.views_r2 = self.views_model.score(X, y_views_log)
        logger.info("  Views R² (log space): %.3f", self.views_r2)
        logger.info("  Top 5 feature importances (views):")
        top_idx = np.argsort(self.views_model.feature_importances)[::-1][:5]
        for idx in top_idx:
            logger.info("    feature_%d: %.3f", idx, self.views_model.feature_importances[idx])

        # 4. Train viral classifier
        logger.info("\n── Training Viral Classifier ──")
        viral_threshold = np.percentile(y_views, VIRAL_PERCENTILE)
        y_viral = (y_views >= viral_threshold).astype(int)
        n_viral = int(np.sum(y_viral))
        logger.info("  Viral threshold: %.0f views (%d/%d viral)", viral_threshold, n_viral, len(y_views))

        if n_viral >= 2 and (len(y_viral) - n_viral) >= 2:
            self.viral_model = LogisticClassifier(lr=0.05, epochs=800)
            self.viral_model.fit(X, y_viral)
            pred_viral = self.viral_model.predict(X)
            self.viral_accuracy = float(np.mean(pred_viral == y_viral))
            logger.info("  Viral classifier accuracy: %.1f%%", self.viral_accuracy * 100)
        else:
            logger.warning("  Not enough viral/non-viral samples for classifier")

        # 5. Topic clustering
        logger.info("\n── Clustering Topics ──")
        self.clusterer = TopicClusterer(n_clusters=min(4, len(topics)))
        self.clusterer.fit(X)

        # Map topics to clusters
        for i, topic in enumerate(topics):
            c = int(self.clusterer.labels_[i])
            if c not in self.topic_clusters:
                self.topic_clusters[c] = []
            self.topic_clusters[c].append(topic)

        for c, tlist in self.topic_clusters.items():
            avg_views = np.mean([
                views[topics.index(t)] for t in tlist if t in topics
            ])
            logger.info("  Cluster %d: %d topics | avg %.0f views | eg: %s",
                       c, len(tlist), avg_views, tlist[0][:50] if tlist else "?")

        # 6. Hook pattern analysis
        logger.info("\n── Analyzing Hook Patterns ──")
        self._analyze_hook_patterns(topics, views)

        # 7. Word-level impact analysis
        logger.info("\n── Word Impact Analysis ──")
        self._analyze_word_impact(topics, views)

        # 8. Pillar performance
        logger.info("\n── Content Pillar Performance ──")
        self._analyze_pillars(topics, views, retention)

        # 9. Slot optimization
        logger.info("\n── Publishing Slot Optimization ──")
        self.load_slot_data()
        best_slot = max(self.slot_performance.items(), key=lambda x: x[1]) if self.slot_performance else ("?", 0)
        logger.info("  Best slot: %s (weight: %.3f)", best_slot[0], best_slot[1])

        self.trained = True
        logger.info("\n✅ Training complete. Models ready for predictions.\n")
        return self

    def _analyze_hook_patterns(self, topics: List[str], views: List[float]):
        """Analyze which hook opening words drive more views."""
        pattern_views = defaultdict(list)
        for topic, v in zip(topics, views):
            first_word = topic.strip().split()[0].lower() if topic.strip() else ""
            pattern_views[first_word].append(v)

        self.hook_pattern_weights = {}
        for pattern, vlist in pattern_views.items():
            if len(vlist) >= 2:
                self.hook_pattern_weights[pattern] = float(np.mean(vlist))

        # Sort and display
        sorted_patterns = sorted(self.hook_pattern_weights.items(),
                                 key=lambda x: x[1], reverse=True)
        for pw, avg_v in sorted_patterns[:8]:
            logger.info("  '%s' → %.0f avg views (%d samples)", pw, avg_v,
                       len(pattern_views[pw]))

    def _analyze_word_impact(self, topics: List[str], views: List[float]):
        """Measure the impact of individual words on view count."""
        word_views = defaultdict(list)
        for topic, v in zip(topics, views):
            words = set(re.findall(r"[a-z]+", topic.lower()))
            for w in words:
                if len(w) >= 4:  # ignore short words
                    word_views[w].append(v)

        # Calculate impact: avg views when word present vs absent
        global_avg = np.mean(views)
        word_impact = {}
        for word, vlist in word_views.items():
            if len(vlist) >= 2:
                impact = float(np.mean(vlist) - global_avg)
                word_impact[word] = impact

        self.word_impact = word_impact
        self.best_word_patterns = sorted(word_impact.items(),
                                         key=lambda x: x[1], reverse=True)[:15]

        for word, impact in self.best_word_patterns[:10]:
            logger.info("  '%s' → %+.0f views (appears in %d topics)",
                       word, impact, len(word_views[word]))

    def _analyze_pillars(self, topics: List[str], views: List[float], retention: List[float]):
        """Analyze which content pillars perform best."""
        pillar_data = defaultdict(lambda: {"views": [], "retention": [], "topics": []})
        for topic, v, r in zip(topics, views, retention):
            topic_lower = topic.lower()
            matched = False
            for pillar, keywords in self.extractor.PILLARS.items():
                if any(kw in topic_lower for kw in keywords):
                    pillar_data[pillar]["views"].append(v)
                    pillar_data[pillar]["retention"].append(r)
                    pillar_data[pillar]["topics"].append(topic)
                    matched = True
                    break
            if not matched:
                pillar_data["other"]["views"].append(v)
                pillar_data["other"]["retention"].append(r)

        self.pillar_performance = {}
        for pillar, data in pillar_data.items():
            if data["views"]:
                self.pillar_performance[pillar] = {
                    "avg_views": float(np.mean(data["views"])),
                    "avg_retention": float(np.mean(data["retention"])),
                    "count": len(data["views"]),
                }
                logger.info("  %-16s → %.0f views | %.1f%% retention | %d topics",
                           pillar,
                           self.pillar_performance[pillar]["avg_views"],
                           self.pillar_performance[pillar]["avg_retention"],
                           self.pillar_performance[pillar]["count"])

    # ── PREDICTION ──────────────────────────────────────────────────────

    def predict_topic(self, topic: str) -> Dict[str, Any]:
        """Score a single topic for viral potential across platforms."""
        if not self.trained:
            return {"error": "ML Brain not trained yet. Run .train() first."}

        X = self.extractor.extract_from_topic(topic).reshape(1, -1)

        result = {"topic": topic}

        # Views prediction
        if self.views_model is not None:
            pred_log = self.views_model.predict(X)[0]
            pred_views = float(np.expm1(pred_log))
            # Confidence interval (simple heuristic)
            pred_lo = float(np.expm1(pred_log - 0.5))
            pred_hi = float(np.expm1(pred_log + 0.5))
            result["predicted_views"] = int(pred_views)
            result["views_range"] = (int(pred_lo), int(pred_hi))

        # Viral probability
        if self.viral_model is not None:
            proba = float(self.viral_model.predict_proba(X)[0])
            result["viral_probability"] = round(proba, 3)
            result["viral_verdict"] = "🔥 HIGH" if proba > 0.66 else (
                "🟡 MEDIUM" if proba > 0.33 else "🔵 LOW"
            )

        # Hook analysis
        first_word = topic.strip().split()[0].lower() if topic.strip() else ""
        if first_word in self.hook_pattern_weights:
            result["hook_pattern_avg_views"] = int(self.hook_pattern_weights[first_word])

        # Word boosts
        words = set(re.findall(r"[a-z]+", topic.lower()))
        boosts = []
        for w in words:
            if w in self.word_impact and self.word_impact[w] > 0:
                boosts.append((w, int(self.word_impact[w])))
        result["positive_word_boosts"] = sorted(boosts, key=lambda x: x[1], reverse=True)[:5]

        # Pillar match
        topic_lower = topic.lower()
        for pillar, keywords in self.extractor.PILLARS.items():
            if any(kw in topic_lower for kw in keywords):
                if pillar in self.pillar_performance:
                    result["pillar"] = pillar
                    result["pillar_avg_views"] = int(
                        self.pillar_performance[pillar]["avg_views"]
                    )
                break

        # Overall score (0-100)
        score = 50  # baseline
        if "predicted_views" in result:
            score += min(result["predicted_views"] / 500 * 30, 30)
        if "viral_probability" in result:
            score += result["viral_probability"] * 20
        result["score"] = min(int(score), 100)

        return result

    def rank_all_topics(self, topics: List[str], top_n: int = 20) -> List[Dict]:
        """Score and rank many topics, returning the best ones."""
        if not self.trained:
            return []

        results = []
        for topic in topics:
            pred = self.predict_topic(topic)
            if "error" not in pred:
                results.append(pred)

        unique_topics = set(); deduped = []; [deduped.append(x) for x in results if x.get("topic") not in unique_topics and not unique_topics.add(x.get("topic"))]
        results = deduped
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:top_n]

    def recommend_publish_strategy(self) -> Dict:
        """Generate a complete publish strategy based on learned patterns."""
        strategy = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_samples": self.n_samples,
            "models_trained": {
                "views_regression": self.views_model is not None,
                "viral_classifier": self.viral_model is not None,
                "topic_clusters": self.clusterer is not None,
            },
            "best_slot": max(self.slot_performance.items(), key=lambda x: x[1])
            if self.slot_performance else ("20:00", 1.0),
            "best_hook_openings": sorted(
                self.hook_pattern_weights.items(), key=lambda x: x[1], reverse=True
            )[:5],
            "best_pillars": sorted(
                self.pillar_performance.items(),
                key=lambda x: x[1]["avg_views"],
                reverse=True,
            )[:3],
            "best_words": self.best_word_patterns[:10],
            "recommended_cadence": 2 if self.n_samples < 30 else 3,
            "youtube_strategy": self._platform_strategy("youtube"),
            "facebook_strategy": self._platform_strategy("facebook"),
            "instagram_strategy": self._platform_strategy("instagram"),
        }
        return strategy

    def _platform_strategy(self, platform: str) -> Dict:
        """Generate per-platform strategy."""
        strategies = {
            "youtube": {
                "ideal_duration": "33-36 seconds",
                "hook_seconds": 2.8,
                "hashtags": ["#shorts", "#science", "#body", "#howitworks"],
                "publish_window": "12:30 / 18:30 / 20:00 NY",
                "cta_style": "loop ending (no spoken CTA)",
                "description": "Keyword-rich, searchable",
            },
            "facebook": {
                "ideal_duration": "24-27 seconds",
                "hook_seconds": 2.0,
                "hashtags": ["#bodyfacts", "#science"],
                "publish_window": "stagger +120min after YT",
                "cta_style": "follow in caption, not audio",
                "description": "UTIS-friendly, plain topic naming",
            },
            "instagram": {
                "ideal_duration": "24-27 seconds",
                "hook_seconds": 2.0,
                "hashtags": ["#bodyfacts", "#dailyscience", "#humanbody"],
                "publish_window": "same as FB",
                "cta_style": "forwardable payoff fact in caption",
                "description": "DM-worthy quotable with sends-per-reach boost",
            },
        }
        return strategies.get(platform, {})

    # ── PERSISTENCE ─────────────────────────────────────────────────────

    def save(self):
        """Save brain state for future use."""
        state = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "n_samples": self.n_samples,
            "views_r2": self.views_r2,
            "viral_accuracy": self.viral_accuracy,
            "hook_pattern_weights": self.hook_pattern_weights,
            "word_impact": {k: float(v) for k, v in list(self.word_impact.items())[:50]},
            "best_word_patterns": [(w, float(i)) for w, i in self.best_word_patterns],
            "pillar_performance": {
                k: {
                    "avg_views": float(v["avg_views"]),
                    "avg_retention": float(v["avg_retention"]),
                    "count": v["count"],
                }
                for k, v in self.pillar_performance.items()
            },
            "slot_performance": self.slot_performance,
            "topic_clusters": {str(k): v for k, v in self.topic_clusters.items()},
        }

        os.makedirs(ML_BRAIN_STATE.parent, exist_ok=True)
        tmp = str(ML_BRAIN_STATE) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, ML_BRAIN_STATE)
        logger.info("Brain state saved → %s", ML_BRAIN_STATE)

    def load(self) -> bool:
        """Load previously saved brain state."""
        if not ML_BRAIN_STATE.exists():
            return False
        with open(ML_BRAIN_STATE) as f:
            state = json.load(f)
        self.n_samples = state.get("n_samples", 0)
        self.views_r2 = state.get("views_r2", 0)
        self.viral_accuracy = state.get("viral_accuracy", 0)
        self.hook_pattern_weights = state.get("hook_pattern_weights", {})
        self.best_word_patterns = [(w, i) for w, i in state.get("best_word_patterns", [])]
        self.word_impact = {k: float(v) for k, v in state.get("word_impact", {}).items()}
        self.pillar_performance = state.get("pillar_performance", {})
        self.slot_performance = state.get("slot_performance", {})
        self.topic_clusters = {int(k): v for k, v in state.get("topic_clusters", {}).items()}
        self.trained = True
        logger.info("Brain state loaded from %s (%d samples)", ML_BRAIN_STATE, self.n_samples)
        return True


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  REPORT GENERATOR                                                          ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


def generate_viral_report(brain: MLBrain) -> str:
    """Generate a human-readable viral growth report."""
    strategy = brain.recommend_publish_strategy()

    report = []
    report.append("=" * 72)
    report.append("  🧬 MrNextep ML BRAIN — Viral Growth Intelligence Report")
    report.append("=" * 72)
    report.append(f"  Generated: {strategy['generated_at'][:19].replace('T', ' ')}")
    report.append(f"  Training Samples: {strategy['n_samples']} videos")
    report.append(f"  Views R²: {brain.views_r2:.3f} | Viral Accuracy: {brain.viral_accuracy:.1%}")
    report.append("")
    report.append("─" * 72)
    report.append("  📈 TOP 10 VIRAL WORD PATTERNS (words that boost views)")
    report.append("─" * 72)
    for word, impact in brain.best_word_patterns[:10]:
        bar = "█" * max(1, int(abs(impact) / 15))
        sign = "+" if impact > 0 else ""
        report.append(f"  {word:<20s} {sign}{impact:+.0f} views  {bar}")
    report.append("")
    report.append("─" * 72)
    report.append("  🎯 BEST HOOK OPENINGS")
    report.append("─" * 72)
    for pattern, avg_v in strategy["best_hook_openings"]:
        report.append(f"  '{pattern}' → {avg_v:.0f} avg views")
    report.append("")
    report.append("─" * 72)
    report.append("  🧠 CONTENT PILLAR RANKINGS")
    report.append("─" * 72)
    for pillar, data in strategy["best_pillars"]:
        report.append(f"  {pillar:<16s} → {data['avg_views']:.0f} views | {data['avg_retention']:.1f}% retention | {data['count']} videos")
    report.append("")
    report.append("─" * 72)
    report.append("  ⏰ OPTIMAL PUBLISHING")
    report.append("─" * 72)
    report.append(f"  Best slot: {strategy['best_slot'][0]} NY (weight: {strategy['best_slot'][1]:.2f})")
    report.append(f"  Recommended cadence: {strategy['recommended_cadence']}/day")
    report.append("")
    for platform, ps in [
        ("YouTube", strategy["youtube_strategy"]),
        ("Facebook", strategy["facebook_strategy"]),
        ("Instagram", strategy["instagram_strategy"]),
    ]:
        report.append(f"  {platform}: {ps.get('ideal_duration','?')}s | hook {ps.get('hook_seconds','?')}s | {ps.get('hashtags',[])}")

    report.append("")
    report.append("=" * 72)
    report.append("  Generated by ml_brain.py — retrain daily with new data")
    report.append("=" * 72)

    return "\n".join(report)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  MAIN / CLI                                                               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


def main():
    import sys

    brain = MLBrain()

    if "--serve" in sys.argv:
        # Interactive mode
        brain.load() or brain.train()
        print("\n🧬 MrNextep ML Brain — Interactive Mode")
        print("   Type a topic to score it, or 'report' for full report, 'quit' to exit.\n")
        while True:
            try:
                cmd = input("ml-brain> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if cmd.lower() in ("quit", "exit", "q"):
                break
            if cmd.lower() == "report":
                print(generate_viral_report(brain))
                continue
            if cmd.lower() == "train":
                brain.train()
                brain.save()
                continue
            if cmd:
                result = brain.predict_topic(cmd)
                print(f"\n📊 {result.get('topic', cmd)[:70]}")
                print(f"   Score: {result.get('score','?')}/100")
                print(f"   Predicted Views: {result.get('predicted_views','?')} (range: {result.get('views_range',('?','?'))})")
                print(f"   Viral: {result.get('viral_verdict','?')} ({result.get('viral_probability',0):.1%})")
                if "positive_word_boosts" in result:
                    boosts = result["positive_word_boosts"]
                    if boosts:
                        print(f"   Word Boosts: {', '.join(f'{w} (+{i})' for w,i in boosts[:5])}")
                if "pillar" in result:
                    print(f"   Pillar: {result['pillar']} (avg {result.get('pillar_avg_views','?')} views)")
                print()
        return

    if "--predict" in sys.argv:
        # Single topic prediction
        idx = sys.argv.index("--predict") + 1
        if idx < len(sys.argv):
            topic = sys.argv[idx]
        else:
            topic = input("Enter topic: ").strip()

        brain.load() or brain.train()
        result = brain.predict_topic(topic)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # Default: full train + report + rank topics
    logger.info("🧬 ML BRAIN — Training on channel data...\n")

    brain.train()
    brain.save()

    print(generate_viral_report(brain))

    # Rank all topics in the catalog
    catalog = brain.load_topic_catalog()
    if catalog:
        logger.info("\n🔮 Ranking %d topics from catalog...", len(catalog))
        ranked = brain.rank_all_topics(catalog, top_n=10)
        print("\n─" * 72)
        print("  🏆 TOP 10 RECOMMENDED TOPICS")
        print("─" * 72)
        for i, r in enumerate(ranked, 1):
            print(f"  {i:2d}. [{r.get('score',0):3d}/100] {r['topic'][:65]}")
            print(f"      ~{r.get('predicted_views','?')} views | Viral: {r.get('viral_probability',0):.0%} | {r.get('viral_verdict','')}")
        print()


if __name__ == "__main__":
    main()
