"""Configurable line-based novel heading recognition with volume hierarchy."""

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from novelatlas.schemas.parsing import (
    ParsedChapter,
    ParsedDocument,
    ParsedVolume,
    TextChunk,
)
from novelatlas.services.token_chunker import ChunkingConfig, TokenChunker

HeadingKind = Literal["chapter", "volume", "special", "fallback"]
_NUMBER = r"[0-9０-９零〇一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟]+"
DEFAULT_HEADING_PATTERNS: tuple[tuple[HeadingKind, str], ...] = (
    (
        "chapter",
        rf"(?:正文[ \t\u3000]*)?第{_NUMBER}[章节回部篇集][ \t\u3000]*[^\n]{{0,48}}",
    ),
    (
        "chapter",
        r"(?i:chapter)[ \t\u3000]+[0-9０-９]+(?:[ \t\u3000]*[:：.．-]?[ \t\u3000]*[^\n]{0,48})",
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

_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "壹": 1,
    "贰": 2,
    "叁": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
}
_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


@dataclass(frozen=True, slots=True)
class HeadingMatch:
    title: str
    kind: HeadingKind
    start: int
    heading_end: int
    content_start: int
    number: int | None = None


@dataclass(frozen=True, slots=True)
class ChapterSpec:
    title: str
    kind: HeadingKind
    heading_start: int
    heading_end: int
    content_start: int
    content_end: int
    volume_index: int | None


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
        """Recognize volume containers and citable chapter content."""

        if not text:
            raise ValueError("source text cannot be empty")

        headings = self._find_headings(text)
        volume_matches = [heading for heading in headings if heading.kind == "volume"]
        specs = self._chapter_specs(text, headings)
        chapters: list[ParsedChapter] = []
        chunks: list[TextChunk] = []
        volume_chapter_ids: list[list[str]] = [[] for _ in volume_matches]

        for ordinal, spec in enumerate(specs, start=1):
            title = spec.title
            chapter_id = self._stable_id(
                "chapter",
                task_id,
                str(spec.heading_start),
                str(spec.content_end),
                title,
            )
            chapter_chunks = self.chunker.chunk_range(
                text=text,
                task_id=task_id,
                chapter_id=chapter_id,
                start_char=spec.content_start,
                end_char=spec.content_end,
                first_ordinal=len(chunks) + 1,
            )
            content = text[spec.content_start : spec.content_end]
            volume_id: str | None = None
            volume_title: str | None = None
            if spec.volume_index is not None:
                volume = volume_matches[spec.volume_index]
                volume_id = self._volume_id(task_id, volume)
                volume_title = volume.title
                volume_chapter_ids[spec.volume_index].append(chapter_id)
            chapters.append(
                ParsedChapter(
                    chapter_id=chapter_id,
                    ordinal=ordinal,
                    title=title,
                    heading_kind=spec.kind,
                    volume_id=volume_id,
                    volume_title=volume_title,
                    heading_start_char=spec.heading_start,
                    heading_end_char=spec.heading_end,
                    content_start_char=spec.content_start,
                    content_end_char=spec.content_end,
                    character_count=len(content),
                    token_count=self.chunker.count(content),
                    preview=self._preview(content),
                    chunk_ids=[chunk.chunk_id for chunk in chapter_chunks],
                )
            )
            chunks.extend(chapter_chunks)

        # A source consisting only of headings still needs one citable range.
        if not chunks:
            chapters, chunks = self._whole_document_fallback(task_id, text)
            headings = []
            volume_matches = []
            volume_chapter_ids = []

        volumes = [
            ParsedVolume(
                volume_id=self._volume_id(task_id, heading),
                ordinal=index + 1,
                title=heading.title,
                heading_start_char=heading.start,
                heading_end_char=heading.heading_end,
                content_start_char=heading.content_start,
                content_end_char=(
                    volume_matches[index + 1].start
                    if index + 1 < len(volume_matches)
                    else len(text)
                ),
                chapter_ids=volume_chapter_ids[index],
            )
            for index, heading in enumerate(volume_matches)
        ]

        return ParsedDocument(
            task_id=task_id,
            filename=filename,
            tokenizer=self.chunker.config.tokenizer_name,
            character_count=len(text),
            token_count=self.chunker.count(text),
            chapter_count=len(chapters),
            chunk_count=len(chunks),
            used_fallback_chapter=not headings,
            volumes=volumes,
            chapters=chapters,
            chunks=chunks,
        )

    def _find_headings(self, text: str) -> list[HeadingMatch]:
        candidates: list[HeadingMatch] = []
        for line in re.finditer(r"[^\n]*(?:\n|$)", text):
            raw = line.group(0)
            if not raw:
                continue
            line_without_newline = raw.removesuffix("\n")
            title = line_without_newline.strip(" \t\u3000\r\ufeff")
            if not title or title.endswith(tuple("。！？；，,.!?;")):
                continue
            for kind, pattern in self.heading_patterns:
                if pattern.fullmatch(title):
                    candidates.append(
                        HeadingMatch(
                            title=title,
                            kind=kind,
                            start=line.start(),
                            heading_end=line.start() + len(line_without_newline),
                            content_start=line.end(),
                            number=self._heading_number(title, kind),
                        )
                    )
                    break
        return self._remove_sequence_outliers(candidates)

    @classmethod
    def _remove_sequence_outliers(
        cls,
        headings: list[HeadingMatch],
    ) -> list[HeadingMatch]:
        """Reject obvious embedded headings between two consecutive chapters."""

        retained = list(headings)
        changed = True
        while changed:
            changed = False
            segments: list[list[int]] = [[]]
            for index, heading in enumerate(retained):
                if heading.kind == "volume":
                    segments.append([])
                elif heading.kind == "chapter":
                    segments[-1].append(index)
            rejected: set[int] = set()
            for segment in segments:
                for previous, current, following in zip(
                    segment,
                    segment[1:],
                    segment[2:],
                    strict=False,
                ):
                    previous_number = retained[previous].number
                    current_number = retained[current].number
                    following_number = retained[following].number
                    if (
                        previous_number is not None
                        and current_number is not None
                        and following_number == previous_number + 1
                        and current_number not in {previous_number, following_number}
                    ):
                        rejected.add(current)
            if rejected:
                retained = [
                    heading
                    for index, heading in enumerate(retained)
                    if index not in rejected
                ]
                changed = True
        return retained

    @staticmethod
    def _chapter_specs(text: str, headings: list[HeadingMatch]) -> list[ChapterSpec]:
        if not headings:
            return [ChapterSpec("全文", "fallback", 0, 0, 0, len(text), None)]

        specs: list[ChapterSpec] = []
        if text[: headings[0].start].strip():
            specs.append(
                ChapterSpec("卷首", "special", 0, 0, 0, headings[0].start, None)
            )

        current_volume_index: int | None = None
        volume_index = -1
        for index, heading in enumerate(headings):
            content_end = (
                headings[index + 1].start if index + 1 < len(headings) else len(text)
            )
            if heading.kind == "volume":
                volume_index += 1
                current_volume_index = volume_index
                if text[heading.content_start : content_end].strip():
                    specs.append(
                        ChapterSpec(
                            f"{heading.title} · 卷首",
                            "special",
                            heading.start,
                            heading.heading_end,
                            heading.content_start,
                            content_end,
                            current_volume_index,
                        )
                    )
                continue
            specs.append(
                ChapterSpec(
                    heading.title,
                    heading.kind,
                    heading.start,
                    heading.heading_end,
                    heading.content_start,
                    content_end,
                    current_volume_index,
                )
            )
        return specs

    @classmethod
    def _heading_number(cls, title: str, kind: HeadingKind) -> int | None:
        if kind != "chapter":
            return None
        match = re.search(rf"第({_NUMBER})[章节回部篇集]", title)
        if match is None:
            match = re.search(r"(?i:chapter)[ \t\u3000]+([0-9０-９]+)", title)
        return cls._parse_number(match.group(1)) if match else None

    @staticmethod
    def _parse_number(value: str) -> int | None:
        normalized = value.translate(_FULLWIDTH_DIGITS)
        if normalized.isdigit():
            return int(normalized)
        if all(character in _DIGITS for character in normalized):
            return int("".join(str(_DIGITS[character]) for character in normalized))

        total = 0
        section = 0
        digit = 0
        for character in normalized:
            if character in _DIGITS:
                digit = _DIGITS[character]
            elif character in _UNITS:
                section += (digit or 1) * _UNITS[character]
                digit = 0
            elif character == "万":
                total += (section + digit) * 10_000
                section = 0
                digit = 0
            else:
                return None
        return total + section + digit

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

    def _volume_id(self, task_id: str, heading: HeadingMatch) -> str:
        return self._stable_id("volume", task_id, str(heading.start), heading.title)

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = sha256("\x1f".join(parts).encode()).hexdigest()[:16]
        return f"{prefix}_{digest}"

    @staticmethod
    def _preview(text: str, limit: int = 160) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= limit else f"{compact[:limit]}…"
