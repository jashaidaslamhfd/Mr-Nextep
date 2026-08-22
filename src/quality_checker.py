"""
Quality Checker Module for SKILLOR Pipeline
--------------------------------------------
Validates a generated script for structural completeness and
retention potential BEFORE it proceeds to image/voice/video
generation. Used by main.py as:

    from quality_checker import QualityChecker
    self.quality_checker = QualityChecker()
    quality_result = self.quality_checker.check_script_quality(script_data)

quality_result looks like:
    {
        'approved': bool,
        'scores': {
            'overall_quality': int (0-100),
            'retention_score': int (0-100),
            'is_viral_ready': bool,
            'scenes': int,
            'word_count': int,
        },
        'issues': [str, ...],       # structural problems (missing fields, etc.)
        'suggestions': [str, ...],  # retention improvement suggestions
    }
"""

import logging
import os
from typing import Dict

from script_generator import (
    _validate_script,
    analyze_retention_potential,
)

logger = logging.getLogger(__name__)

# Minimum overall_quality score (0-100) required for a script to be approved.
# Overridable via the QUALITY_APPROVAL_THRESHOLD env var (falls back to 60).
try:
    APPROVAL_THRESHOLD = int(os.environ.get("QUALITY_APPROVAL_THRESHOLD", "60"))
except ValueError:
    APPROVAL_THRESHOLD = 60


class QualityChecker:
    """
    Single quality gate combining:
      1. Structural validation (required fields, scene count, word count)
      2. Retention potential scoring (hook strength, cliffhangers, "you"
         language, pacing, etc.)
    """

    def __init__(self, approval_threshold: int = APPROVAL_THRESHOLD):
        self.approval_threshold = approval_threshold

    def check_script_quality(self, script_data: Dict, lenient: bool = False) -> Dict:
        if not script_data:
            return {
                'approved': False,
                'scores': {'overall_quality': 0},
                'issues': ['Empty script data'],
                'suggestions': [],
            }

        # --- 1. Structural validation ---
        try:
            is_valid, issues = _validate_script(script_data, lenient=lenient)
            if lenient:
                # 2026-08-17 LLM-outage fallback: _validate_script already
                # downgrades the explicitly subjective story-arc issues in
                # lenient mode. Preserve its boolean result and issue list so
                # malformed scripts remain blocked; the fallback is only for
                # structurally complete, spam-clean scripts.
                pass
        except Exception as e:
            logger.error(f"Script structural validation failed: {e}")
            is_valid, issues = False, [f"Validation error: {e}"]

        # --- 2. Retention potential scoring ---
        try:
            retention = analyze_retention_potential(script_data)
        except Exception as e:
            logger.error(f"Retention analysis failed: {e}")
            retention = {
                'retention_score': 0,
                'suggestions': [f"Retention analysis error: {e}"],
                'scenes': len(script_data.get('scenes', [])),
                'word_count': len(script_data.get('voiceover', '').split()),
                'is_viral_ready': False,
            }

        overall_quality = retention.get('retention_score', 0)

        # Hard structural failures cap the score regardless of retention score,
        # so a script missing required fields can never be "approved".
        if not is_valid:
            overall_quality = min(overall_quality, 40)
        # In lenient (fallback) mode cap below the normal quality bar so a
        # free-model outage script never pretends to be premium. It still has a
        # separate, explicit floor: the fallback is reachable only for a
        # structurally valid script with a decent retention score.
        lenient_threshold = max(45, self.approval_threshold - 15)
        if lenient:
            overall_quality = min(overall_quality, max(0, self.approval_threshold - 1))

        approved = is_valid and (
            overall_quality >= self.approval_threshold
            or (lenient and overall_quality >= lenient_threshold)
        )

        scores = {
            'overall_quality': overall_quality,
            'retention_score': retention.get('retention_score', 0),
            'is_viral_ready': retention.get('is_viral_ready', False),
            'scenes': retention.get('scenes', len(script_data.get('scenes', []))),
            'word_count': retention.get('word_count', 0),
        }

        if not is_valid:
            logger.warning(f"Script failed structural validation: {issues}")
        else:
            logger.info(
                f"Script quality check: overall={overall_quality}, approved={approved}"
            )

        return {
            'approved': approved,
            'scores': scores,
            'issues': issues,
            'suggestions': retention.get('suggestions', []),
        }
