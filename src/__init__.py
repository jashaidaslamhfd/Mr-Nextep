"""
MrNextep — Automated YouTube Shorts pipeline (US audience)
==========================================================

Generates body-science Shorts end-to-end and auto-publishes at US peak times:
  Script → Images → Voice → Video → SEO → Upload (scheduled via publishAt)

Public API
----------
Main pipeline entry point::

    from src import NextepPipeline
    pipeline = NextepPipeline()
    pipeline.run_pipeline(topic="Why Your Brain Lies to You")

Granular access still works::

    from src.script_generator import generate_script
    from src.image_providers import available_providers
"""

__version__ = "1.1.0"
__author__ = "jashaidaslamhfd"


_LAZY_EXPORTS = {
    # Pipeline
    "NextepPipeline": "src.main",
    # Script
    "generate_script": "src.script_generator",
    # Image
    "available_providers": "src.image_providers",
    "RateLimitError": "src.image_providers",
    # Voice
    "generate_voice_segments": "src.voice_generator",
    "generate_voice": "src.voice_generator",
    # Video
    "build_video": "src.video_editor",
    "generate_thumbnail": "src.video_editor",
    # Upload
    "upload_all": "src.uploader",
    # Niche / SEO
    "get_random_topic": "src.niche_strategy",
    "get_topic_category": "src.niche_strategy",
    "generate_seo_tags": "src.niche_strategy",
    "generate_seo_package": "src.seo_generator",
    # Quality / Spam
    "QualityChecker": "src.quality_checker",
    "USAPeakTimeScheduler": "src.scheduler",
    "AntiSpamSystem": "src.anti_spam",
    # Analytics
    "predict_ctr": "src.seo_analytics",
    "score_thumbnail": "src.seo_analytics",
    # Shorts
    "build_shorts_report": "src.shorts_enhancer",
    "generate_srt": "src.shorts_enhancer",
    # Validation
    "validate_scene_image": "src.media_validator",
    "probe_video": "src.media_validator",
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name):
    """Resolve public API names on first access (PEP 562)."""
    if name in _LAZY_EXPORTS:
        import importlib
        import os
        import sys
        # Modules inside src/ use flat sibling imports (`from seo_generator
        # import ...`), which only resolve with src/ itself on sys.path —
        # same trick src/main.py has always used.
        _src_dir = os.path.dirname(os.path.abspath(__file__))
        if _src_dir not in sys.path:
            sys.path.insert(0, _src_dir)
        module = importlib.import_module(_LAZY_EXPORTS[name])
        attr = getattr(module, name)
        globals()[name] = attr  # cache for subsequent lookups
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
