"""FastAPI dependency providers."""

from fastapi import Request

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
