"""Schemas for uploaded novel documents."""

from datetime import datetime

from pydantic import BaseModel, Field


class UploadedDocument(BaseModel):
    """Metadata returned after a TXT document is accepted."""

    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    filename: str
    detected_encoding: str
    size_bytes: int = Field(ge=1)
    character_count: int = Field(ge=1)
    created_at: datetime
    expires_at: datetime


class DeleteUploadResponse(BaseModel):
    """Response returned after deleting a temporary upload."""

    task_id: str
    deleted: bool


class UploadConstraints(BaseModel):
    """Public limits used by the upload interface."""

    max_upload_bytes: int = Field(ge=1)
    upload_ttl_seconds: int = Field(ge=1)
    accepted_extensions: list[str]
