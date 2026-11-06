import pytest

from tests.contract_support import error

pytestmark = [pytest.mark.anyio, pytest.mark.controlled]


async def test_native_range_and_application_errors(client, setup):
    work = (await client.post("/api/v1/works", json={"topic_ids": [1]})).json()
    url = work["pdf"]["url"]
    full = await client.get(url)
    assert full.status_code == 200 and full.headers["content-disposition"].startswith("inline")
    single = await client.get(url, headers={"Range": "bytes=0-3"})
    assert single.status_code == 206 and single.content == full.content[:4]
    assert single.headers["content-range"].startswith("bytes 0-3/")
    multi = await client.get(url, headers={"Range": "bytes=0-3,8-11"})
    assert multi.status_code == 206 and multi.headers["content-type"].startswith("multipart/byteranges")
    assert "content-range" not in multi.headers
    for value in ("items=0-3", "bytes="):
        bad = await client.get(url, headers={"Range": value})
        assert bad.status_code == 400 and bad.headers["content-type"].startswith("text/plain")
    bad = await client.get(url, headers={"Range": "bytes=99999-"})
    assert bad.status_code == 416 and bad.content == b""
    assert bad.headers["content-range"] == f"bytes */{len(full.content)}"
    whole = await client.get(url, headers={"Range": "bytes=0-3", "If-Range": '"different"'})
    assert whole.status_code == 200 and whole.content == full.content
    many = ",".join("0-0" for _ in range(101))
    assert (await client.get(url, headers={"Range": "bytes=" + many})).status_code == 200
    error(await client.get(url + "?path=/tmp/anything"), 422, "validation_error")
    assert setup[3].calls == [[1]]
