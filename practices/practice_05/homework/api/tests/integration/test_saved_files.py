"""REAL-LOCAL: real exporter, then real TCP/HTTP FileResponse and process restart."""
import httpx
import pytest

from app.config import Settings
from app.main import create_app
from tests.contract_support import error
from tests.server_support import free_port, server
from tests.source_fixture import install_source

pytestmark = [pytest.mark.anyio, pytest.mark.real_local]


async def test_tcp_restart_range_and_partial_download(tmp_path, monkeypatch):
    install_source(monkeypatch)
    settings = Settings(origin=f"http://127.0.0.1:{free_port()}", storage_root=tmp_path / "works")
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as local:
        work = (await local.post("/api/v1/works", json={"topic_ids": [3, 2, 1]})).json()
    # Parent network sentinel remains active, but child only reads saved data. No source can be used.
    log = tmp_path / "server.log"
    # Readiness uses Client.request for localhost, not the source-only replacement of Client.get.
    for iteration in range(2):
        with server(settings, log, offline=True):
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                metadata = await client.get(settings.origin + f'/api/v1/works/{work["work_id"]}')
                assert metadata.json() == work
                result = await client.get(work["result"]["url"])
                if iteration == 0:
                    before = result.content
                else:
                    assert result.content == before
                async with client.stream("GET", work["pdf"]["url"]) as response:
                    assert response.status_code == 200
                    async for chunk in response.aiter_bytes(chunk_size=64):
                        assert chunk
                        break
                assert (await client.get(work["pdf"]["url"])).status_code == 200
                part = await client.get(work["pdf"]["url"], headers={"Range": "bytes=0-3"})
                assert part.status_code == 206 and part.content == b"%PDF"
                if iteration == 1:
                    folder = settings.storage_root / work["work_id"]
                    (folder / "work.answers.txt").unlink()
                    error(await client.get(work["answers"]["url"], headers={"Range": "bytes="}), 404, "not_found")
                    assert (await client.get(work["sources"]["url"])).status_code == 200
