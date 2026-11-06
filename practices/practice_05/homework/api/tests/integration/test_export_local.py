"""REAL-LOCAL: real HTTP handlers, Bank, parser, Chromium and export_pdf.

Only upstream HTTP is replaced; no claim about the live source or delivered UI.
"""
import hashlib
import io
import re
from urllib.parse import unquote
from zipfile import ZipFile

import httpx
import pymupdf
import pytest

from app.config import Settings
from app.main import create_app
from tests.contract_support import error, validate
from tests.source_fixture import install_source

pytestmark = [pytest.mark.anyio, pytest.mark.real_local]


@pytest.mark.parametrize("size", [1, 3, 100])
async def test_real_bank_export_pdf_zip_order_and_transfer(tmp_path, monkeypatch, size):
    calls = install_source(monkeypatch)
    settings = Settings(storage_root=tmp_path / "works", ui_root=tmp_path / "ui")
    app = create_app(settings)
    ids = list(range(size, 0, -1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as client:
        cats = await client.get("/api/v1/categories?ege_number=20")
        validate(cats.json(), "CategoryResult")
        assert cats.json()["ege_number"] == 19
        found = (await client.get("/api/v1/tasks?ege_number=5&limit=1")).json()
        validate(found, "SearchResult")
        assert found["total"] == 99 and found["next_offset"] == 1
        next_page = (await client.get("/api/v1/tasks?ege_number=5&limit=1&offset=1")).json()
        assert next_page["tasks"][0]["id"] == 3
        filtered = (await client.get("/api/v1/tasks?ege_number=5&contains=task-&exclude_ids=1&limit=1")).json()
        assert filtered["total"] == 98 and filtered["tasks"][0]["id"] == 3
        image = await client.get(found["tasks"][0]["images"][0])
        assert image.status_code == 200
        error(await client.get("/api/v1/tasks?ege_number=5&category_ids=999"), 422, "validation_error")
        response = await client.post("/api/v1/works", json={"topic_ids": ids, "name": "НЕ ПЕЧАТАТЬ ЗАГОЛОВОК"})
        assert response.status_code == 201, response.text
        work = response.json()
        validate(work, "Work")
        assert work["topic_ids"] == ids and work["count"] == size
        pdf = await client.get(work["pdf"]["url"])
        answers = await client.get(work["answers"]["url"])
        sources_response = await client.get(work["sources"]["url"])
        manifest = sources_response.json()
        validate(manifest, "SourcesManifest")
        assert [t["id"] for t in manifest["tasks"]] == ids
        assert manifest["pdf_sha256"] == hashlib.sha256(pdf.content).hexdigest()
        before_download_calls = len(calls)
        assert (await client.get(work["pdf"]["url"])).content == pdf.content
        assert len(calls) == before_download_calls
        with pymupdf.open(stream=pdf.content, filetype="pdf") as document:
            text = "\n".join(page.get_text() for page in document)
            assert document[0].rect.width == pytest.approx(595, abs=1)
            positions = [text.index(f"TASK-{ident:03d}") for ident in ids]
            assert positions == sorted(positions)
            assert all(re.search(rf"\b{position}\)", text) for position in range(1, size + 1))
            assert "SECRET_" not in text and "НЕ ПЕЧАТАТЬ" not in text
            if 2 in ids:
                assert "Вопрос 3." in text
                assert f"{ids.index(2) + 1}. 19) 41; 20) 36 40; 21) 35" in answers.text
        result = await client.get(work["result"]["url"])
        assert (await client.get(work["result"]["url"])).content == result.content
        if 3 in ids:
            number = ids.index(3) + 1
            assert work["attachments"] == [f"{number}.ods"]
            assert manifest["attachment_map"][0]["task_number"] == number
            assert manifest["tasks"][ids.index(3)]["attachments"][0].startswith("https://kpolyakov.spb.ru/")
            destination = tmp_path / "elsewhere"
            with ZipFile(io.BytesIO(result.content)) as archive:
                assert set(archive.namelist()) == {"work.pdf", f"work.files/{number}.ods"}
                archive.extractall(destination)
                assert archive.read("work.pdf") == pdf.content
            with pymupdf.open(destination / "work.pdf") as document:
                links = [link for page in document for link in page.get_links()]
            assert links
            for link in links:
                target = unquote(link["file"])
                assert target == f"work.files/{number}.ods"
                assert (destination / target).read_bytes() == b"PK\x00fixture-ods"
        else:
            assert work["archive"] is None and result.content == pdf.content
        # Fresh application, no bank allowed: known downloads are disk-only.
        app2 = create_app(settings, bank_factory=lambda: (_ for _ in ()).throw(AssertionError("No source during GET")))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url=settings.origin) as restarted:
            assert (await restarted.get(f'/api/v1/works/{work["work_id"]}')).json() == work
            assert (await restarted.get(work["sources"]["url"])).content == sources_response.content
            assert (await restarted.get(work["result"]["url"])).content == result.content


async def test_real_parser_failure_is_not_a_partial_work(tmp_path, monkeypatch):
    install_source(monkeypatch)
    settings = Settings(storage_root=tmp_path / "works")
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as client:
        error(await client.post("/api/v1/works", json={"topic_ids": [1, 999]}), 502, "source_error")
    assert not list(settings.storage_root.glob("*/work.json"))


async def test_incomplete_game_is_source_error_before_pdf(tmp_path, monkeypatch):
    import json
    from tests.source_fixture import page, statement
    html = page([2], 19).replace(json.dumps(statement(2)), json.dumps("Вопрос 1. А<br>Вопрос 2. Б"))
    monkeypatch.setattr(httpx.Client, "get", lambda client, url: httpx.Response(
        200, text=html, request=httpx.Request("GET", url)))
    settings = Settings(storage_root=tmp_path / "works")
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as client:
        error(await client.post("/api/v1/works", json={"topic_ids": [2]}), 502, "source_error")
    assert not list(settings.storage_root.glob("*/work.json"))
    assert not list(settings.storage_root.glob("*/work.pdf"))
