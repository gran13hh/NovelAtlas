"""Capability-based provider selection with bounded retry behavior."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar
from urllib.parse import urlsplit

import httpx

from novelatlas.schemas.models import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ModelGatewayStatus,
    ModelProviderStatus,
    TextGenerationRequest,
    TextGenerationResult,
)

from .base import (
    ImageModelProvider,
    ModelConfigurationError,
    ModelGatewayError,
    ProviderConfig,
    TextModelProvider,
)
from .mock import MockImageModelProvider, MockTextModelProvider
from .openai import (
    OpenAIImageModelProvider,
    OpenAIModelCatalog,
    OpenAITextModelProvider,
)

ResultT = TypeVar("ResultT")


class ModelGateway:
    """Expose text and image capabilities without leaking provider details."""

    def __init__(
        self,
        *,
        text: ProviderConfig,
        image: ProviderConfig,
        timeout_seconds: float,
        max_retries: int,
        retry_base_delay_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.text_config = text
        self.image_config = image
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.transport = transport

    @property
    def status(self) -> ModelGatewayStatus:
        return ModelGatewayStatus(
            text=self._provider_status(self.text_config, "TEXT_MODEL_API_KEY"),
            image=self._provider_status(self.image_config, "IMAGE_MODEL_API_KEY"),
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
        )

    async def generate_text(
        self,
        request: TextGenerationRequest,
    ) -> TextGenerationResult:
        provider = self._text_provider()
        return await self._with_retries(lambda: provider.generate_text(request))

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        provider = self._image_provider()
        return await self._with_retries(lambda: provider.generate_image(request))

    async def list_models(self, capability: str) -> list[str]:
        """List provider-visible model IDs for a text or image configuration."""

        config = self.text_config if capability == "text" else self.image_config
        if config.provider == "mock":
            return [config.model]
        if config.provider == "openai":
            catalog = OpenAIModelCatalog(
                config,
                timeout_seconds=self.timeout_seconds,
                transport=self.transport,
            )
            return await self._with_retries(catalog.list_models)
        raise ModelConfigurationError("不支持的模型供应商")

    def _text_provider(self) -> TextModelProvider:
        if self.text_config.provider == "mock":
            return MockTextModelProvider(self.text_config)
        if self.text_config.provider == "openai":
            return OpenAITextModelProvider(
                self.text_config,
                timeout_seconds=self.timeout_seconds,
                transport=self.transport,
            )
        raise ModelConfigurationError("不支持的文本模型供应商")

    def _image_provider(self) -> ImageModelProvider:
        if self.image_config.provider == "mock":
            return MockImageModelProvider(self.image_config)
        if self.image_config.provider == "openai":
            return OpenAIImageModelProvider(
                self.image_config,
                timeout_seconds=self.timeout_seconds,
                transport=self.transport,
            )
        raise ModelConfigurationError("不支持的图片模型供应商")

    async def _with_retries(
        self,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        for attempt in range(self.max_retries + 1):
            try:
                return await operation()
            except ModelGatewayError as error:
                if not error.retryable or attempt >= self.max_retries:
                    raise
                delay = self.retry_base_delay_seconds * (2**attempt)
                if delay:
                    await asyncio.sleep(delay)
        raise AssertionError("retry loop exited unexpectedly")

    @staticmethod
    def _provider_status(
        config: ProviderConfig,
        api_key_setting: str,
    ) -> ModelProviderStatus:
        if config.provider == "mock":
            return ModelProviderStatus(
                provider="mock",
                model=config.model,
                base_url=None,
                configured=True,
                is_mock=True,
                missing_settings=[],
            )

        missing: list[str] = []
        if not config.api_key:
            missing.append(f"NOVELATLAS_{api_key_setting}")
        if not config.model:
            missing.append("model name")
        parsed_base_url = urlsplit(config.base_url)
        base_url_is_safe = (
            parsed_base_url.scheme in {"http", "https"}
            and bool(parsed_base_url.netloc)
            and parsed_base_url.username is None
            and parsed_base_url.password is None
            and not parsed_base_url.query
            and not parsed_base_url.fragment
        )
        if not base_url_is_safe:
            missing.append("HTTP(S) base URL")
        return ModelProviderStatus(
            provider="openai",
            model=config.model,
            base_url=config.base_url if base_url_is_safe else None,
            configured=not missing,
            is_mock=False,
            missing_settings=missing,
        )
