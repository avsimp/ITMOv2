import pytest
from conftest import add, search
from playwright.sync_api import expect

pytestmark = pytest.mark.controlled


def test_teacher_json_download_and_no_extra_post(page, scenario, tmp_path):
    search(page)
    add(page, 4)
    page.locator("#create-work").click()
    button = page.locator('[data-download="sources"]')
    button.click()
    expect(page.locator("#save-file")).to_have_attribute("download", "work.sources.json")
    with page.expect_download() as observed:
        page.locator("#save-file").click()
    download = observed.value
    download.save_as(tmp_path / download.suggested_filename)
    assert "teacher sources" in (tmp_path / download.suggested_filename).read_text()
    assert len(scenario.posts) == 1
    assert all("range" not in headers and "if-range" not in headers
               for _, path, headers in scenario.requests if "/files/" in path)


@pytest.mark.parametrize("status,media,body", [(404,"application/json",'{"error":{"code":"not_found","message":"Файл удалён","fields":[]}}'),
                         (400,"text/plain","Bad range"),(416,"text/plain",""),
                         (206,"application/pdf","partial")])
def test_file_error_never_becomes_full_file_or_new_export(page, scenario, status, media, body):
    search(page)
    add(page, 4)
    page.locator("#create-work").click()
    scenario.download_error = (status, media, body)
    page.locator('[data-download="result"]').click()
    expect(page.locator("#download-status")).to_have_attribute("data-state", "error")
    expect(page.locator("#save-file")).to_be_hidden()
    assert len(scenario.posts) == 1
    scenario.download_error = None
    page.locator('[data-download="result"]').click()
    expect(page.locator("#save-file")).to_be_visible()
