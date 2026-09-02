"""Integration tests for TXT upload and temporary cleanup."""

from datetime import timedelta

from fastapi.testclient import TestClient


def test_upload_constraints_match_runtime_settings(client: TestClient) -> None:
    response = client.get("/api/uploads/config")

    assert response.status_code == 200
    assert response.json() == {
        "max_upload_bytes": 1024,
        "upload_ttl_seconds": 3600,
        "accepted_extensions": [".txt"],
    }


def test_upload_utf8_read_metadata_and_delete(
    client: TestClient,
    tmp_path,
) -> None:
    content = "第一章 初见\r\n这是小说正文。\r\n"

    response = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", content.encode(), "text/plain")},
    )

    assert response.status_code == 201
    metadata = response.json()
    task_id = metadata["task_id"]
    assert metadata["filename"] == "novel.txt"
    assert metadata["detected_encoding"] == "utf-8"
    assert metadata["character_count"] == len(content.replace("\r\n", "\n"))

    task_directory = tmp_path / "uploads" / task_id
    assert (task_directory / "source.txt").read_text(encoding="utf-8") == (
        "第一章 初见\n这是小说正文。\n"
    )
    assert not (task_directory / "upload.raw").exists()

    get_response = client.get(f"/api/uploads/{task_id}")
    assert get_response.status_code == 200
    assert get_response.json() == metadata

    delete_response = client.delete(f"/api/uploads/{task_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"task_id": task_id, "deleted": True}
    assert not task_directory.exists()
    assert client.get(f"/api/uploads/{task_id}").status_code == 404


def test_upload_detects_gb18030(client: TestClient) -> None:
    content = "第一回 风起云涌\n江湖故事从这里开始。"

    response = client.post(
        "/api/uploads",
        files={"file": ("武侠小说.TXT", content.encode("gb18030"), "text/plain")},
    )

    assert response.status_code == 201
    assert response.json()["detected_encoding"] == "gb18030"
    task_id = response.json()["task_id"]
    assert client.app.state.upload_storage.source_path(task_id).read_text(
        encoding="utf-8"
    ) == content


def test_upload_rejects_wrong_extension(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        files={"file": ("novel.pdf", b"plain text", "application/pdf")},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "仅支持 .txt 文件"


def test_upload_rejects_non_text_content_type(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", b"plain text", "application/pdf")},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "文件内容类型必须为纯文本"


def test_upload_rejects_empty_file(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "TXT 文件为空"
    assert list(client.app.state.upload_storage.root.iterdir()) == []


def test_upload_rejects_whitespace_only_text(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        files={"file": ("empty.txt", b" \n\t", "text/plain")},
    )

    assert response.status_code == 422
    assert list(client.app.state.upload_storage.root.iterdir()) == []


def test_upload_rejects_oversized_file_and_removes_partial_data(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/uploads",
        files={"file": ("large.txt", b"a" * 1025, "text/plain")},
    )

    assert response.status_code == 413
    assert list(client.app.state.upload_storage.root.iterdir()) == []


def test_expired_upload_is_removed(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        files={"file": ("novel.txt", "正文".encode(), "text/plain")},
    )
    metadata = response.json()
    expires_at = client.app.state.upload_storage.get(
        metadata["task_id"]
    ).expires_at

    deleted = client.app.state.upload_storage.cleanup_expired(
        now=expires_at + timedelta(seconds=1)
    )

    assert deleted == 1
    assert client.get(f"/api/uploads/{metadata['task_id']}").status_code == 404
