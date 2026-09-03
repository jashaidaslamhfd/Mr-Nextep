from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

def env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()

@dataclass
class Settings:
    language: str = env("CHANNEL_LANGUAGE", "en-US")
    timezone: str = env("PUBLISH_TIMEZONE", "America/New_York")
    output_dir: Path = Path(env("OUTPUT_DIR", "output"))
    data_dir: Path = Path(env("DATA_DIR", "data"))
    dry_run: bool = env("DRY_RUN", "false").lower() == "true"
    privacy_status: str = env("YT_PRIVACY_STATUS", "private")
    schedule_publish: bool = env("YT_SCHEDULE_PUBLISH", "true").lower() == "true"
    min_seconds: float = float(env("TARGET_MIN_SECONDS", "15"))
    max_seconds: float = float(env("TARGET_MAX_SECONDS", "30"))
    topic: str = env("VIDEO_TOPIC")
    @property
    def youtube_ready(self) -> bool:
        return all(env(k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "REFRESH_TOKEN"))
    @property
    def llm_ready(self) -> bool:
        return any(env(k) for k in ("GROQ_API_KEY", "OPENROUTER_API_KEY"))
    def validate(self) -> list[str]:
        errors = []
        if not 0 < self.min_seconds < self.max_seconds <= 60: errors.append("TARGET_MIN_SECONDS/TARGET_MAX_SECONDS must be within 60 seconds")
        if self.privacy_status not in {"private", "unlisted", "public"}: errors.append("YT_PRIVACY_STATUS must be private, unlisted, or public")
        if self.schedule_publish and self.privacy_status != "private": errors.append("Scheduled publication requires YT_PRIVACY_STATUS=private")
        if not self.dry_run and not self.youtube_ready: errors.append("YouTube OAuth secrets are required outside dry-run mode")
        return errors
    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True); self.data_dir.mkdir(parents=True, exist_ok=True)
SETTINGS = Settings()
