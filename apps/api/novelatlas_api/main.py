"""FastAPI application entry point for NovelAtlas."""

import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from novelatlas.analysis import AnalysisTaskManager
from novelatlas.services.temporary_storage import TemporaryUploadStorage

from . import __version__
from .config import Settings
from .dependencies import create_model_gateway
from .routes.analyses import router as analyses_router
from .routes.documents import router as documents_router
from .routes.exports import router as exports_router
from .routes.knowledge import router as knowledge_router
from .routes.models import router as models_router
from .routes.uploads import router as uploads_router


class HealthResponse(BaseModel):
    """Public health-check response."""

    status: Literal["ok"]
    service: str
    version: str


async def _cleanup_expired_uploads(
    storage: TemporaryUploadStorage,
    analysis_tasks: AnalysisTaskManager,
    interval_seconds: int,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(storage.cleanup_expired)
        await analysis_tasks.prune_missing_uploads()


def create_app(
    *,
    settings: Settings | None = None,
    storage_root: Path | None = None,
) -> FastAPI:
    """Create an API app with isolated lifecycle-managed temporary storage."""

    resolved_settings = settings or Settings()
    resolved_storage_root = storage_root or (
        Path(tempfile.gettempdir()) / "novelatlas-uploads"
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        storage = TemporaryUploadStorage(
            ttl_seconds=resolved_settings.upload_ttl_seconds,
            root=resolved_storage_root,
        )
        application.state.settings = resolved_settings
        application.state.upload_storage = storage
        application.state.model_gateway = create_model_gateway(resolved_settings)
        analysis_tasks = AnalysisTaskManager(storage)
        application.state.analysis_task_manager = analysis_tasks
        cleaner = asyncio.create_task(
            _cleanup_expired_uploads(
                storage,
                analysis_tasks,
                resolved_settings.cleanup_interval_seconds,
            )
        )
        try:
            yield
        finally:
            await analysis_tasks.close()
            cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await cleaner
            storage.close()

    application = FastAPI(
        title="NovelAtlas API",
        summary="AI Agent powered long-novel outline API",
        version=__version__,
        lifespan=lifespan,
    )
    application.include_router(uploads_router)
    application.include_router(documents_router)
    application.include_router(exports_router)
    application.include_router(models_router)
    application.include_router(analyses_router)
    application.include_router(knowledge_router)

    @application.get(
        "/api/health",
        response_model=HealthResponse,
        tags=["system"],
        summary="Check whether the API is ready",
    )
    async def health_check() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="novelatlas-api",
            version=__version__,
        )

    return application


app = create_app()
