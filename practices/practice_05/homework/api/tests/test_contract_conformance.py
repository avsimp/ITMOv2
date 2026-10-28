import pytest
from openapi_spec_validator import validate as validate_openapi

from tests.contract_support import CONTRACT, validate

pytestmark = [pytest.mark.anyio, pytest.mark.controlled]


async def test_public_routes_and_shared_openapi(client, setup):
    schema = (await client.get("/openapi.json")).json()
    validate_openapi(schema)
    assert schema["paths"] == CONTRACT["paths"] and schema["components"] == CONTRACT["components"]
    assert schema["info"]["version"] == "1.0.0"
    actual = {(route.path, method.lower()) for route in setup[0].routes for method in getattr(route, "methods", [])
              if getattr(route, "path", "").startswith("/api/v1/")}
    expected = {(path, method) for path, operations in CONTRACT["paths"].items() for method in operations}
    assert actual == expected
    work = await client.post("/api/v1/works", json={"topic_ids": [2, 3]})
    validate(work.json(), "Work")
    for kind in ("result", "pdf", "archive", "answers", "sources"):
        response = await client.get(work.json()[kind]["url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == work.json()[kind]["media_type"]
        if kind == "sources":
            validate(response.json(), "SourcesManifest")
