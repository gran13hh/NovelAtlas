"""Environment-backed API settings."""

from typing import Literal

from pydantic import Field, SecretStr, model_validator
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

    analysis_context_window_tokens: int = Field(default=128_000, ge=512)
    analysis_max_input_tokens: int = Field(default=24_000, ge=128)
    analysis_output_reserve_tokens: int = Field(default=4_000, ge=32, le=32_000)
    analysis_safety_margin_tokens: int = Field(default=2_000, ge=512)

    text_model_provider: Literal["mock", "openai"] = "mock"
    text_model_name: str = Field(default="novelatlas-mock-text", min_length=1)
    text_model_base_url: str = Field(
        default="https://api.openai.com/v1",
        min_length=1,
    )
    text_model_api_key: SecretStr | None = None

    model_timeout_seconds: float = Field(default=60, gt=0, le=600)
    model_max_retries: int = Field(default=2, ge=0, le=5)
    model_retry_base_delay_seconds: float = Field(default=0.25, ge=0, le=10)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        """Keep sliding windows progressing for every configured chunk size."""

        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_max_tokens")
        if (
            self.analysis_output_reserve_tokens
            + self.analysis_safety_margin_tokens
            >= self.analysis_context_window_tokens
        ):
            raise ValueError(
                "analysis output reserve and safety margin must fit the context window"
            )
        available_content_tokens = min(
            self.analysis_max_input_tokens,
            self.analysis_context_window_tokens
            - self.analysis_output_reserve_tokens,
        ) - self.analysis_safety_margin_tokens
        if available_content_tokens < 64:
            raise ValueError("analysis settings leave fewer than 64 content tokens")
        return self
