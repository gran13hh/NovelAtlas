"""Task-scoped retrieval, evidence and graph observability endpoints."""

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from novelatlas.analysis.telemetry import Trace
from novelatlas.schemas.knowledge import (
    Evidence,
    KnowledgeReport,
    Passage,
    SearchArgs,
    SemanticPlan,
)
from novelatlas.services.temporary_storage import (
    ArtifactNotFoundError,
    UploadNotFoundError,
)
from novelatlas.tools.retrieval import SourceIndex

from .analyses import Storage, TaskId

router = APIRouter(prefix="/api/analyses", tags=["knowledge"])


def load_index(storage, task_id):
    index = SourceIndex(storage, task_id)
    index.ensure()
    return index


@router.post("/{task_id}/search", response_model=list[Passage])
async def search(task_id: TaskId, args: SearchArgs, storage: Storage):
    try:
        index = await run_in_threadpool(load_index, storage, task_id)
        return await run_in_threadpool(index.search, args)
    except (UploadNotFoundError, ArtifactNotFoundError) as error:
        raise HTTPException(404, "任务或解析产物不存在或已过期") from error


@router.post("/{task_id}/verify")
async def verify(task_id: TaskId, evidence: Evidence, storage: Storage):
    try:
        index = await run_in_threadpool(load_index, storage, task_id)
        return {
            "quote_valid": await run_in_threadpool(index.verify, evidence),
            "meaning_verified": False,
        }
    except (UploadNotFoundError, ArtifactNotFoundError) as error:
        raise HTTPException(404, "任务或解析产物不存在或已过期") from error


@router.get("/{task_id}/semantic-plan", response_model=SemanticPlan)
async def semantic_plan(task_id: TaskId, storage: Storage):
    try:
        return SemanticPlan.model_validate_json(
            await run_in_threadpool(
                storage.read_json_artifact, task_id, "semantic-plan"
            )
        )
    except (UploadNotFoundError, ArtifactNotFoundError) as error:
        raise HTTPException(404, "语义计划尚未生成或已作废") from error


@router.get("/{task_id}/knowledge", response_model=KnowledgeReport)
async def knowledge(task_id: TaskId, storage: Storage):
    try:
        return KnowledgeReport.model_validate_json(
            await run_in_threadpool(
                storage.read_json_artifact, task_id, "knowledge-report"
            )
        )
    except (UploadNotFoundError, ArtifactNotFoundError) as error:
        raise HTTPException(404, "核验报告尚未生成或已作废") from error


@router.get("/{task_id}/trace")
async def trace(task_id: TaskId, storage: Storage):
    try:
        return await run_in_threadpool(Trace(storage, task_id).records)
    except UploadNotFoundError as error:
        raise HTTPException(404, "任务不存在或已过期") from error
