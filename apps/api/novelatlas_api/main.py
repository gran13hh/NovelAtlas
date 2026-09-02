"""FastAPI application entry point for NovelAtlas."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from . import __version__


class HealthResponse(BaseModel):
    """Public health-check response."""

    status: Literal["ok"]
    service: str
    version: str


app = FastAPI(
    title="NovelAtlas API",
    summary="AI Agent powered novel analysis API",
    version=__version__,
)


@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Check whether the API is ready",
)
async def health_check() -> HealthResponse:
    """Return a small response used by the frontend and local diagnostics."""

    return HealthResponse(
        status="ok",
        service="novelatlas-api",
        version=__version__,
    )
