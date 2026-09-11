from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from os import getenv


class Settings(BaseSettings):
    language: str = Field(default="en-US")
    timezone: str = Field(default="America/New_York")
    output_dir: Path = Field(default_factory=lambda: Path(getenv("OUTPUT_DIR", "output")))
    data_dir: Path = Field(default_factory=lambda: Path(getenv("DATA_DIR", "data")))
    dry_run: bool = Field(default=False)
    privacy_status: str = Field(default="private")
    schedule_publish: bool = Field(default=True)
    min_seconds: float = Field(default=15.0)
    max_seconds: float = Field(default=30.0)
    topic: str = Field(default="")
    max_attempts: int = Field(default=10)
    # Number of recent videos to compare against for duplicate detection
    duplicate_check_last: int = Field(default=10)
    # Default jitter in minutes to apply when scheduling publish times (US peak windows)
    schedule_jitter_minutes: int = Field(default=20)

    class Config:
        env_prefix = ""
        case_sensitive = False

    def __init__(self, **data):
        # Load from environment variables
        env_data = {
            "language": getenv("CHANNEL_LANGUAGE", "en-US"),
            "timezone": getenv("PUBLISH_TIMEZONE", "America/New_York"),
            "output_dir": getenv("OUTPUT_DIR", "output"),
            "data_dir": getenv("DATA_DIR", "data"),
            "dry_run": getenv("DRY_RUN", "false").lower() == "true",
            "privacy_status": getenv("YT_PRIVACY_STATUS", "private"),
            "schedule_publish": getenv("YT_SCHEDULE_PUBLISH", "true").lower() == "true",
            "min_seconds": float(getenv("TARGET_MIN_SECONDS", "15")),
            "max_seconds": float(getenv("TARGET_MAX_SECONDS", "30")),
            "topic": getenv("VIDEO_TOPIC", ""),
            "max_attempts": int(getenv("MAX_GENERATION_ATTEMPTS", "10")),
            "duplicate_check_last": int(getenv("DUPLICATE_CHECK_LAST", "10")),
            "schedule_jitter_minutes": int(getenv("SCHEDULE_JITTER_MINUTES", "20")),
        }
        env_data.update(data)
        super().__init__(**env_data)


settings = Settings()
