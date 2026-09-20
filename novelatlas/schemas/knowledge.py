"""Strict contracts for semantic plans, evidence and bounded agent decisions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SemanticTask(Contract):
    task_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    role: Literal["events", "relationships", "worldbuilding"]
    objective: str = Field(min_length=1, max_length=600)
    query: str = Field(min_length=1, max_length=200)
    depends_on: list[str] = Field(default_factory=list, max_length=8)
    expected_artifact: str = Field(min_length=1, max_length=200)


class SemanticPlan(Contract):
    goal: str = Field(min_length=1, max_length=1000)
    tasks: list[SemanticTask] = Field(min_length=1, max_length=8)
    mode: Literal["model", "mock"] = "model"

    @model_validator(mode="after")
    def valid_dag(self):
        ids = [t.task_id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate semantic task IDs")
        done: set[str] = set()
        while len(done) < len(ids):
            ready = [
                t.task_id
                for t in self.tasks
                if t.task_id not in done and set(t.depends_on) <= done
            ]
            if not ready:
                raise ValueError("semantic dependencies missing or cyclic")
            done.update(ready)
        return self


class SearchArgs(Contract):
    query: str = Field(min_length=1, max_length=200)
    chapter_ids: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=4, ge=1, le=8)


class Evidence(Contract):
    origin: Literal["original", "user_edit"] = "original"
    passage_id: str = Field(min_length=1, max_length=200)
    chapter_id: str = Field(min_length=1, max_length=200)
    chunk_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=1200)


class Passage(Contract):
    passage_id: str
    chapter_id: str
    chunk_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=1)
    content: str
    origin: Literal["original", "user_edit"]
    score: float = 0


class KnowledgeItem(Contract):
    subject: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    predicate: str = Field(min_length=1, max_length=200)
    object: str = Field(min_length=1, max_length=400)
    description: str = Field(min_length=1, max_length=1200)
    classification: Literal["fact", "inference", "uncertain"] = "uncertain"
    evidence: list[Evidence] = Field(default_factory=list, max_length=8)


class DomainResult(Contract):
    task_id: str
    role: Literal["events", "relationships", "worldbuilding"]
    items: list[KnowledgeItem] = Field(default_factory=list, max_length=24)


class ReviewDecision(Contract):
    action: Literal["search", "verify", "finish"]
    search: SearchArgs | None = None
    evidence: Evidence | None = None
    verdict: Literal["supported", "contradicted", "uncertain"] = "uncertain"
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def tool_args(self):
        if self.action == "search" and self.search is None:
            raise ValueError("search requires parameters")
        if self.action == "verify" and self.evidence is None:
            raise ValueError("verify requires evidence")
        return self


class ReviewResult(Contract):
    task_id: str
    item_index: int = Field(ge=0)
    verdict: Literal["supported", "contradicted", "uncertain"]
    quote_valid: bool
    note: str = Field(max_length=500)
    steps: int = Field(ge=0)
    calls: int = Field(ge=0)
    evidence: list[Evidence] = Field(default_factory=list)


class KnowledgeReport(Contract):
    schema_version: Literal[1] = 1
    fingerprint: str
    plan: SemanticPlan
    domains: list[DomainResult]
    reviews: list[ReviewResult]
    entities: dict[str, list[str]]
    relation_history: list[dict[str, str | list[str]]]
    conflicts: list[str]
    repaired_tasks: list[str]
