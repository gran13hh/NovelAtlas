"""Schemas for safe, stateless outline export."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .analysis import NovelOutline

ExportFormat = Literal["docx", "html"]
ExportSection = Literal[
    "overall_summary",
    "chapter_outline",
    "storylines",
    "characters",
    "worldbuilding",
    "foreshadowing",
    "unresolved_items",
]

DEFAULT_EXPORT_SECTIONS: list[ExportSection] = [
    "overall_summary",
    "chapter_outline",
    "storylines",
    "characters",
    "worldbuilding",
    "foreshadowing",
    "unresolved_items",
]


class OutlineExportRequest(BaseModel):
    """Browser-supplied, validated outline rendered without server persistence."""

    title: str = Field(min_length=1, max_length=240)
    format: ExportFormat
    sections: list[ExportSection] = Field(
        default_factory=lambda: list(DEFAULT_EXPORT_SECTIONS),
        min_length=1,
    )
    outline: NovelOutline

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("export title cannot contain only whitespace")
        return normalized

    @field_validator("sections")
    @classmethod
    def reject_duplicate_sections(
        cls,
        value: list[ExportSection],
    ) -> list[ExportSection]:
        if len(value) != len(set(value)):
            raise ValueError("export sections cannot contain duplicates")
        return value
