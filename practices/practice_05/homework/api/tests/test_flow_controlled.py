"""CONTROLLED full HTTP journey; neither PDF rendering nor source is real here."""
import pytest

from app.bank_adapter import SourceError
from tests.contract_support import error, validate

pytestmark = [pytest.mark.anyio, pytest.mark.controlled]


async def test_controlled_journey_and_preserved_previous_work(client, setup):
    categories = await client.get("/api/v1/categories?ege_number=5")
    validate(categories.json(), "CategoryResult")
    page = await client.get("/api/v1/tasks?ege_number=5&limit=3")
    validate(page.json(), "SearchResult")
    tasks = page.json()["tasks"]
    for ids in ([tasks[1]["id"], tasks[0]["id"]], [tasks[1]["id"], tasks[2]["id"]]):
        response = await client.post("/api/v1/works", json={"topic_ids": ids})
        assert response.status_code == 201
        work = response.json()
        validate(work, "Work")
        assert work["topic_ids"] == ids
        for kind in ("result", "pdf", "answers", "sources"):
            assert (await client.get(work[kind]["url"])).status_code == 200
    before = (await client.get(work["result"]["url"])).content
    setup[2].failure = SourceError("controlled upstream refusal")
    error(await client.get("/api/v1/categories?ege_number=5"), 502, "source_error")
    error(await client.post("/api/v1/works", json={"topic_ids": [1]}), 502, "source_error")
    assert (await client.get(work["result"]["url"])).content == before
    assert len(setup[3].calls) == 3  # two creations, one failed explicit attempt; downloads add none
