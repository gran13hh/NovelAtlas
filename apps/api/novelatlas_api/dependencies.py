"""FastAPI dependency providers."""

from fastapi import Request

from novelatlas.analysis import AnalysisTaskManager
from novelatlas.models import ModelGateway, ProviderConfig
from novelatlas.schemas.models import BrowserModelConnectionConfig
from novelatlas.services.temporary_storage import TemporaryUploadStorage

from .config import Settings


def get_upload_storage(request: Request) -> TemporaryUploadStorage:
    """Return the process-scoped temporary upload storage."""

    return request.app.state.upload_storage


def get_max_upload_bytes(request: Request) -> int:
    """Return the configured maximum upload size."""

    return request.app.state.settings.max_upload_bytes


def get_settings(request: Request) -> Settings:
    """Return validated runtime settings."""

    return request.app.state.settings


def create_model_gateway(settings: Settings) -> ModelGateway:
    """Build the process-scoped gateway from private server-side settings."""

    text_api_key = (
        settings.text_model_api_key.get_secret_value()
        if settings.text_model_api_key is not None
        else None
    )
    return ModelGateway(
        text=ProviderConfig(
            provider=settings.text_model_provider,
            model=settings.text_model_name,
            base_url=settings.text_model_base_url,
            api_key=text_api_key,
        ),
        timeout_seconds=settings.model_timeout_seconds,
        max_retries=settings.model_max_retries,
        retry_base_delay_seconds=settings.model_retry_base_delay_seconds,
    )


def get_model_gateway(request: Request) -> ModelGateway:
    """Return the process-scoped text model gateway."""

    return request.app.state.model_gateway


def get_analysis_task_manager(request: Request) -> AnalysisTaskManager:
    """Return the process-local coordinator backed by persistent checkpoints."""

    return request.app.state.analysis_task_manager


def create_transient_model_gateway(
    *,
    config: BrowserModelConnectionConfig,
    model: str,
    server_gateway: ModelGateway,
) -> ModelGateway:
    """Build a one-request browser gateway without persisting its API key."""

    api_key = config.api_key.get_secret_value() if config.api_key is not None else None
    provider = ProviderConfig(
        provider=config.provider,
        model=model,
        base_url=config.base_url,
        api_key=api_key,
    )
    return ModelGateway(
        text=provider,
        timeout_seconds=server_gateway.timeout_seconds,
        max_retries=server_gateway.max_retries,
        retry_base_delay_seconds=server_gateway.retry_base_delay_seconds,
    )
