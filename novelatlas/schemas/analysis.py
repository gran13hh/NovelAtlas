"""Schemas for token-budgeted novel analysis planning and execution."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from .models import BrowserModelConfig, ModelProviderName, ModelUsage


class AnalysisBudget(BaseModel):
    """Token limits used to keep every later model request bounded."""

    context_window_tokens: int = Field(ge=512, le=10_000_000)
    max_input_tokens: int = Field(ge=128, le=10_000_000)
    output_reserve_tokens: int = Field(ge=32, le=32_000)
    safety_margin_tokens: int = Field(ge=512, le=1_000_000)

    @computed_field
    @property
    def request_input_limit_tokens(self) -> int:
        """Maximum input after reserving the model's output window."""

        return min(
            self.max_input_tokens,
            self.context_window_tokens - self.output_reserve_tokens,
        )

    @computed_field
    @property
    def available_content_tokens(self) -> int:
        """Budget available for source or summary content in one request."""

        return self.request_input_limit_tokens - self.safety_margin_tokens

    @model_validator(mode="after")
    def validate_available_content(self) -> "AnalysisBudget":
        if self.output_reserve_tokens + self.safety_margin_tokens >= (
            self.context_window_tokens
        ):
            raise ValueError("输出预留与安全余量之和必须小于上下文窗口")
        if self.available_content_tokens < 64:
            raise ValueError("扣除输出预留与安全余量后至少需要 64 个内容 Token")
        return self


class AnalysisPlanRequest(BaseModel):
    """Optional browser-local limits; omitted values use server defaults."""

    budget: AnalysisBudget | None = None


class AnalysisSegment(BaseModel):
    """One non-overlapping piece of current parsed novel content."""

    segment_id: str = Field(pattern=r"^segment_[0-9a-f]{16}$")
    chapter_id: str
    chapter_ordinal: int = Field(ge=1)
    chapter_title: str
    part_ordinal: int = Field(ge=1)
    part_count: int = Field(ge=1)
    source_start_char: int = Field(ge=0)
    source_end_char: int = Field(ge=0)
    source_chunk_ids: list[str]
    token_count: int = Field(ge=1)
    character_count: int = Field(ge=1)
    content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    contains_edited_content: bool

    @model_validator(mode="after")
    def validate_source_range(self) -> "AnalysisSegment":
        if self.source_end_char < self.source_start_char:
            raise ValueError("analysis segment source range is reversed")
        if self.part_ordinal > self.part_count:
            raise ValueError("analysis segment part ordinal exceeds part count")
        return self


class AnalysisBatch(BaseModel):
    """Adjacent analysis segments packed into one future summary request."""

    batch_id: str = Field(pattern=r"^batch_[0-9a-f]{16}$")
    ordinal: int = Field(ge=1)
    segment_ids: list[str] = Field(min_length=1)
    chapter_ids: list[str] = Field(min_length=1)
    chapter_start_ordinal: int = Field(ge=1)
    chapter_end_ordinal: int = Field(ge=1)
    chapter_range_label: str
    source_chunk_ids: list[str]
    token_count: int = Field(ge=1)
    character_count: int = Field(ge=1)
    content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    contains_edited_content: bool

    @model_validator(mode="after")
    def validate_chapter_range(self) -> "AnalysisBatch":
        if self.chapter_end_ordinal < self.chapter_start_ordinal:
            raise ValueError("analysis batch chapter range is reversed")
        return self


class AnalysisPlan(BaseModel):
    """Persisted, secret-free preview of the work required for one novel."""

    schema_version: Literal[1] = 1
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{16}$")
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    tokenizer: str
    budget: AnalysisBudget
    source_token_count: int = Field(ge=1)
    planned_input_token_count: int = Field(ge=0)
    skipped_empty_chapter_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    batch_count: int = Field(ge=0)
    summary_call_count: int = Field(ge=0)
    estimated_merge_call_count: int = Field(ge=0)
    estimated_total_call_count: int = Field(ge=0)
    estimated_merge_input_tokens: int = Field(ge=0)
    estimated_total_input_tokens: int = Field(ge=0)
    estimated_summary_tokens_per_batch: int = Field(ge=1)
    segments: list[AnalysisSegment]
    batches: list[AnalysisBatch]

    @model_validator(mode="after")
    def validate_counts(self) -> "AnalysisPlan":
        if self.segment_count != len(self.segments):
            raise ValueError("segment_count does not match segments")
        if self.batch_count != len(self.batches):
            raise ValueError("batch_count does not match batches")
        if self.summary_call_count != self.batch_count:
            raise ValueError("summary calls must match planned batches")
        if self.estimated_total_call_count != (
            self.summary_call_count + self.estimated_merge_call_count
        ):
            raise ValueError("estimated total call count is inconsistent")
        return self


SummaryConfidence = Literal["certain", "likely", "uncertain"]


class BatchSummaryClaim(BaseModel):
    """One source-linked event, clue, foreshadowing, or unresolved item."""

    description: str = Field(min_length=1, max_length=4_000)
    chapter_ids: list[str] = Field(min_length=1)
    source_chunk_ids: list[str] = Field(min_length=1)
    confidence: SummaryConfidence = "certain"


class BatchCharacterUpdate(BaseModel):
    """What this batch establishes or changes about one character."""

    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4_000)
    relationship_changes: list[str] = Field(default_factory=list)
    chapter_ids: list[str] = Field(min_length=1)
    source_chunk_ids: list[str] = Field(min_length=1)
    confidence: SummaryConfidence = "certain"


class BatchWorldbuildingUpdate(BaseModel):
    """One setting element that is materially present in this batch."""

    category: Literal[
        "location",
        "faction",
        "rule",
        "power_system",
        "item",
        "history",
        "other",
    ]
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=4_000)
    chapter_ids: list[str] = Field(min_length=1)
    source_chunk_ids: list[str] = Field(min_length=1)
    confidence: SummaryConfidence = "certain"


class BatchSummaryContent(BaseModel):
    """Structured important-content summary produced for one source batch."""

    overview: str = Field(min_length=1, max_length=12_000)
    key_events: list[BatchSummaryClaim] = Field(default_factory=list)
    characters: list[BatchCharacterUpdate] = Field(default_factory=list)
    worldbuilding: list[BatchWorldbuildingUpdate] = Field(default_factory=list)
    foreshadowing: list[BatchSummaryClaim] = Field(default_factory=list)
    unresolved_items: list[BatchSummaryClaim] = Field(default_factory=list)


class BatchSummaryRecord(BaseModel):
    """One validated batch result plus secret-free provider metadata."""

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{16}$")
    batch: AnalysisBatch
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: BatchSummaryContent
    provider: ModelProviderName
    model: str
    request_id: str | None = None
    usage: ModelUsage | None = None
    completed_at: datetime
    user_edited_at: datetime | None = None


class OutlineSource(BaseModel):
    """Batch and chapter provenance retained across every merge layer."""

    input_ids: list[str] = Field(min_length=1)
    batch_ids: list[str] = Field(default_factory=list)
    chapter_ids: list[str] = Field(default_factory=list)


class OutlineClaim(BaseModel):
    """One source-linked fact or uncertainty in a merged outline."""

    description: str = Field(min_length=1, max_length=8_000)
    sources: OutlineSource
    confidence: SummaryConfidence = "certain"


class ChapterRangeOutline(BaseModel):
    """A chronological outline item covering one or more source batches."""

    chapter_range: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=12_000)
    key_events: list[str] = Field(default_factory=list)
    sources: OutlineSource


class OutlineStoryline(BaseModel):
    """A storyline and its ordered developments."""

    name: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=12_000)
    developments: list[str] = Field(default_factory=list)
    sources: OutlineSource


class OutlineCharacter(BaseModel):
    """A principal character, relationships, and stage changes."""

    name: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=12_000)
    relationships: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    sources: OutlineSource
    confidence: SummaryConfidence = "certain"


class OutlineWorldbuilding(BaseModel):
    """A merged location, faction, rule, power, item, or concept."""

    category: Literal[
        "location",
        "faction",
        "rule",
        "power_system",
        "item",
        "history",
        "other",
    ]
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=12_000)
    sources: OutlineSource
    confidence: SummaryConfidence = "certain"


class MergeSummaryContent(BaseModel):
    """Loss-controlled summary used as input to a higher merge layer."""

    overview: str = Field(min_length=1, max_length=20_000)
    chapter_outline: list[ChapterRangeOutline] = Field(default_factory=list)
    key_events: list[OutlineClaim] = Field(default_factory=list)
    characters: list[OutlineCharacter] = Field(default_factory=list)
    worldbuilding: list[OutlineWorldbuilding] = Field(default_factory=list)
    foreshadowing: list[OutlineClaim] = Field(default_factory=list)
    unresolved_items: list[OutlineClaim] = Field(default_factory=list)
    uncertainties: list[OutlineClaim] = Field(default_factory=list)


class MergeSummaryRecord(BaseModel):
    """One restart-safe intermediate node in the hierarchical merge tree."""

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{16}$")
    node_id: str = Field(pattern=r"^merge_[0-9a-f]{16}$")
    level: int = Field(ge=1)
    input_ids: list[str] = Field(min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_batch_ids: list[str] = Field(min_length=1)
    source_chapter_ids: list[str] = Field(min_length=1)
    summary: MergeSummaryContent
    provider: ModelProviderName
    model: str
    request_id: str | None = None
    usage: ModelUsage | None = None
    completed_at: datetime


class NovelOutline(BaseModel):
    """Final detailed outline of the complete supplied novel text."""

    overall_summary: str = Field(min_length=1, max_length=40_000)
    chapter_outline: list[ChapterRangeOutline] = Field(default_factory=list)
    storylines: list[OutlineStoryline] = Field(default_factory=list)
    characters: list[OutlineCharacter] = Field(default_factory=list)
    worldbuilding: list[OutlineWorldbuilding] = Field(default_factory=list)
    foreshadowing: list[OutlineClaim] = Field(default_factory=list)
    unresolved_items: list[OutlineClaim] = Field(default_factory=list)
    conflicts_and_uncertainties: list[OutlineClaim] = Field(default_factory=list)


class FinalOutlineRecord(BaseModel):
    """Validated final artifact plus its complete source coverage."""

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{16}$")
    input_ids: list[str] = Field(min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_batch_ids: list[str] = Field(min_length=1)
    source_chapter_ids: list[str] = Field(min_length=1)
    outline: NovelOutline
    provider: ModelProviderName
    model: str
    request_id: str | None = None
    usage: ModelUsage | None = None
    completed_at: datetime
    user_edited_at: datetime | None = None


class AnalysisTaskError(BaseModel):
    """Safe task failure details that never include provider bodies or secrets."""

    code: str
    message: str
    retryable: bool
    batch_id: str | None = None
    merge_node_id: str | None = None


BatchCheckpointStatus = Literal["pending", "running", "completed", "failed"]


class BatchCheckpoint(BaseModel):
    """Persistent status for exactly one planned source batch."""

    batch_id: str = Field(pattern=r"^batch_[0-9a-f]{16}$")
    ordinal: int = Field(ge=1)
    status: BatchCheckpointStatus
    attempt_count: int = Field(ge=0)
    summary_artifact: str | None = None
    last_error: AnalysisTaskError | None = None
    completed_at: datetime | None = None


MergeCheckpointStatus = Literal["pending", "running", "completed", "failed"]


class MergeCheckpoint(BaseModel):
    """Persistent status for one deterministic intermediate merge node."""

    node_id: str = Field(pattern=r"^merge_[0-9a-f]{16}$")
    level: int = Field(ge=1)
    input_ids: list[str] = Field(min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: MergeCheckpointStatus
    attempt_count: int = Field(ge=0)
    summary_artifact: str | None = None
    last_error: AnalysisTaskError | None = None
    completed_at: datetime | None = None


AnalysisTaskStatus = Literal[
    "queued",
    "running",
    "failed",
    "interrupted",
    "batch_summaries_completed",
    "merging",
    "finalizing",
    "completed",
]


class AnalysisTaskManifest(BaseModel):
    """Atomic, restart-safe progress manifest without credentials or source text."""

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{16}$")
    status: AnalysisTaskStatus
    engine: Literal["baseline", "langgraph"] = "baseline"
    graph_node: str | None = None
    summary_revision: str | None = None
    analysis_goal: str = Field(default="分析跨章节事件、人物别名与关系变化、世界观及证据冲突", min_length=1, max_length=1000)
    agent_concurrency: int = Field(default=2, ge=1, le=3)
    agent_review_limit: int = Field(default=32, ge=1, le=96)
    provider: ModelProviderName
    model: str
    batch_count: int = Field(ge=0)
    completed_batch_count: int = Field(ge=0)
    current_batch_id: str | None = None
    error: AnalysisTaskError | None = None
    batches: list[BatchCheckpoint]
    merge_node_count: int = Field(default=0, ge=0)
    completed_merge_node_count: int = Field(default=0, ge=0)
    current_merge_node_id: str | None = None
    merge_nodes: list[MergeCheckpoint] = Field(default_factory=list)
    final_outline_status: MergeCheckpointStatus = "pending"
    final_outline_attempt_count: int = Field(default=0, ge=0)
    final_outline_artifact: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_progress(self) -> "AnalysisTaskManifest":
        if self.batch_count != len(self.batches):
            raise ValueError("task batch_count does not match checkpoints")
        completed = sum(batch.status == "completed" for batch in self.batches)
        if self.completed_batch_count != completed:
            raise ValueError("completed_batch_count does not match checkpoints")
        if self.completed_batch_count > self.batch_count:
            raise ValueError("completed batches exceed planned batches")
        if self.merge_node_count != len(self.merge_nodes):
            raise ValueError("task merge_node_count does not match checkpoints")
        completed_merges = sum(
            node.status == "completed" for node in self.merge_nodes
        )
        if self.completed_merge_node_count != completed_merges:
            raise ValueError("completed_merge_node_count does not match checkpoints")
        return self


AnalysisProgressPhase = Literal[
    "queued",
    "batch_summary",
    "hierarchical_merge",
    "final_outline",
    "completed",
    "failed",
    "interrupted",
]


class AnalysisProgressSnapshot(BaseModel):
    """Compact secret-free task state emitted through server-sent events."""

    event_id: str = Field(pattern=r"^progress_[0-9a-f]{16}$")
    graph_node: str | None = None
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: AnalysisTaskStatus
    phase: AnalysisProgressPhase
    completed_batch_count: int = Field(ge=0)
    batch_count: int = Field(ge=0)
    current_batch_id: str | None = None
    current_batch_ordinal: int | None = Field(default=None, ge=1)
    completed_merge_node_count: int = Field(ge=0)
    merge_node_count: int = Field(ge=0)
    current_merge_node_id: str | None = None
    current_merge_level: int | None = Field(default=None, ge=1)
    final_outline_status: MergeCheckpointStatus
    error: AnalysisTaskError | None = None
    terminal: bool
    updated_at: datetime


class AnalysisRunRequest(BaseModel):
    """Optional one-run browser model configuration; its key stays in memory."""

    config: BrowserModelConfig | None = None
    engine: Literal["baseline", "langgraph"] = "baseline"
    goal: str = Field(default="分析跨章节事件、人物别名与关系变化、世界观及证据冲突", min_length=1, max_length=1000)
    concurrency: int = Field(default=2, ge=1, le=3)
    review_limit: int = Field(default=32, ge=1, le=96)

    @model_validator(mode="after")
    def nonblank_goal(self):
        self.goal = self.goal.strip()
        if not self.goal:
            raise ValueError("analysis goal cannot be blank")
        return self


class UpdateBatchSummaryRequest(BaseModel):
    """User correction for one completed batch summary."""

    summary: BatchSummaryContent


class UpdateNovelOutlineRequest(BaseModel):
    """User correction for the generated final outline."""

    outline: NovelOutline
