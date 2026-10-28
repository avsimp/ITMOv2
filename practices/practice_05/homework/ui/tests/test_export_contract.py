import pytest
from conftest import add, search
from playwright.sync_api import expect

pytestmark = pytest.mark.controlled


def test_pending_single_post_and_pdf_result(page, scenario):
    search(page)
    add(page, 4)
    scenario.hold_export = True
    page.locator("#create-work").click()
    expect(page.locator("#export-status")).to_contain_text("Создаём работу")
    expect(page.locator("#create-work")).to_be_disabled()
    expect(page.locator("#selection button:enabled")).to_have_count(0)
    assert page.evaluate("async()=>{const {state}=await import('/assets/state.js');return state.submittedRevision===state.selection.revision;}")
    page.locator("#create-work").evaluate("el=>{for(let i=0;i<5;i++) el.dispatchEvent(new MouseEvent('click',{bubbles:true}));}")
    assert len(scenario.posts) == 1
    page.locator("#next-page").click()
    expect(page.locator("#search-status")).to_have_attribute("data-state", "ready")
    expect(page.locator(".add-task:enabled")).to_have_count(0)
    page.locator("#previous-page").click()
    expect(page.locator("#search-status")).to_have_attribute("data-state", "ready")
    scenario.finish()
    expect(page.locator("#export-status")).to_contain_text("Работа создана")
    expect(page.locator('[data-download="result"]')).to_contain_text("PDF")
    assert scenario.posts == [{"topic_ids": [4]}]
    add(page, 5)
    expect(page.locator("#work-version")).to_contain_text("Для предыдущей подборки")


def test_zip_is_student_result_and_answers_separate(page, scenario):
    search(page)
    add(page, 3)
    page.locator("#create-work").click()
    expect(page.locator('[data-download="result"]')).to_contain_text("ZIP")
    expect(page.locator("#preview-pdf")).to_be_visible()
    expect(page.locator('[data-download="answers"]')).to_contain_text("Для преподавателя")
    expect(page.locator('[data-download="sources"]')).to_contain_text("Для преподавателя")
