"""Deterministic source parsing and parse-preview endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as ApiPath
from starlette.concurrency import run_in_threadpool

from novelatlas.schemas.parsing import (
    ParsedDocument,
    TextChunk,
    TextChunkContent,
    UpdateTextChunkRequest,
)
from novelatlas.services.chapter_parser import ChapterParser
from novelatlas.services.temporary_storage import (
    ArtifactNotFoundError,
    TemporaryUploadStorage,
    UploadNotFoundError,
)
from novelatlas.services.token_chunker import ChunkingConfig, TokenChunker

from ..config import Settings
from ..dependencies import get_settings, get_upload_storage

router = APIRouter(prefix="/api/documents", tags=["documents"])
TaskId = Annotated[str, ApiPath(pattern=r"^[0-9a-f]{32}$")]
ChunkId = Annotated[str, ApiPath(pattern=r"^chunk_[0-9a-f]{16}$")]
Storage = Annotated[TemporaryUploadStorage, Depends(get_upload_storage)]
ParseSettings = Annotated[Settings, Depends(get_settings)]
PARSE_ARTIFACT = "parse-result"


class ChunkNotFoundError(LookupError):
    """Raised when a parsed manifest does not contain a requested chunk."""


class ChunkTokenLimitError(ValueError):
    """Raised when an edited chunk exceeds the configured model-safe limit."""

    def __init__(self, token_count: int, max_tokens: int) -> None:
        self.token_count = token_count
        self.max_tokens = max_tokens
        super().__init__(f"{token_count} > {max_tokens}")


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


def _load_parsed_document(
    task_id: str,
    storage: TemporaryUploadStorage,
) -> ParsedDocument:
    payload = storage.read_json_artifact(task_id, PARSE_ARTIFACT)
    return ParsedDocument.model_validate_json(payload)


def _save_parsed_document(
    parsed: ParsedDocument,
    storage: TemporaryUploadStorage,
) -> ParsedDocument:
    storage.write_json_artifact(
        parsed.task_id,
        PARSE_ARTIFACT,
        parsed.model_dump_json(indent=2),
    )
    return parsed


def _find_chunk(parsed: ParsedDocument, chunk_id: str) -> TextChunk:
    for chunk in parsed.chunks:
        if chunk.chunk_id == chunk_id:
            return chunk
    raise ChunkNotFoundError(chunk_id)


def _original_chunk_content(
    task_id: str,
    chunk: TextChunk,
    storage: TemporaryUploadStorage,
) -> str:
    source = storage.source_path(task_id).read_text(encoding="utf-8")
    reference = chunk.reference
    return source[reference.start_char : reference.end_char]


def _get_chunk_content(
    task_id: str,
    chunk_id: str,
    storage: TemporaryUploadStorage,
) -> TextChunkContent:
    parsed = _load_parsed_document(task_id, storage)
    chunk = _find_chunk(parsed, chunk_id)
    original_content = _original_chunk_content(task_id, chunk, storage)
    return TextChunkContent(
        chunk=chunk,
        content=chunk.content_override or original_content,
        original_content=original_content,
        is_edited=chunk.content_override is not None,
    )


def _update_chunk_content(
    task_id: str,
    chunk_id: str,
    content: str,
    storage: TemporaryUploadStorage,
    settings: Settings,
) -> ParsedDocument:
    parsed = _load_parsed_document(task_id, storage)
    chunk = _find_chunk(parsed, chunk_id)
    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
    tokenizer = TokenChunker(
        ChunkingConfig(
            tokenizer_name=settings.tokenizer_name,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
    )
    token_count = tokenizer.count(normalized_content)
    if token_count > settings.chunk_max_tokens:
        raise ChunkTokenLimitError(token_count, settings.chunk_max_tokens)

    original_content = _original_chunk_content(task_id, chunk, storage)
    chunk.content_override = (
        None if normalized_content == original_content else normalized_content
    )
    chunk.token_count = token_count
    return _save_parsed_document(parsed, storage)


def _delete_chunk(
    task_id: str,
    chunk_id: str,
    storage: TemporaryUploadStorage,
) -> ParsedDocument:
    parsed = _load_parsed_document(task_id, storage)
    _find_chunk(parsed, chunk_id)
    parsed.chunks = [chunk for chunk in parsed.chunks if chunk.chunk_id != chunk_id]
    parsed.chunk_count = len(parsed.chunks)
    for chapter in parsed.chapters:
        chapter.chunk_ids = [
            existing_id for existing_id in chapter.chunk_ids if existing_id != chunk_id
        ]
    return _save_parsed_document(parsed, storage)


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


@router.get(
    "/{task_id}/chunks/{chunk_id}",
    response_model=TextChunkContent,
)
async def get_chunk_content(
    task_id: TaskId,
    chunk_id: ChunkId,
    storage: Storage,
) -> TextChunkContent:
    """Load one chunk's editable content without returning the complete source."""

    try:
        return await run_in_threadpool(
            _get_chunk_content,
            task_id,
            chunk_id,
            storage,
        )
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error
    except ArtifactNotFoundError as error:
        raise HTTPException(status_code=404, detail="该小说尚未解析") from error
    except ChunkNotFoundError as error:
        raise HTTPException(status_code=404, detail="文本块不存在或已删除") from error
    except ValueError as error:
        raise HTTPException(status_code=500, detail="解析结果已损坏，请重新解析") from error


@router.patch(
    "/{task_id}/chunks/{chunk_id}",
    response_model=ParsedDocument,
)
async def update_chunk_content(
    task_id: TaskId,
    chunk_id: ChunkId,
    request: UpdateTextChunkRequest,
    storage: Storage,
    settings: ParseSettings,
) -> ParsedDocument:
    """Persist a task-scoped content override while preserving source coordinates."""

    try:
        return await run_in_threadpool(
            _update_chunk_content,
            task_id,
            chunk_id,
            request.content,
            storage,
            settings,
        )
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error
    except ArtifactNotFoundError as error:
        raise HTTPException(status_code=404, detail="该小说尚未解析") from error
    except ChunkNotFoundError as error:
        raise HTTPException(status_code=404, detail="文本块不存在或已删除") from error
    except ChunkTokenLimitError as error:
        raise HTTPException(
            status_code=422,
            detail=(
                f"编辑后的文本块包含 {error.token_count} Token，"
                f"不能超过 {error.max_tokens} Token"
            ),
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=500, detail="解析结果已损坏，请重新解析") from error


@router.delete(
    "/{task_id}/chunks/{chunk_id}",
    response_model=ParsedDocument,
)
async def delete_chunk(
    task_id: TaskId,
    chunk_id: ChunkId,
    storage: Storage,
) -> ParsedDocument:
    """Remove one chunk from the current manifest without rewriting source text."""

    try:
        return await run_in_threadpool(_delete_chunk, task_id, chunk_id, storage)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error
    except ArtifactNotFoundError as error:
        raise HTTPException(status_code=404, detail="该小说尚未解析") from error
    except ChunkNotFoundError as error:
        raise HTTPException(status_code=404, detail="文本块不存在或已删除") from error
    except ValueError as error:
        raise HTTPException(status_code=500, detail="解析结果已损坏，请重新解析") from error
