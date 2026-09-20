"""Meaningful retrieval, plan, graph resume and provider contract regressions."""

import asyncio
import json
import time

import httpx
import pytest
from pydantic import ValidationError

from novelatlas.models import ModelGateway, ProviderConfig
from novelatlas.schemas.knowledge import SemanticPlan
from novelatlas.schemas.models import TextGenerationRequest

TEXT = "第一章 归来\n林舟又名阿舟，与沈月结盟。青城禁止私斗。\n第二章 决裂\n沈月发现密信后与林舟决裂。林舟仍称她为盟友。\n第三章 真相\n密信是伪造的。沈月回到青城，二人重新结盟。"


def setup(client):
    upload = client.post(
        "/api/uploads", files={"file": ("sample.txt", TEXT.encode(), "text/plain")}
    )
    assert upload.status_code == 201, upload.text
    tid = upload.json()["task_id"]
    response = client.post(f"/api/documents/{tid}/parse")
    assert response.status_code == 200, response.text
    response = client.post(f"/api/analyses/{tid}/plan", json={})
    assert response.status_code == 200, response.text
    return tid


def wait(client, tid):
    for _ in range(150):
        r = client.get(f"/api/analyses/{tid}/run").json()
        if r["status"] in {"completed", "failed", "interrupted"}:
            return r
        time.sleep(0.02)
    pytest.fail("graph did not complete")


def test_retrieval_exact_quote_and_cross_chapter(client):
    tid = setup(client)
    rows = client.post(
        f"/api/analyses/{tid}/search", json={"query": "沈月 林舟 决裂"}
    ).json()
    assert rows and any("决裂" in r["content"] for r in rows)
    row = rows[0]
    evidence = {k: row[k] for k in ["passage_id", "chapter_id", "chunk_id"]}
    evidence["quote"] = row["content"][:10]
    assert client.post(f"/api/analyses/{tid}/verify", json=evidence).json() == {
        "quote_valid": True,
        "meaning_verified": False,
    }
    evidence["quote"] = "原文不存在的事实"
    assert not client.post(f"/api/analyses/{tid}/verify", json=evidence).json()[
        "quote_valid"
    ]
    evidence["quote"] = row["content"][:10]
    evidence["chapter_id"] = "forged"
    assert not client.post(f"/api/analyses/{tid}/verify", json=evidence).json()[
        "quote_valid"
    ]
    assert (
        client.post(
            f"/api/analyses/{tid}/search", json={"query": "x", "limit": 100}
        ).status_code
        == 422
    )


def test_plan_rejects_cycles_and_missing_dependency():
    task = {
        "task_id": "events",
        "role": "events",
        "objective": "剧情",
        "query": "密信",
        "expected_artifact": "事件",
        "depends_on": ["events"],
    }
    with pytest.raises(ValidationError):
        SemanticPlan(goal="检查事件", tasks=[task])
    task["depends_on"] = ["missing"]
    with pytest.raises(ValidationError):
        SemanticPlan(goal="检查事件", tasks=[task])


def test_actual_graph_handoffs_react_and_edit_invalidation(client):
    tid = setup(client)
    assert (
        client.post(
            f"/api/analyses/{tid}/run", json={"engine": "langgraph"}
        ).status_code
        == 202
    )
    result = wait(client, tid)
    assert result["status"] == "completed", client.get(
        f"/api/analyses/{tid}/trace"
    ).json()
    plan = client.get(f"/api/analyses/{tid}/semantic-plan").json()
    assert plan["mode"] == "mock" and len(plan["tasks"]) == 3
    trace = client.get(f"/api/analyses/{tid}/trace").json()
    assert {"planning", "batch", "solve", "review", "report"} <= {
        r["node"] for r in trace if r["kind"] == "node"
    }
    assert {"search_source", "verify_evidence"} <= {
        r["tool"] for r in trace if r["kind"] == "tool"
    }
    assert len([r for r in trace if r["kind"] == "handoff"]) == 3
    report = client.get(f"/api/analyses/{tid}/knowledge").json()
    assert len(report["reviews"]) == 3
    assert all(r["calls"] <= 3 and r["steps"] <= 4 for r in report["reviews"])
    # Completed task replay has zero additional model calls.
    before = len([r for r in trace if r["kind"] == "model"])
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    assert wait(client, tid)["status"] == "completed"
    assert (
        len(
            [
                r
                for r in client.get(f"/api/analyses/{tid}/trace").json()
                if r["kind"] == "model"
            ]
        )
        == before
    )
    summary = client.get(f"/api/analyses/{tid}/summaries").json()[0]
    summary["summary"]["overview"] = "人工修正"
    response = client.patch(
        f"/api/analyses/{tid}/summaries/{summary['batch']['batch_id']}",
        json={"summary": summary["summary"]},
    )
    assert response.status_code == 200
    assert client.get(f"/api/analyses/{tid}/knowledge").status_code == 404
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    assert wait(client, tid)["status"] == "completed"


def test_deepseek_uses_chat_contract_and_real_usage():
    def serve(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["messages"][0]["role"] == "system"
        assert payload["thinking"] == {"type": "disabled"}
        assert "input" not in payload and payload["max_tokens"] == 100
        return httpx.Response(
            200,
            json={
                "id": "ds-contract",
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {
                            "content": '{"ok":true}',
                            "reasoning_content": "private",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "total_tokens": 25,
                },
            },
        )

    gateway = ModelGateway(
        text=ProviderConfig(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com/v1",
            api_key="secret",
        ),
        timeout_seconds=10,
        max_retries=0,
        retry_base_delay_seconds=0,
        transport=httpx.MockTransport(serve),
    )
    result = asyncio.run(
        gateway.generate_text(
            TextGenerationRequest(
                prompt="数据", instructions="JSON", max_output_tokens=100
            )
        )
    )
    assert result.provider == "deepseek" and result.usage.total_tokens == 25
    assert "private" not in result.content


class ScriptedSemanticGateway:
    """Oracle fixture for orchestration tests, not a model quality benchmark."""

    text_config = ProviderConfig(
        provider="openai",
        model="scripted",
        base_url="https://example.test",
        api_key="private-test-key",
    )

    def __init__(self, fail_review=False, pause_domain=False):
        self.fail_review, self.pause_domain = fail_review, pause_domain
        self.active = self.max_active = 0
        self.plan_calls = self.domain_calls = self.batch_calls = 0
        self.derived_dependency_seen = False

    async def generate_text(self, request):
        from novelatlas.schemas.models import TextGenerationResult

        instructions = request.instructions or ""
        if "JSON Schema：" not in instructions:
            self.batch_calls += 1
            return TextGenerationResult(
                provider="openai",
                model="scripted",
                content="Mock fixture baseline payload",
                is_mock=True,
            )
        schema = json.loads(instructions.split("JSON Schema：")[1])
        data = json.loads(request.prompt)
        title = schema["title"]
        if title == "SemanticPlan":
            self.plan_calls += 1
            output = {
                "goal": data["goal"],
                "tasks": [
                    {
                        "task_id": "names",
                        "role": "relationships",
                        "objective": "人物别名",
                        "query": "林舟 阿舟",
                        "depends_on": [],
                        "expected_artifact": "人物别名映射",
                    },
                    {
                        "task_id": "rules",
                        "role": "worldbuilding",
                        "objective": "青城规则",
                        "query": "青城 禁止私斗",
                        "depends_on": [],
                        "expected_artifact": "规则",
                    },
                    {
                        "task_id": "life",
                        "role": "events",
                        "objective": "跨章生死冲突",
                        "query": "林舟 活着 密信",
                        "depends_on": ["names"],
                        "expected_artifact": "事件证据",
                    },
                ],
            }
        elif title == "DomainResult":
            self.domain_calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(10 if self.pause_domain else 0.03)
            finally:
                self.active -= 1
            task = data["task"]
            if task["task_id"] == "life":
                self.derived_dependency_seen = (
                    bool(data["dependencies"])
                    and data["dependencies"][0]["task_id"] == "names"
                )
            passages = data["evidence_passages"]
            phrase = (
                "林舟又名阿舟"
                if task["task_id"] == "names"
                else "青城禁止私斗"
                if task["task_id"] == "rules"
                else "林舟活着来到城门"
            )
            p = next(p for p in passages if phrase in p["content"])
            conflict = task["task_id"] == "life" and not data["feedback"]
            output = {
                "task_id": task["task_id"],
                "role": task["role"],
                "items": [
                    {
                        "subject": "林舟" if task["task_id"] != "rules" else "青城",
                        "aliases": ["阿舟"] if task["task_id"] == "names" else [],
                        "predicate": "状态"
                        if task["task_id"] == "life"
                        else "别名"
                        if task["task_id"] == "names"
                        else "规则",
                        "object": "死亡" if conflict else phrase,
                        "description": "林舟已死" if conflict else phrase,
                        "classification": "fact",
                        "evidence": [
                            {k: p[k] for k in ["passage_id", "chapter_id", "chunk_id"]}
                            | {"quote": phrase},
                        ],
                    }
                ],
            }
        elif title == "ReviewDecision":
            if self.fail_review:
                self.fail_review = False
                from novelatlas.models import ModelGatewayError

                raise ModelGatewayError(
                    code="provider_timeout", message="模拟核验超时", retryable=True
                )
            observations = data["observations"]
            if not observations:
                output = {
                    "action": "search",
                    "search": {"query": data["item"]["evidence"][0]["quote"]},
                }
            elif len(observations) == 1:
                output = {"action": "verify", "evidence": data["item"]["evidence"][0]}
            else:
                output = {
                    "action": "finish",
                    "verdict": "contradicted"
                    if data["item"]["object"] == "死亡"
                    else "supported",
                    "note": "原句显示活着，与死亡结论矛盾"
                    if data["item"]["object"] == "死亡"
                    else "原句直接支持结论",
                }
        else:
            raise AssertionError(title)
        return TextGenerationResult(
            provider="openai",
            model="scripted",
            content=json.dumps(output, ensure_ascii=False),
            is_mock=False,
        )


def test_semantic_dag_parallel_handoff_conflict_feedback_and_memory(client):
    # Use the full fixed fixture including a prompt-injection sentence.
    from pathlib import Path

    full = Path("tests/fixtures/novels/agent_demo.txt").read_bytes()
    tid = client.post(
        "/api/uploads", files={"file": ("demo.txt", full, "text/plain")}
    ).json()["task_id"]
    client.post(f"/api/documents/{tid}/parse")
    client.post(f"/api/analyses/{tid}/plan", json={})
    gateway = ScriptedSemanticGateway()
    client.app.state.model_gateway = gateway
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    result = wait(client, tid)
    assert result["status"] == "completed", client.get(
        f"/api/analyses/{tid}/trace"
    ).json()
    assert gateway.max_active == 2 and gateway.derived_dependency_seen
    assert gateway.domain_calls == 4  # names + rules + life + targeted life repair
    report = client.get(f"/api/analyses/{tid}/knowledge").json()
    assert report["plan"]["mode"] == "model"
    assert report["entities"]["林舟"] == ["林舟", "阿舟"]
    assert report["repaired_tasks"] == ["life"]
    assert all(r["verdict"] == "supported" for r in report["reviews"])
    assert any(
        r["kind"] == "repair" and r["targets"] == ["life"]
        for r in client.get(f"/api/analyses/{tid}/trace").json()
    )
    # No body instruction became a goal or a tool name.
    assert "忽略" not in report["plan"]["goal"]


def test_graph_resume_after_review_failure_uses_completed_domain_artifacts(client):
    from pathlib import Path

    full = Path("tests/fixtures/novels/agent_demo.txt").read_bytes()
    tid = client.post(
        "/api/uploads", files={"file": ("demo.txt", full, "text/plain")}
    ).json()["task_id"]
    client.post(f"/api/documents/{tid}/parse")
    client.post(f"/api/analyses/{tid}/plan", json={})
    gateway = ScriptedSemanticGateway(fail_review=True)
    client.app.state.model_gateway = gateway
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    assert wait(client, tid)["status"] == "failed"
    assert (
        gateway.domain_calls == 3
        and gateway.plan_calls == 1
        and gateway.batch_calls == 1
    )
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    assert wait(client, tid)["status"] == "completed"
    assert gateway.domain_calls == 4 and gateway.plan_calls == 1
    # A single targeted semantic repair; no second batch model call.
    assert gateway.batch_calls == 2  # leaf + final outline


def test_graph_checkpoint_survives_new_application(client):
    from pathlib import Path

    from fastapi.testclient import TestClient

    from apps.api.novelatlas_api.config import Settings
    from apps.api.novelatlas_api.main import create_app

    full = Path("tests/fixtures/novels/agent_demo.txt").read_bytes()
    tid = client.post(
        "/api/uploads", files={"file": ("demo.txt", full, "text/plain")}
    ).json()["task_id"]
    client.post(f"/api/documents/{tid}/parse")
    client.post(f"/api/analyses/{tid}/plan", json={})
    client.app.state.model_gateway = ScriptedSemanticGateway(fail_review=True)
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    assert wait(client, tid)["status"] == "failed"
    root = client.app.state.upload_storage.root
    restarted = create_app(settings=Settings(_env_file=None), storage_root=root)
    with TestClient(restarted) as second:
        gateway = ScriptedSemanticGateway()
        second.app.state.model_gateway = gateway
        second.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
        assert wait(second, tid)["status"] == "completed"
        assert (
            gateway.plan_calls == 0
            and gateway.domain_calls == 1
            and gateway.batch_calls == 1
        )


def test_cancel_domains_resume_and_task_scoped_index_deletion(client):
    tid = setup(client)
    gateway = ScriptedSemanticGateway(pause_domain=True)
    client.app.state.model_gateway = gateway
    # Keep the scripted schema test on the fixture containing its expected phrases.
    from pathlib import Path

    client.delete(f"/api/uploads/{tid}")
    full = Path("tests/fixtures/novels/agent_demo.txt").read_bytes()
    tid = client.post(
        "/api/uploads", files={"file": ("demo.txt", full, "text/plain")}
    ).json()["task_id"]
    client.post(f"/api/documents/{tid}/parse")
    client.post(f"/api/analyses/{tid}/plan", json={})
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    for _ in range(100):
        if gateway.active:
            break
        time.sleep(0.01)
    assert gateway.active == 2
    assert client.post(f"/api/analyses/{tid}/cancel").status_code == 200
    assert wait(client, tid)["status"] == "interrupted"
    assert gateway.active == 0
    gateway.pause_domain = False
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    assert wait(client, tid)["status"] == "completed"
    path = client.app.state.upload_storage.source_path(tid).parent
    assert (path / "graph.sqlite").is_file() and (path / "retrieval.sqlite").is_file()
    client.delete(f"/api/uploads/{tid}")
    assert not path.exists()
    assert client.get(f"/api/analyses/{tid}/knowledge").status_code == 404


def test_chunk_edit_rebuilds_index_and_invalidates_old_passage(client):
    tid = setup(client)
    row = client.post(f"/api/analyses/{tid}/search", json={"query": "林舟"}).json()[0]
    client.patch(
        f"/api/documents/{tid}/chunks/{row['chunk_id']}",
        json={"content": "人工改文：赵星在白城独自等待。"},
    )
    current = client.post(
        f"/api/analyses/{tid}/search", json={"query": "赵星 白城"}
    ).json()
    assert any(r["origin"] == "user_edit" for r in current)
    e = {k: row[k] for k in ["passage_id", "chapter_id", "chunk_id"]} | {
        "quote": row["content"][:10]
    }
    assert not client.post(f"/api/analyses/{tid}/verify", json=e).json()["quote_valid"]


def test_gateway_overall_timeout_has_finite_retries():
    attempts = []
    gateway = ModelGateway(
        text=ProviderConfig(provider="mock", model="test", base_url="", api_key=None),
        timeout_seconds=0.005,
        max_retries=2,
        retry_base_delay_seconds=0,
        observer=attempts.append,
    )

    async def slow():
        await asyncio.sleep(0.1)
        return "never reached"

    from novelatlas.models import ModelGatewayError

    with pytest.raises(ModelGatewayError) as error:
        asyncio.run(gateway._with_retries(slow))
    assert error.value.code == "provider_timeout"
    assert len(attempts) == 3 and all(a["status"] == "failed" for a in attempts)


def test_react_exits_on_budget_even_if_model_keeps_searching(client):
    from novelatlas.agents.knowledge import VerificationAgent
    from novelatlas.analysis.telemetry import Trace
    from novelatlas.schemas.knowledge import KnowledgeItem
    from novelatlas.schemas.models import TextGenerationResult
    from novelatlas.tools.retrieval import SourceIndex

    class Endless:
        text_config = ProviderConfig(
            provider="openai", model="endless", base_url="", api_key=None
        )

        async def generate_text(self, request):
            return TextGenerationResult(
                provider="openai",
                model="endless",
                content='{"action":"search","search":{"query":"林舟"}}',
                is_mock=False,
            )

    tid = setup(client)
    storage = client.app.state.upload_storage
    index = SourceIndex(storage, tid)
    index.ensure()
    item = KnowledgeItem(
        subject="林舟", predicate="状态", object="未知", description="未知事实"
    )
    result = asyncio.run(
        VerificationAgent(max_steps=4, call_budget=2).review(
            "events",
            0,
            item,
            index,
            Endless(),
            Trace(storage, tid),
            tokenizer="o200k_base",
            input_limit=24000,
            output_limit=4000,
        )
    )
    assert result.verdict == "uncertain" and result.calls == 2 and result.steps == 3
    assert len([r for r in Trace(storage, tid).records() if r["kind"] == "tool"]) == 2


def test_task_review_budget_marks_unreviewed_items_uncertain(client):
    tid = setup(client)
    response = client.post(
        f"/api/analyses/{tid}/run", json={"engine": "langgraph", "review_limit": 1}
    )
    assert response.status_code == 202
    assert wait(client, tid)["status"] == "completed"
    report = client.get(f"/api/analyses/{tid}/knowledge").json()
    assert len([r for r in report["reviews"] if r["steps"] > 0]) == 1
    assert len([r for r in report["reviews"] if r["steps"] == 0]) == 2
    assert report["repaired_tasks"] == []
    assert (
        len(
            [
                i
                for d in report["domains"]
                for i in d["items"]
                if i["classification"] == "uncertain"
            ]
        )
        == 2
    )


def test_graph_schedules_multiple_original_batches(tmp_path):
    from fastapi.testclient import TestClient

    from apps.api.novelatlas_api.config import Settings
    from apps.api.novelatlas_api.main import create_app

    text = "\n".join(
        f"第{i}章 联盟\n" + "林舟与沈月在青城结盟。" * 4000 for i in range(1, 4)
    )
    app = create_app(
        settings=Settings(_env_file=None), storage_root=tmp_path / "graph-long"
    )
    with TestClient(app) as client:
        tid = client.post(
            "/api/uploads", files={"file": ("long.txt", text.encode(), "text/plain")}
        ).json()["task_id"]
        client.post(f"/api/documents/{tid}/parse")
        plan = client.post(f"/api/analyses/{tid}/plan", json={}).json()
        assert plan["batch_count"] > 1
        client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
        assert wait(client, tid)["status"] == "completed"
        trace = client.get(f"/api/analyses/{tid}/trace").json()
        assert (
            len(
                [
                    r
                    for r in trace
                    if r["kind"] == "node"
                    and r["node"] == "batch"
                    and r["status"] == "completed"
                ]
            )
            == plan["batch_count"]
        )
        assert (
            len(client.get(f"/api/analyses/{tid}/summaries").json())
            == plan["batch_count"]
        )


def test_report_cannot_upgrade_uncertain_knowledge_to_certain():
    from novelatlas.agents.hierarchical_outline import (
        OutlineInputMaterial,
        _expand_sources,
    )
    from novelatlas.schemas.analysis import NovelOutline, OutlineClaim, OutlineSource

    material = OutlineInputMaterial(
        input_id="knowledge_events",
        fingerprint="a" * 64,
        chapter_range="第三章",
        batch_ids=("batch_source",),
        chapter_ids=("chapter_source",),
        payload={
            "items": [{"description": "未经核验的推断", "classification": "uncertain"}]
        },
    )
    claim = OutlineClaim(
        description="模型把未核验信息称为事实",
        confidence="certain",
        sources=OutlineSource(input_ids=["knowledge_events"]),
    )
    outline = NovelOutline(
        overall_summary="测试报告", conflicts_and_uncertainties=[claim]
    )
    _expand_sources(outline, [material])
    assert claim.confidence == "uncertain" and claim.sources.chapter_ids == [
        "chapter_source"
    ]


def test_edited_evidence_cannot_be_presented_as_original(client):
    tid = setup(client)
    row = client.post(f"/api/analyses/{tid}/search", json={"query": "林舟"}).json()[0]
    client.patch(
        f"/api/documents/{tid}/chunks/{row['chunk_id']}",
        json={"content": "赵星在白城等待。"},
    )
    edited = client.post(
        f"/api/analyses/{tid}/search", json={"query": "赵星 白城"}
    ).json()[0]
    e = {k: edited[k] for k in ["passage_id", "chapter_id", "chunk_id", "origin"]} | {
        "quote": "赵星在白城等待。"
    }
    assert client.post(f"/api/analyses/{tid}/verify", json=e).json()["quote_valid"]
    e["origin"] = "original"
    assert not client.post(f"/api/analyses/{tid}/verify", json=e).json()["quote_valid"]


def test_edit_crash_between_summary_write_and_downstream_reset_is_reconciled(client):
    from datetime import UTC, datetime

    from novelatlas.schemas.analysis import BatchSummaryRecord

    tid = setup(client)
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    assert wait(client, tid)["status"] == "completed"
    runner = client.app.state.analysis_task_manager.runner
    old = runner.load_manifest(tid).summary_revision
    record = BatchSummaryRecord.model_validate(
        client.get(f"/api/analyses/{tid}/summaries").json()[0]
    )
    record.summary.overview = "模拟：人工结果已落盘，但派生失效过程尚未发生"
    record.user_edited_at = datetime.now(UTC)
    runner._save_summary(record)
    # Manifest and graph still say completed: restart must detect revision mismatch.
    client.post(f"/api/analyses/{tid}/run", json={"engine": "langgraph"})
    assert wait(client, tid)["status"] == "completed"
    assert runner.load_manifest(tid).summary_revision != old
    assert (
        client.get(f"/api/analyses/{tid}/summaries").json()[0]["summary"]["overview"]
        == record.summary.overview
    )
