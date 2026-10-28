import pytest
from conftest import add, search
from playwright.sync_api import expect

pytestmark = pytest.mark.controlled


def test_selection_order_duplicates_and_search_preservation(page, scenario):
    search(page)
    add(page, 4)
    add(page, 5)
    expect(page.locator('.task-card[data-task-id="4"] .add-task')).to_be_disabled()
    search(page, "19")
    add(page, 2)
    row = page.locator('#selection li[data-task-id="2"]')
    row.get_by_role("button", name="Вверх", exact=True).click()
    assert page.locator("#selection li").evaluate_all("els=>els.map(e=>Number(e.dataset.taskId))") == [4, 2, 5]
    page.locator('#selection li[data-task-id="4"]').get_by_role("button", name="Удалить", exact=True).click()
    expect(page.locator("#selection-count")).to_have_text("2 / 100")
    search(page)
    add(page, 4)
    assert page.locator("#selection li").evaluate_all("els=>els.map(e=>Number(e.dataset.taskId))") == [2, 5, 4]
    page.locator("#next-page").click()
    expect(page.locator("#selection-count")).to_have_text("3 / 100")


def test_hundred_limit_through_browser(page, scenario):
    search(page)
    for _ in range(10):
        buttons = page.locator(".add-task")
        for button in buttons.all():
            button.click()
        if _ < 9:
            page.locator("#next-page").click()
            expect(page.locator("#search-status")).to_have_attribute("data-state", "ready")
    expect(page.locator("#selection-count")).to_have_text("100 / 100")
    page.locator("#next-page").click()
    expect(page.locator(".add-task:enabled")).to_have_count(0)
    page.locator("#selection li").first.get_by_role("button", name="Удалить", exact=True).click()
    expect(page.locator(".add-task:enabled").first).to_be_enabled()


def test_keyboard_focus_after_reorder_and_delete(page, scenario):
    search(page)
    add(page, 4)
    add(page, 5)
    button = page.locator('#selection li[data-task-id="5"] [data-action="up"]')
    button.focus()
    button.press("Enter")
    expect(page.locator("#selection button:focus")).to_have_count(1)
    remove = page.locator('#selection li[data-task-id="5"] [data-action="remove"]')
    remove.focus()
    remove.press("Enter")
    expect(page.locator("#selection button:focus")).to_have_count(1)
