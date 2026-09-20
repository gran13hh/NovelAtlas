"""Batch-summary Agent persistence, failure, and restart tests."""

import asyncio
import json
import re
import time
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.novelatlas_api.config import Settings
from apps.api.novelatlas_api.main import create_app
from novelatlas.analysis import BatchSummaryRunner
from novelatlas.models import ModelGatewayError, ProviderConfig
from novelatlas.schemas.analysis import AnalysisBatch, AnalysisTaskManifest
from novelatlas.schemas.models import ModelUsage, TextGenerationResult
from novelatlas.skills.batch_summary import (
    BatchSummaryOutputError,
    parse_batch_summary_response,
)
from novelatlas.skills.hierarchical_outline import (
    HierarchicalOutlineOutputError,
    parse_final_outline_response,
    parse_merge_summary_response,
)


class CountingGateway:
    """Mock-compatible gateway that can fail exactly one logical batch call."""

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.text_config = ProviderConfig(
            provider="mock",
            model="counting-mock",
            base_url="",
            api_key=None,
        )
        self.fail_on_call = fail_on_call
        self.calls: list[str] = []
        self._failed = False

    async def generate_text(self, request) -> TextGenerationResult:
        match = re.search(r'"batch_id": "(batch_[0-9a-f]{16})"', request.prompt)
        if match is not None:
            call_id = match.group(1)
        elif '"operation": "hierarchical_merge"' in request.prompt:
            node = re.search(
                r'"merge_node_id": "(merge_[0-9a-f]{16})"', request.prompt
            )
            assert node is not None
            call_id = node.group(1)
        else:
            assert '"operation": "final_outline"' in request.prompt
            call_id = "final_outline"
        self.calls.append(call_id)
        if (
            self.fail_on_call is not None
            and len(self.calls) == self.fail_on_call
            and not self._failed
        ):
            self._failed = True
            raise ModelGatewayError(
                code="provider_unreachable",
                message="无法连接模型供应商",
                retryable=True,
            )
        return TextGenerationResult(
            provider="mock",
            model=self.text_config.model,
            content="counting mock response",
            request_id=f"counting-{len(self.calls)}",
            usage=ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            is_mock=True,
        )


def _upload_parse_and_plan(client: TestClient) -> tuple[str, dict]:
    text = "".join(
        f"第{ordinal}章 测试\n"
        + f"第{ordinal}章的重要事件持续推进，人物做出新的决定。" * 2
        + "\n"
        for ordinal in range(1, 7)
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
    assert plan.json()["batch_count"] >= 2
    return task_id, plan.json()


def _wait_for_terminal_status(client: TestClient, task_id: str) -> dict:
    endpoint = f"/api/analyses/{task_id}/run"
    for _attempt in range(100):
        response = client.get(endpoint)
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {
            "failed",
            "interrupted",
            "batch_summaries_completed",
            "completed",
        }:
            return payload
        time.sleep(0.01)
    raise AssertionError("batch summary task did not reach a terminal status")


def test_mock_api_persists_each_batch_without_browser_key(
    client: TestClient,
    tmp_path: Path,
) -> None:
    task_id, plan = _upload_parse_and_plan(client)
    browser_secret = "browser-key-must-never-reach-disk"

    started = client.post(
        f"/api/analyses/{task_id}/run",
        json={
            "config": {
                "provider": "mock",
                "model": "browser-mock-model",
                "base_url": "http://127.0.0.1:9999/v1",
                "api_key": browser_secret,
            }
        },
    )
    assert started.status_code == 202
    completed = _wait_for_terminal_status(client, task_id)

    assert completed["status"] == "completed"
    assert completed["completed_batch_count"] == plan["batch_count"]
    assert all(batch["attempt_count"] == 1 for batch in completed["batches"])

    summaries = client.get(f"/api/analyses/{task_id}/summaries")
    assert summaries.status_code == 200
    assert len(summaries.json()) == plan["batch_count"]
    assert all(item["summary"]["overview"] for item in summaries.json())
    outline = client.get(f"/api/analyses/{task_id}/outline")
    assert outline.status_code == 200
    assert outline.json()["outline"]["overall_summary"]
    assert outline.json()["source_batch_ids"] == [
        batch["batch_id"] for batch in plan["batches"]
    ]

    task_directory = tmp_path / "uploads" / task_id
    artifacts = list(task_directory.glob("*.json"))
    assert len(list(task_directory.glob("batch-summary-*.json"))) == plan[
        "batch_count"
    ]
    assert browser_secret not in "\n".join(
        artifact.read_text(encoding="utf-8") for artifact in artifacts
    )


def test_failed_batch_resumes_without_recalling_completed_batches(
    client: TestClient,
) -> None:
    task_id, plan = _upload_parse_and_plan(client)
    storage = client.app.state.upload_storage
    gateway = CountingGateway(fail_on_call=2)
    runner = BatchSummaryRunner(storage)

    runner.prepare_manifest(task_id, gateway)  # type: ignore[arg-type]
    failed = asyncio.run(runner.run(task_id, gateway))  # type: ignore[arg-type]

    assert failed.status == "failed"
    assert failed.completed_batch_count == 1
    assert failed.batches[0].status == "completed"
    assert failed.batches[1].status == "failed"
    first_batch_id = gateway.calls[0]

    restarted_runner = BatchSummaryRunner(storage)
    restarted_runner.prepare_manifest(task_id, gateway)  # type: ignore[arg-type]
    completed = asyncio.run(
        restarted_runner.run(task_id, gateway)  # type: ignore[arg-type]
    )

    assert completed.status == "completed"
    assert completed.completed_batch_count == plan["batch_count"]
    assert gateway.calls.count(first_batch_id) == 1
    batch_calls = [call for call in gateway.calls if call.startswith("batch_")]
    assert len(batch_calls) == plan["batch_count"] + 1
    assert completed.batches[0].attempt_count == 1
    assert completed.batches[1].attempt_count == 2


def test_completed_task_survives_application_recreation(tmp_path: Path) -> None:
    storage_root = tmp_path / "restartable-uploads"
    settings = Settings(
        max_upload_bytes=4096,
        upload_ttl_seconds=3600,
        cleanup_interval_seconds=3600,
    )
    first_app = create_app(settings=settings, storage_root=storage_root)
    with TestClient(first_app) as first_client:
        task_id, plan = _upload_parse_and_plan(first_client)
        assert first_client.post(
            f"/api/analyses/{task_id}/run",
            json={},
        ).status_code == 202
        completed = _wait_for_terminal_status(first_client, task_id)
        assert completed["completed_batch_count"] == plan["batch_count"]

    second_app = create_app(settings=settings, storage_root=storage_root)
    with TestClient(second_app) as second_client:
        restored = second_client.get(f"/api/analyses/{task_id}/run")
        summaries = second_client.get(f"/api/analyses/{task_id}/summaries")

    assert restored.status_code == 200
    assert restored.json()["status"] == "completed"
    assert len(summaries.json()) == plan["batch_count"]


def test_saved_summary_is_recovered_if_manifest_update_was_interrupted(
    client: TestClient,
) -> None:
    task_id, _plan = _upload_parse_and_plan(client)
    storage = client.app.state.upload_storage
    first_gateway = CountingGateway()
    runner = BatchSummaryRunner(storage)
    runner.prepare_manifest(task_id, first_gateway)  # type: ignore[arg-type]
    completed = asyncio.run(
        runner.run(task_id, first_gateway)  # type: ignore[arg-type]
    )
    assert completed.status == "completed"

    manifest = AnalysisTaskManifest.model_validate_json(
        storage.read_json_artifact(task_id, "analysis-task")
    )
    manifest.batches[0].status = "running"
    manifest.batches[0].summary_artifact = None
    manifest.batches[0].completed_at = None
    manifest.completed_batch_count -= 1
    manifest.status = "running"
    storage.delete_json_artifact(task_id, "final-outline")
    manifest.final_outline_status = "pending"
    manifest.final_outline_artifact = None
    storage.write_json_artifact(
        task_id,
        "analysis-task",
        manifest.model_dump_json(indent=2),
    )

    recovery_gateway = CountingGateway()
    restarted_runner = BatchSummaryRunner(storage)
    restarted_runner.prepare_manifest(
        task_id,
        recovery_gateway,  # type: ignore[arg-type]
    )
    recovered = asyncio.run(
        restarted_runner.run(
            task_id,
            recovery_gateway,  # type: ignore[arg-type]
        )
    )

    assert recovered.status == "completed"
    assert recovery_gateway.calls == ["final_outline"]


def test_skill_rejects_references_outside_planned_batch(client: TestClient) -> None:
    _task_id, plan = _upload_parse_and_plan(client)
    batch = plan["batches"][0]
    invalid = {
        "overview": "测试概括",
        "key_events": [
            {
                "description": "越界引用",
                "chapter_ids": ["chapter_not_allowed"],
                "source_chunk_ids": [batch["source_chunk_ids"][0]],
                "confidence": "certain",
            }
        ],
        "characters": [],
        "worldbuilding": [],
        "foreshadowing": [],
        "unresolved_items": [],
    }

    try:
        parse_batch_summary_response(
            response_text=json.dumps(invalid, ensure_ascii=False),
            batch=AnalysisBatch.model_validate(batch),
        )
    except BatchSummaryOutputError as error:
        assert "计划之外的章节" in str(error)
    else:
        raise AssertionError("expected BatchSummaryOutputError")


def test_final_skill_rejects_references_outside_direct_inputs() -> None:
    invalid = {
        "overall_summary": "测试全书概述",
        "chapter_outline": [
            {
                "chapter_range": "第 1 章",
                "summary": "测试",
                "key_events": [],
                "sources": {"input_ids": ["merge_not_allowed"]},
            }
        ],
        "storylines": [],
        "characters": [],
        "worldbuilding": [],
        "foreshadowing": [],
        "unresolved_items": [],
        "conflicts_and_uncertainties": [],
    }

    try:
        parse_final_outline_response(
            response_text=json.dumps(invalid, ensure_ascii=False),
            allowed_input_ids=["batch_allowed"],
        )
    except HierarchicalOutlineOutputError as error:
        assert "本节点之外" in str(error)
    else:
        raise AssertionError("expected HierarchicalOutlineOutputError")


def test_merge_skill_normalizes_sources_array_shorthand() -> None:
    payload = {
        "overview": "测试中间汇总",
        "chapter_outline": [
            {
                "chapter_range": "第一章至第二章",
                "summary": "故事继续推进。",
                "key_events": ["人物作出决定。"],
                "sources": ["batch_allowed"],
            }
        ],
        "key_events": [],
        "characters": [],
        "worldbuilding": [],
        "foreshadowing": [],
        "unresolved_items": [],
        "uncertainties": [],
    }

    result = parse_merge_summary_response(
        response_text=json.dumps(payload, ensure_ascii=False),
        allowed_input_ids=["batch_allowed"],
    )

    assert result.chapter_outline[0].sources.input_ids == ["batch_allowed"]


def test_final_skill_normalizes_sources_array_but_keeps_source_whitelist() -> None:
    payload = {
        "overall_summary": "测试全书概述",
        "chapter_outline": [],
        "storylines": [
            {
                "name": "主线",
                "summary": "主线概述",
                "developments": [],
                "sources": ["batch_not_allowed"],
            }
        ],
        "characters": [],
        "worldbuilding": [],
        "foreshadowing": [],
        "unresolved_items": [],
        "conflicts_and_uncertainties": [],
    }

    try:
        parse_final_outline_response(
            response_text=json.dumps(payload, ensure_ascii=False),
            allowed_input_ids=["batch_allowed"],
        )
    except HierarchicalOutlineOutputError as error:
        assert "本节点之外" in str(error)
    else:
        raise AssertionError("expected HierarchicalOutlineOutputError")


def test_merge_skill_reports_json_location_without_response_content() -> None:
    try:
        parse_merge_summary_response(
            response_text='{"overview": "未闭合"',
            allowed_input_ids=["batch_allowed"],
        )
    except HierarchicalOutlineOutputError as error:
        assert "不是有效 JSON" in str(error)
        assert "第 1 行" in str(error)
        assert "未闭合" not in str(error)
    else:
        raise AssertionError("expected HierarchicalOutlineOutputError")


def test_merge_failure_resumes_without_recalling_leaf_batches(tmp_path: Path) -> None:
    settings = Settings(
        max_upload_bytes=100_000,
        upload_ttl_seconds=3600,
        cleanup_interval_seconds=3600,
    )
    app = create_app(settings=settings, storage_root=tmp_path / "merge-uploads")
    with TestClient(app) as client:
        text = "".join(
            f"第{ordinal}章 测试\n"
            + "重要事件推进，人物作出决定。" * 8
            + "\n"
            for ordinal in range(1, 81)
        )
        upload = client.post(
            "/api/uploads",
            files={"file": ("long.txt", text.encode(), "text/plain")},
        )
        task_id = upload.json()["task_id"]
        assert client.post(f"/api/documents/{task_id}/parse").status_code == 200
        plan_response = client.post(
            f"/api/analyses/{task_id}/plan",
            json={
                "budget": {
                    "context_window_tokens": 8192,
                    "max_input_tokens": 3000,
                    "output_reserve_tokens": 512,
                    "safety_margin_tokens": 2872,
                }
            },
        )
        plan = plan_response.json()
        assert plan["batch_count"] >= 40

        storage = client.app.state.upload_storage
        gateway = CountingGateway(fail_on_call=plan["batch_count"] + 2)
        runner = BatchSummaryRunner(storage)
        runner.prepare_manifest(task_id, gateway)  # type: ignore[arg-type]
        failed = asyncio.run(runner.run(task_id, gateway))  # type: ignore[arg-type]

        assert failed.status == "failed"
        assert failed.error is not None
        assert failed.error.merge_node_id is not None
        assert failed.completed_batch_count == plan["batch_count"]
        assert failed.completed_merge_node_count == 1
        first_merge_id = next(
            node.node_id for node in failed.merge_nodes if node.status == "completed"
        )
        failed_merge_id = failed.error.merge_node_id

        restarted = BatchSummaryRunner(storage)
        restarted.prepare_manifest(task_id, gateway)  # type: ignore[arg-type]
        completed = asyncio.run(
            restarted.run(task_id, gateway)  # type: ignore[arg-type]
        )

        assert completed.status == "completed"
        assert len([call for call in gateway.calls if call.startswith("batch_")]) == (
            plan["batch_count"]
        )
        assert gateway.calls.count(first_merge_id) == 1
        assert gateway.calls.count(failed_merge_id) == 2
        assert completed.completed_merge_node_count == completed.merge_node_count
        record = restarted.load_outline(task_id)
        assert record.source_batch_ids == [
            batch["batch_id"] for batch in plan["batches"]
        ]
        serialized = record.outline.model_dump()
        assert "style" not in serialized
        assert "quotes" not in serialized

        manifest = AnalysisTaskManifest.model_validate_json(
            storage.read_json_artifact(task_id, "analysis-task")
        )
        recovered_node = manifest.merge_nodes[0]
        recovered_node.status = "running"
        recovered_node.summary_artifact = None
        recovered_node.completed_at = None
        manifest.completed_merge_node_count -= 1
        manifest.status = "merging"
        manifest.final_outline_status = "pending"
        manifest.final_outline_artifact = None
        storage.delete_json_artifact(task_id, "final-outline")
        storage.write_json_artifact(
            task_id,
            "analysis-task",
            manifest.model_dump_json(indent=2),
        )

        recovery_gateway = CountingGateway()
        recovery_runner = BatchSummaryRunner(storage)
        recovery_runner.prepare_manifest(
            task_id,
            recovery_gateway,  # type: ignore[arg-type]
        )
        recovered = asyncio.run(
            recovery_runner.run(
                task_id,
                recovery_gateway,  # type: ignore[arg-type]
            )
        )
        assert recovered.status == "completed"
        assert recovery_gateway.calls == ["final_outline"]


def test_mock_builds_more_than_one_merge_level(tmp_path: Path) -> None:
    settings = Settings(
        max_upload_bytes=150_000,
        upload_ttl_seconds=3600,
        cleanup_interval_seconds=3600,
    )
    app = create_app(settings=settings, storage_root=tmp_path / "layered-uploads")
    with TestClient(app) as client:
        text = "".join(
            f"第{ordinal}章 测试\n"
            + "重要事件推进，人物作出决定。" * 8
            + "\n"
            for ordinal in range(1, 301)
        )
        task_id = client.post(
            "/api/uploads",
            files={"file": ("very-long.txt", text.encode(), "text/plain")},
        ).json()["task_id"]
        assert client.post(f"/api/documents/{task_id}/parse").status_code == 200
        plan = client.post(
            f"/api/analyses/{task_id}/plan",
            json={
                "budget": {
                    "context_window_tokens": 8192,
                    "max_input_tokens": 3000,
                    "output_reserve_tokens": 512,
                    "safety_margin_tokens": 2872,
                }
            },
        ).json()
        assert plan["batch_count"] >= 200

        storage = client.app.state.upload_storage
        gateway = CountingGateway()
        runner = BatchSummaryRunner(storage)
        runner.prepare_manifest(task_id, gateway)  # type: ignore[arg-type]
        completed = asyncio.run(
            runner.run(task_id, gateway)  # type: ignore[arg-type]
        )

        assert completed.status == "completed"
        assert {node.level for node in completed.merge_nodes}.issuperset({1, 2})
        assert len(list((tmp_path / "layered-uploads" / task_id).glob("merge-*.json"))) == (
            completed.merge_node_count
        )
