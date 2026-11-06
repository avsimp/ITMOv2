"""First red check before the HTTP application is implemented."""
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.controlled
async def test_exact_post_path_and_storage_boundary(tmp_path):
    import httpx
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(storage_root=tmp_path / "works", ui_root=tmp_path / "ui"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        response = await client.post("/api/v1/works/", json={"topic_ids": [1]})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert not response.headers.get("location")
        assert not (tmp_path / "works").exists()


@pytest.mark.anyio
@pytest.mark.controlled
async def test_missing_ui_is_not_a_server_error(tmp_path):
    import httpx
    from app.config import Settings
    from app.main import create_app
    app = create_app(Settings(storage_root=tmp_path / "works", ui_root=tmp_path / "not-delivered-ui"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                base_url="http://127.0.0.1:8000") as client:
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/assets/app.js")).status_code == 404
        assert (await client.get("/api/v1/works/not-a-uuid")).status_code == 422
