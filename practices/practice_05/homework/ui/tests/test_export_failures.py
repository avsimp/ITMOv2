import pytest
from conftest import add, search
from playwright.sync_api import expect

pytestmark = pytest.mark.controlled


@pytest.mark.parametrize("status,code", [(400,"invalid_request"),(404,"not_found"),
                         (409,"output_conflict"),(415,"invalid_request"),
                         (422,"validation_error"),(500,"export_failed"),
                         (502,"source_error"),(504,"source_timeout")])
def test_confirmed_error_unlocks_without_retry(page, scenario, status, code):
    search(page)
    add(page, 4)
    scenario.error = (status, code)
    page.locator("#create-work").click()
    expect(page.locator("#export-status")).to_have_attribute("data-state", "failed")
    expect(page.locator("#create-work")).to_be_enabled(timeout=1000)
    expect(page.locator("#selection-count")).to_have_text("1 / 100")
    assert len(scenario.posts) == 1


@pytest.mark.parametrize("redirect", [False, True])
def test_unknown_requires_explicit_new_work(page, scenario, redirect):
    search(page)
    add(page, 4)
    scenario.redirect_export = redirect
    scenario.abort_export = not redirect
    page.locator("#create-work").click()
    expect(page.locator("#export-status")).to_have_attribute("data-state", "unknown")
    expect(page.locator("#export-status")).to_contain_text("Предыдущая работа могла быть создана")
    expect(page.locator("#create-work")).to_have_text("Создать новую работу")
    expect(page.locator("#create-work")).to_be_enabled(timeout=1000)
    add(page, 5)
    expect(page.locator("#export-status")).to_contain_text("Предыдущая работа могла быть создана")
    assert len(scenario.posts) == 1
    assert not any(p == "/redirect-target" for _, p, _ in scenario.requests)
    scenario.abort_export = scenario.redirect_export = False
    page.locator("#create-work").click()
    expect(page.locator("#export-status")).to_have_attribute("data-state", "succeeded")
    assert len(scenario.posts) == 2


def test_invalid_success_is_unknown_and_does_not_publish_links(page, scenario):
    search(page)
    add(page, 4)
    scenario.make_work = lambda ids: {"work_id": "broken"}
    page.locator("#create-work").click()
    expect(page.locator("#export-status")).to_have_attribute("data-state", "unknown")
    expect(page.locator("#work-result")).to_be_hidden()
    expect(page.locator("#create-work")).to_be_enabled(timeout=1000)
    assert len(scenario.posts) == 1
