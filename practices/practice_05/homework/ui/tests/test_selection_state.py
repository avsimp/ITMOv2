import pytest

pytestmark = pytest.mark.controlled


def test_invalid_ids_pending_and_revision(page, scenario):
    result = page.evaluate("""async () => {
      const {Selection} = await import('/assets/state.js'); const s = new Selection();
      const invalid = [0,-1,true,'4',1.5,NaN].map(id=>s.add({id}));
      s.add({id:2,statement:'game',ege_numbers:[19,20,21]});
      const revision=s.revision; s.move(2,-1); s.add({id:2});
      const noops=s.revision===revision; s.locked=true;
      return {invalid,noops,add:s.add({id:3}),remove:s.remove(2),move:s.move(2,1),ids:s.ids};
    }""")
    assert result == {"invalid": [False]*6, "noops": True, "add": False,
                      "remove": False, "move": False, "ids": [2]}
