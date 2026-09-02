"""Environment-backed API settings."""

from pydantic import Field, model_validator
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
    tokenizer_name: str = Field(default="o200k_base", min_length=1)
    chunk_max_tokens: int = Field(default=6000, ge=32)
    chunk_overlap_tokens: int = Field(default=300, ge=0)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        """Keep sliding windows progressing for every configured chunk size."""

        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_max_tokens")
        return self
