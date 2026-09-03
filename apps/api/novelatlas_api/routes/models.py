"""Secret-free model status and explicit connection-test endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from novelatlas.models import (
    ModelConfigurationError,
    ModelGateway,
    ModelGatewayError,
)
from novelatlas.schemas.models import (
    BrowserTextModelTestRequest,
    ModelCatalogRequest,
    ModelCatalogResult,
    ModelGatewayStatus,
    TextGenerationRequest,
    TextGenerationResult,
)

from ..dependencies import create_transient_model_gateway, get_model_gateway

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


@router.post(
    "/browser/catalog/text",
    response_model=ModelCatalogResult,
)
async def list_browser_models(
    request: ModelCatalogRequest,
    server_gateway: Gateway,
) -> ModelCatalogResult:
    """List models using credentials supplied only for this request."""

    gateway = create_transient_model_gateway(
        config=request.config,
        server_gateway=server_gateway,
        model="novelatlas-mock-text",
    )
    try:
        models = await gateway.list_models()
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

    gateway = create_transient_model_gateway(
        config=request.config,
        server_gateway=server_gateway,
        model=request.config.model,
    )
    try:
        return await gateway.generate_text(request.request)
    except ModelGatewayError as error:
        raise _model_http_error(error) from error
