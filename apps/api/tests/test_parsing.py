"""Regression tests for chapter recognition, chunking, and parse endpoints."""

import pytest
from fastapi.testclient import TestClient

from novelatlas.services.chapter_parser import ChapterParser
from novelatlas.services.token_chunker import ChunkingConfig

TASK_ID = "a" * 32


def make_parser(*, max_tokens: int = 24, overlap_tokens: int = 4) -> ChapterParser:
    return ChapterParser(
        ChunkingConfig(
            tokenizer_name="o200k_base",
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
    )


def test_recognizes_common_headings_and_preserves_exact_ranges() -> None:
    text = (
        "作品说明\n这是一段卷首文字。\n"
        "正文 第十二章 雨夜来客\n风吹过长街，来客推门而入。\n"
        "卷二 山河远阔\n第二卷的故事由此开始。\n"
        "尾声\n所有人终于回到了故乡。\n"
    )

    result = make_parser().parse(task_id=TASK_ID, filename="novel.txt", text=text)

    assert [chapter.title for chapter in result.chapters] == [
        "卷首",
        "正文 第十二章 雨夜来客",
        "卷二 山河远阔",
        "尾声",
    ]
    assert [chapter.heading_kind for chapter in result.chapters] == [
        "special",
        "chapter",
        "volume",
        "special",
    ]
    assert result.used_fallback_chapter is False
    assert result.chapter_count == 4

    for chapter in result.chapters:
        assert chapter.character_count == (
            chapter.content_end_char - chapter.content_start_char
        )
        assert all(chunk_id.startswith("chunk_") for chunk_id in chapter.chunk_ids)

    for chunk in result.chunks:
        reference = chunk.reference
        source_slice = text[reference.start_char : reference.end_char]
        assert source_slice
        assert reference.preview
        assert reference.citation_id.startswith("cite_")
        assert chunk.token_count <= 24


@pytest.mark.parametrize(
    "title, expected_kind",
    [
        ("第一百二十章 风雪", "chapter"),
        ("第１２回 故人", "chapter"),
        ("正文 第3节 夜谈", "chapter"),
        ("第三卷", "volume"),
        ("下卷 归途", "volume"),
        ("番外 灯会", "special"),
    ],
)
def test_supports_common_heading_number_styles(
    title: str,
    expected_kind: str,
) -> None:
    text = f"{title}\n正文内容。"

    result = make_parser().parse(task_id=TASK_ID, filename="novel.txt", text=text)

    assert result.chapter_count == 1
    assert result.chapters[0].title == title
    assert result.chapters[0].heading_kind == expected_kind
    assert result.used_fallback_chapter is False


def test_parse_is_deterministic_and_chunk_windows_overlap() -> None:
    text = "第一章 长路\n" + "山河辽阔，旅人继续向前。" * 40
    parser = make_parser(max_tokens=18, overlap_tokens=5)

    first = parser.parse(task_id=TASK_ID, filename="novel.txt", text=text)
    second = parser.parse(task_id=TASK_ID, filename="novel.txt", text=text)

    assert first == second
    assert first.chunk_count > 1
    for previous, current in zip(first.chunks, first.chunks[1:], strict=False):
        assert current.reference.start_char < previous.reference.end_char
        assert current.reference.end_char > previous.reference.end_char
        assert 0 < current.overlap_with_previous_tokens <= 5


def test_text_without_headings_uses_one_fallback_chapter() -> None:
    text = "这是第一章里的故事，但这一行并不是章节标题。\n故事仍在继续。"

    result = make_parser().parse(task_id=TASK_ID, filename="plain.txt", text=text)

    assert result.used_fallback_chapter is True
    assert result.chapter_count == 1
    assert result.chapters[0].title == "全文"
    assert result.chapters[0].content_start_char == 0
    assert result.chapters[0].content_end_char == len(text)
    assert result.chunks[0].reference.start_char == 0


def test_parse_api_persists_preview_manifest(client: TestClient, tmp_path) -> None:
    text = "第一章 初见\n这是小说正文。\n第二章 重逢\n故事继续。\n"
    upload = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", text.encode(), "text/plain")},
    )
    task_id = upload.json()["task_id"]

    assert client.get(f"/api/documents/{task_id}/parse").status_code == 404

    response = client.post(f"/api/documents/{task_id}/parse")
    assert response.status_code == 200
    parsed = response.json()
    assert parsed["chapter_count"] == 2
    assert [chapter["title"] for chapter in parsed["chapters"]] == [
        "第一章 初见",
        "第二章 重逢",
    ]
    assert parsed["tokenizer"] == "o200k_base"
    assert (tmp_path / "uploads" / task_id / "parse-result.json").is_file()

    stored = client.get(f"/api/documents/{task_id}/parse")
    assert stored.status_code == 200
    assert stored.json() == parsed


def test_chunk_content_can_be_loaded_and_edited_without_changing_source(
    client: TestClient,
) -> None:
    text = "第一章 初见\n这是未经修改的小说正文。\n"
    upload = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", text.encode(), "text/plain")},
    )
    task_id = upload.json()["task_id"]
    parsed = client.post(f"/api/documents/{task_id}/parse").json()
    chunk_id = parsed["chunks"][0]["chunk_id"]
    source_path = client.app.state.upload_storage.source_path(task_id)

    detail = client.get(f"/api/documents/{task_id}/chunks/{chunk_id}")
    assert detail.status_code == 200
    assert detail.json()["content"] == "这是未经修改的小说正文。\n"
    assert detail.json()["original_content"] == detail.json()["content"]
    assert detail.json()["is_edited"] is False

    updated = client.patch(
        f"/api/documents/{task_id}/chunks/{chunk_id}",
        json={"content": "这是用户修正后的正文。\n"},
    )
    assert updated.status_code == 200
    updated_chunk = updated.json()["chunks"][0]
    assert updated_chunk["content_override"] == "这是用户修正后的正文。\n"
    assert updated_chunk["token_count"] > 0
    assert source_path.read_text(encoding="utf-8") == text

    edited_detail = client.get(f"/api/documents/{task_id}/chunks/{chunk_id}")
    assert edited_detail.json()["content"] == "这是用户修正后的正文。\n"
    assert edited_detail.json()["original_content"] == "这是未经修改的小说正文。\n"
    assert edited_detail.json()["is_edited"] is True
    assert client.get(f"/api/documents/{task_id}/parse").json() == updated.json()

    restored = client.patch(
        f"/api/documents/{task_id}/chunks/{chunk_id}",
        json={"content": "这是未经修改的小说正文。\n"},
    )
    assert restored.status_code == 200
    assert restored.json()["chunks"][0]["content_override"] is None

    client.patch(
        f"/api/documents/{task_id}/chunks/{chunk_id}",
        json={"content": "再次修改，随后重新解析。\n"},
    )
    reparsed = client.post(f"/api/documents/{task_id}/parse").json()
    assert reparsed["chunks"][0]["content_override"] is None


def test_chunk_edit_rejects_whitespace_and_token_overflow(client: TestClient) -> None:
    upload = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", "正文内容。".encode(), "text/plain")},
    )
    task_id = upload.json()["task_id"]
    parsed = client.post(f"/api/documents/{task_id}/parse").json()
    chunk_id = parsed["chunks"][0]["chunk_id"]
    endpoint = f"/api/documents/{task_id}/chunks/{chunk_id}"

    whitespace = client.patch(endpoint, json={"content": " \n\t"})
    assert whitespace.status_code == 422

    overflow = client.patch(endpoint, json={"content": "天地" * 7000})
    assert overflow.status_code == 422
    assert "不能超过 6000 Token" in overflow.json()["detail"]


def test_chunks_can_be_deleted_and_reparse_restores_them(client: TestClient) -> None:
    text = "第一章 初见\n第一段正文。\n第二章 重逢\n第二段正文。\n"
    upload = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", text.encode(), "text/plain")},
    )
    task_id = upload.json()["task_id"]
    parsed = client.post(f"/api/documents/{task_id}/parse").json()
    chunk_ids = [chunk["chunk_id"] for chunk in parsed["chunks"]]

    first_delete = client.delete(
        f"/api/documents/{task_id}/chunks/{chunk_ids[0]}"
    )
    assert first_delete.status_code == 200
    assert first_delete.json()["chunk_count"] == 1
    assert chunk_ids[0] not in first_delete.json()["chapters"][0]["chunk_ids"]
    assert (
        client.get(f"/api/documents/{task_id}/chunks/{chunk_ids[0]}").status_code
        == 404
    )

    last_delete = client.delete(
        f"/api/documents/{task_id}/chunks/{chunk_ids[1]}"
    )
    assert last_delete.status_code == 200
    assert last_delete.json()["chunk_count"] == 0
    assert client.get(f"/api/documents/{task_id}/parse").json()["chunks"] == []
    assert client.app.state.upload_storage.source_path(task_id).read_text(
        encoding="utf-8"
    ) == text

    reparsed = client.post(f"/api/documents/{task_id}/parse").json()
    assert reparsed["chunk_count"] == 2
    assert [chunk["chunk_id"] for chunk in reparsed["chunks"]] == chunk_ids


def test_parse_api_returns_missing_upload(client: TestClient) -> None:
    response = client.post(f"/api/documents/{'f' * 32}/parse")

    assert response.status_code == 404
    assert response.json()["detail"] == "上传任务不存在或已过期"
