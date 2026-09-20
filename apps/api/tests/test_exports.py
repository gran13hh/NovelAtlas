"""Stage 7 export and complete Mock workflow regression tests."""

import time
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from novelatlas.services.outline_export import safe_export_filename


def _source() -> dict:
    return {
        "input_ids": ["batch_aaaaaaaaaaaaaaaa"],
        "batch_ids": ["batch_aaaaaaaaaaaaaaaa"],
        "chapter_ids": ["chapter_aaaaaaaaaaaaaaaa"],
    }


def _outline(*, summary: str = "少年离开故乡，踏上寻找真相的旅程。") -> dict:
    source = _source()
    return {
        "overall_summary": summary,
        "chapter_outline": [
            {
                "chapter_range": "第一章至第二章",
                "summary": "少年收到来信后作出远行决定。",
                "key_events": ["收到密信", "离开故乡"],
                "sources": source,
            }
        ],
        "storylines": [
            {
                "name": "远行主线",
                "summary": "主人公追查旧案。",
                "developments": ["发现线索"],
                "sources": source,
            }
        ],
        "characters": [
            {
                "name": "林舟",
                "summary": "谨慎而坚定的主人公。",
                "relationships": ["与顾先生亦师亦友"],
                "changes": ["从迟疑转为主动"],
                "sources": source,
                "confidence": "certain",
            }
        ],
        "worldbuilding": [
            {
                "category": "location",
                "name": "停云山",
                "description": "位于神洲西陲的山门。",
                "sources": source,
                "confidence": "certain",
            }
        ],
        "foreshadowing": [
            {
                "description": "旧信可能指向失踪真相。",
                "sources": source,
                "confidence": "likely",
            }
        ],
        "unresolved_items": [],
        "conflicts_and_uncertainties": [],
    }


def test_html_export_is_self_contained_escaped_and_selective(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/exports/outline",
        json={
            "title": "../../<危险>.txt",
            "format": "html",
            "sections": ["overall_summary"],
            "outline": _outline(summary='<script>alert("x")</script>'),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert "../" not in response.headers["content-disposition"]
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "远行主线" not in response.text
    assert "<style>" in response.text


def test_docx_export_contains_real_headings_toc_and_selected_content(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/exports/outline",
        json={
            "title": "停云山.txt",
            "format": "docx",
            "sections": ["overall_summary", "characters"],
            "outline": _outline(),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        document_xml = archive.read("word/document.xml").decode()
        settings_xml = archive.read("word/settings.xml").decode()
        styles_xml = archive.read("word/styles.xml").decode()
    assert "停云山.txt" in document_xml
    assert "少年离开故乡" in document_xml
    assert "林舟" in document_xml
    assert "停云山</w:t>" not in document_xml
    assert "TOC" in document_xml
    assert "updateFields" in settings_xml
    assert "Heading1" in styles_xml


def test_export_rejects_empty_or_duplicate_section_selection(
    client: TestClient,
) -> None:
    empty = client.post(
        "/api/exports/outline",
        json={
            "title": "小说.txt",
            "format": "html",
            "sections": [],
            "outline": _outline(),
        },
    )
    duplicate = client.post(
        "/api/exports/outline",
        json={
            "title": "小说.txt",
            "format": "html",
            "sections": ["overall_summary", "overall_summary"],
            "outline": _outline(),
        },
    )

    assert empty.status_code == 422
    assert duplicate.status_code == 422


def test_safe_export_filename_removes_paths_controls_and_txt_suffix() -> None:
    assert safe_export_filename("../../山海:卷?.TXT", "docx") == "山海_卷-全书细纲.docx"
    assert safe_export_filename("\x00/../", "html") == "NovelAtlas-全书细纲.html"


def test_upload_to_mock_outline_to_html_export_is_a_complete_flow(
    client: TestClient,
) -> None:
    text = (
        "第一章 初见\n林舟在停云山收到顾先生的密信。\n"
        "第二章 远行\n林舟决定下山追查旧案。\n"
    )
    upload = client.post(
        "/api/uploads",
        files={"file": ("完整流程.txt", text.encode(), "text/plain")},
    )
    assert upload.status_code == 201
    task_id = upload.json()["task_id"]
    assert client.post(f"/api/documents/{task_id}/parse").status_code == 200
    plan = client.post(
        f"/api/analyses/{task_id}/plan",
        json={
            "budget": {
                "context_window_tokens": 4096,
                "max_input_tokens": 1328,
                "output_reserve_tokens": 64,
                "safety_margin_tokens": 1200,
            }
        },
    )
    assert plan.status_code == 200
    assert client.post(f"/api/analyses/{task_id}/run", json={}).status_code == 202

    for _attempt in range(300):
        manifest = client.get(f"/api/analyses/{task_id}/run").json()
        if manifest["status"] in {"completed", "failed", "interrupted"}:
            break
        time.sleep(0.01)
    assert manifest["status"] == "completed"
    outline = client.get(f"/api/analyses/{task_id}/outline")
    assert outline.status_code == 200

    exported = client.post(
        "/api/exports/outline",
        json={
            "title": upload.json()["filename"],
            "format": "html",
            "sections": ["overall_summary", "chapter_outline"],
            "outline": outline.json()["outline"],
        },
    )
    assert exported.status_code == 200
    assert "全书细纲" in exported.text
    assert client.delete(f"/api/uploads/{task_id}").status_code == 200
    assert not (client.app.state.upload_storage.root / task_id).exists()
