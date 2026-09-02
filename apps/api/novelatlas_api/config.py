"""Environment-backed API settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings that are safe to configure without code changes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NOVELATLAS_",
        extra="ignore",
    )

    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    upload_ttl_seconds: int = Field(default=60 * 60, ge=1)
    cleanup_interval_seconds: int = Field(default=60, ge=1)
