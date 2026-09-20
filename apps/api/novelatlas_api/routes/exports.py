"""Stateless DOCX and HTML outline export endpoint."""

from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from novelatlas.schemas.exports import OutlineExportRequest
from novelatlas.services.outline_export import (
    render_outline_docx,
    render_outline_html,
    safe_export_filename,
)

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.post("/outline")
async def export_outline(request: OutlineExportRequest) -> StreamingResponse:
    """Render a validated browser outline without persisting supplied content."""

    if request.format == "docx":
        payload = await run_in_threadpool(
            render_outline_docx,
            title=request.title,
            outline=request.outline,
            sections=request.sections,
        )
        media_type = (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
    else:
        payload = await run_in_threadpool(
            render_outline_html,
            title=request.title,
            outline=request.outline,
            sections=request.sections,
        )
        media_type = "text/html; charset=utf-8"

    filename = safe_export_filename(request.title, request.format)
    disposition = (
        'attachment; filename="NovelAtlas-outline.'
        f'{request.format}"; filename*=UTF-8\'\'{quote(filename)}'
    )
    return StreamingResponse(
        BytesIO(payload),
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
