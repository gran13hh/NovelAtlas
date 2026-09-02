"""Schemas shared by model providers, the gateway, and public API routes."""

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

ModelProviderName = Literal["mock", "openai"]


class ModelUsage(BaseModel):
    """Normalized token usage when a provider supplies it."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class TextGenerationRequest(BaseModel):
    """Provider-neutral text generation input."""

    prompt: str = Field(min_length=1, max_length=200_000)
    instructions: str | None = Field(default=None, max_length=20_000)
    max_output_tokens: int = Field(default=512, ge=1, le=32_000)

    @model_validator(mode="after")
    def reject_blank_input(self) -> "TextGenerationRequest":
        if not self.prompt.strip():
            raise ValueError("prompt cannot contain only whitespace")
        if self.instructions is not None and not self.instructions.strip():
            self.instructions = None
        return self


class TextGenerationResult(BaseModel):
    """Normalized text returned by any configured provider."""

    provider: ModelProviderName
    model: str
    content: str = Field(min_length=1)
    request_id: str | None = None
    usage: ModelUsage | None = None
    is_mock: bool


class ImageGenerationRequest(BaseModel):
    """Provider-neutral first-pass image generation input."""

    prompt: str = Field(min_length=1, max_length=20_000)
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1024x1024"

    @model_validator(mode="after")
    def reject_blank_prompt(self) -> "ImageGenerationRequest":
        if not self.prompt.strip():
            raise ValueError("prompt cannot contain only whitespace")
        return self


class ImageGenerationResult(BaseModel):
    """Normalized image payload or temporary provider URL."""

    provider: ModelProviderName
    model: str
    request_id: str | None = None
    image_base64: str | None = None
    image_url: str | None = None
    revised_prompt: str | None = None
    is_mock: bool

    @model_validator(mode="after")
    def require_one_image_reference(self) -> "ImageGenerationResult":
        if self.image_base64 is None and self.image_url is None:
            raise ValueError("image provider returned no image reference")
        return self


class ModelProviderStatus(BaseModel):
    """Public, secret-free configuration for one model capability."""

    provider: ModelProviderName
    model: str
    base_url: str | None
    configured: bool
    is_mock: bool
    missing_settings: list[str]


class ModelGatewayStatus(BaseModel):
    """Public model configuration; API keys are deliberately excluded."""

    text: ModelProviderStatus
    image: ModelProviderStatus
    timeout_seconds: float
    max_retries: int


class BrowserModelConnectionConfig(BaseModel):
    """Credentials supplied transiently to discover provider-visible models."""

    provider: ModelProviderName
    base_url: str = Field(min_length=1, max_length=2_000)
    api_key: SecretStr | None = None


class BrowserModelConfig(BrowserModelConnectionConfig):
    """Browser-local connection plus the model selected for an actual call."""

    model: str = Field(min_length=1, max_length=200)


class ModelCatalogRequest(BaseModel):
    """Request available model IDs using one browser-supplied connection."""

    config: BrowserModelConnectionConfig


class ModelCatalogResult(BaseModel):
    """Model IDs returned by the configured provider."""

    provider: ModelProviderName
    models: list[str]


class BrowserTextModelTestRequest(BaseModel):
    """Transient browser configuration plus a text connection test."""

    config: BrowserModelConfig
    request: TextGenerationRequest


class BrowserImageModelTestRequest(BaseModel):
    """Transient browser configuration plus an image connection test."""

    config: BrowserModelConfig
    request: ImageGenerationRequest
