import httpx
import pytest

from tests.conftest import IMAGE
from tests.contract_support import error

pytestmark = [pytest.mark.anyio, pytest.mark.controlled]


async def test_browser_allowlist_and_original_isolation(client, setup):
    original = ('<div class="lmar evil"><script>alert(1)</script><table border="1"><tr>'
                '<td colspan="2" onclick="bad()">2<sup>3</sup></td></tr></table>'
                f'<img class="in" onerror="bad()" src="{IMAGE}"></div>')
    setup[2].items[1]["statement_html"] = original
    item = (await client.get("/api/v1/tasks?ege_number=5")).json()["tasks"][0]
    html = item["statement_html"]
    assert "onclick" not in html and "onerror" not in html and "script" not in html and "evil" not in html
    assert 'colspan="2"' in html and '<sup>3</sup>' in html and 'class="in"' in html and 'class="lmar"' in html
    assert setup[2].items[1]["statement_html"] == original
    setup[2].items[1]["statement_html"] = "<math>essential notation</math>"
    error(await client.get("/api/v1/tasks?ege_number=5"), 502, "source_error")
    setup[2].items[1]["statement_html"] = "<form><p>Essential statement text</p></form>"
    error(await client.get("/api/v1/tasks?ege_number=5"), 502, "source_error")


async def test_image_mime_and_svg_headers(client, setup):
    url = "/api/v1/tasks/1/resources/image"
    setup[2].fetch = lambda _: httpx.Response(200, text="<html>wrong</html>", headers={"content-type": "text/html"})
    error(await client.get(url, params={"url": IMAGE}), 502, "source_error")
    payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>bad()</script></svg>'
    setup[2].fetch = lambda _: httpx.Response(200, content=payload, headers={"content-type": "image/svg+xml"})
    response = await client.get(url, params={"url": IMAGE})
    assert response.content == payload
    assert "sandbox" in response.headers["content-security-policy"]
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["content-disposition"] == "inline"


@pytest.mark.parametrize("url", ["javascript:bad()", "file:///tmp/x", "", "https://"])
async def test_invalid_resource_addresses(client, url):
    error(await client.get("/api/v1/tasks/1/resources/image", params={"url": url}), 422, "validation_error")
