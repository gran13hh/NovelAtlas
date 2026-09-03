"""Persistent batch-summary execution and process-local task coordination."""

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256

import tiktoken
from pydantic import ValidationError

from novelatlas.agents import (
    BatchSummaryAgent,
    BatchSummaryInputBudgetError,
    FinalOutlineAgent,
    HierarchicalMergeAgent,
    OutlineInputBudgetError,
    OutlineInputMaterial,
)
from novelatlas.models import ModelGateway, ModelGatewayError
from novelatlas.schemas.analysis import (
    AnalysisPlan,
    AnalysisTaskError,
    AnalysisTaskManifest,
    BatchCheckpoint,
    BatchSummaryRecord,
    FinalOutlineRecord,
    MergeCheckpoint,
    MergeSummaryRecord,
)
from novelatlas.schemas.parsing import ParsedDocument
from novelatlas.services.temporary_storage import (
    ArtifactNotFoundError,
    TemporaryUploadStorage,
    UploadNotFoundError,
)
from novelatlas.skills.batch_summary import BatchSummaryOutputError
from novelatlas.skills.hierarchical_outline import (
    FINAL_OUTLINE_INSTRUCTIONS,
    MERGE_SUMMARY_INSTRUCTIONS,
    HierarchicalOutlineOutputError,
    build_final_outline_prompt,
    build_merge_summary_prompt,
)

from .planner import AnalysisPlanningResult, PlannedBatchMaterial, plan_analysis

PARSE_ARTIFACT = "parse-result"
PLAN_ARTIFACT = "analysis-plan"
TASK_ARTIFACT = "analysis-task"
SUMMARY_ARTIFACT_PREFIX = "batch-summary-"
MERGE_ARTIFACT_PREFIX = "merge-summary-"
FINAL_OUTLINE_ARTIFACT = "final-outline"
_PROMPT_FIT_MARGIN_TOKENS = 64


class AnalysisTaskAlreadyRunningError(RuntimeError):
    """Raised when a second runner targets the same upload task."""


class AnalysisTaskNotFoundError(FileNotFoundError):
    """Raised when no batch-summary manifest has been created."""


class AnalysisPlanMismatchError(ValueError):
    """Raised when current source reconstruction differs from the saved plan."""


class BatchSummaryRunner:
    """Execute and checkpoint planned batches sequentially."""

    def __init__(
        self,
        storage: TemporaryUploadStorage,
        *,
        agent: BatchSummaryAgent | None = None,
        merge_agent: HierarchicalMergeAgent | None = None,
        final_agent: FinalOutlineAgent | None = None,
    ) -> None:
        self.storage = storage
        self.agent = agent or BatchSummaryAgent()
        self.merge_agent = merge_agent or HierarchicalMergeAgent()
        self.final_agent = final_agent or FinalOutlineAgent()

    def prepare_manifest(
        self,
        task_id: str,
        gateway: ModelGateway,
    ) -> AnalysisTaskManifest:
        plan = self._load_plan(task_id)
        now = datetime.now(UTC)
        try:
            manifest = self._load_manifest(task_id)
        except AnalysisTaskNotFoundError:
            manifest = self._new_manifest(task_id, plan, gateway, now)
        else:
            if manifest.plan_id != plan.plan_id:
                self.discard_artifacts(task_id, include_plan=False)
                manifest = self._new_manifest(task_id, plan, gateway, now)
            else:
                manifest.provider = gateway.text_config.provider
                manifest.model = gateway.text_config.model
                manifest.status = "queued"
                manifest.current_batch_id = None
                manifest.error = None
                manifest.updated_at = now
                for checkpoint in manifest.batches:
                    if checkpoint.status in {"running", "failed"}:
                        checkpoint.status = "pending"
                        checkpoint.last_error = None
                for checkpoint in manifest.merge_nodes:
                    if checkpoint.status in {"running", "failed"}:
                        checkpoint.status = "pending"
                        checkpoint.last_error = None
                if manifest.final_outline_status in {"running", "failed"}:
                    manifest.final_outline_status = "pending"

        if manifest.final_outline_status == "completed":
            manifest.status = "completed"
        elif manifest.batch_count == manifest.completed_batch_count:
            manifest.status = "batch_summaries_completed"
        self._save_manifest(manifest)
        return manifest

    async def run(
        self,
        task_id: str,
        gateway: ModelGateway,
    ) -> AnalysisTaskManifest:
        plan = await asyncio.to_thread(self._load_plan, task_id)
        planning = await asyncio.to_thread(self._reconstruct_plan, task_id, plan)
        manifest = await asyncio.to_thread(self._load_manifest, task_id)
        if manifest.plan_id != planning.plan.plan_id:
            raise AnalysisPlanMismatchError("当前正文与已保存批次计划不一致，请重新规划")

        manifest.status = "running"
        manifest.error = None
        manifest.updated_at = datetime.now(UTC)
        await asyncio.to_thread(self._save_manifest, manifest)

        current_checkpoint: BatchCheckpoint | None = None
        try:
            for batch in planning.batches:
                checkpoint = self._checkpoint(manifest, batch.metadata.batch_id)
                current_checkpoint = checkpoint
                existing = await asyncio.to_thread(
                    self._load_valid_summary,
                    task_id,
                    plan.plan_id,
                    batch,
                )
                if checkpoint.status == "completed" and existing is not None:
                    continue
                if existing is not None:
                    self._complete_checkpoint(manifest, checkpoint, existing)
                    await asyncio.to_thread(self._save_manifest, manifest)
                    continue
                if checkpoint.status == "completed":
                    checkpoint.status = "pending"
                    checkpoint.summary_artifact = None
                    checkpoint.completed_at = None
                    manifest.completed_batch_count = sum(
                        item.status == "completed" for item in manifest.batches
                    )
                    await asyncio.to_thread(self._save_manifest, manifest)

                checkpoint.status = "running"
                checkpoint.attempt_count += 1
                checkpoint.last_error = None
                manifest.current_batch_id = batch.metadata.batch_id
                manifest.status = "running"
                manifest.error = None
                manifest.updated_at = datetime.now(UTC)
                await asyncio.to_thread(self._save_manifest, manifest)

                try:
                    record = await self.agent.summarize(
                        task_id=task_id,
                        plan_id=plan.plan_id,
                        batch=batch,
                        gateway=gateway,
                        max_output_tokens=plan.budget.output_reserve_tokens,
                        tokenizer_name=plan.tokenizer,
                        request_input_limit_tokens=(
                            plan.budget.request_input_limit_tokens
                        ),
                    )
                except ModelGatewayError as error:
                    failure = AnalysisTaskError(
                        code=error.code,
                        message=error.message,
                        retryable=error.retryable,
                        batch_id=batch.metadata.batch_id,
                    )
                    return await self._fail(manifest, checkpoint, failure)
                except (BatchSummaryOutputError, ValidationError) as error:
                    failure = AnalysisTaskError(
                        code="invalid_batch_summary",
                        message=str(error),
                        retryable=True,
                        batch_id=batch.metadata.batch_id,
                    )
                    return await self._fail(manifest, checkpoint, failure)
                except BatchSummaryInputBudgetError as error:
                    failure = AnalysisTaskError(
                        code="batch_input_over_budget",
                        message=str(error),
                        retryable=False,
                        batch_id=batch.metadata.batch_id,
                    )
                    return await self._fail(manifest, checkpoint, failure)

                await asyncio.to_thread(self._save_summary, record)
                self._complete_checkpoint(manifest, checkpoint, record)
                await asyncio.to_thread(self._save_manifest, manifest)

            manifest.status = "batch_summaries_completed"
            manifest.current_batch_id = None
            manifest.error = None
            manifest.updated_at = datetime.now(UTC)
            await asyncio.to_thread(self._save_manifest, manifest)
            return await self._run_hierarchy(
                task_id=task_id,
                plan=plan,
                manifest=manifest,
                gateway=gateway,
            )
        except asyncio.CancelledError:
            failure = AnalysisTaskError(
                code="analysis_interrupted",
                message="分析任务已中断，可重新提交模型配置后继续",
                retryable=True,
                batch_id=(current_checkpoint.batch_id if current_checkpoint else None),
            )
            if current_checkpoint is not None and current_checkpoint.status == "running":
                current_checkpoint.status = "failed"
                current_checkpoint.last_error = failure
            manifest.status = "interrupted"
            manifest.error = failure
            manifest.current_batch_id = None
            manifest.updated_at = datetime.now(UTC)
            await asyncio.to_thread(self._save_manifest, manifest)
            raise
        except (AnalysisPlanMismatchError, OSError):
            failure = AnalysisTaskError(
                code="analysis_internal_error",
                message="批次概括发生内部错误，可重试当前批次",
                retryable=True,
                batch_id=(current_checkpoint.batch_id if current_checkpoint else None),
            )
            if current_checkpoint is not None:
                return await self._fail(manifest, current_checkpoint, failure)
            manifest.status = "failed"
            manifest.error = failure
            manifest.updated_at = datetime.now(UTC)
            await asyncio.to_thread(self._save_manifest, manifest)
            return manifest

    def load_manifest(self, task_id: str) -> AnalysisTaskManifest:
        return self._load_manifest(task_id)

    def mark_interrupted(self, task_id: str) -> AnalysisTaskManifest:
        manifest = self._load_manifest(task_id)
        if manifest.status not in {"queued", "running", "merging", "finalizing"}:
            return manifest
        failure = AnalysisTaskError(
            code="analysis_process_interrupted",
            message="后端进程已重启或任务曾中断，请重新提交模型配置继续",
            retryable=True,
            batch_id=manifest.current_batch_id,
        )
        for checkpoint in manifest.batches:
            if checkpoint.status == "running":
                checkpoint.status = "failed"
                checkpoint.last_error = failure
        manifest.status = "interrupted"
        manifest.current_batch_id = None
        manifest.current_merge_node_id = None
        manifest.error = failure
        manifest.updated_at = datetime.now(UTC)
        self._save_manifest(manifest)
        return manifest

    def load_summaries(self, task_id: str) -> list[BatchSummaryRecord]:
        manifest = self._load_manifest(task_id)
        summaries: list[BatchSummaryRecord] = []
        for checkpoint in manifest.batches:
            if checkpoint.status != "completed" or not checkpoint.summary_artifact:
                continue
            payload = self.storage.read_json_artifact(
                task_id,
                checkpoint.summary_artifact,
            )
            summaries.append(BatchSummaryRecord.model_validate_json(payload))
        return summaries

    def load_outline(self, task_id: str) -> FinalOutlineRecord:
        manifest = self._load_manifest(task_id)
        if (
            manifest.final_outline_status != "completed"
            or manifest.final_outline_artifact != FINAL_OUTLINE_ARTIFACT
        ):
            raise ArtifactNotFoundError(FINAL_OUTLINE_ARTIFACT)
        return FinalOutlineRecord.model_validate_json(
            self.storage.read_json_artifact(task_id, FINAL_OUTLINE_ARTIFACT)
        )

    def discard_artifacts(self, task_id: str, *, include_plan: bool) -> None:
        try:
            self.storage.delete_json_artifact(task_id, TASK_ARTIFACT)
            self.storage.delete_json_artifacts(task_id, SUMMARY_ARTIFACT_PREFIX)
            self.storage.delete_json_artifacts(task_id, MERGE_ARTIFACT_PREFIX)
            self.storage.delete_json_artifact(task_id, FINAL_OUTLINE_ARTIFACT)
            if include_plan:
                self.storage.delete_json_artifact(task_id, PLAN_ARTIFACT)
        except UploadNotFoundError:
            return

    def _reconstruct_plan(
        self,
        task_id: str,
        plan: AnalysisPlan,
    ) -> AnalysisPlanningResult:
        parsed = ParsedDocument.model_validate_json(
            self.storage.read_json_artifact(task_id, PARSE_ARTIFACT)
        )
        source = self.storage.source_path(task_id).read_text(encoding="utf-8")
        planning = plan_analysis(parsed=parsed, source=source, budget=plan.budget)
        if planning.plan.plan_id != plan.plan_id:
            raise AnalysisPlanMismatchError(
                "当前正文与已保存批次计划不一致，请重新规划"
            )
        return planning

    def _load_plan(self, task_id: str) -> AnalysisPlan:
        try:
            payload = self.storage.read_json_artifact(task_id, PLAN_ARTIFACT)
        except ArtifactNotFoundError as error:
            raise AnalysisPlanMismatchError("请先生成分析批次计划") from error
        return AnalysisPlan.model_validate_json(payload)

    def _load_manifest(self, task_id: str) -> AnalysisTaskManifest:
        try:
            payload = self.storage.read_json_artifact(task_id, TASK_ARTIFACT)
        except ArtifactNotFoundError as error:
            raise AnalysisTaskNotFoundError(task_id) from error
        return AnalysisTaskManifest.model_validate_json(payload)

    def _new_manifest(
        self,
        task_id: str,
        plan: AnalysisPlan,
        gateway: ModelGateway,
        now: datetime,
    ) -> AnalysisTaskManifest:
        return AnalysisTaskManifest(
            task_id=task_id,
            plan_id=plan.plan_id,
            status="queued",
            provider=gateway.text_config.provider,
            model=gateway.text_config.model,
            batch_count=plan.batch_count,
            completed_batch_count=0,
            batches=[
                BatchCheckpoint(
                    batch_id=batch.batch_id,
                    ordinal=batch.ordinal,
                    status="pending",
                    attempt_count=0,
                )
                for batch in plan.batches
            ],
            created_at=now,
            updated_at=now,
        )

    def _save_manifest(self, manifest: AnalysisTaskManifest) -> None:
        self.storage.write_json_artifact(
            manifest.task_id,
            TASK_ARTIFACT,
            manifest.model_dump_json(indent=2),
        )

    def _save_summary(self, record: BatchSummaryRecord) -> None:
        self.storage.write_json_artifact(
            record.task_id,
            self._summary_artifact(record.batch.batch_id),
            record.model_dump_json(indent=2),
        )

    def _load_valid_summary(
        self,
        task_id: str,
        plan_id: str,
        batch: PlannedBatchMaterial,
    ) -> BatchSummaryRecord | None:
        try:
            payload = self.storage.read_json_artifact(
                task_id,
                self._summary_artifact(batch.metadata.batch_id),
            )
            record = BatchSummaryRecord.model_validate_json(payload)
        except (ArtifactNotFoundError, ValidationError, ValueError):
            return None
        if (
            record.plan_id != plan_id
            or record.batch.batch_id != batch.metadata.batch_id
            or record.source_fingerprint != batch.metadata.content_fingerprint
        ):
            return None
        return record

    async def _fail(
        self,
        manifest: AnalysisTaskManifest,
        checkpoint: BatchCheckpoint,
        failure: AnalysisTaskError,
    ) -> AnalysisTaskManifest:
        checkpoint.status = "failed"
        checkpoint.last_error = failure
        manifest.status = "failed"
        manifest.current_batch_id = None
        manifest.error = failure
        manifest.updated_at = datetime.now(UTC)
        await asyncio.to_thread(self._save_manifest, manifest)
        return manifest

    @staticmethod
    def _complete_checkpoint(
        manifest: AnalysisTaskManifest,
        checkpoint: BatchCheckpoint,
        record: BatchSummaryRecord,
    ) -> None:
        checkpoint.status = "completed"
        checkpoint.summary_artifact = BatchSummaryRunner._summary_artifact(
            checkpoint.batch_id
        )
        checkpoint.last_error = None
        checkpoint.completed_at = record.completed_at
        manifest.completed_batch_count = sum(
            item.status == "completed" for item in manifest.batches
        )
        manifest.current_batch_id = None
        manifest.error = None
        manifest.updated_at = datetime.now(UTC)

    @staticmethod
    def _checkpoint(
        manifest: AnalysisTaskManifest,
        batch_id: str,
    ) -> BatchCheckpoint:
        for checkpoint in manifest.batches:
            if checkpoint.batch_id == batch_id:
                return checkpoint
        raise AnalysisPlanMismatchError("任务清单缺少规划批次")

    @staticmethod
    def _summary_artifact(batch_id: str) -> str:
        return f"{SUMMARY_ARTIFACT_PREFIX}{batch_id}"

    async def _run_hierarchy(
        self,
        *,
        task_id: str,
        plan: AnalysisPlan,
        manifest: AnalysisTaskManifest,
        gateway: ModelGateway,
    ) -> AnalysisTaskManifest:
        materials = [self._batch_material(record) for record in self.load_summaries(task_id)]
        if not materials:
            failure = AnalysisTaskError(
                code="outline_has_no_inputs",
                message="没有可供汇总的批次概括",
                retryable=False,
            )
            return await self._fail_hierarchy(manifest, failure)

        level = 1
        while not self._fits_final(plan, materials):
            try:
                groups = self._pack_merge_groups(plan, level, materials)
            except OutlineInputBudgetError as error:
                failure = AnalysisTaskError(
                    code="merge_input_over_budget",
                    message=str(error),
                    retryable=False,
                )
                return await self._fail_hierarchy(manifest, failure)
            if len(groups) >= len(materials):
                failure = AnalysisTaskError(
                    code="merge_cannot_reduce",
                    message="当前输入上限无法容纳两个相邻概括，请提高模型最大输入",
                    retryable=False,
                )
                return await self._fail_hierarchy(manifest, failure)

            next_materials: list[OutlineInputMaterial] = []
            for group in groups:
                input_fingerprint = self._input_fingerprint(plan.plan_id, group)
                node_id = f"merge_{sha256(f'{level}:{input_fingerprint}'.encode()).hexdigest()[:16]}"
                checkpoint = self._merge_checkpoint(
                    manifest,
                    node_id=node_id,
                    level=level,
                    materials=group,
                    input_fingerprint=input_fingerprint,
                )
                existing = await asyncio.to_thread(
                    self._load_valid_merge,
                    task_id,
                    plan.plan_id,
                    node_id,
                    input_fingerprint,
                )
                if existing is not None:
                    self._complete_merge_checkpoint(manifest, checkpoint, existing)
                    await asyncio.to_thread(self._save_manifest, manifest)
                    next_materials.append(self._merge_material(existing))
                    continue

                checkpoint.status = "running"
                checkpoint.attempt_count += 1
                checkpoint.last_error = None
                manifest.status = "merging"
                manifest.current_merge_node_id = node_id
                manifest.error = None
                manifest.updated_at = datetime.now(UTC)
                await asyncio.to_thread(self._save_manifest, manifest)
                try:
                    record = await self.merge_agent.merge(
                        task_id=task_id,
                        plan_id=plan.plan_id,
                        node_id=node_id,
                        level=level,
                        input_fingerprint=input_fingerprint,
                        materials=group,
                        gateway=gateway,
                        max_output_tokens=plan.budget.output_reserve_tokens,
                        tokenizer_name=plan.tokenizer,
                        request_input_limit_tokens=plan.budget.request_input_limit_tokens,
                    )
                except ModelGatewayError as error:
                    return await self._fail_merge(
                        manifest,
                        checkpoint,
                        AnalysisTaskError(
                            code=error.code,
                            message=error.message,
                            retryable=error.retryable,
                            merge_node_id=node_id,
                        ),
                    )
                except (HierarchicalOutlineOutputError, ValidationError) as error:
                    return await self._fail_merge(
                        manifest,
                        checkpoint,
                        AnalysisTaskError(
                            code="invalid_merge_summary",
                            message=str(error),
                            retryable=True,
                            merge_node_id=node_id,
                        ),
                    )
                except OutlineInputBudgetError as error:
                    return await self._fail_merge(
                        manifest,
                        checkpoint,
                        AnalysisTaskError(
                            code="merge_input_over_budget",
                            message=str(error),
                            retryable=False,
                            merge_node_id=node_id,
                        ),
                    )
                await asyncio.to_thread(self._save_merge, record)
                self._complete_merge_checkpoint(manifest, checkpoint, record)
                await asyncio.to_thread(self._save_manifest, manifest)
                next_materials.append(self._merge_material(record))
            materials = next_materials
            level += 1

        input_fingerprint = self._input_fingerprint(plan.plan_id, materials)
        existing_outline = await asyncio.to_thread(
            self._load_valid_outline,
            task_id,
            plan.plan_id,
            input_fingerprint,
        )
        if existing_outline is not None:
            self._complete_outline(manifest, existing_outline)
            await asyncio.to_thread(self._save_manifest, manifest)
            return manifest

        manifest.status = "finalizing"
        manifest.final_outline_status = "running"
        manifest.final_outline_attempt_count += 1
        manifest.current_merge_node_id = None
        manifest.error = None
        manifest.updated_at = datetime.now(UTC)
        await asyncio.to_thread(self._save_manifest, manifest)
        try:
            outline = await self.final_agent.outline(
                task_id=task_id,
                plan_id=plan.plan_id,
                input_fingerprint=input_fingerprint,
                materials=materials,
                gateway=gateway,
                max_output_tokens=plan.budget.output_reserve_tokens,
                tokenizer_name=plan.tokenizer,
                request_input_limit_tokens=plan.budget.request_input_limit_tokens,
            )
        except ModelGatewayError as error:
            return await self._fail_final(
                manifest,
                AnalysisTaskError(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                ),
            )
        except (HierarchicalOutlineOutputError, ValidationError) as error:
            return await self._fail_final(
                manifest,
                AnalysisTaskError(
                    code="invalid_final_outline",
                    message=str(error),
                    retryable=True,
                ),
            )
        except OutlineInputBudgetError as error:
            return await self._fail_final(
                manifest,
                AnalysisTaskError(
                    code="final_input_over_budget",
                    message=str(error),
                    retryable=False,
                ),
            )
        await asyncio.to_thread(self._save_outline, outline)
        self._complete_outline(manifest, outline)
        await asyncio.to_thread(self._save_manifest, manifest)
        return manifest

    @staticmethod
    def _batch_material(record: BatchSummaryRecord) -> OutlineInputMaterial:
        return OutlineInputMaterial(
            input_id=record.batch.batch_id,
            fingerprint=record.source_fingerprint,
            chapter_range=record.batch.chapter_range_label,
            batch_ids=(record.batch.batch_id,),
            chapter_ids=tuple(record.batch.chapter_ids),
            payload=record.summary.model_dump(mode="json"),
        )

    @staticmethod
    def _merge_material(record: MergeSummaryRecord) -> OutlineInputMaterial:
        chapter_ranges = record.summary.chapter_outline
        range_label = (
            f"{chapter_ranges[0].chapter_range}—{chapter_ranges[-1].chapter_range}"
            if chapter_ranges
            else f"汇总层级 {record.level}"
        )
        return OutlineInputMaterial(
            input_id=record.node_id,
            fingerprint=record.input_fingerprint,
            chapter_range=range_label,
            batch_ids=tuple(record.source_batch_ids),
            chapter_ids=tuple(record.source_chapter_ids),
            payload=record.summary.model_dump(mode="json"),
        )

    @staticmethod
    def _input_fingerprint(plan_id: str, materials: list[OutlineInputMaterial]) -> str:
        value = json.dumps(
            [plan_id, *[(item.input_id, item.fingerprint) for item in materials]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(value.encode()).hexdigest()

    @staticmethod
    def _source_ids(materials: list[OutlineInputMaterial]) -> tuple[list[str], list[str]]:
        return (
            list(dict.fromkeys(x for item in materials for x in item.batch_ids)),
            list(dict.fromkeys(x for item in materials for x in item.chapter_ids)),
        )

    def _fits_final(self, plan: AnalysisPlan, materials: list[OutlineInputMaterial]) -> bool:
        prompt = build_final_outline_prompt(
            allowed_input_ids=[item.input_id for item in materials],
            items=[item.prompt_item() for item in materials],
        )
        return self._request_tokens(plan, prompt, FINAL_OUTLINE_INSTRUCTIONS) <= (
            plan.budget.request_input_limit_tokens - _PROMPT_FIT_MARGIN_TOKENS
        )

    def _pack_merge_groups(
        self,
        plan: AnalysisPlan,
        level: int,
        materials: list[OutlineInputMaterial],
    ) -> list[list[OutlineInputMaterial]]:
        groups: list[list[OutlineInputMaterial]] = []
        current: list[OutlineInputMaterial] = []
        for material in materials:
            candidate = [*current, material]
            prompt = build_merge_summary_prompt(
                level=level,
                node_id="merge_0000000000000000",
                allowed_input_ids=[item.input_id for item in candidate],
                items=[item.prompt_item() for item in candidate],
            )
            if self._request_tokens(plan, prompt, MERGE_SUMMARY_INSTRUCTIONS) <= (
                plan.budget.request_input_limit_tokens - _PROMPT_FIT_MARGIN_TOKENS
            ):
                current = candidate
                continue
            if not current:
                raise OutlineInputBudgetError("单个概括已超过汇总请求最大输入")
            groups.append(current)
            current = [material]
        if current:
            groups.append(current)
        return groups

    @staticmethod
    def _request_tokens(plan: AnalysisPlan, prompt: str, instructions: str) -> int:
        encoding = tiktoken.get_encoding(plan.tokenizer)
        return len(encoding.encode_ordinary(prompt)) + len(
            encoding.encode_ordinary(instructions)
        )

    def _merge_checkpoint(
        self,
        manifest: AnalysisTaskManifest,
        *,
        node_id: str,
        level: int,
        materials: list[OutlineInputMaterial],
        input_fingerprint: str,
    ) -> MergeCheckpoint:
        for checkpoint in manifest.merge_nodes:
            if checkpoint.node_id == node_id:
                return checkpoint
        checkpoint = MergeCheckpoint(
            node_id=node_id,
            level=level,
            input_ids=[item.input_id for item in materials],
            input_fingerprint=input_fingerprint,
            status="pending",
            attempt_count=0,
        )
        manifest.merge_nodes.append(checkpoint)
        manifest.merge_node_count = len(manifest.merge_nodes)
        manifest.updated_at = datetime.now(UTC)
        return checkpoint

    def _load_valid_merge(
        self,
        task_id: str,
        plan_id: str,
        node_id: str,
        input_fingerprint: str,
    ) -> MergeSummaryRecord | None:
        try:
            payload = self.storage.read_json_artifact(
                task_id, f"{MERGE_ARTIFACT_PREFIX}{node_id}"
            )
            record = MergeSummaryRecord.model_validate_json(payload)
        except (ArtifactNotFoundError, ValidationError, ValueError):
            return None
        if (
            record.plan_id != plan_id
            or record.node_id != node_id
            or record.input_fingerprint != input_fingerprint
        ):
            return None
        return record

    def _save_merge(self, record: MergeSummaryRecord) -> None:
        self.storage.write_json_artifact(
            record.task_id,
            f"{MERGE_ARTIFACT_PREFIX}{record.node_id}",
            record.model_dump_json(indent=2),
        )

    def _load_valid_outline(
        self,
        task_id: str,
        plan_id: str,
        input_fingerprint: str,
    ) -> FinalOutlineRecord | None:
        try:
            payload = self.storage.read_json_artifact(task_id, FINAL_OUTLINE_ARTIFACT)
            record = FinalOutlineRecord.model_validate_json(payload)
        except (ArtifactNotFoundError, ValidationError, ValueError):
            return None
        if record.plan_id != plan_id or record.input_fingerprint != input_fingerprint:
            return None
        return record

    def _save_outline(self, record: FinalOutlineRecord) -> None:
        self.storage.write_json_artifact(
            record.task_id,
            FINAL_OUTLINE_ARTIFACT,
            record.model_dump_json(indent=2),
        )

    @staticmethod
    def _complete_merge_checkpoint(
        manifest: AnalysisTaskManifest,
        checkpoint: MergeCheckpoint,
        record: MergeSummaryRecord,
    ) -> None:
        checkpoint.status = "completed"
        checkpoint.summary_artifact = f"{MERGE_ARTIFACT_PREFIX}{record.node_id}"
        checkpoint.last_error = None
        checkpoint.completed_at = record.completed_at
        manifest.completed_merge_node_count = sum(
            node.status == "completed" for node in manifest.merge_nodes
        )
        manifest.current_merge_node_id = None
        manifest.error = None
        manifest.updated_at = datetime.now(UTC)

    @staticmethod
    def _complete_outline(
        manifest: AnalysisTaskManifest,
        record: FinalOutlineRecord,
    ) -> None:
        manifest.status = "completed"
        manifest.final_outline_status = "completed"
        manifest.final_outline_artifact = FINAL_OUTLINE_ARTIFACT
        manifest.current_merge_node_id = None
        manifest.error = None
        manifest.updated_at = record.completed_at

    async def _fail_merge(
        self,
        manifest: AnalysisTaskManifest,
        checkpoint: MergeCheckpoint,
        failure: AnalysisTaskError,
    ) -> AnalysisTaskManifest:
        checkpoint.status = "failed"
        checkpoint.last_error = failure
        return await self._fail_hierarchy(manifest, failure)

    async def _fail_final(
        self,
        manifest: AnalysisTaskManifest,
        failure: AnalysisTaskError,
    ) -> AnalysisTaskManifest:
        manifest.final_outline_status = "failed"
        return await self._fail_hierarchy(manifest, failure)

    async def _fail_hierarchy(
        self,
        manifest: AnalysisTaskManifest,
        failure: AnalysisTaskError,
    ) -> AnalysisTaskManifest:
        manifest.status = "failed"
        manifest.current_merge_node_id = None
        manifest.error = failure
        manifest.updated_at = datetime.now(UTC)
        await asyncio.to_thread(self._save_manifest, manifest)
        return manifest


class AnalysisTaskManager:
    """Keep background work alive independently of individual HTTP requests."""

    def __init__(
        self,
        storage: TemporaryUploadStorage,
        *,
        runner: BatchSummaryRunner | None = None,
    ) -> None:
        self.storage = storage
        self.runner = runner or BatchSummaryRunner(storage)
        self._tasks: dict[str, asyncio.Task[AnalysisTaskManifest]] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        task_id: str,
        gateway: ModelGateway,
    ) -> AnalysisTaskManifest:
        async with self._lock:
            existing = self._tasks.get(task_id)
            if existing is not None and not existing.done():
                raise AnalysisTaskAlreadyRunningError(task_id)
            manifest = await asyncio.to_thread(
                self.runner.prepare_manifest,
                task_id,
                gateway,
            )
            if manifest.status == "completed":
                return manifest
            task = asyncio.create_task(self._execute(task_id, gateway))
            task.add_done_callback(self._consume_task_result)
            self._tasks[task_id] = task
            return manifest

    async def get(self, task_id: str) -> AnalysisTaskManifest:
        async with self._lock:
            task = self._tasks.get(task_id)
            active = task is not None and not task.done()
        manifest = await asyncio.to_thread(self.runner.load_manifest, task_id)
        if not active and manifest.status in {
            "queued",
            "running",
            "merging",
            "finalizing",
        }:
            manifest = await asyncio.to_thread(self.runner.mark_interrupted, task_id)
        return manifest

    async def summaries(self, task_id: str) -> list[BatchSummaryRecord]:
        return await asyncio.to_thread(self.runner.load_summaries, task_id)

    async def outline(self, task_id: str) -> FinalOutlineRecord:
        return await asyncio.to_thread(self.runner.load_outline, task_id)

    async def is_running(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            return task is not None and not task.done()

    async def discard(self, task_id: str, *, include_plan: bool) -> None:
        async with self._lock:
            task = self._tasks.pop(task_id, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(
            self.runner.discard_artifacts,
            task_id,
            include_plan=include_plan,
        )

    async def prune_missing_uploads(self) -> None:
        async with self._lock:
            task_ids = list(self._tasks)
        for task_id in task_ids:
            try:
                await asyncio.to_thread(self.storage.get, task_id)
            except UploadNotFoundError:
                await self.discard(task_id, include_plan=False)

    async def close(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(
        self,
        task_id: str,
        gateway: ModelGateway,
    ) -> AnalysisTaskManifest:
        try:
            return await self.runner.run(task_id, gateway)
        finally:
            async with self._lock:
                current = self._tasks.get(task_id)
                if current is asyncio.current_task():
                    self._tasks.pop(task_id, None)

    @staticmethod
    def _consume_task_result(task: asyncio.Task[AnalysisTaskManifest]) -> None:
        """Retrieve detached task failures so asyncio never leaks warnings."""

        with suppress(asyncio.CancelledError):
            task.exception()
