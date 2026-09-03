"""Deterministic, token-budgeted planning for long-novel analysis."""

from dataclasses import dataclass
from hashlib import sha256

from novelatlas.schemas.analysis import (
    AnalysisBatch,
    AnalysisBudget,
    AnalysisPlan,
    AnalysisSegment,
)
from novelatlas.schemas.parsing import ParsedChapter, ParsedDocument, TextChunk
from novelatlas.services.token_chunker import ChunkingConfig, TokenChunker

_BATCH_SEPARATOR = "\n\n"
_MERGE_ITEM_OVERHEAD_TOKENS = 16


@dataclass(frozen=True, slots=True)
class PlannedSegmentMaterial:
    """Private content paired with public, secret-free segment metadata."""

    metadata: AnalysisSegment
    content: str


@dataclass(frozen=True, slots=True)
class PlannedBatchMaterial:
    """Private content for one later batch-summary model request."""

    metadata: AnalysisBatch
    content: str


@dataclass(frozen=True, slots=True)
class AnalysisPlanningResult:
    """Public plan plus private in-memory content needed by later stages."""

    plan: AnalysisPlan
    segments: tuple[PlannedSegmentMaterial, ...]
    batches: tuple[PlannedBatchMaterial, ...]


def plan_analysis(
    *,
    parsed: ParsedDocument,
    source: str,
    budget: AnalysisBudget,
) -> AnalysisPlanningResult:
    """Build a stable plan without calling or depending on a model provider."""

    chunker = TokenChunker(
        ChunkingConfig(
            tokenizer_name=parsed.tokenizer,
            max_tokens=budget.available_content_tokens,
            overlap_tokens=0,
        )
    )
    chunks_by_id = {chunk.chunk_id: chunk for chunk in parsed.chunks}
    segments: list[PlannedSegmentMaterial] = []
    skipped_empty_chapters = 0

    for chapter in parsed.chapters:
        body, contains_edits, source_chunk_ids = _chapter_body(
            chapter=chapter,
            chunks_by_id=chunks_by_id,
            source=source,
            chunker=chunker,
        )
        if not body.strip():
            skipped_empty_chapters += 1
            continue
        segments.extend(
            _chapter_segments(
                parsed=parsed,
                chapter=chapter,
                body=body,
                contains_edits=contains_edits,
                source_chunk_ids=source_chunk_ids,
                chunker=chunker,
                budget=budget,
            )
        )

    batches = _pack_batches(
        task_id=parsed.task_id,
        segments=segments,
        chunker=chunker,
        content_limit=budget.available_content_tokens,
    )
    summary_tokens = min(
        budget.output_reserve_tokens,
        max(32, budget.available_content_tokens // 4),
        1200,
    )
    merge_calls, merge_input_tokens = _estimate_merge_work(
        batch_count=len(batches),
        content_limit=budget.available_content_tokens,
        summary_tokens=summary_tokens,
    )
    planned_input_tokens = sum(batch.metadata.token_count for batch in batches)
    budget_fingerprint = budget.model_dump_json(exclude_computed_fields=True)
    plan_id = _stable_id(
        "plan",
        parsed.task_id,
        budget_fingerprint,
        *(batch.metadata.batch_id for batch in batches),
    )
    plan = AnalysisPlan(
        plan_id=plan_id,
        task_id=parsed.task_id,
        tokenizer=parsed.tokenizer,
        budget=budget,
        source_token_count=parsed.token_count,
        planned_input_token_count=planned_input_tokens,
        skipped_empty_chapter_count=skipped_empty_chapters,
        segment_count=len(segments),
        batch_count=len(batches),
        summary_call_count=len(batches),
        estimated_merge_call_count=merge_calls,
        estimated_total_call_count=len(batches) + merge_calls,
        estimated_merge_input_tokens=merge_input_tokens,
        estimated_total_input_tokens=planned_input_tokens + merge_input_tokens,
        estimated_summary_tokens_per_batch=summary_tokens,
        segments=[segment.metadata for segment in segments],
        batches=[batch.metadata for batch in batches],
    )
    return AnalysisPlanningResult(
        plan=plan,
        segments=tuple(segments),
        batches=tuple(batches),
    )


def _chapter_body(
    *,
    chapter: ParsedChapter,
    chunks_by_id: dict[str, TextChunk],
    source: str,
    chunker: TokenChunker,
) -> tuple[str, bool, list[str]]:
    """Assemble active chunks while removing their sliding-window overlap."""

    pieces: list[str] = []
    contains_edits = False
    source_chunk_ids: list[str] = []
    covered_until: int | None = None

    active_chunks = [
        chunks_by_id[chunk_id]
        for chunk_id in chapter.chunk_ids
        if chunk_id in chunks_by_id
    ]
    active_chunks.sort(key=lambda chunk: chunk.reference.start_char)

    for chunk in active_chunks:
        reference = chunk.reference
        unique_start = (
            reference.start_char
            if covered_until is None
            else max(reference.start_char, covered_until)
        )
        if unique_start >= reference.end_char:
            covered_until = max(covered_until or 0, reference.end_char)
            continue

        if chunk.content_override is None:
            piece = source[unique_start : reference.end_char]
        else:
            contains_edits = True
            overlap_tokens = chunker.count(source[reference.start_char:unique_start])
            encoded_override = chunker.encoding.encode_ordinary(chunk.content_override)
            piece = chunker.encoding.decode(encoded_override[overlap_tokens:])

        if piece:
            pieces.append(piece)
            source_chunk_ids.append(chunk.chunk_id)
        covered_until = max(covered_until or 0, reference.end_char)

    return "".join(pieces), contains_edits, source_chunk_ids


def _chapter_segments(
    *,
    parsed: ParsedDocument,
    chapter: ParsedChapter,
    body: str,
    contains_edits: bool,
    source_chunk_ids: list[str],
    chunker: TokenChunker,
    budget: AnalysisBudget,
) -> list[PlannedSegmentMaterial]:
    complete_prefix = f"【章节 {chapter.ordinal}：{chapter.title}】\n"
    complete_content = f"{complete_prefix}{body}"
    if chunker.count(complete_content) <= budget.available_content_tokens:
        return [
            _segment_material(
                parsed=parsed,
                chapter=chapter,
                content=complete_content,
                part_ordinal=1,
                part_count=1,
                contains_edits=contains_edits,
                source_chunk_ids=source_chunk_ids,
                chunker=chunker,
                content_limit=budget.available_content_tokens,
            )
        ]

    conservative_prefix = (
        f"【章节 {chapter.ordinal}：{chapter.title} · 片段 999999】\n"
    )
    body_limit = budget.available_content_tokens - chunker.count(conservative_prefix)
    if body_limit < 1:
        raise ValueError(f"章节标题超过可用分析预算：{chapter.title}")

    body_chunker = TokenChunker(
        ChunkingConfig(
            tokenizer_name=parsed.tokenizer,
            max_tokens=body_limit,
            overlap_tokens=0,
        )
    )
    raw_parts = body_chunker.chunk_range(
        text=body,
        task_id=parsed.task_id,
        chapter_id=chapter.chapter_id,
        start_char=0,
        end_char=len(body),
        first_ordinal=1,
    )
    part_contents = [
        body[part.reference.start_char : part.reference.end_char]
        for part in raw_parts
    ]
    part_count = len(part_contents)
    return [
        _segment_material(
            parsed=parsed,
            chapter=chapter,
            content=(
                f"【章节 {chapter.ordinal}：{chapter.title} · 片段 {part_ordinal}】\n"
                f"{part_content}"
            ),
            part_ordinal=part_ordinal,
            part_count=part_count,
            contains_edits=contains_edits,
            source_chunk_ids=source_chunk_ids,
            chunker=chunker,
            content_limit=budget.available_content_tokens,
        )
        for part_ordinal, part_content in enumerate(part_contents, start=1)
    ]


def _segment_material(
    *,
    parsed: ParsedDocument,
    chapter: ParsedChapter,
    content: str,
    part_ordinal: int,
    part_count: int,
    contains_edits: bool,
    source_chunk_ids: list[str],
    chunker: TokenChunker,
    content_limit: int,
) -> PlannedSegmentMaterial:
    token_count = chunker.count(content)
    if token_count > content_limit:
        raise ValueError("analysis segment exceeds available content budget")
    fingerprint = sha256(content.encode()).hexdigest()
    segment_id = _stable_id(
        "segment",
        parsed.task_id,
        chapter.chapter_id,
        str(part_ordinal),
        fingerprint,
        str(content_limit),
    )
    metadata = AnalysisSegment(
        segment_id=segment_id,
        chapter_id=chapter.chapter_id,
        chapter_ordinal=chapter.ordinal,
        chapter_title=chapter.title,
        part_ordinal=part_ordinal,
        part_count=part_count,
        source_start_char=chapter.content_start_char,
        source_end_char=chapter.content_end_char,
        source_chunk_ids=source_chunk_ids,
        token_count=token_count,
        character_count=len(content),
        content_fingerprint=fingerprint,
        contains_edited_content=contains_edits,
    )
    return PlannedSegmentMaterial(metadata=metadata, content=content)


def _pack_batches(
    *,
    task_id: str,
    segments: list[PlannedSegmentMaterial],
    chunker: TokenChunker,
    content_limit: int,
) -> list[PlannedBatchMaterial]:
    batches: list[PlannedBatchMaterial] = []
    pending: list[PlannedSegmentMaterial] = []

    for segment in segments:
        candidate = [*pending, segment]
        candidate_content = _BATCH_SEPARATOR.join(item.content for item in candidate)
        if pending and chunker.count(candidate_content) > content_limit:
            batches.append(
                _batch_material(
                    task_id=task_id,
                    ordinal=len(batches) + 1,
                    segments=pending,
                    chunker=chunker,
                )
            )
            pending = [segment]
        else:
            pending = candidate

    if pending:
        batches.append(
            _batch_material(
                task_id=task_id,
                ordinal=len(batches) + 1,
                segments=pending,
                chunker=chunker,
            )
        )
    return batches


def _batch_material(
    *,
    task_id: str,
    ordinal: int,
    segments: list[PlannedSegmentMaterial],
    chunker: TokenChunker,
) -> PlannedBatchMaterial:
    content = _BATCH_SEPARATOR.join(segment.content for segment in segments)
    fingerprint = sha256(content.encode()).hexdigest()
    segment_metadata = [segment.metadata for segment in segments]
    chapter_ids = list(dict.fromkeys(item.chapter_id for item in segment_metadata))
    chunk_ids = list(
        dict.fromkeys(
            chunk_id
            for item in segment_metadata
            for chunk_id in item.source_chunk_ids
        )
    )
    start_ordinal = segment_metadata[0].chapter_ordinal
    end_ordinal = segment_metadata[-1].chapter_ordinal
    start_title = segment_metadata[0].chapter_title
    end_title = segment_metadata[-1].chapter_title
    range_label = start_title if start_title == end_title else f"{start_title} → {end_title}"
    batch_id = _stable_id(
        "batch",
        task_id,
        fingerprint,
        *(item.segment_id for item in segment_metadata),
    )
    metadata = AnalysisBatch(
        batch_id=batch_id,
        ordinal=ordinal,
        segment_ids=[item.segment_id for item in segment_metadata],
        chapter_ids=chapter_ids,
        chapter_start_ordinal=start_ordinal,
        chapter_end_ordinal=end_ordinal,
        chapter_range_label=range_label,
        source_chunk_ids=chunk_ids,
        token_count=chunker.count(content),
        character_count=len(content),
        content_fingerprint=fingerprint,
        contains_edited_content=any(
            item.contains_edited_content for item in segment_metadata
        ),
    )
    return PlannedBatchMaterial(metadata=metadata, content=content)


def _estimate_merge_work(
    *,
    batch_count: int,
    content_limit: int,
    summary_tokens: int,
) -> tuple[int, int]:
    if batch_count == 0:
        return 0, 0

    item_sizes = [summary_tokens] * batch_count
    calls = 0
    input_tokens = 0
    if batch_count == 1:
        return 1, summary_tokens

    while len(item_sizes) > 1:
        groups: list[list[int]] = []
        current: list[int] = []
        current_tokens = 0
        for item_size in item_sizes:
            item_cost = item_size + (_MERGE_ITEM_OVERHEAD_TOKENS if current else 0)
            if current and current_tokens + item_cost > content_limit:
                groups.append(current)
                current = [item_size]
                current_tokens = item_size
            else:
                current.append(item_size)
                current_tokens += item_cost
        if current:
            groups.append(current)

        if len(groups) == len(item_sizes):
            groups = [item_sizes[index : index + 2] for index in range(0, len(item_sizes), 2)]

        calls += len(groups)
        input_tokens += sum(
            sum(group) + _MERGE_ITEM_OVERHEAD_TOKENS * (len(group) - 1)
            for group in groups
        )
        item_sizes = [summary_tokens] * len(groups)

    return calls, input_tokens


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"
