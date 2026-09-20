"""Secret-free progress snapshots and detached SSE polling."""

import asyncio
from collections.abc import AsyncIterator
from hashlib import sha256

from novelatlas.schemas.analysis import (
    AnalysisProgressPhase,
    AnalysisProgressSnapshot,
    AnalysisTaskManifest,
)

from .tasks import AnalysisTaskManager

_TERMINAL_STATUSES = {"completed", "failed", "interrupted"}


def build_progress_snapshot(
    manifest: AnalysisTaskManifest,
) -> AnalysisProgressSnapshot:
    """Reduce a full checkpoint manifest to safe browser progress metadata."""

    current_batch = next(
        (
            checkpoint
            for checkpoint in manifest.batches
            if checkpoint.batch_id == manifest.current_batch_id
        ),
        None,
    )
    current_merge = next(
        (
            checkpoint
            for checkpoint in manifest.merge_nodes
            if checkpoint.node_id == manifest.current_merge_node_id
        ),
        None,
    )
    fingerprint = sha256(
        manifest.model_dump_json(exclude_none=False).encode()
    ).hexdigest()[:16]
    return AnalysisProgressSnapshot(
        event_id=f"progress_{fingerprint}",
        task_id=manifest.task_id,
        graph_node=manifest.graph_node,
        status=manifest.status,
        phase=_phase(manifest.status),
        completed_batch_count=manifest.completed_batch_count,
        batch_count=manifest.batch_count,
        current_batch_id=manifest.current_batch_id,
        current_batch_ordinal=(current_batch.ordinal if current_batch else None),
        completed_merge_node_count=manifest.completed_merge_node_count,
        merge_node_count=manifest.merge_node_count,
        current_merge_node_id=manifest.current_merge_node_id,
        current_merge_level=(current_merge.level if current_merge else None),
        final_outline_status=manifest.final_outline_status,
        error=manifest.error,
        terminal=manifest.status in _TERMINAL_STATUSES,
        updated_at=manifest.updated_at,
    )


async def watch_analysis_progress(
    tasks: AnalysisTaskManager,
    task_id: str,
    *,
    initial: AnalysisTaskManifest | None = None,
    last_event_id: str | None = None,
    poll_interval_seconds: float = 0.1,
) -> AsyncIterator[AnalysisProgressSnapshot]:
    """Poll persisted state without owning or cancelling the background task."""

    manifest = initial
    previous_event_id = last_event_id
    while True:
        if manifest is None:
            manifest = await tasks.get(task_id)
        snapshot = build_progress_snapshot(manifest)
        if snapshot.event_id != previous_event_id:
            yield snapshot
            previous_event_id = snapshot.event_id
        if snapshot.terminal:
            return
        await asyncio.sleep(poll_interval_seconds)
        manifest = await tasks.get(task_id)


def _phase(status: str) -> AnalysisProgressPhase:
    if status == "queued":
        return "queued"
    if status in {"running", "batch_summaries_completed"}:
        return "batch_summary"
    if status == "merging":
        return "hierarchical_merge"
    if status == "finalizing":
        return "final_outline"
    if status == "completed":
        return "completed"
    if status == "interrupted":
        return "interrupted"
    return "failed"
