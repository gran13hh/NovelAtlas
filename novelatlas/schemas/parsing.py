"""Schemas for deterministic chapter parsing and source citations."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SourceReference(BaseModel):
    """A stable, half-open character range in the normalized source text."""

    citation_id: str
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    chapter_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    preview: str

    @model_validator(mode="after")
    def validate_range(self) -> "SourceReference":
        if self.end_char <= self.start_char:
            raise ValueError("citation end_char must be greater than start_char")
        return self


class TextChunk(BaseModel):
    """A model-safe source window with an exact citation range."""

    chunk_id: str
    chapter_id: str
    ordinal: int = Field(ge=1)
    token_count: int = Field(ge=1)
    overlap_with_previous_tokens: int = Field(ge=0)
    reference: SourceReference


class ParsedChapter(BaseModel):
    """A recognized heading and the source range belonging to it."""

    chapter_id: str
    ordinal: int = Field(ge=1)
    title: str
    heading_kind: Literal["chapter", "volume", "special", "fallback"]
    heading_start_char: int = Field(ge=0)
    heading_end_char: int = Field(ge=0)
    content_start_char: int = Field(ge=0)
    content_end_char: int = Field(ge=0)
    character_count: int = Field(ge=0)
    token_count: int = Field(ge=0)
    preview: str
    chunk_ids: list[str]

    @model_validator(mode="after")
    def validate_ranges(self) -> "ParsedChapter":
        if self.heading_end_char < self.heading_start_char:
            raise ValueError("heading range is reversed")
        if self.content_end_char < self.content_start_char:
            raise ValueError("content range is reversed")
        return self


class ParsedDocument(BaseModel):
    """Persisted parse manifest returned to the preview interface."""

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    filename: str
    tokenizer: str
    character_count: int = Field(ge=1)
    token_count: int = Field(ge=1)
    chapter_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    used_fallback_chapter: bool
    chapters: list[ParsedChapter]
    chunks: list[TextChunk]

    @model_validator(mode="after")
    def validate_counts(self) -> "ParsedDocument":
        if self.chapter_count != len(self.chapters):
            raise ValueError("chapter_count does not match chapters")
        if self.chunk_count != len(self.chunks):
            raise ValueError("chunk_count does not match chunks")
        return self
