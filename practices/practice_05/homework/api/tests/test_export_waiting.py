import threading

import anyio
import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.controlled]


async def test_waiting_serialization_reads_and_cancellation(client, setup):
    work = (await client.post("/api/v1/works", json={"topic_ids": [1]})).json()
    service = setup[0].state.work_service
    original = service.exporter
    started, release = threading.Event(), threading.Event()
    state = {"running": 0, "max": 0, "scopes": [], "responses": []}

    def slow(bank, ids, path):
        state["running"] += 1
        state["max"] = max(state["max"], state["running"])
        started.set()
        try:
            if not release.wait(5):
                raise TimeoutError("Test release not signalled")
            return original(bank, ids, path)
        finally:
            state["running"] -= 1

    service.exporter = slow

    async def request():
        with anyio.CancelScope() as scope:
            state["scopes"].append(scope)
            state["responses"].append(await client.post("/api/v1/works", json={"topic_ids": [2]}))

    async with anyio.create_task_group() as group:
        group.start_soon(request)
        with anyio.fail_after(3):
            while not started.is_set():
                await anyio.sleep(0.01)
        assert not state["responses"]
        with anyio.fail_after(1):
            assert (await client.get(work["result"]["url"])).status_code == 200
            assert (await client.get(f'/api/v1/works/{work["work_id"]}')).status_code == 200
        group.start_soon(request)
        await anyio.sleep(0.03)
        state["scopes"][0].cancel()
        release.set()
    assert state["max"] == 1
    assert len(list(setup[1].storage_root.glob("*/work.json"))) == 3
    assert len(original.calls) == 3


async def test_conflict_and_incomplete_export(client, setup):
    from app.main import create_app
    from render import OutputConflictError
    import httpx
    from tests.contract_support import error

    for exporter, code, status in (
        (lambda *args: (_ for _ in ()).throw(OutputConflictError("conflict")), "output_conflict", 409),
        (lambda bank, ids, path: {"count": len(ids), "attachments": [], "archive": None}, "export_failed", 500),
    ):
        app = create_app(setup[1], bank_factory=lambda: setup[2], exporter=exporter)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as other:
            error(await other.post("/api/v1/works", json={"topic_ids": [1]}), status, code)
    assert not list(setup[1].storage_root.glob("*/work.json"))
