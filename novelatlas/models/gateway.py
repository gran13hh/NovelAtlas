"""Text-model provider selection with bounded retry behavior."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar
from urllib.parse import urlsplit

import httpx

from novelatlas.schemas.models import (
    ModelGatewayStatus,
    ModelProviderStatus,
    TextGenerationRequest,
    TextGenerationResult,
)

from .base import (
    ModelConfigurationError,
    ModelGatewayError,
    ProviderConfig,
    TextModelProvider,
)
from .deepseek import DeepSeekTextModelProvider
from .mock import MockTextModelProvider
from .openai import OpenAIModelCatalog, OpenAITextModelProvider

ResultT = TypeVar("ResultT")


class ModelGateway:
    """Expose text generation without leaking provider details."""

    def __init__(
        self,
        *,
        text: ProviderConfig,
        timeout_seconds: float,
        max_retries: int,
        retry_base_delay_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        observer: Callable[[dict], None] | None = None,
    ) -> None:
        self.text_config = text
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.transport = transport
        self.observer = observer

    def with_observer(self, observer):
        return ModelGateway(
            text=self.text_config,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            retry_base_delay_seconds=self.retry_base_delay_seconds,
            transport=self.transport,
            observer=observer,
        )

    @property
    def status(self) -> ModelGatewayStatus:
        return ModelGatewayStatus(
            text=self._provider_status(self.text_config),
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
        )

    async def generate_text(
        self,
        request: TextGenerationRequest,
    ) -> TextGenerationResult:
        provider = self._text_provider()
        return await self._with_retries(lambda: provider.generate_text(request))

    async def list_models(self) -> list[str]:
        """List model IDs visible to the configured text provider."""

        config = self.text_config
        if config.provider == "mock":
            return [config.model]
        if config.provider in {"openai", "deepseek"}:
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
        if self.text_config.provider == "deepseek":
            return DeepSeekTextModelProvider(
                self.text_config,
                timeout_seconds=self.timeout_seconds,
                transport=self.transport,
            )
        if self.text_config.provider == "openai":
            return OpenAITextModelProvider(
                self.text_config,
                timeout_seconds=self.timeout_seconds,
                transport=self.transport,
            )
        raise ModelConfigurationError("不支持的文本模型供应商")

    async def _with_retries(
        self,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                try:
                    async with asyncio.timeout(self.timeout_seconds):
                        result = await operation()
                except TimeoutError as timeout:
                    raise ModelGatewayError(
                        code="provider_timeout",
                        message="模型供应商请求超时",
                        retryable=True,
                    ) from timeout
                if self.observer:
                    self.observer(
                        {
                            "attempt": attempt + 1,
                            "status": "completed",
                            "duration_ms": round(
                                (time.perf_counter() - started) * 1000, 2
                            ),
                        }
                    )
                return result
            except ModelGatewayError as error:
                if self.observer:
                    self.observer(
                        {
                            "attempt": attempt + 1,
                            "status": "failed",
                            "error_code": error.code,
                            "duration_ms": round(
                                (time.perf_counter() - started) * 1000, 2
                            ),
                        }
                    )
                if not error.retryable or attempt >= self.max_retries:
                    raise
                delay = self.retry_base_delay_seconds * (2**attempt)
                if delay:
                    await asyncio.sleep(delay)
        raise AssertionError("retry loop exited unexpectedly")

    @staticmethod
    def _provider_status(
        config: ProviderConfig,
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
            missing.append("NOVELATLAS_TEXT_MODEL_API_KEY")
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
            provider=config.provider,
            model=config.model,
            base_url=config.base_url if base_url_is_safe else None,
            configured=not missing,
            is_mock=False,
            missing_settings=missing,
        )
