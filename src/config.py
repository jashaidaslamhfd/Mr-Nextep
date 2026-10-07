"""Configuration for the Mr-Nextep production pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_PRIVACY_STATUSES = ("private", "public", "unlisted")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True, extra="ignore")

    language: str = Field(default="en-US", validation_alias="CHANNEL_LANGUAGE")
    timezone: str = Field(default="America/New_York", validation_alias="PUBLISH_TIMEZONE")
    output_dir: Path = Field(default=Path("output"), validation_alias="OUTPUT_DIR")
    data_dir: Path = Field(default=Path("data"), validation_alias="DATA_DIR")
    dry_run: bool = Field(default=False, validation_alias="DRY_RUN")
    privacy_status: str = Field(default="private", validation_alias="YT_PRIVACY_STATUS")
    schedule_publish: bool = Field(default=True, validation_alias="YT_SCHEDULE_PUBLISH")
    # Real channel median is ~38% viewed. Keep the production target tight.
    min_seconds: float = Field(default=17.5, validation_alias="TARGET_MIN_SECONDS")
    max_seconds: float = Field(default=23.0, validation_alias="TARGET_MAX_SECONDS")
    topic: str = Field(default="", validation_alias="VIDEO_TOPIC")
    max_attempts: int = Field(default=10, validation_alias="MAX_GENERATION_ATTEMPTS")
    duplicate_check_last: int = Field(default=25, validation_alias="DUPLICATE_CHECK_LAST")
    min_publish_gap_hours: float = Field(default=5.0, validation_alias="MIN_PUBLISH_GAP_HOURS")
    schedule_jitter_minutes: int = Field(default=20, validation_alias="SCHEDULE_JITTER_MINUTES")
    max_hashtags: int = Field(default=30, validation_alias="MAX_HASHTAGS")

    def __init__(self, **values: Any) -> None:
        for field_name, field_info in self.__class__.model_fields.items():
            alias = field_info.validation_alias
            if field_name in values and isinstance(alias, str) and alias not in values:
                values[alias] = values.pop(field_name)
        super().__init__(**values)

    @field_validator("privacy_status")
    @classmethod
    def _normalize_privacy(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in VALID_PRIVACY_STATUSES:
            raise ValueError(f"YT_PRIVACY_STATUS must be one of {VALID_PRIVACY_STATUSES}, got {value!r}")
        return normalized

    def check_config(self) -> list[str]:
        errors: list[str] = []
        if self.max_seconds < self.min_seconds:
            errors.append(f"TARGET_MAX_SECONDS ({self.max_seconds}) must be >= TARGET_MIN_SECONDS ({self.min_seconds})")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            errors.append(f"PUBLISH_TIMEZONE is invalid: {self.timezone}")
        if self.max_attempts < 1:
            errors.append(f"MAX_GENERATION_ATTEMPTS must be >= 1, got {self.max_attempts}")
        return errors

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


SETTINGS = Settings()
