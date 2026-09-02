"""Tests for the API health endpoint."""

from fastapi.testclient import TestClient

from apps.api.novelatlas_api.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "novelatlas-api",
        "version": "0.1.0",
    }
