"""Explicit live server/site checks. Failures remain failures, never fake/skip fallbacks."""
import hashlib
import io
import json
import socket
from datetime import datetime, timezone
from uuid import uuid4
from zipfile import ZipFile

import httpx
import anyio
import pytest

from app.config import API_ROOT, Settings
from tests.contract_support import error, validate
from tests.server_support import free_port, server

pytestmark = [pytest.mark.anyio, pytest.mark.live_api]


async def test_live_http_bank_exports_and_restart():
    run = API_ROOT / "var/checks" / datetime.now(timezone.utc).strftime("live-%Y%m%d-%H%M%S-%f")
    run.mkdir(parents=True)
    settings = Settings(origin=f"http://127.0.0.1:{free_port()}", storage_root=run / "works")
    journal = {"level": "LIVE-API", "contract": "1.0.0", "source_replaced": False,
               "status": "running", "calls": [], "works": []}

    def save():
        (run / "journal.json").write_text(json.dumps(journal, ensure_ascii=False, indent=2))

    async def call(client, method, url, **kwargs):
        response = await client.request(method, url if url.startswith("http") else settings.origin + url, **kwargs)
        record = {"method": method, "url": str(response.url), "status": response.status_code,
                  "content_type": response.headers.get("content-type"),
                  "sha256": hashlib.sha256(response.content).hexdigest()}
        if response.status_code >= 400:
            record["body"] = response.text[:1000]
        journal["calls"].append(record)
        save()
        return response

    try:
        with server(settings, run / "server.log"):
            async with httpx.AsyncClient(timeout=240, trust_env=False, follow_redirects=False) as client:
                selected = []
                for number in (1, 5, 19):
                    cats = await call(client, "GET", f"/api/v1/categories?ege_number={number}")
                    assert cats.status_code == 200, cats.text
                    validate(cats.json(), "CategoryResult")
                    result = await call(client, "GET", f"/api/v1/tasks?ege_number={number}&limit=10")
                    assert result.status_code == 200, result.text
                    validate(result.json(), "SearchResult")
                    selected.append(next(task for task in result.json()["tasks"] if not task["attachments"]))
                    if result.json()["next_offset"] is not None:
                        page = await call(client, "GET", f'/api/v1/tasks?ege_number={number}&limit=10&offset={result.json()["next_offset"]}')
                        assert page.status_code == 200, page.text
                        validate(page.json(), "SearchResult")
                image_urls = [url for task in selected for url in task["images"]]
                assert image_urls
                assert (await call(client, "GET", image_urls[0])).status_code == 200
                attached = await call(client, "GET", "/api/v1/tasks?ege_number=9&limit=10")
                assert attached.status_code == 200, attached.text
                with_file = next(task for task in attached.json()["tasks"] if task["attachments"])
                assert (await call(client, "GET", with_file["attachments"][0])).status_code == 200
                for ids in ([task["id"] for task in selected], [selected[2]["id"], with_file["id"]]):
                    response = await call(client, "POST", "/api/v1/works", json={"topic_ids": ids})
                    assert response.status_code == 201, response.text
                    work = response.json()
                    validate(work, "Work")
                    assert work["topic_ids"] == ids
                    journal["works"].append(work)
                    save()
                    result = await call(client, "GET", work["result"]["url"])
                    again = await call(client, "GET", work["result"]["url"])
                    assert result.content == again.content
                    pdf = await call(client, "GET", work["pdf"]["url"])
                    sources = await call(client, "GET", work["sources"]["url"])
                    validate(sources.json(), "SourcesManifest")
                    assert sources.json()["pdf_sha256"] == hashlib.sha256(pdf.content).hexdigest()
                    answers = await call(client, "GET", work["answers"]["url"])
                    assert "19)" in answers.text and "20)" in answers.text and "21)" in answers.text
                    if work["archive"]:
                        with ZipFile(io.BytesIO(result.content)) as archive:
                            assert set(archive.namelist()) == {"work.pdf", *("work.files/" + name for name in work["attachments"])}
                            assert archive.read("work.pdf") == pdf.content
                    part = await call(client, "GET", work["pdf"]["url"], headers={"Range": "bytes=0-3"})
                    assert part.status_code == 206 and part.content == b"%PDF"
                error(await call(client, "POST", "/api/v1/works/", json={"topic_ids": [selected[0]["id"]]}),
                      404, "not_found")
                error(await call(client, "GET", "/api/v1/tasks?ege_number=0"), 422, "validation_error")
                error(await call(client, "GET", f"/api/v1/works/{uuid4()}"), 404, "not_found")
        # Same origin/storage, real process restart. No upstream needed or reachable in this child.
        with server(settings, run / "server.log", offline=True):
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                for work in journal["works"]:
                    response = await call(client, "GET", f'/api/v1/works/{work["work_id"]}')
                    assert response.json() == work
                    for kind in ("result", "pdf", "answers", "sources"):
                        assert (await call(client, "GET", work[kind]["url"])).status_code == 200
                work = journal["works"][-1]
                (settings.storage_root / work["work_id"] / "work.answers.txt").unlink()
                error(await call(client, "GET", work["answers"]["url"]), 404, "not_found")
                assert (await call(client, "GET", work["sources"]["url"])).status_code == 200
        journal["status"] = "passed"
    except BaseException as exc:
        journal["status"] = "failed"
        journal["failure"] = str(exc)
        raise
    finally:
        save()
        print(f"LIVE-API journal: {run / 'journal.json'}")


async def test_live_client_disconnect_does_not_cancel_publication():
    run = API_ROOT / "var/checks" / datetime.now(timezone.utc).strftime("disconnect-%Y%m%d-%H%M%S-%f")
    run.mkdir(parents=True)
    port = free_port()
    settings = Settings(origin=f"http://127.0.0.1:{port}", storage_root=run / "works")
    record = {"level": "LIVE-API", "source_replaced": False, "status": "running"}
    try:
        with server(settings, run / "server.log"):
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                response = await client.get(settings.origin + "/api/v1/tasks?ege_number=5&limit=1")
                assert response.status_code == 200, response.text
                ids = [response.json()["tasks"][0]["id"]]
            body = json.dumps({"topic_ids": ids}).encode()
            request = (f"POST /api/v1/works HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                       f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body
            with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
                connection.sendall(request)
                with anyio.fail_after(30):
                    while not list(settings.storage_root.glob("*")):
                        await anyio.sleep(0.005)
                # Private filesystem observation is test instrumentation, not a recovery API.
                folder = next(settings.storage_root.iterdir())
                assert not (folder / "work.json").exists()
            with anyio.fail_after(90):
                while not (folder / "work.json").exists():
                    await anyio.sleep(0.03)
            record.update(status="passed", topic_ids=ids, observed_work_id=folder.name,
                          test_observation="private storage marker; no client response/recovery endpoint")
    except BaseException as exc:
        record.update(status="failed", failure=str(exc))
        raise
    finally:
        (run / "journal.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        print(f"LIVE disconnect journal: {run / 'journal.json'}")
