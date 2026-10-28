"""Six actual HTTP operations; only raw upstream HTTP is fixed in this level."""
import pytest
from conftest import add, search
from contract_support import validate
from test_ui import create

pytestmark = pytest.mark.real_local


def test_six_real_api_operations(page, api_server, journal):
    page.goto(api_server.origin)
    categories = page.request.get(api_server.origin + "/api/v1/categories?ege_number=19")
    assert categories.status == 200
    validate(categories.json(), "CategoryResult")
    search(page)
    root = page.request.get(api_server.origin + "/api/v1/tasks?ege_number=5&offset=0&limit=10")
    found = validate(root.json(), "SearchResult")
    image = page.request.get(found["tasks"][0]["images"][0])
    assert image.status == 200 and image.headers["content-type"] == "image/png"
    add(page, 1)
    work = create(page, journal)
    metadata = page.request.get(api_server.origin + "/api/v1/works/" + work["work_id"])
    assert metadata.status == 200
    assert validate(metadata.json(), "Work") == work
    for kind in ["result", "pdf", "answers", "sources"]:
        response = page.request.get(work[kind]["url"])
        assert response.status == 200
        assert response.headers["content-type"].split(";")[0] == work[kind]["media_type"].split(";")[0]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "work." in response.headers["content-disposition"]
        if kind == "sources":
            validate(response.json(), "SourcesManifest")
    invalid = page.request.get(api_server.origin + "/api/v1/tasks?ege_number=0")
    assert invalid.status == 422
    validate(invalid.json(), "ErrorResponse")
