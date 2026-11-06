import json
import uuid

import httpx
import pytest

from app.main import create_app
from tests.contract_support import error, validate

pytestmark = [pytest.mark.anyio, pytest.mark.controlled]


@pytest.mark.parametrize("ids,is_zip", [([2, 1], False), ([2, 3], True)])
async def test_create_and_download(client, setup, ids, is_zip):
    response = await client.post("/api/v1/works", json={"topic_ids": ids})
    assert response.status_code == 201, response.text
    work = response.json()
    validate(work, "Work")
    assert work["topic_ids"] == ids and setup[3].calls == [ids]
    assert bool(work["archive"]) == is_zip
    assert work["name"].startswith("Работа ")
    assert "SECRET" not in response.text and "/Users/" not in response.text
    first = await client.get(work["result"]["url"])
    assert first.status_code == 200
    assert (await client.get(work["result"]["url"])).content == first.content
    assert (await client.get(work["answers"]["url"])).text == "1. SECRET\n"
    sources = await client.get(work["sources"]["url"])
    validate(sources.json(), "SourcesManifest")
    assert json.loads(sources.content)["tasks"][0]["id"] == ids[0]
    assert setup[3].calls == [ids]
    if not is_zip:
        error(await client.get(f'/api/v1/works/{work["work_id"]}/files/archive'), 404, "not_found")


@pytest.mark.parametrize("body", [{"topic_ids": []}, {"topic_ids": [1, 1]}, {"topic_ids": [0]},
    {"topic_ids": [True]}, {"topic_ids": [1.0]}, {"topic_ids": ["1"]}, {"topic_ids": list(range(1, 102))},
    {"topic_ids": [1], "name": None}, {"topic_ids": [1], "name": " "},
    {"topic_ids": [1], "name": "../escape"}, {"topic_ids": [1], "name": "C:lesson"},
    {"topic_ids": [1], "name": "."}, {"topic_ids": [1], "name": "a" * 81},
    {"topic_ids": [1], "output_path": "/tmp/out.pdf"}])
async def test_invalid_creation(client, setup, body):
    response = await client.post("/api/v1/works", json=body)
    error(response, 422, "validation_error")
    if "name" in body:
        assert response.json()["error"]["fields"][0]["field"] == "name"
    assert setup[3].calls == []


async def test_protocol_and_redirect(client, setup):
    for redirects in (True, False):
        response = await client.post("/api/v1/works/", json={"topic_ids": [1]}, follow_redirects=redirects)
        error(response, 404, "not_found")
        assert not response.history and "location" not in response.headers
    error(await client.post("/api/v1/works", content="{", headers={"Content-Type": "application/json"}),
          400, "invalid_request")
    error(await client.post("/api/v1/works", content="x"), 415, "invalid_request")
    error(await client.get("/api/v1/works"), 405, "invalid_request")
    assert setup[3].calls == []


async def test_restart_missing_and_corrupt(client, setup):
    work = (await client.post("/api/v1/works", json={"topic_ids": [2, 3], "name": "  Урок  "})).json()
    other = (await client.post("/api/v1/works", json={"topic_ids": [2, 3], "name": "Урок"})).json()
    assert work["work_id"] != other["work_id"]
    app = create_app(setup[1], bank_factory=lambda: (_ for _ in ()).throw(AssertionError("No bank during GET")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as new:
        assert (await new.get(f'/api/v1/works/{work["work_id"]}')).json() == work
        folder = setup[1].storage_root / work["work_id"]
        saved = await new.get(work["result"]["url"])
        (folder / "work.answers.txt").unlink()
        error(await new.get(work["answers"]["url"], headers={"Range": "invalid"}), 404, "not_found")
        assert (await new.get(work["result"]["url"])).content == saved.content
        (folder / "work.json").write_text("{")
        error(await new.get(work["result"]["url"]), 500, "internal_error")
    error(await client.get(f"/api/v1/works/{uuid.uuid4()}"), 404, "not_found")


async def test_unpublished_and_symlinks(client, setup, tmp_path):
    ident = str(uuid.uuid4())
    folder = setup[1].storage_root / ident
    folder.mkdir(parents=True)
    (folder / "work.pdf").write_bytes(b"partial")
    error(await client.get(f"/api/v1/works/{ident}/files/pdf"), 404, "not_found")
    work = (await client.post("/api/v1/works", json={"topic_ids": [1]})).json()
    path = setup[1].storage_root / work["work_id"] / "work.pdf"
    path.unlink()
    outside = tmp_path / "secret"
    outside.write_bytes(b"PRIVATE")
    path.symlink_to(outside)
    error(await client.get(work["result"]["url"]), 404, "not_found")


async def test_export_failure_not_published(setup):
    def broken(bank, ids, path):
        from pathlib import Path
        Path(path).write_bytes(b"partial")
        raise OSError("/Users/name/private/disk")

    app = create_app(setup[1], bank_factory=lambda: setup[2], exporter=broken)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        error(await client.post("/api/v1/works", json={"topic_ids": [1]}), 500, "export_failed")
    assert not list(setup[1].storage_root.glob("*/work.json"))
