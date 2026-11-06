import pytest
from conftest import search
from playwright.sync_api import expect

pytestmark = pytest.mark.controlled


def test_original_html_and_pagination(page, scenario):
    search(page)
    expect(page.locator('.task-card[data-task-id="1"] table')).to_contain_text("Таблица")
    expect(page.locator('.task-card[data-task-id="1"] sup')).to_have_text("3")
    expect(page.locator('.task-card[data-task-id="1"] img')).to_be_visible()
    expect(page.locator('.task-card[data-task-id="3"]')).to_contain_text("Есть приложения")
    expect(page.locator("#previous-page")).to_be_disabled()
    page.locator("#next-page").click()
    expect(page.locator(".task-card").first).to_have_attribute("data-task-id", "12")
    page.locator("#previous-page").click()
    expect(page.locator(".task-card").first).to_have_attribute("data-task-id", "1")
    search(page, "19")
    expect(page.locator(".task-card")).to_have_count(1)
    expect(page.locator(".task-card")).to_contain_text("19–21")


def test_category_is_optional(page, scenario):
    search(page)
    assert "category_ids" not in page.url
    page.get_by_label("Категория", exact=True).select_option("7")
    with page.expect_request("**/api/v1/tasks?*") as observed:
        page.get_by_role("button", name="Найти задачи", exact=True).click()
    assert "category_ids=7" in observed.value.url
