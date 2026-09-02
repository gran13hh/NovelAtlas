"""Deterministic source parsing and parse-preview endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as ApiPath
from starlette.concurrency import run_in_threadpool

from novelatlas.schemas.parsing import ParsedDocument
from novelatlas.services.chapter_parser import ChapterParser
from novelatlas.services.temporary_storage import (
    ArtifactNotFoundError,
    TemporaryUploadStorage,
    UploadNotFoundError,
)
from novelatlas.services.token_chunker import ChunkingConfig

from ..config import Settings
from ..dependencies import get_settings, get_upload_storage

router = APIRouter(prefix="/api/documents", tags=["documents"])
TaskId = Annotated[str, ApiPath(pattern=r"^[0-9a-f]{32}$")]
Storage = Annotated[TemporaryUploadStorage, Depends(get_upload_storage)]
ParseSettings = Annotated[Settings, Depends(get_settings)]
PARSE_ARTIFACT = "parse-result"


def _parse_document(
    task_id: str,
    storage: TemporaryUploadStorage,
    settings: Settings,
) -> ParsedDocument:
    metadata = storage.get(task_id)
    text = storage.source_path(task_id).read_text(encoding="utf-8")
    parser = ChapterParser(
        ChunkingConfig(
            tokenizer_name=settings.tokenizer_name,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
    )
    parsed = parser.parse(task_id=task_id, filename=metadata.filename, text=text)
    storage.write_json_artifact(
        task_id,
        PARSE_ARTIFACT,
        parsed.model_dump_json(indent=2),
    )
    return parsed


@router.post("/{task_id}/parse", response_model=ParsedDocument)
async def parse_document(
    task_id: TaskId,
    storage: Storage,
    settings: ParseSettings,
) -> ParsedDocument:
    """Parse or reparse one temporary source and persist its manifest."""

    try:
        return await run_in_threadpool(_parse_document, task_id, storage, settings)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"小说解析失败：{error}") from error


@router.get("/{task_id}/parse", response_model=ParsedDocument)
async def get_parse_result(task_id: TaskId, storage: Storage) -> ParsedDocument:
    """Return a previously generated parse manifest without reparsing source."""

    try:
        payload = await run_in_threadpool(
            storage.read_json_artifact,
            task_id,
            PARSE_ARTIFACT,
        )
        return ParsedDocument.model_validate_json(payload)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error
    except ArtifactNotFoundError as error:
        raise HTTPException(status_code=404, detail="该小说尚未解析") from error
    except ValueError as error:
        raise HTTPException(status_code=500, detail="解析结果已损坏，请重新解析") from error
