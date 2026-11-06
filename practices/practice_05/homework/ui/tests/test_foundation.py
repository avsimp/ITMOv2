import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.controlled


def test_initial_accessible_state(page, scenario):
    expect(page.get_by_label("Номер задания ЕГЭ", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Найти задачи", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Создать работу", exact=True)).to_be_disabled()
    expect(page.locator("#selection-count")).to_have_text("0 / 100")


def test_store_boundaries(page, scenario):
    result = page.evaluate("""async () => {
      const {Selection} = await import('/assets/state.js');
      const s = new Selection();
      for(let id=1; id<=100; id++) s.add({id, ege_numbers:[5], statement:'x'});
      const before = s.revision;
      const overflow = s.add({id:101});
      const duplicate = s.add({id:1});
      s.move(100,-1); s.remove(1);
      return {overflow,duplicate,count:s.ids.length,first:s.ids[0],
              last:s.ids.at(-1),revision:s.revision-before};
    }""")
    assert result == {"overflow": False, "duplicate": False, "count": 99,
                      "first": 2, "last": 99, "revision": 2}
