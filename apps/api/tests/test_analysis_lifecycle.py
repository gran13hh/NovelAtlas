"""Stage 5 end-to-end progress, cleanup, and real-fixture tests."""

import asyncio
import json
import time
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.novelatlas_api.config import Settings
from apps.api.novelatlas_api.main import create_app
from novelatlas.analysis import AnalysisTaskManager, watch_analysis_progress
from novelatlas.models import ModelGatewayError, ProviderConfig
from novelatlas.schemas.models import ModelUsage, TextGenerationResult

REAL_NOVEL_FIXTURE = (
    Path(__file__).parents[3] / "tests" / "fixtures" / "novels" / "test_novel.txt"
)


class DelayedMockGateway:
    """A deterministic gateway slow enough to observe detached task behavior."""

    def __init__(self, delay_seconds: float = 0.02) -> None:
        self.text_config = ProviderConfig(
            provider="mock",
            model="delayed-mock",
            base_url="",
            api_key=None,
        )
        self.delay_seconds = delay_seconds
        self.call_count = 0

    async def generate_text(self, request) -> TextGenerationResult:
        await asyncio.sleep(self.delay_seconds)
        self.call_count += 1
        return TextGenerationResult(
            provider="mock",
            model=self.text_config.model,
            content="delayed mock response",
            request_id=f"delayed-{self.call_count}",
            usage=ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            is_mock=True,
        )


class FailingMockGateway(DelayedMockGateway):
    """Fail the first call with a safe provider-neutral error."""

    async def generate_text(self, request) -> TextGenerationResult:
        raise ModelGatewayError(
            code="provider_unreachable",
            message="无法连接模型供应商",
            retryable=True,
        )


def _upload_parse_plan(client: TestClient, *, chapters: int = 6) -> tuple[str, dict]:
    text = "".join(
        f"第{ordinal}章 测试\n"
        + f"第{ordinal}章的重要事件持续推进，人物做出新的决定。" * 2
        + "\n"
        for ordinal in range(1, chapters + 1)
    )
    upload = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", text.encode(), "text/plain")},
    )
    assert upload.status_code == 201
    task_id = upload.json()["task_id"]
    assert client.post(f"/api/documents/{task_id}/parse").status_code == 200
    plan = client.post(
        f"/api/analyses/{task_id}/plan",
        json={
            "budget": {
                "context_window_tokens": 4096,
                "max_input_tokens": 1328,
                "output_reserve_tokens": 64,
                "safety_margin_tokens": 1200,
            }
        },
    )
    assert plan.status_code == 200
    return task_id, plan.json()


def _wait_for_completion(client: TestClient, task_id: str) -> dict:
    for _attempt in range(300):
        response = client.get(f"/api/analyses/{task_id}/run")
        assert response.status_code == 200
        manifest = response.json()
        if manifest["status"] in {"completed", "failed", "interrupted"}:
            return manifest
        time.sleep(0.01)
    raise AssertionError("analysis task did not reach a terminal state")


def _first_sse_data(body: str) -> dict:
    data_line = next(line for line in body.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


def test_completed_sse_is_compact_and_supports_last_event_id(
    client: TestClient,
) -> None:
    task_id, plan = _upload_parse_plan(client)
    assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202
    completed = _wait_for_completion(client, task_id)
    assert completed["status"] == "completed"

    events = client.get(f"/api/analyses/{task_id}/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: analysis.completed" in events.text
    payload = _first_sse_data(events.text)
    assert payload["phase"] == "completed"
    assert payload["terminal"] is True
    assert payload["completed_batch_count"] == plan["batch_count"]
    assert "batches" not in payload
    assert "api_key" not in events.text.lower()
    assert "base_url" not in events.text.lower()

    replay = client.get(
        f"/api/analyses/{task_id}/events",
        headers={"Last-Event-ID": payload["event_id"]},
    )
    assert replay.status_code == 200
    assert replay.text == ""


def test_closing_progress_watcher_does_not_cancel_analysis(
    client: TestClient,
) -> None:
    task_id, _plan = _upload_parse_plan(client)
    storage = client.app.state.upload_storage
    gateway = DelayedMockGateway()
    manager = AnalysisTaskManager(storage)

    async def scenario() -> None:
        initial = await manager.start(task_id, gateway)  # type: ignore[arg-type]
        stream = watch_analysis_progress(
            manager,
            task_id,
            initial=initial,
            poll_interval_seconds=0.001,
        )
        first = await anext(stream)
        assert first.status == "queued"
        await stream.aclose()
        assert await manager.is_running(task_id)

        for _attempt in range(500):
            manifest = await manager.get(task_id)
            if manifest.status in {"completed", "failed", "interrupted"}:
                assert manifest.status == "completed"
                break
            await asyncio.sleep(0.005)
        else:
            raise AssertionError("detached analysis did not complete")
        await manager.close()

    asyncio.run(scenario())
    assert gateway.call_count > 1


def test_failed_task_emits_safe_sse_error(client: TestClient) -> None:
    task_id, _plan = _upload_parse_plan(client)
    client.app.state.model_gateway = FailingMockGateway()
    assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202
    failed = _wait_for_completion(client, task_id)
    assert failed["status"] == "failed"

    events = client.get(f"/api/analyses/{task_id}/events")
    assert "event: analysis.error" in events.text
    payload = _first_sse_data(events.text)
    assert payload["phase"] == "failed"
    assert payload["error"] == {
        "code": "provider_unreachable",
        "message": "无法连接模型供应商",
        "retryable": True,
        "batch_id": failed["error"]["batch_id"],
        "merge_node_id": None,
    }


def test_user_edits_batch_then_rebuilds_and_edits_outline(
    client: TestClient,
) -> None:
    task_id, _plan = _upload_parse_plan(client)
    assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202
    first_completion = _wait_for_completion(client, task_id)
    assert first_completion["status"] == "completed"
    original_attempts = [item["attempt_count"] for item in first_completion["batches"]]
    summaries = client.get(f"/api/analyses/{task_id}/summaries").json()
    first = summaries[0]
    first["summary"]["overview"] = "用户修正后的批次概述。"

    updated = client.patch(
        f"/api/analyses/{task_id}/summaries/{first['batch']['batch_id']}",
        json={"summary": first["summary"]},
    )
    assert updated.status_code == 200
    assert updated.json()["user_edited_at"] is not None
    manifest = client.get(f"/api/analyses/{task_id}/run").json()
    assert manifest["status"] == "batch_summaries_completed"
    assert manifest["merge_node_count"] == 0
    assert manifest["final_outline_status"] == "pending"
    assert client.get(f"/api/analyses/{task_id}/outline").status_code == 409

    assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202
    rebuilt = _wait_for_completion(client, task_id)
    assert rebuilt["status"] == "completed"
    assert [item["attempt_count"] for item in rebuilt["batches"]] == original_attempts
    outline = client.get(f"/api/analyses/{task_id}/outline").json()
    outline["outline"]["overall_summary"] = "用户修正后的全书概述。"
    saved_outline = client.patch(
        f"/api/analyses/{task_id}/outline",
        json={"outline": outline["outline"]},
    )
    assert saved_outline.status_code == 200
    assert saved_outline.json()["outline"]["overall_summary"] == (
        "用户修正后的全书概述。"
    )
    assert saved_outline.json()["user_edited_at"] is not None


def test_pause_retains_checkpoints_and_can_resume(tmp_path: Path) -> None:
    settings = Settings(
        max_upload_bytes=4096,
        upload_ttl_seconds=3600,
        cleanup_interval_seconds=3600,
    )
    app = create_app(settings=settings, storage_root=tmp_path / "pause-active")
    with TestClient(app) as client:
        task_id, _plan = _upload_parse_plan(client)
        default_gateway = client.app.state.model_gateway
        client.app.state.model_gateway = DelayedMockGateway(delay_seconds=0.5)
        assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202
        paused = client.post(f"/api/analyses/{task_id}/cancel")
        assert paused.status_code == 200
        assert paused.json()["status"] == "interrupted"
        assert (tmp_path / "pause-active" / task_id / "analysis-task.json").is_file()

        client.app.state.model_gateway = default_gateway
        assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202
        assert _wait_for_completion(client, task_id)["status"] == "completed"


def test_delete_cancels_active_analysis_and_removes_all_artifacts(
    tmp_path: Path,
) -> None:
    settings = Settings(
        max_upload_bytes=4096,
        upload_ttl_seconds=3600,
        cleanup_interval_seconds=3600,
    )
    storage_root = tmp_path / "delete-active"
    app = create_app(settings=settings, storage_root=storage_root)
    with TestClient(app) as client:
        task_id, _plan = _upload_parse_plan(client)
        client.app.state.model_gateway = DelayedMockGateway(delay_seconds=0.5)
        assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202
        assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 409
        assert client.delete(f"/api/uploads/{task_id}").status_code == 200

        assert not (storage_root / task_id).exists()
        assert client.get(f"/api/analyses/{task_id}/run").status_code == 404
        assert client.get(f"/api/analyses/{task_id}/events").status_code == 404


def test_expiry_prunes_detached_active_analysis(client: TestClient) -> None:
    task_id, _plan = _upload_parse_plan(client)
    storage = client.app.state.upload_storage
    gateway = DelayedMockGateway(delay_seconds=0.5)
    manager = AnalysisTaskManager(storage)

    async def scenario() -> None:
        await manager.start(task_id, gateway)  # type: ignore[arg-type]
        expires_at = storage.get(task_id).expires_at
        assert storage.cleanup_expired(
            now=expires_at + timedelta(seconds=1)
        ) == 1
        await manager.prune_missing_uploads()
        assert not await manager.is_running(task_id)
        await manager.close()

    asyncio.run(scenario())
    assert not (storage.root / task_id).exists()


def test_real_novel_fixture_completes_mock_outline(tmp_path: Path) -> None:
    source = REAL_NOVEL_FIXTURE.read_bytes()
    settings = Settings(
        max_upload_bytes=max(200_000, len(source) + 1024),
        upload_ttl_seconds=3600,
        cleanup_interval_seconds=3600,
    )
    app = create_app(settings=settings, storage_root=tmp_path / "real-fixture")
    with TestClient(app) as client:
        upload = client.post(
            "/api/uploads",
            files={"file": ("test_novel.txt", source, "text/plain")},
        )
        assert upload.status_code == 201
        task_id = upload.json()["task_id"]
        parsed = client.post(f"/api/documents/{task_id}/parse")
        assert parsed.status_code == 200
        assert parsed.json()["chapter_count"] >= 10
        plan = client.post(
            f"/api/analyses/{task_id}/plan",
            json={
                "budget": {
                    "context_window_tokens": 10_000,
                    "max_input_tokens": 6000,
                    "output_reserve_tokens": 512,
                    "safety_margin_tokens": 5488,
                }
            },
        )
        assert plan.status_code == 200
        assert plan.json()["batch_count"] > 10

        assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202
        completed = _wait_for_completion(client, task_id)
        assert completed["status"] == "completed"
        outline = client.get(f"/api/analyses/{task_id}/outline")
        assert outline.status_code == 200
        assert len(outline.json()["source_batch_ids"]) == plan.json()["batch_count"]
