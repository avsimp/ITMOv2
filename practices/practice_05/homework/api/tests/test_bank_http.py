import copy

import httpx
import pytest

from tests.contract_support import error, validate

pytestmark = [pytest.mark.anyio, pytest.mark.controlled]


@pytest.mark.parametrize("number,canonical", [(1, 1), (19, 19), (20, 19), (21, 19), (27, 27)])
async def test_categories(client, number, canonical):
    response = await client.get("/api/v1/categories", params={"ege_number": number})
    assert response.status_code == 200
    validate(response.json(), "CategoryResult")
    assert response.json()["ege_number"] == canonical


async def test_search_pages_and_projection(client, setup):
    original = copy.deepcopy(setup[2].items)
    result = (await client.get("/api/v1/tasks?ege_number=5&limit=1")).json()
    validate(result, "SearchResult")
    assert result["total"] == 3 and result["next_offset"] == 1
    first = result["tasks"][0]
    assert "answer" not in first and "answer_html" not in first
    assert first["images"][0] in first["statement_html"]
    image = await client.get(first["images"][0])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"
    page = (await client.get("/api/v1/tasks?ege_number=5&offset=1&limit=1")).json()
    assert page["tasks"][0]["ege_numbers"] == [19, 20, 21]
    empty = (await client.get("/api/v1/tasks?ege_number=5&offset=99")).json()
    assert empty["tasks"] == [] and empty["next_offset"] is None and empty["total"] == 3
    assert setup[2].items == original


@pytest.mark.parametrize("query", ["ege_number=0", "ege_number=28", "ege_number=true", "ege_number=5.0",
    "ege_number=5&category_ids=", "ege_number=5&category_ids=99", "ege_number=5&offset=-1",
    "ege_number=5&limit=0", "ege_number=5&limit=31", "ege_number=5&other=x",
    "ege_number=5&limit=1&limit=2", "ege_number=5&exclude_ids=0"])
async def test_bad_search_inputs(client, query):
    error(await client.get("/api/v1/tasks?" + query), 422, "validation_error")


async def test_source_failures(client, setup):
    from app.bank_adapter import SourceError
    setup[2].failure = SourceError("Sensitive /Users/name/source")
    error(await client.get("/api/v1/categories?ege_number=5"), 502, "source_error")
    problem = SourceError("Timed out")
    problem.__cause__ = httpx.ReadTimeout("timeout")
    setup[2].failure = problem
    error(await client.get("/api/v1/categories?ege_number=5"), 504, "source_timeout")


async def test_filters_and_resources(client, setup):
    result = (await client.get("/api/v1/tasks?ege_number=5&contains=УСЛОВИЕ&exclude_ids=1&exclude_ids=1")).json()
    assert result["total"] == 0
    page = (await client.get("/api/v1/tasks?ege_number=5")).json()
    attachment = await client.get(page["tasks"][2]["attachments"][0])
    assert attachment.content == b"original-ods\x00"
    assert attachment.headers["content-disposition"].startswith("attachment;")
    count = len(setup[2].requests)
    error(await client.get("/api/v1/tasks/1/resources/image?url=https://example.com/x"), 404, "not_found")
    assert len(setup[2].requests) == count
    error(await client.get("/api/v1/tasks/999/resources/image?url=https://example.com/x"), 502, "source_error")
