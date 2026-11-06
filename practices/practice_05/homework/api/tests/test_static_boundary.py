import pytest

from tests.contract_support import error

pytestmark = [pytest.mark.anyio, pytest.mark.controlled]


async def test_only_index_and_assets_are_served(client, setup):
    root = setup[1].ui_root
    (root / "specs").mkdir()
    (root / "specs/secret.md").write_text("not public")
    (root / "assets/escape.txt").symlink_to(root / "specs/secret.md")
    assert (await client.get("/")).status_code == 200
    assert "javascript" in (await client.get("/assets/app.js")).headers["content-type"]
    for url in ("/specs/secret.md", "/.specify/feature.json", "/var/works/", "/api/v1/unknown", "/assets/escape.txt"):
        error(await client.get(url), 404, "not_found")


async def test_static_and_reads_continue_during_export(client, setup):
    import threading
    import anyio
    started, release = threading.Event(), threading.Event()
    original = setup[0].state.work_service.exporter
    responses = []

    def slow(bank, ids, path):
        started.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release exporter")
        return original(bank, ids, path)

    async def create():
        responses.append(await client.post("/api/v1/works", json={"topic_ids": [1]}))

    setup[0].state.work_service.exporter = slow
    async with anyio.create_task_group() as group:
        group.start_soon(create)
        try:
            with anyio.fail_after(3):
                while not started.is_set():
                    await anyio.sleep(0.01)
            assert not responses
            with anyio.fail_after(1):
                assert (await client.get("/")).status_code == 200
                assert (await client.get("/assets/app.js")).status_code == 200
                assert (await client.get("/api/v1/categories?ege_number=5")).status_code == 200
        finally:
            release.set()
    assert responses[0].status_code == 201
