"""Shared API test fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from apps.api.novelatlas_api.config import Settings
from apps.api.novelatlas_api.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        max_upload_bytes=1024,
        upload_ttl_seconds=3600,
        cleanup_interval_seconds=3600,
    )
    app = create_app(settings=settings, storage_root=tmp_path / "uploads")
    with TestClient(app) as test_client:
        yield test_client
