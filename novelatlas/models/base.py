"""Interfaces and normalized failures shared by every model provider."""

from dataclasses import dataclass, field
from typing import Protocol

from novelatlas.schemas.models import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ModelProviderName,
    TextGenerationRequest,
    TextGenerationResult,
)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Private runtime configuration for one provider capability."""

    provider: ModelProviderName
    model: str
    base_url: str
    api_key: str | None = field(repr=False)


class ModelGatewayError(RuntimeError):
    """A safe, provider-neutral model failure exposed to API callers."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


class ModelConfigurationError(ModelGatewayError):
    """Raised before a request when required provider settings are missing."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code="model_not_configured",
            message=message,
            retryable=False,
        )


class TextModelProvider(Protocol):
    """Capability required by analysis and writing agents."""

    async def generate_text(
        self,
        request: TextGenerationRequest,
    ) -> TextGenerationResult: ...


class ImageModelProvider(Protocol):
    """Capability required by character and map generation tools."""

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult: ...
