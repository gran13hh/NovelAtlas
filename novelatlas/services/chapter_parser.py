"""Configurable line-based Chinese novel heading recognition."""

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from novelatlas.schemas.parsing import ParsedChapter, ParsedDocument, TextChunk
from novelatlas.services.token_chunker import ChunkingConfig, TokenChunker

HeadingKind = Literal["chapter", "volume", "special", "fallback"]
_NUMBER = r"[0-9０-９零〇一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟]+"
DEFAULT_HEADING_PATTERNS: tuple[tuple[HeadingKind, str], ...] = (
    (
        "chapter",
        rf"(?:正文[ \t\u3000]*)?第{_NUMBER}[章节回部篇集][ \t\u3000]*[^\n]{{0,48}}",
    ),
    (
        "volume",
        (
            rf"(?:正文[ \t\u3000]*)?(?:第{_NUMBER}卷|卷{_NUMBER}|[上中下]卷)"
            r"[ \t\u3000]*[^\n]{0,48}"
        ),
    ),
    (
        "special",
        (
            r"(?:序章|序言|前言|楔子|引子|终章|尾声|后记|番外)"
            r"[ \t\u3000]*[^\n]{0,48}"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class HeadingMatch:
    title: str
    kind: HeadingKind
    start: int
    heading_end: int
    content_start: int


class ChapterParser:
    """Build a stable parse manifest from normalized UTF-8 source text."""

    def __init__(
        self,
        chunking: ChunkingConfig,
        *,
        heading_patterns: tuple[tuple[HeadingKind, str], ...] = DEFAULT_HEADING_PATTERNS,
    ) -> None:
        self.chunker = TokenChunker(chunking)
        self.heading_patterns = tuple(
            (kind, re.compile(rf"^(?:{pattern})$"))
            for kind, pattern in heading_patterns
        )

    def parse(self, *, task_id: str, filename: str, text: str) -> ParsedDocument:
        """Recognize chapters and create model-safe chunks with citations."""

        if not text:
            raise ValueError("source text cannot be empty")

        headings = self._find_headings(text)
        specs = self._chapter_specs(text, headings)
        chapters: list[ParsedChapter] = []
        chunks: list[TextChunk] = []

        for ordinal, spec in enumerate(specs, start=1):
            title, kind, heading_start, heading_end, content_start, content_end = spec
            chapter_id = self._stable_id(
                "chapter",
                task_id,
                str(heading_start),
                str(content_end),
                title,
            )
            chapter_chunks = self.chunker.chunk_range(
                text=text,
                task_id=task_id,
                chapter_id=chapter_id,
                start_char=content_start,
                end_char=content_end,
                first_ordinal=len(chunks) + 1,
            )
            content = text[content_start:content_end]
            chapters.append(
                ParsedChapter(
                    chapter_id=chapter_id,
                    ordinal=ordinal,
                    title=title,
                    heading_kind=kind,
                    heading_start_char=heading_start,
                    heading_end_char=heading_end,
                    content_start_char=content_start,
                    content_end_char=content_end,
                    character_count=len(content),
                    token_count=self.chunker.count(content),
                    preview=self._preview(content),
                    chunk_ids=[chunk.chunk_id for chunk in chapter_chunks],
                )
            )
            chunks.extend(chapter_chunks)

        # A source consisting only of headings still needs one citable range for
        # later agents. Fall back to the whole document in that edge case.
        if not chunks:
            chapters, chunks = self._whole_document_fallback(task_id, text)
            headings = []

        return ParsedDocument(
            task_id=task_id,
            filename=filename,
            tokenizer=self.chunker.config.tokenizer_name,
            character_count=len(text),
            token_count=self.chunker.count(text),
            chapter_count=len(chapters),
            chunk_count=len(chunks),
            used_fallback_chapter=not headings,
            chapters=chapters,
            chunks=chunks,
        )

    def _find_headings(self, text: str) -> list[HeadingMatch]:
        headings: list[HeadingMatch] = []
        for line in re.finditer(r"[^\n]*(?:\n|$)", text):
            raw = line.group(0)
            if not raw:
                continue
            line_without_newline = raw.removesuffix("\n")
            title = line_without_newline.strip(" \t\u3000\r")
            if not title or title.endswith(tuple("。！？；，,.!?;")):
                continue
            for kind, pattern in self.heading_patterns:
                if pattern.fullmatch(title):
                    headings.append(
                        HeadingMatch(
                            title=title,
                            kind=kind,
                            start=line.start(),
                            heading_end=line.start() + len(line_without_newline),
                            content_start=line.end(),
                        )
                    )
                    break
        return headings

    @staticmethod
    def _chapter_specs(
        text: str,
        headings: list[HeadingMatch],
    ) -> list[tuple[str, HeadingKind, int, int, int, int]]:
        if not headings:
            return [("全文", "fallback", 0, 0, 0, len(text))]

        specs: list[tuple[str, HeadingKind, int, int, int, int]] = []
        if text[: headings[0].start].strip():
            specs.append(("卷首", "special", 0, 0, 0, headings[0].start))

        for index, heading in enumerate(headings):
            content_end = (
                headings[index + 1].start
                if index + 1 < len(headings)
                else len(text)
            )
            specs.append(
                (
                    heading.title,
                    heading.kind,
                    heading.start,
                    heading.heading_end,
                    heading.content_start,
                    content_end,
                )
            )
        return specs

    def _whole_document_fallback(
        self,
        task_id: str,
        text: str,
    ) -> tuple[list[ParsedChapter], list[TextChunk]]:
        chapter_id = self._stable_id("chapter", task_id, "0", str(len(text)), "全文")
        chunks = self.chunker.chunk_range(
            text=text,
            task_id=task_id,
            chapter_id=chapter_id,
            start_char=0,
            end_char=len(text),
            first_ordinal=1,
        )
        chapter = ParsedChapter(
            chapter_id=chapter_id,
            ordinal=1,
            title="全文",
            heading_kind="fallback",
            heading_start_char=0,
            heading_end_char=0,
            content_start_char=0,
            content_end_char=len(text),
            character_count=len(text),
            token_count=self.chunker.count(text),
            preview=self._preview(text),
            chunk_ids=[chunk.chunk_id for chunk in chunks],
        )
        return [chapter], chunks

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = sha256("\x1f".join(parts).encode()).hexdigest()[:16]
        return f"{prefix}_{digest}"

    @staticmethod
    def _preview(text: str, limit: int = 160) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= limit else f"{compact[:limit]}…"
