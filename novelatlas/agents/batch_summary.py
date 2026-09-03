"""Agent that performs exactly one model call for one planned source batch."""

from datetime import UTC, datetime

import tiktoken

from novelatlas.analysis.planner import PlannedBatchMaterial
from novelatlas.models import ModelGateway
from novelatlas.schemas.analysis import (
    BatchSummaryClaim,
    BatchSummaryContent,
    BatchSummaryRecord,
)
from novelatlas.schemas.models import TextGenerationRequest, TextGenerationResult
from novelatlas.skills.batch_summary import (
    BATCH_SUMMARY_INSTRUCTIONS,
    build_batch_summary_prompt,
    parse_batch_summary_response,
)


class BatchSummaryInputBudgetError(ValueError):
    """Raised before a call when prompt plus source exceed the planned input."""


class BatchSummaryAgent:
    """Turn one planned batch into validated structured important content."""

    async def summarize(
        self,
        *,
        task_id: str,
        plan_id: str,
        batch: PlannedBatchMaterial,
        gateway: ModelGateway,
        max_output_tokens: int,
        tokenizer_name: str,
        request_input_limit_tokens: int,
    ) -> BatchSummaryRecord:
        request = TextGenerationRequest(
            prompt=build_batch_summary_prompt(
                batch=batch.metadata,
                content=batch.content,
            ),
            instructions=BATCH_SUMMARY_INSTRUCTIONS,
            max_output_tokens=max_output_tokens,
        )
        encoding = tiktoken.get_encoding(tokenizer_name)
        actual_input_tokens = len(encoding.encode_ordinary(request.prompt)) + len(
            encoding.encode_ordinary(request.instructions or "")
        )
        if actual_input_tokens > request_input_limit_tokens:
            raise BatchSummaryInputBudgetError(
                "批次正文加提示词超过最大输入，请增大安全余量后重新规划"
            )
        result = await gateway.generate_text(request)
        summary = (
            self._mock_summary(batch)
            if result.is_mock
            else parse_batch_summary_response(
                response_text=result.content,
                batch=batch.metadata,
            )
        )
        return self._record(
            task_id=task_id,
            plan_id=plan_id,
            batch=batch,
            result=result,
            summary=summary,
        )

    @staticmethod
    def _mock_summary(batch: PlannedBatchMaterial) -> BatchSummaryContent:
        metadata = batch.metadata
        claims: list[BatchSummaryClaim] = []
        if metadata.chapter_ids and metadata.source_chunk_ids:
            claims.append(
                BatchSummaryClaim(
                    description="Mock 已确认该批次正文可进入结构化概括流程。",
                    chapter_ids=metadata.chapter_ids,
                    source_chunk_ids=metadata.source_chunk_ids,
                    confidence="certain",
                )
            )
        return BatchSummaryContent(
            overview=(
                f"Mock 批次概括：已处理 {metadata.chapter_range_label}，"
                "用于验证持久化、失败恢复和后续汇总流程。"
            ),
            key_events=claims,
            characters=[],
            worldbuilding=[],
            foreshadowing=[],
            unresolved_items=[],
        )

    @staticmethod
    def _record(
        *,
        task_id: str,
        plan_id: str,
        batch: PlannedBatchMaterial,
        result: TextGenerationResult,
        summary: BatchSummaryContent,
    ) -> BatchSummaryRecord:
        return BatchSummaryRecord(
            task_id=task_id,
            plan_id=plan_id,
            batch=batch.metadata,
            source_fingerprint=batch.metadata.content_fingerprint,
            summary=summary,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            usage=result.usage,
            completed_at=datetime.now(UTC),
        )
