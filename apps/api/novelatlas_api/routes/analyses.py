"""Token-budgeted analysis planning endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi import Path as ApiPath
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from novelatlas.analysis import (
    AnalysisPlanMismatchError,
    AnalysisTaskAlreadyRunningError,
    AnalysisTaskManager,
    AnalysisTaskNotFoundError,
    plan_analysis,
    watch_analysis_progress,
)
from novelatlas.models import ModelGateway
from novelatlas.schemas.analysis import (
    AnalysisBudget,
    AnalysisPlan,
    AnalysisPlanRequest,
    AnalysisRunRequest,
    AnalysisTaskManifest,
    BatchSummaryRecord,
    FinalOutlineRecord,
)
from novelatlas.schemas.parsing import ParsedDocument
from novelatlas.services.temporary_storage import (
    ArtifactNotFoundError,
    TemporaryUploadStorage,
    UploadNotFoundError,
)

from ..config import Settings
from ..dependencies import (
    create_transient_model_gateway,
    get_analysis_task_manager,
    get_model_gateway,
    get_settings,
    get_upload_storage,
)

router = APIRouter(prefix="/api/analyses", tags=["analyses"])
TaskId = Annotated[str, ApiPath(pattern=r"^[0-9a-f]{32}$")]
Storage = Annotated[TemporaryUploadStorage, Depends(get_upload_storage)]
AnalysisSettings = Annotated[Settings, Depends(get_settings)]
TaskManager = Annotated[AnalysisTaskManager, Depends(get_analysis_task_manager)]
Gateway = Annotated[ModelGateway, Depends(get_model_gateway)]
PARSE_ARTIFACT = "parse-result"
PLAN_ARTIFACT = "analysis-plan"


def _default_budget(settings: Settings) -> AnalysisBudget:
    return AnalysisBudget(
        context_window_tokens=settings.analysis_context_window_tokens,
        max_input_tokens=settings.analysis_max_input_tokens,
        output_reserve_tokens=settings.analysis_output_reserve_tokens,
        safety_margin_tokens=settings.analysis_safety_margin_tokens,
    )


def _build_plan(
    task_id: str,
    storage: TemporaryUploadStorage,
    budget: AnalysisBudget,
) -> AnalysisPlan:
    parsed = ParsedDocument.model_validate_json(
        storage.read_json_artifact(task_id, PARSE_ARTIFACT)
    )
    source = storage.source_path(task_id).read_text(encoding="utf-8")
    result = plan_analysis(parsed=parsed, source=source, budget=budget)
    storage.write_json_artifact(
        task_id,
        PLAN_ARTIFACT,
        result.plan.model_dump_json(indent=2),
    )
    return result.plan


@router.get("/config", response_model=AnalysisBudget)
async def get_analysis_budget(settings: AnalysisSettings) -> AnalysisBudget:
    """Return secret-free server defaults for analysis planning."""

    return _default_budget(settings)


@router.post("/{task_id}/plan", response_model=AnalysisPlan)
async def create_analysis_plan(
    task_id: TaskId,
    request: AnalysisPlanRequest,
    storage: Storage,
    settings: AnalysisSettings,
    tasks: TaskManager,
) -> AnalysisPlan:
    """Plan bounded model calls without invoking a model provider."""

    budget = request.budget or _default_budget(settings)
    try:
        if await tasks.is_running(task_id):
            raise HTTPException(status_code=409, detail="分析任务正在运行，不能重新规划")
        await tasks.discard(task_id, include_plan=False)
        return await run_in_threadpool(_build_plan, task_id, storage, budget)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error
    except ArtifactNotFoundError as error:
        raise HTTPException(status_code=409, detail="请先完成小说章节解析") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"分析批次规划失败：{error}") from error


@router.post(
    "/{task_id}/run",
    response_model=AnalysisTaskManifest,
    status_code=202,
)
async def run_analysis(
    task_id: TaskId,
    request: AnalysisRunRequest,
    tasks: TaskManager,
    server_gateway: Gateway,
) -> AnalysisTaskManifest:
    """Start or resume batch summaries, hierarchical merges, and final outline."""

    gateway = (
        create_transient_model_gateway(
            config=request.config,
            model=request.config.model,
            server_gateway=server_gateway,
        )
        if request.config is not None
        else server_gateway
    )
    try:
        return await tasks.start(task_id, gateway)
    except AnalysisTaskAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail="分析任务已经在运行") from error
    except (AnalysisPlanMismatchError, ArtifactNotFoundError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error


@router.get("/{task_id}/run", response_model=AnalysisTaskManifest)
async def get_analysis_status(
    task_id: TaskId,
    tasks: TaskManager,
) -> AnalysisTaskManifest:
    """Read persistent progress and normalize stale running tasks."""

    try:
        return await tasks.get(task_id)
    except AnalysisTaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="尚未启动分析任务") from error
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error


@router.get("/{task_id}/events")
async def stream_analysis_progress(
    task_id: TaskId,
    request: Request,
    tasks: TaskManager,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Stream compact persisted progress without owning the analysis task."""

    try:
        initial = await tasks.get(task_id)
    except AnalysisTaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="尚未启动分析任务") from error
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error

    async def event_stream():
        async for snapshot in watch_analysis_progress(
            tasks,
            task_id,
            initial=initial,
            last_event_id=last_event_id,
        ):
            if await request.is_disconnected():
                return
            event_name = (
                "analysis.completed"
                if snapshot.status == "completed"
                else "analysis.error"
                if snapshot.status in {"failed", "interrupted"}
                else "analysis.progress"
            )
            yield (
                f"id: {snapshot.event_id}\n"
                f"event: {event_name}\n"
                "retry: 1000\n"
                f"data: {snapshot.model_dump_json()}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{task_id}/summaries",
    response_model=list[BatchSummaryRecord],
)
async def get_batch_summaries(
    task_id: TaskId,
    tasks: TaskManager,
) -> list[BatchSummaryRecord]:
    """Return validated results for batches completed so far."""

    try:
        return await tasks.summaries(task_id)
    except AnalysisTaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="尚未启动分析任务") from error
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error


@router.get(
    "/{task_id}/outline",
    response_model=FinalOutlineRecord,
)
async def get_final_outline(
    task_id: TaskId,
    tasks: TaskManager,
) -> FinalOutlineRecord:
    """Return the validated final detailed outline once it is complete."""

    try:
        return await tasks.outline(task_id)
    except AnalysisTaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="尚未启动分析任务") from error
    except ArtifactNotFoundError as error:
        raise HTTPException(status_code=409, detail="全书细纲尚未生成") from error
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error


@router.get("/{task_id}/plan", response_model=AnalysisPlan)
async def get_analysis_plan(task_id: TaskId, storage: Storage) -> AnalysisPlan:
    """Return the latest persisted plan without rebuilding it."""

    try:
        payload = await run_in_threadpool(
            storage.read_json_artifact,
            task_id,
            PLAN_ARTIFACT,
        )
        return AnalysisPlan.model_validate_json(payload)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error
    except ArtifactNotFoundError as error:
        raise HTTPException(status_code=404, detail="尚未生成分析批次计划") from error
    except ValueError as error:
        raise HTTPException(status_code=500, detail="分析批次计划已损坏，请重新规划") from error
