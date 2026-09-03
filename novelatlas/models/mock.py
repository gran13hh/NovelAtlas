"""Deterministic model providers for local workflows and automated tests."""

from hashlib import sha256

from novelatlas.schemas.models import (
    ModelUsage,
    TextGenerationRequest,
    TextGenerationResult,
)

from .base import ProviderConfig


class MockTextModelProvider:
    """Return stable metadata without sending novel content over the network."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def generate_text(
        self,
        request: TextGenerationRequest,
    ) -> TextGenerationResult:
        fingerprint = sha256(request.prompt.encode()).hexdigest()[:12]
        input_tokens = max(1, len(request.prompt) // 2)
        content = (
            "NovelAtlas Mock 文本模型响应：模型网关工作正常；"
            f"已接收 {len(request.prompt)} 个字符，指纹 {fingerprint}。"
        )
        output_tokens = max(1, len(content) // 2)
        return TextGenerationResult(
            provider="mock",
            model=self.config.model,
            content=content,
            request_id=f"mock_text_{fingerprint}",
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            is_mock=True,
        )
