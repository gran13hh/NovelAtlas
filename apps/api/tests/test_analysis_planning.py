"""Token-budget planning tests that never invoke a model provider."""

from pathlib import Path

from fastapi.testclient import TestClient

from novelatlas.analysis import plan_analysis
from novelatlas.schemas.analysis import AnalysisBudget
from novelatlas.services.chapter_parser import ChapterParser
from novelatlas.services.token_chunker import ChunkingConfig

TASK_ID = "b" * 32
REAL_NOVEL_FIXTURE = (
    Path(__file__).parents[3] / "tests" / "fixtures" / "novels" / "test_novel.txt"
)


def budget(*, max_input_tokens: int = 220) -> AnalysisBudget:
    return AnalysisBudget(
        context_window_tokens=4096,
        max_input_tokens=max_input_tokens + 512,
        output_reserve_tokens=64,
        safety_margin_tokens=512,
    )


def parse(text: str, *, max_tokens: int = 48, overlap_tokens: int = 8):
    parser = ChapterParser(
        ChunkingConfig(
            tokenizer_name="o200k_base",
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
    )
    return parser.parse(task_id=TASK_ID, filename="novel.txt", text=text)


def test_short_adjacent_chapters_are_packed_without_chunk_overlap() -> None:
    text = "".join(
        f"第{ordinal}章 测试\n第{ordinal}章唯一正文，故事继续。\n"
        for ordinal in range(1, 7)
    )
    parsed = parse(text, max_tokens=12, overlap_tokens=3)

    result = plan_analysis(parsed=parsed, source=text, budget=budget())
    combined = "\n".join(batch.content for batch in result.batches)

    assert 1 <= result.plan.batch_count < parsed.chapter_count
    assert result.plan.summary_call_count == result.plan.batch_count
    assert result.plan.planned_input_token_count <= (
        result.plan.batch_count * result.plan.budget.available_content_tokens
    )
    for ordinal in range(1, 7):
        assert combined.count(f"第{ordinal}章唯一正文") == 1
    assert all(
        batch.metadata.token_count <= result.plan.budget.available_content_tokens
        for batch in result.batches
    )


def test_oversized_chapter_is_split_into_exact_non_overlapping_parts() -> None:
    body = "".join(f"段落{index}沿着山路继续前行。" for index in range(180))
    text = f"第一章 长路\n{body}"
    parsed = parse(text, max_tokens=90, overlap_tokens=12)

    result = plan_analysis(
        parsed=parsed,
        source=text,
        budget=budget(max_input_tokens=180),
    )
    chapter_segments = [
        segment
        for segment in result.plan.segments
        if segment.chapter_id == parsed.chapters[0].chapter_id
    ]
    reconstructed_body = "".join(
        segment.content.split("\n", maxsplit=1)[1]
        for segment in result.segments
        if segment.metadata.chapter_id == parsed.chapters[0].chapter_id
    )

    assert len(chapter_segments) > 1
    assert {segment.part_count for segment in chapter_segments} == {
        len(chapter_segments)
    }
    assert [segment.part_ordinal for segment in chapter_segments] == list(
        range(1, len(chapter_segments) + 1)
    )
    assert reconstructed_body == body
    assert all(
        segment.token_count <= result.plan.budget.available_content_tokens
        for segment in chapter_segments
    )
def test_plan_ids_and_fingerprints_are_deterministic() -> None:
    text = "第一章 初见\n一场雨后，两人在山门相遇。\n第二章 同行\n二人结伴下山。\n"
    parsed = parse(text)
    limits = budget()

    first = plan_analysis(parsed=parsed, source=text, budget=limits)
    second = plan_analysis(parsed=parsed, source=text, budget=limits)

    assert first.plan == second.plan
    assert [batch.content for batch in first.batches] == [
        batch.content for batch in second.batches
    ]
    assert first.plan.estimated_total_call_count == (
        first.plan.summary_call_count + first.plan.estimated_merge_call_count
    )
    assert first.plan.estimated_total_input_tokens == (
        first.plan.planned_input_token_count
        + first.plan.estimated_merge_input_tokens
    )


def test_empty_volume_heading_is_skipped_without_creating_a_model_batch() -> None:
    text = "第一卷\n第一章 起行\n旅人从山门出发。\n第二章 夜宿\n众人在客栈落脚。\n"
    parsed = parse(text)

    result = plan_analysis(parsed=parsed, source=text, budget=budget())

    assert parsed.chapters[0].heading_kind == "volume"
    assert parsed.chapters[0].token_count == 0
    assert result.plan.skipped_empty_chapter_count == 1
    assert all(
        parsed.chapters[0].chapter_id not in batch.chapter_ids
        for batch in result.plan.batches
    )


def test_current_chunk_override_is_used_and_marked_in_plan() -> None:
    text = "第一章 修改测试\n" + "原始正文沿着山路前行。" * 30
    parsed = parse(text, max_tokens=32, overlap_tokens=6)
    replacement = "用户修正后的关键情节。"
    parsed.chunks[0].content_override = replacement
    parsed.chunks[0].token_count = 10

    result = plan_analysis(parsed=parsed, source=text, budget=budget())
    combined = "\n".join(batch.content for batch in result.batches)

    assert replacement in combined
    assert any(batch.contains_edited_content for batch in result.plan.batches)
    assert any(segment.contains_edited_content for segment in result.plan.segments)


def test_real_chinese_novel_fixture_can_be_planned() -> None:
    text = REAL_NOVEL_FIXTURE.read_text(encoding="utf-8")
    parsed = parse(text, max_tokens=256, overlap_tokens=32)

    result = plan_analysis(
        parsed=parsed,
        source=text,
        budget=budget(max_input_tokens=512),
    )

    assert parsed.chapter_count == 10
    assert parsed.token_count > 1000
    assert result.plan.batch_count > 1
    assert result.plan.segment_count >= result.plan.batch_count
    assert all(batch.content for batch in result.batches)


def test_plan_api_persists_preview_and_uses_browser_budget(
    client: TestClient,
    tmp_path: Path,
) -> None:
    text = "第一章 初见\n正文内容。\n第二章 重逢\n故事继续。\n"
    upload = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", text.encode(), "text/plain")},
    )
    task_id = upload.json()["task_id"]
    endpoint = f"/api/analyses/{task_id}/plan"

    before_parse = client.post(endpoint, json={})
    assert before_parse.status_code == 409

    client.post(f"/api/documents/{task_id}/parse")
    response = client.post(
        endpoint,
        json={
            "budget": {
                "context_window_tokens": 4096,
                "max_input_tokens": 992,
                "output_reserve_tokens": 128,
                "safety_margin_tokens": 512,
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["budget"]["available_content_tokens"] == 480
    assert payload["summary_call_count"] == payload["batch_count"]
    assert payload["estimated_total_call_count"] >= payload["batch_count"]
    assert client.get(endpoint).json() == payload
    assert (
        tmp_path / "uploads" / task_id / "analysis-plan.json"
    ).is_file()
    assert client.get("/api/analyses/config").status_code == 200

    chunk_id = client.get(f"/api/documents/{task_id}/parse").json()["chunks"][0][
        "chunk_id"
    ]
    client.patch(
        f"/api/documents/{task_id}/chunks/{chunk_id}",
        json={"content": "用户修正后的正文。"},
    )
    assert client.get(endpoint).status_code == 404


def test_plan_api_rejects_impossible_budget(client: TestClient) -> None:
    response = client.post(
        f"/api/analyses/{'f' * 32}/plan",
        json={
            "budget": {
                "context_window_tokens": 512,
                "max_input_tokens": 256,
                "output_reserve_tokens": 480,
                "safety_margin_tokens": 32,
            }
        },
    )

    assert response.status_code == 422
