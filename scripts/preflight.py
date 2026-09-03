from __future__ import annotations
import shutil, sys
sys.path.insert(0, 'src')
from config import SETTINGS
errors = SETTINGS.validate()
if not shutil.which('ffmpeg'): errors.append('ffmpeg is required')
if not shutil.which('ffprobe'): errors.append('ffprobe is required')
if errors:
    print({'ok': False, 'errors': errors}); raise SystemExit(1)
print({'ok': True, 'errors': []})
