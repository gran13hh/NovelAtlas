"""Secret-free model status and explicit connection-test endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException

from novelatlas.models import (
    ModelConfigurationError,
    ModelGateway,
    ModelGatewayError,
    ProviderConfig,
)
from novelatlas.schemas.models import (
    BrowserImageModelTestRequest,
    BrowserModelConnectionConfig,
    BrowserTextModelTestRequest,
    ImageGenerationRequest,
    ImageGenerationResult,
    ModelCatalogRequest,
    ModelCatalogResult,
    ModelGatewayStatus,
    TextGenerationRequest,
    TextGenerationResult,
)

from ..dependencies import get_model_gateway

router = APIRouter(prefix="/api/models", tags=["models"])
Gateway = Annotated[ModelGateway, Depends(get_model_gateway)]


def _model_http_error(error: ModelGatewayError) -> HTTPException:
    if isinstance(error, ModelConfigurationError):
        status_code = 503
    elif error.code == "provider_timeout":
        status_code = 504
    else:
        status_code = 502
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
        },
    )


def _browser_gateway(
    config: BrowserModelConnectionConfig,
    server_gateway: ModelGateway,
    *,
    capability: str,
    model: str,
) -> ModelGateway:
    api_key = config.api_key.get_secret_value() if config.api_key is not None else None
    provider = ProviderConfig(
        provider=config.provider,
        model=model,
        base_url=config.base_url,
        api_key=api_key,
    )
    mock = ProviderConfig(
        provider="mock",
        model="novelatlas-unused-mock",
        base_url="",
        api_key=None,
    )
    return ModelGateway(
        text=provider if capability == "text" else mock,
        image=provider if capability == "image" else mock,
        timeout_seconds=server_gateway.timeout_seconds,
        max_retries=server_gateway.max_retries,
        retry_base_delay_seconds=server_gateway.retry_base_delay_seconds,
    )


@router.get("/config", response_model=ModelGatewayStatus)
async def get_model_config(gateway: Gateway) -> ModelGatewayStatus:
    """Return provider names and readiness without returning API keys."""

    return gateway.status


@router.post("/test/text", response_model=TextGenerationResult)
async def test_text_model(
    request: TextGenerationRequest,
    gateway: Gateway,
) -> TextGenerationResult:
    """Run one explicit text request through the configured gateway."""

    try:
        return await gateway.generate_text(request)
    except ModelGatewayError as error:
        raise _model_http_error(error) from error


@router.post("/test/image", response_model=ImageGenerationResult)
async def test_image_model(
    request: ImageGenerationRequest,
    gateway: Gateway,
) -> ImageGenerationResult:
    """Run one explicit image request through the configured gateway."""

    try:
        return await gateway.generate_image(request)
    except ModelGatewayError as error:
        raise _model_http_error(error) from error


@router.post(
    "/browser/catalog/{capability}",
    response_model=ModelCatalogResult,
)
async def list_browser_models(
    capability: Literal["text", "image"],
    request: ModelCatalogRequest,
    server_gateway: Gateway,
) -> ModelCatalogResult:
    """List models using credentials supplied only for this request."""

    gateway = _browser_gateway(
        request.config,
        server_gateway,
        capability=capability,
        model=f"novelatlas-mock-{capability}",
    )
    try:
        models = await gateway.list_models(capability)
        return ModelCatalogResult(
            provider=request.config.provider,
            models=models,
        )
    except ModelGatewayError as error:
        raise _model_http_error(error) from error


@router.post(
    "/browser/test/text",
    response_model=TextGenerationResult,
)
async def test_browser_text_model(
    request: BrowserTextModelTestRequest,
    server_gateway: Gateway,
) -> TextGenerationResult:
    """Test one browser-local text configuration without persisting its key."""

    gateway = _browser_gateway(
        request.config,
        server_gateway,
        capability="text",
        model=request.config.model,
    )
    try:
        return await gateway.generate_text(request.request)
    except ModelGatewayError as error:
        raise _model_http_error(error) from error


@router.post(
    "/browser/test/image",
    response_model=ImageGenerationResult,
)
async def test_browser_image_model(
    request: BrowserImageModelTestRequest,
    server_gateway: Gateway,
) -> ImageGenerationResult:
    """Test one browser-local image configuration without persisting its key."""

    gateway = _browser_gateway(
        request.config,
        server_gateway,
        capability="image",
        model=request.config.model,
    )
    try:
        return await gateway.generate_image(request.request)
    except ModelGatewayError as error:
        raise _model_http_error(error) from error
