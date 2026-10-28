from contextlib import suppress

import pytest
from conftest import add, search
from playwright.sync_api import Error, expect

pytestmark = pytest.mark.controlled


def test_category_error_is_retryable(page, scenario):
    scenario.category_error = True
    page.get_by_label("Номер задания ЕГЭ", exact=True).select_option("5")
    expect(page.locator("#search-status")).to_contain_text("Не удалось загрузить категории")
    expect(page.get_by_role("button", name="Найти задачи", exact=True)).to_be_disabled()
    scenario.category_error = False
    page.locator("#retry-categories").click()
    expect(page.get_by_label("Категория", exact=True)).to_be_enabled()


def test_empty_error_and_retry_keep_selection(page, scenario):
    search(page)
    add(page, 4)
    scenario.empty = True
    page.get_by_role("button", name="Найти задачи", exact=True).click()
    expect(page.locator("#search-status")).to_contain_text("Ничего не найдено")
    scenario.error = (502, "source_error")
    page.get_by_role("button", name="Найти задачи", exact=True).click()
    expect(page.locator("#search-status")).to_contain_text("Источник недоступен")
    expect(page.locator("#selection-count")).to_have_text("1 / 100")
    scenario.error = None
    scenario.empty = False
    page.locator("#retry-search").click()
    expect(page.locator("#search-status")).to_have_attribute("data-state", "ready")


def test_image_failure_blocks_only_its_card(page, scenario):
    scenario.bad_image = True
    search(page)
    card = page.locator('.task-card[data-task-id="1"]')
    expect(card.locator(".add-task")).to_be_disabled()
    expect(card).to_contain_text("Рисунок не загружен")
    scenario.bad_image = False
    card.get_by_role("button", name="Повторить загрузку рисунков").click()
    expect(card.locator(".add-task")).to_be_enabled()


def test_late_search_does_not_replace_new_filter(page, scenario):
    search(page)
    scenario.hold_search = True
    page.get_by_role("button", name="Найти задачи", exact=True).click()
    page.wait_for_timeout(100)
    scenario.hold_search = False
    search(page, "19")
    route, value = scenario.search_pending
    with suppress(Error):
        route.fulfill(json=value)
    expect(page.locator(".task-card")).to_have_count(1)
    expect(page.locator(".task-card")).to_have_attribute("data-task-id", "2")
