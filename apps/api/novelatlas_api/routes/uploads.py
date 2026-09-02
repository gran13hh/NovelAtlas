"""TXT upload and temporary lifecycle endpoints."""

from pathlib import Path
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi import Path as ApiPath
from starlette.concurrency import run_in_threadpool

from novelatlas.schemas.document import (
    DeleteUploadResponse,
    UploadConstraints,
    UploadedDocument,
)
from novelatlas.services.temporary_storage import (
    TemporaryUploadStorage,
    UploadNotFoundError,
)
from novelatlas.services.text_decoder import TextDecodeError, decode_txt

from ..config import Settings
from ..dependencies import get_max_upload_bytes, get_settings, get_upload_storage

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
TaskId = Annotated[str, ApiPath(pattern=r"^[0-9a-f]{32}$")]
Storage = Annotated[TemporaryUploadStorage, Depends(get_upload_storage)]
MaxUploadBytes = Annotated[int, Depends(get_max_upload_bytes)]
UploadSettings = Annotated[Settings, Depends(get_settings)]


def _safe_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    basename = Path(filename.replace("\\", "/")).name.strip()
    if not basename or len(basename) > 255:
        raise HTTPException(status_code=400, detail="文件名无效或过长")
    if Path(basename).suffix.lower() != ".txt":
        raise HTTPException(status_code=415, detail="仅支持 .txt 文件")
    return basename


def _validate_content_type(content_type: str | None) -> None:
    if not content_type:
        return
    media_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if not (media_type.startswith("text/") or media_type == "application/octet-stream"):
        raise HTTPException(status_code=415, detail="文件内容类型必须为纯文本")


@router.post("", response_model=UploadedDocument, status_code=201)
async def upload_txt(
    file: Annotated[UploadFile, File(description="Novel text in TXT format")],
    storage: Storage,
    max_upload_bytes: MaxUploadBytes,
) -> UploadedDocument:
    """Validate, decode, normalize, and temporarily store a TXT novel."""

    filename = _safe_filename(file.filename)
    _validate_content_type(file.content_type)
    storage.cleanup_expired()
    task_id, raw_path = storage.begin_upload()
    size_bytes = 0

    try:
        async with await anyio.open_file(raw_path, "wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"TXT 文件不能超过 {max_upload_bytes} 字节",
                    )
                await destination.write(chunk)

        if size_bytes == 0:
            raise HTTPException(status_code=400, detail="TXT 文件为空")

        decoded = await run_in_threadpool(lambda: decode_txt(raw_path.read_bytes()))
        return await run_in_threadpool(
            lambda: storage.finalize_upload(
                task_id=task_id,
                filename=filename,
                size_bytes=size_bytes,
                decoded=decoded,
            )
        )
    except TextDecodeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()
        if raw_path.exists():
            storage.discard_incomplete(task_id)


@router.get("/config", response_model=UploadConstraints)
async def get_upload_constraints(settings: UploadSettings) -> UploadConstraints:
    """Return the limits the browser should enforce before uploading."""

    return UploadConstraints(
        max_upload_bytes=settings.max_upload_bytes,
        upload_ttl_seconds=settings.upload_ttl_seconds,
        accepted_extensions=[".txt"],
    )


@router.get("/{task_id}", response_model=UploadedDocument)
async def get_upload(task_id: TaskId, storage: Storage) -> UploadedDocument:
    """Return metadata for a temporary upload."""

    try:
        return await run_in_threadpool(storage.get, task_id)
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期") from error


@router.delete("/{task_id}", response_model=DeleteUploadResponse)
async def delete_upload(task_id: TaskId, storage: Storage) -> DeleteUploadResponse:
    """Delete an uploaded novel and all task-scoped temporary files."""

    deleted = await run_in_threadpool(storage.delete, task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="上传任务不存在或已过期")
    return DeleteUploadResponse(task_id=task_id, deleted=True)
