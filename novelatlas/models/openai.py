"""OpenAI Responses and Image API provider adapters."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from novelatlas.schemas.models import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ModelUsage,
    TextGenerationRequest,
    TextGenerationResult,
)

from .base import ModelConfigurationError, ModelGatewayError, ProviderConfig


class _OpenAIProvider:
    def __init__(
        self,
        config: ProviderConfig,
        *,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not config.api_key:
            raise ModelConfigurationError("OpenAI 模型缺少 API Key")
        parsed_base_url = urlsplit(config.base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ModelConfigurationError("OpenAI Base URL 必须是有效的 HTTP(S) 地址")
        if (
            parsed_base_url.username
            or parsed_base_url.password
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ModelConfigurationError("OpenAI Base URL 不能包含凭据、查询参数或片段")
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=dict(payload) if payload is not None else None,
                )
        except httpx.TimeoutException as error:
            raise ModelGatewayError(
                code="provider_timeout",
                message="模型供应商请求超时",
                retryable=True,
            ) from error
        except httpx.RequestError as error:
            raise ModelGatewayError(
                code="provider_unreachable",
                message="无法连接模型供应商",
                retryable=True,
            ) from error

        if response.is_error:
            raise self._response_error(response)
        try:
            body = response.json()
        except ValueError as error:
            raise ModelGatewayError(
                code="invalid_provider_response",
                message="模型供应商返回了无效 JSON",
                retryable=False,
                status_code=response.status_code,
            ) from error
        if not isinstance(body, dict):
            raise ModelGatewayError(
                code="invalid_provider_response",
                message="模型供应商返回格式不正确",
                retryable=False,
                status_code=response.status_code,
            )
        return body, response.headers.get("x-request-id")

    async def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        return await self._request("POST", path, payload)

    async def _get(self, path: str) -> tuple[dict[str, Any], str | None]:
        return await self._request("GET", path)

    @staticmethod
    def _response_error(response: httpx.Response) -> ModelGatewayError:
        status = response.status_code
        retryable = status == 429 or status >= 500
        messages = {
            400: "模型供应商拒绝了请求参数",
            401: "模型供应商认证失败，请检查 API Key",
            403: "模型供应商拒绝访问，请检查模型权限",
            404: "模型或 API 地址不存在",
            429: "模型供应商请求过于频繁",
        }
        message = messages.get(
            status,
            "模型供应商暂时不可用" if status >= 500 else "模型供应商请求失败",
        )
        return ModelGatewayError(
            code=f"provider_http_{status}",
            message=message,
            retryable=retryable,
            status_code=status,
        )


class OpenAITextModelProvider(_OpenAIProvider):
    """Generate text through the OpenAI Responses API."""

    async def generate_text(
        self,
        request: TextGenerationRequest,
    ) -> TextGenerationResult:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "input": request.prompt,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
        }
        if request.instructions:
            payload["instructions"] = request.instructions

        body, header_request_id = await self._post("responses", payload)
        content = self._response_text(body)
        usage_payload = body.get("usage")
        usage = (
            ModelUsage(
                input_tokens=usage_payload.get("input_tokens"),
                output_tokens=usage_payload.get("output_tokens"),
                total_tokens=usage_payload.get("total_tokens"),
            )
            if isinstance(usage_payload, dict)
            else None
        )
        return TextGenerationResult(
            provider="openai",
            model=str(body.get("model") or self.config.model),
            content=content,
            request_id=str(body.get("id") or header_request_id or "") or None,
            usage=usage,
            is_mock=False,
        )

    @staticmethod
    def _response_text(body: dict[str, Any]) -> str:
        direct = body.get("output_text")
        if isinstance(direct, str) and direct:
            return direct

        fragments: list[str] = []
        output = body.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                contents = item.get("content")
                if not isinstance(contents, list):
                    continue
                for content in contents:
                    if (
                        isinstance(content, dict)
                        and content.get("type") == "output_text"
                        and isinstance(content.get("text"), str)
                    ):
                        fragments.append(content["text"])
        if fragments:
            return "\n".join(fragments)
        raise ModelGatewayError(
            code="empty_provider_response",
            message="文本模型没有返回可用内容",
            retryable=False,
        )


class OpenAIImageModelProvider(_OpenAIProvider):
    """Generate one image through the OpenAI Image API."""

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        body, header_request_id = await self._post(
            "images/generations",
            {
                "model": self.config.model,
                "prompt": request.prompt,
                "size": request.size,
                "n": 1,
            },
        )
        data = body.get("data")
        first = data[0] if isinstance(data, list) and data else None
        if not isinstance(first, dict):
            raise ModelGatewayError(
                code="empty_provider_response",
                message="图片模型没有返回可用内容",
                retryable=False,
            )
        image_base64 = first.get("b64_json")
        image_url = first.get("url")
        return ImageGenerationResult(
            provider="openai",
            model=self.config.model,
            request_id=header_request_id,
            image_base64=image_base64 if isinstance(image_base64, str) else None,
            image_url=image_url if isinstance(image_url, str) else None,
            revised_prompt=(
                first.get("revised_prompt")
                if isinstance(first.get("revised_prompt"), str)
                else None
            ),
            is_mock=False,
        )


class OpenAIModelCatalog(_OpenAIProvider):
    """List model IDs available to the configured OpenAI-compatible key."""

    async def list_models(self) -> list[str]:
        body, _request_id = await self._get("models")
        data = body.get("data")
        if not isinstance(data, list):
            raise ModelGatewayError(
                code="invalid_provider_response",
                message="模型供应商没有返回模型列表",
                retryable=False,
            )
        model_ids = sorted(
            {
                item["id"]
                for item in data
                if isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and item["id"]
            }
        )
        if not model_ids:
            raise ModelGatewayError(
                code="empty_provider_response",
                message="当前 API Key 没有可用模型",
                retryable=False,
            )
        return model_ids
