"""Actual LangGraph scheduling with task-local SQLite checkpoints and artifacts."""

import asyncio
import json
import time
from hashlib import sha256
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from novelatlas.agents.knowledge import DomainAgent, PlanningAgent, VerificationAgent
from novelatlas.analysis.telemetry import Trace, TracedGateway
from novelatlas.schemas.knowledge import (
    DomainResult,
    KnowledgeReport,
    ReviewResult,
    SemanticPlan,
)
from novelatlas.schemas.parsing import ParsedDocument
from novelatlas.services.temporary_storage import ArtifactNotFoundError
from novelatlas.tools.retrieval import SourceIndex


class GraphState(TypedDict, total=False):
    task_id: str
    plan_id: str
    cursor: int
    completed: list[str]
    repair_round: int
    repair_tasks: list[str]
    repaired_tasks: list[str]
    reviews: list[dict]


class GraphExecutionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def digest(value) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def run_graph(runner, task_id, gateway):
    storage = runner.storage
    budget_plan = runner._load_plan(task_id)
    await asyncio.to_thread(runner._reconstruct_plan, task_id, budget_plan)
    manifest = runner.load_manifest(task_id)
    parsed = ParsedDocument.model_validate_json(
        storage.read_json_artifact(task_id, "parse-result")
    )
    index = SourceIndex(storage, task_id)
    await asyncio.to_thread(index.ensure)
    trace = Trace(storage, task_id)
    traced = TracedGateway(gateway, trace, budget_plan.tokenizer)
    limits = {
        "tokenizer": budget_plan.tokenizer,
        "input_limit": budget_plan.budget.request_input_limit_tokens,
        "output_limit": budget_plan.budget.output_reserve_tokens,
    }
    semaphore = asyncio.Semaphore(manifest.agent_concurrency)

    def read(name, schema):
        return schema.model_validate_json(storage.read_json_artifact(task_id, name))

    def save(name, value):
        storage.write_json_artifact(task_id, name, value.model_dump_json())

    def semantic():
        return read("semantic-plan", SemanticPlan)

    def domains(completed):
        return [read("domain-" + tid, DomainResult) for tid in completed]

    async def planning(state):
        try:
            semantic()
        except ArtifactNotFoundError:
            plan = await PlanningAgent().plan(
                manifest.analysis_goal, parsed, traced, **limits
            )
            save("semantic-plan", plan)
        return {
            "completed": state.get("completed", []),
            "cursor": state.get("cursor", 0),
            "repair_round": state.get("repair_round", 0),
        }

    async def batch(state):
        cursor = state["cursor"]
        batches = budget_plan.batches
        if cursor < len(batches):
            # A graph node handles one business batch. Artifact reconciliation is reused.
            result = await runner.run(
                task_id,
                traced,
                batch_ids={batches[cursor].batch_id},
                graph_dispatch=False,
            )
            if result.status == "failed":
                raise GraphExecutionError(result.error.code)
        return {"cursor": cursor + 1}

    def after_batch(state):
        return "batch" if state["cursor"] < len(budget_plan.batches) else "solve"

    async def solve(state):
        plan = semantic()
        completed = state.get("completed", [])
        ready = [
            t
            for t in plan.tasks
            if t.task_id not in completed and set(t.depends_on) <= set(completed)
        ]
        if not ready:
            return {}
        summaries = runner.load_summaries(task_id)
        previous_reviews = state.get("reviews", [])

        async def execute(task):
            dependencies = [r.model_dump() for r in domains(task.depends_on)]
            feedback = [
                r
                for r in previous_reviews
                if r["task_id"] == task.task_id and r["verdict"] != "supported"
            ]
            fp = digest(
                {
                    "task": task.model_dump(),
                    "summaries": [r.model_dump(mode="json") for r in summaries],
                    "dependencies": dependencies,
                    "feedback": feedback,
                }
            )
            name = "domain-cache-" + task.task_id
            try:
                cached = json.loads(storage.read_json_artifact(task_id, name))
                result = (
                    DomainResult.model_validate(cached["result"])
                    if cached["fingerprint"] == fp
                    else None
                )
            except ArtifactNotFoundError:
                result = None
            if result is None:
                async with semaphore:
                    result = await DomainAgent().solve(
                        task,
                        summaries,
                        dependencies,
                        index,
                        traced,
                        trace,
                        feedback=feedback,
                        **limits,
                    )
                storage.write_json_artifact(
                    task_id,
                    name,
                    json.dumps(
                        {"fingerprint": fp, "result": result.model_dump()},
                        ensure_ascii=False,
                    ),
                )
            save("domain-" + task.task_id, result)
            trace.emit(
                "handoff",
                task=task.task_id,
                depends_on=task.depends_on,
                artifact="domain-" + task.task_id,
                item_count=len(result.items),
            )
            return task.task_id

        running = [asyncio.create_task(execute(task)) for task in ready]
        try:
            done = await asyncio.gather(*running)
        except BaseException:
            for job in running:
                job.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            raise
        return {"completed": [*completed, *done]}

    def after_solve(state):
        return "review" if len(state["completed"]) == len(semantic().tasks) else "solve"

    async def review(state):
        results = []
        reviewed = 0
        for domain in domains(state["completed"]):
            for idx, item in enumerate(domain.items):
                if reviewed >= manifest.agent_review_limit:
                    results.append(
                        ReviewResult(
                            task_id=domain.task_id,
                            item_index=idx,
                            verdict="uncertain",
                            quote_valid=False,
                            note="超出任务核验条目预算，保留人工核验",
                            steps=0,
                            calls=0,
                        ).model_dump()
                    )
                    continue
                reviewed += 1
                # Per-item cache prevents repeated review calls after a crash.
                fp = digest(item.model_dump())
                name = "review-" + domain.task_id + "-" + str(idx) + "-" + fp[:16]
                try:
                    result = read(name, ReviewResult)
                except ArtifactNotFoundError:
                    result = await VerificationAgent().review(
                        domain.task_id, idx, item, index, traced, trace, **limits
                    )
                    save(name, result)
                results.append(result.model_dump())
        failed = list(
            dict.fromkeys(
                r["task_id"]
                for r in results
                if r["verdict"] != "supported" and r["steps"] > 0
            )
        )
        return {"reviews": results, "repair_tasks": failed}

    def after_review(state):
        return (
            "repair"
            if state["repair_tasks"] and state["repair_round"] < 1
            else "report"
        )

    async def repair(state):
        affected = set(state["repair_tasks"])
        changed = True
        while changed:
            before = len(affected)
            for task in semantic().tasks:
                if set(task.depends_on) & affected:
                    affected.add(task.task_id)
            changed = before != len(affected)
        trace.emit("repair", targets=sorted(affected), round=1)
        return {
            "repair_round": 1,
            "completed": [tid for tid in state["completed"] if tid not in affected],
            "repair_tasks": sorted(affected),
            "repaired_tasks": sorted(affected),
        }

    async def report(state):
        ds = domains(state["completed"])
        rs = [ReviewResult.model_validate(r) for r in state["reviews"]]
        entities, history, conflicts = {}, [], []
        # Canonicalization only uses aliases from semantically supported items.
        aliases = {}
        for domain in ds:
            for idx, item in enumerate(domain.items):
                review = next(
                    r for r in rs if r.task_id == domain.task_id and r.item_index == idx
                )
                if review.verdict != "supported":
                    item.classification = "uncertain"
                    item.aliases = []
                    conflicts.append(
                        f"{domain.task_id}:{idx} {review.verdict}: {review.note}"
                    )
                if review.verdict == "supported":
                    item.evidence = review.evidence
                    for alias in item.aliases:
                        if alias in aliases and aliases[alias] != item.subject:
                            conflicts.append(f"别名 {alias} 对应多个人物，暂不归并")
                            aliases[alias] = None
                        else:
                            aliases[alias] = item.subject
        for domain in ds:
            for item in domain.items:
                canonical = aliases.get(item.subject) or item.subject
                entities.setdefault(canonical, [])
                entities[canonical] = sorted(
                    set(entities[canonical] + [item.subject] + item.aliases)
                )
                history.append(
                    {
                        "subject": canonical,
                        "predicate": item.predicate,
                        "object": item.object,
                        "chapter_ids": list(
                            dict.fromkeys(e.chapter_id for e in item.evidence)
                        ),
                        "classification": item.classification,
                    }
                )
        # Multiple values stay as a chapter-linked timeline, not silently overwritten.
        report = KnowledgeReport(
            fingerprint=digest(
                {"domains": [d.model_dump() for d in ds], "reviews": state["reviews"]}
            ),
            plan=semantic(),
            domains=ds,
            reviews=rs,
            entities=entities,
            relation_history=history,
            conflicts=conflicts,
            repaired_tasks=state.get("repaired_tasks", []),
        )
        save("knowledge-report", report)
        result = await runner._run_hierarchy(
            task_id=task_id,
            plan=budget_plan,
            manifest=runner.load_manifest(task_id),
            gateway=traced,
        )
        if result.status == "failed":
            raise GraphExecutionError(result.error.code)
        return {}

    def observed(name, node):
        async def call(state):
            start = time.perf_counter()
            current = runner.load_manifest(task_id)
            current.graph_node = name
            current.status = "running"
            from datetime import UTC, datetime

            current.updated_at = datetime.now(UTC)
            runner._save_manifest(current)
            trace.emit("node", node=name, status="running")
            try:
                result = await node(state)
            except BaseException as error:
                trace.emit(
                    "node",
                    node=name,
                    status="interrupted"
                    if isinstance(error, asyncio.CancelledError)
                    else "failed",
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    error_code=getattr(error, "code", type(error).__name__),
                )
                raise
            trace.emit(
                "node",
                node=name,
                status="completed",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            return result

        return call

    builder = StateGraph(GraphState)
    for name, node in [
        ("planning", planning),
        ("batch", batch),
        ("solve", solve),
        ("review", review),
        ("repair", repair),
        ("report", report),
    ]:
        builder.add_node(name, observed(name, node))
    builder.add_edge(START, "planning")
    builder.add_edge("planning", "batch")
    builder.add_conditional_edges("batch", after_batch)
    builder.add_conditional_edges("solve", after_solve)
    builder.add_conditional_edges("review", after_review)
    builder.add_edge("repair", "solve")
    builder.add_edge("report", END)
    checkpoint_path = storage.source_path(task_id).parent / "graph.sqlite"
    config = {
        "configurable": {"thread_id": task_id + ":" + budget_plan.plan_id},
        "recursion_limit": len(budget_plan.batches) + 64,
    }
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        graph = builder.compile(checkpointer=saver)
        snapshot = await graph.aget_state(config)
        await graph.ainvoke(
            None
            if snapshot.next
            else {
                "task_id": task_id,
                "plan_id": budget_plan.plan_id,
                "cursor": 0,
                "completed": [],
                "repair_round": 0,
            },
            config,
        )
    return runner.load_manifest(task_id)
