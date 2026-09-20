"""DeepSeek official Chat Completions adapter (not Responses compatibility)."""

from pydantic import BaseModel, Field, ValidationError

from novelatlas.schemas.models import ModelUsage, TextGenerationResult

from .base import ModelGatewayError
from .openai import _OpenAIProvider


class Message(BaseModel):
    content: str | None = None


class Choice(BaseModel):
    message: Message
    finish_reason: str


class Usage(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class Completion(BaseModel):
    id: str
    model: str
    choices: list[Choice] = Field(min_length=1)
    usage: Usage | None = None


class DeepSeekTextModelProvider(_OpenAIProvider):
    async def generate_text(self, request):
        messages = []
        if request.instructions:
            messages.append({"role": "system", "content": request.instructions})
        messages.append({"role": "user", "content": request.prompt})
        body, header_id = await self._post(
            "chat/completions",
            {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": request.max_output_tokens,
                "stream": False,
                "thinking": {"type": "disabled"},
            },
        )
        try:
            completion = Completion.model_validate(body)
        except ValidationError as error:
            raise ModelGatewayError(
                code="invalid_provider_response",
                message="DeepSeek 返回格式不正确",
                retryable=False,
            ) from error
        choice = completion.choices[0]
        if choice.finish_reason != "stop" or not choice.message.content:
            raise ModelGatewayError(
                code="incomplete_provider_response",
                message="DeepSeek 未返回完整结果，请检查输出预算",
                retryable=False,
            )
        return TextGenerationResult(
            provider="deepseek",
            model=completion.model,
            content=choice.message.content,
            request_id=completion.id or header_id,
            is_mock=False,
            usage=ModelUsage(
                input_tokens=completion.usage.prompt_tokens,
                output_tokens=completion.usage.completion_tokens,
                total_tokens=completion.usage.total_tokens,
            )
            if completion.usage
            else None,
        )
