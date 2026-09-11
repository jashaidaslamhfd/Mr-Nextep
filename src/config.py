from pydantic_settings import BaseSettings
from pathlib import Path
from os import environ as env


class Settings(BaseSettings):
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
    max_attempts: int = int(env("MAX_GENERATION_ATTEMPTS", "10"))
    # Number of recent videos to compare against for duplicate detection
    duplicate_check_last: int = int(env("DUPLICATE_CHECK_LAST", "10"))
    # Default jitter in minutes to apply when scheduling publish times (US peak windows)
    schedule_jitter_minutes: int = int(env("SCHEDULE_JITTER_MINUTES", "20"))


settings = Settings()
