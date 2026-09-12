from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SETTINGS  # noqa: E402

errors = SETTINGS.check_config()
if not shutil.which("ffmpeg"):
    errors.append("ffmpeg is required")
if not shutil.which("ffprobe"):
    errors.append("ffprobe is required")
if errors:
    print({"ok": False, "errors": errors})
    raise SystemExit(1)
print({"ok": True, "errors": []})
