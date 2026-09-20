"""Agents for recoverable intermediate merges and the final novel outline."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import tiktoken

from novelatlas.models import ModelGateway
from novelatlas.schemas.analysis import (
    ChapterRangeOutline,
    FinalOutlineRecord,
    MergeSummaryContent,
    MergeSummaryRecord,
    NovelOutline,
    OutlineClaim,
    OutlineSource,
    OutlineStoryline,
)
from novelatlas.schemas.models import TextGenerationRequest
from novelatlas.skills.hierarchical_outline import (
    FINAL_OUTLINE_INSTRUCTIONS,
    MERGE_SUMMARY_INSTRUCTIONS,
    build_final_outline_prompt,
    build_merge_summary_prompt,
    parse_final_outline_response,
    parse_merge_summary_response,
)


@dataclass(frozen=True, slots=True)
class OutlineInputMaterial:
    """One batch or lower merge node prepared for another model call."""

    input_id: str
    fingerprint: str
    chapter_range: str
    batch_ids: tuple[str, ...]
    chapter_ids: tuple[str, ...]
    payload: dict[str, Any]

    def prompt_item(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "chapter_range": self.chapter_range,
            "summary": _compact_payload(self.payload, self.input_id),
        }


class OutlineInputBudgetError(ValueError):
    """Raised before a call if the complete prompt exceeds its input limit."""


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _compact_payload(value: Any, input_id: str) -> Any:
    """Replace nested expanded provenance with this direct material ID."""

    if isinstance(value, list):
        return [_compact_payload(item, input_id) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                {"input_ids": [input_id]}
                if key == "sources"
                else _compact_payload(item, input_id)
            )
            for key, item in value.items()
        }
    return value


def _sources(materials: list[OutlineInputMaterial]) -> OutlineSource:
    return OutlineSource(
        input_ids=[item.input_id for item in materials],
        batch_ids=_ordered_unique(
            [batch_id for item in materials for batch_id in item.batch_ids]
        ),
        chapter_ids=_ordered_unique(
            [chapter_id for item in materials for chapter_id in item.chapter_ids]
        ),
    )


def _chapter_items(
    materials: list[OutlineInputMaterial],
) -> list[ChapterRangeOutline]:
    return [
        ChapterRangeOutline(
            chapter_range=item.chapter_range,
            summary=f"Mock 汇总已覆盖 {item.chapter_range}。",
            key_events=["该范围的重要内容已纳入全书细纲。"],
            sources=OutlineSource(
                input_ids=[item.input_id],
                batch_ids=list(item.batch_ids),
                chapter_ids=list(item.chapter_ids),
            ),
        )
        for item in materials
    ]


def _check_budget(
    request: TextGenerationRequest,
    *,
    tokenizer_name: str,
    request_input_limit_tokens: int,
) -> None:
    encoding = tiktoken.get_encoding(tokenizer_name)
    actual = len(encoding.encode_ordinary(request.prompt)) + len(
        encoding.encode_ordinary(request.instructions or "")
    )
    if actual > request_input_limit_tokens:
        raise OutlineInputBudgetError(
            "汇总内容加提示词超过最大输入，请提高输入上限或重新规划"
        )


class HierarchicalMergeAgent:
    """Compress one ordered material group with exactly one model call."""

    async def merge(
        self,
        *,
        task_id: str,
        plan_id: str,
        node_id: str,
        level: int,
        input_fingerprint: str,
        materials: list[OutlineInputMaterial],
        gateway: ModelGateway,
        max_output_tokens: int,
        tokenizer_name: str,
        request_input_limit_tokens: int,
    ) -> MergeSummaryRecord:
        sources = _sources(materials)
        request = TextGenerationRequest(
            prompt=build_merge_summary_prompt(
                level=level,
                node_id=node_id,
                allowed_input_ids=sources.input_ids,
                items=[item.prompt_item() for item in materials],
            ),
            instructions=MERGE_SUMMARY_INSTRUCTIONS,
            max_output_tokens=max_output_tokens,
        )
        _check_budget(
            request,
            tokenizer_name=tokenizer_name,
            request_input_limit_tokens=request_input_limit_tokens,
        )
        result = await gateway.generate_text(request)
        summary = (
            self._mock_summary(materials)
            if result.is_mock
            else parse_merge_summary_response(
                response_text=result.content,
                allowed_input_ids=sources.input_ids,
            )
        )
        _expand_sources(summary, materials)
        return MergeSummaryRecord(
            task_id=task_id,
            plan_id=plan_id,
            node_id=node_id,
            level=level,
            input_ids=[item.input_id for item in materials],
            input_fingerprint=input_fingerprint,
            source_batch_ids=sources.batch_ids,
            source_chapter_ids=sources.chapter_ids,
            summary=summary,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            usage=result.usage,
            completed_at=datetime.now(UTC),
        )

    @staticmethod
    def _mock_summary(
        materials: list[OutlineInputMaterial],
    ) -> MergeSummaryContent:
        sources = _sources(materials)
        combined_range = (
            f"{materials[0].chapter_range}—{materials[-1].chapter_range}"
            if len(materials) > 1
            else materials[0].chapter_range
        )
        return MergeSummaryContent(
            overview=(
                f"Mock 分层汇总：合并 {len(materials)} 个连续输入，"
                f"覆盖 {materials[0].chapter_range} 至 {materials[-1].chapter_range}。"
            ),
            chapter_outline=[
                ChapterRangeOutline(
                    chapter_range=combined_range,
                    summary="Mock 已压缩该连续章节范围的重要内容。",
                    key_events=["该范围的重要推进已保留来源后进入上一层。"],
                    sources=sources,
                )
            ],
            key_events=[
                OutlineClaim(
                    description="Mock 已保留该范围的重要事件及其来源。",
                    sources=sources,
                )
            ],
        )


class FinalOutlineAgent:
    """Produce the validated root outline with exactly one model call."""

    async def outline(
        self,
        *,
        task_id: str,
        plan_id: str,
        input_fingerprint: str,
        materials: list[OutlineInputMaterial],
        gateway: ModelGateway,
        max_output_tokens: int,
        tokenizer_name: str,
        request_input_limit_tokens: int,
    ) -> FinalOutlineRecord:
        sources = _sources(materials)
        request = TextGenerationRequest(
            prompt=build_final_outline_prompt(
                allowed_input_ids=sources.input_ids,
                items=[item.prompt_item() for item in materials],
            ),
            instructions=FINAL_OUTLINE_INSTRUCTIONS,
            max_output_tokens=max_output_tokens,
        )
        _check_budget(
            request,
            tokenizer_name=tokenizer_name,
            request_input_limit_tokens=request_input_limit_tokens,
        )
        result = await gateway.generate_text(request)
        outline = (
            self._mock_outline(materials)
            if result.is_mock
            else parse_final_outline_response(
                response_text=result.content,
                allowed_input_ids=sources.input_ids,
            )
        )
        _expand_sources(outline, materials)
        return FinalOutlineRecord(
            task_id=task_id,
            plan_id=plan_id,
            input_ids=[item.input_id for item in materials],
            input_fingerprint=input_fingerprint,
            source_batch_ids=sources.batch_ids,
            source_chapter_ids=sources.chapter_ids,
            outline=outline,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            usage=result.usage,
            completed_at=datetime.now(UTC),
        )

    @staticmethod
    def _mock_outline(materials: list[OutlineInputMaterial]) -> NovelOutline:
        sources = _sources(materials)
        return NovelOutline(
            overall_summary=(
                f"Mock 全书细纲：已汇总 {len(sources.batch_ids)} 个原文批次，"
                "用于验证长篇小说分析闭环。"
            ),
            chapter_outline=_chapter_items(materials),
            storylines=[
                OutlineStoryline(
                    name="Mock 主线",
                    summary="各章节范围的重要内容依次推进并汇入全书细纲。",
                    developments=[item.chapter_range for item in materials],
                    sources=sources,
                )
            ],
            conflicts_and_uncertainties=[
                OutlineClaim(
                    description="Mock 不推断输入概括未明确说明的远距离关联。",
                    sources=sources,
                    confidence="uncertain",
                )
            ],
        )


def _confidence_floor(value: Any) -> int:
    """Conservatively retain uncertainty across coarse direct-input citations."""
    if isinstance(value, list):
        return max((_confidence_floor(v) for v in value), default=0)
    if isinstance(value, dict):
        own = max(
            {"uncertain": 2, "inference": 1}.get(value.get("classification"), 0),
            {"uncertain": 2, "likely": 1}.get(value.get("confidence"), 0),
        )
        return max(own, max((_confidence_floor(v) for v in value.values()), default=0))
    return 0


def _expand_sources(
    output: MergeSummaryContent | NovelOutline,
    materials: list[OutlineInputMaterial],
) -> None:
    """Expand direct model citations to stable leaf batch/chapter provenance."""

    by_id = {material.input_id: material for material in materials}
    if isinstance(output, MergeSummaryContent):
        groups = (
            output.chapter_outline,
            output.key_events,
            output.characters,
            output.worldbuilding,
            output.foreshadowing,
            output.unresolved_items,
            output.uncertainties,
        )
    else:
        groups = (
            output.chapter_outline,
            output.storylines,
            output.characters,
            output.worldbuilding,
            output.foreshadowing,
            output.unresolved_items,
            output.conflicts_and_uncertainties,
        )
    for group in groups:
        for item in group:
            referenced = [by_id[input_id] for input_id in item.sources.input_ids]
            floor = max(
                (_confidence_floor(source.payload) for source in referenced), default=0
            )
            if hasattr(item, "confidence"):
                current = {"certain": 0, "likely": 1, "uncertain": 2}[item.confidence]
                item.confidence = ["certain", "likely", "uncertain"][
                    max(current, floor)
                ]
            elif floor and hasattr(item, "summary"):
                label = "【含不确定信息】" if floor == 2 else "【含模型推断】"
                if not item.summary.startswith(label):
                    item.summary = label + item.summary[: 12000 - len(label)]
            item.sources.batch_ids = _ordered_unique(
                [batch_id for source in referenced for batch_id in source.batch_ids]
            )
            item.sources.chapter_ids = _ordered_unique(
                [
                    chapter_id
                    for source in referenced
                    for chapter_id in source.chapter_ids
                ]
            )
