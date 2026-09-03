"""Model gateway configuration, mock, adapter, and retry tests."""

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from apps.api.novelatlas_api.config import Settings
from apps.api.novelatlas_api.main import create_app
from novelatlas.models import ModelGateway, ModelGatewayError, ProviderConfig
from novelatlas.schemas.models import TextGenerationRequest


def test_public_model_config_contains_no_api_keys(client: TestClient) -> None:
    response = client.get("/api/models/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "text": {
            "provider": "mock",
            "model": "novelatlas-mock-text",
            "base_url": None,
            "configured": True,
            "is_mock": True,
            "missing_settings": [],
        },
        "timeout_seconds": 60.0,
        "max_retries": 2,
    }
    assert "key" not in json.dumps(payload).lower()


def test_private_provider_config_repr_masks_api_key() -> None:
    config = ProviderConfig(
        provider="openai",
        model="test-model",
        base_url="https://example.test/v1",
        api_key="never-print-this-key",
    )

    assert "never-print-this-key" not in repr(config)


def test_unsafe_base_url_is_not_returned_by_public_status() -> None:
    gateway = ModelGateway(
        text=ProviderConfig(
            "openai",
            "test-model",
            "https://user:password@example.test/v1?token=secret",
            "private-key",
        ),
        timeout_seconds=5,
        max_retries=0,
        retry_base_delay_seconds=0,
    )

    assert gateway.status.text.configured is False
    assert gateway.status.text.base_url is None
    assert "secret" not in gateway.status.model_dump_json()


def test_mock_text_model_is_available_without_keys(
    client: TestClient,
) -> None:
    secret_prompt = "不要在 Mock 输出中回显这段测试原文"
    text_response = client.post(
        "/api/models/test/text",
        json={"prompt": secret_prompt, "max_output_tokens": 128},
    )

    assert text_response.status_code == 200
    text_payload = text_response.json()
    assert text_payload["provider"] == "mock"
    assert text_payload["is_mock"] is True
    assert secret_prompt not in text_payload["content"]
    assert text_payload["usage"]["total_tokens"] > 0

def test_browser_local_mock_configuration_is_transient(client: TestClient) -> None:
    browser_config = {
        "provider": "mock",
        "model": "browser-only-text-model",
        "base_url": "http://127.0.0.1:9999/v1",
        "api_key": "browser-only-secret",
    }

    catalog = client.post(
        "/api/models/browser/catalog/text",
        json={
            "config": {
                "provider": "mock",
                "base_url": browser_config["base_url"],
                "api_key": browser_config["api_key"],
            }
        },
    )
    tested = client.post(
        "/api/models/browser/test/text",
        json={
            "config": browser_config,
            "request": {"prompt": "浏览器配置测试", "max_output_tokens": 64},
        },
    )

    assert catalog.status_code == 200
    assert catalog.json() == {
        "provider": "mock",
        "models": ["novelatlas-mock-text"],
    }
    assert tested.status_code == 200
    assert tested.json()["model"] == "browser-only-text-model"
    assert "browser-only-secret" not in tested.text
    assert client.get("/api/models/config").json()["text"]["model"] == (
        "novelatlas-mock-text"
    )


def test_browser_configuration_error_does_not_echo_api_key(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/models/browser/catalog/text",
        json={
            "config": {
                "provider": "openai",
                "base_url": "not-a-valid-url",
                "api_key": "never-echo-browser-key",
            }
        },
    )

    assert response.status_code == 503
    assert "never-echo-browser-key" not in response.text
    assert response.json()["detail"]["code"] == "model_not_configured"


def configured_client(tmp_path, **overrides: object) -> TestClient:
    settings = Settings(
        max_upload_bytes=1024,
        upload_ttl_seconds=3600,
        cleanup_interval_seconds=3600,
        **overrides,
    )
    app = create_app(settings=settings, storage_root=tmp_path / "model-uploads")
    return TestClient(app)


def test_openai_provider_reports_missing_key_without_exposing_secret(tmp_path) -> None:
    with configured_client(
        tmp_path,
        text_model_provider="openai",
        text_model_name="configured-text-model",
    ) as client:
        config = client.get("/api/models/config").json()
        response = client.post(
            "/api/models/test/text",
            json={"prompt": "连接测试"},
        )

    assert config["text"]["configured"] is False
    assert config["text"]["missing_settings"] == [
        "NOVELATLAS_TEXT_MODEL_API_KEY"
    ]
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "model_not_configured",
        "message": "OpenAI 模型缺少 API Key",
        "retryable": False,
    }


def test_openai_responses_adapter_retries_rate_limit_and_normalizes_output() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.url == "https://example.test/v1/responses"
        assert request.headers["authorization"] == "Bearer private-test-key"
        request_payload = json.loads(request.content)
        assert request_payload == {
            "model": "test-text-model",
            "input": "分析这一段",
            "max_output_tokens": 200,
            "store": False,
            "instructions": "返回简短摘要",
        }
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "rate limit"}})
        return httpx.Response(
            200,
            headers={"x-request-id": "header-request-id"},
            json={
                "id": "resp_test",
                "model": "test-text-model-2026",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "归一化模型输出"}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    gateway = ModelGateway(
        text=ProviderConfig(
            provider="openai",
            model="test-text-model",
            base_url="https://example.test/v1",
            api_key="private-test-key",
        ),
        timeout_seconds=5,
        max_retries=1,
        retry_base_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(
        gateway.generate_text(
            TextGenerationRequest(
                prompt="分析这一段",
                instructions="返回简短摘要",
                max_output_tokens=200,
            )
        )
    )

    assert attempts == 2
    assert result.provider == "openai"
    assert result.model == "test-text-model-2026"
    assert result.content == "归一化模型输出"
    assert result.request_id == "resp_test"
    assert result.usage is not None and result.usage.total_tokens == 15


def test_openai_model_catalog_returns_sorted_unique_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == "https://example.test/v1/models"
        assert request.headers["authorization"] == "Bearer catalog-key"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "model-z", "object": "model"},
                    {"id": "model-a", "object": "model"},
                    {"id": "model-z", "object": "model"},
                ],
            },
        )

    gateway = ModelGateway(
        text=ProviderConfig(
            "openai",
            "model-a",
            "https://example.test/v1",
            "catalog-key",
        ),
        timeout_seconds=5,
        max_retries=0,
        retry_base_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    models = asyncio.run(gateway.list_models())

    assert models == ["model-a", "model-z"]


def test_non_retryable_provider_error_is_not_retried() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": {"message": "raw secret detail"}})

    gateway = ModelGateway(
        text=ProviderConfig(
            "openai",
            "test-model",
            "https://example.test/v1",
            "private-key",
        ),
        timeout_seconds=5,
        max_retries=3,
        retry_base_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    try:
        asyncio.run(
            gateway.generate_text(TextGenerationRequest(prompt="test request"))
        )
    except ModelGatewayError as error:
        assert error.code == "provider_http_401"
        assert error.message == "模型供应商认证失败，请检查 API Key"
        assert "raw secret detail" not in error.message
    else:
        raise AssertionError("expected ModelGatewayError")
    assert attempts == 1
