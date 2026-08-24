"""
MrNextep — Standalone utility scripts
======================================

These scripts are meant to be run directly from the command line,
NOT imported by the main pipeline.  Each has its own ``sys.path``
setup so it works when invoked as::

    python scripts/generate_fallback_images.py --count 100
    python scripts/fix_voice_reference.py
"""

__all__: list[str] = []
