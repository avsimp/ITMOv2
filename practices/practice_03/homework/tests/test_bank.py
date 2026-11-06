import httpx
import pytest

from polyakov import Bank, SourceError, normalize_html, parse_tasks
from render import answer_line, export_pdf


def page(statement="Число 2<sup>3</sup>", answer="8", number="5", ident=42):
    return f"""
    <input id="imagePath" value="../../cms/images/">
    <input id="filePath" value="../../cms/files/">
    <table><tr><td class="egeno">{number}</td><td class="topicview">
    <script>document.write('(№&nbsp;{ident}) ');
    document.write(changeImageFilePath('{statement}'));</script></td></tr>
    <tr><td></td><td><div class="hidedata" id="{ident}">
    <script>document.write(changeImageFilePath('{answer}'));</script>
    </div></td></tr></table>"""


def test_parse_keeps_markup_and_does_not_leak_answer():
    tasks = parse_tasks(page('Кириллица <img src="42.gif"> 2<sup>3</sup>', "SECRET"), "listing")
    task = tasks[0]
    assert task["id"] == 42
    assert "<sup>3</sup>" in task["statement_html"]
    assert task["images"] == ["https://kpolyakov.spb.ru/cms/images/42.gif"]
    assert "SECRET" not in task["statement_html"]
    assert task["answer"] == "SECRET"


def test_javascript_escapes_are_decoded_without_execution():
    task = parse_tasks(page(r"Строка \'abc\' и \\ путь"), "listing")[0]
    assert "'abc'" in task["statement"]
    assert "\\ путь" in task["statement"]


def test_missing_answer_fails_instead_of_pairing_next_task():
    html = page().replace('id="42"', 'id="43"') + page(ident=43)
    with pytest.raises(SourceError):
        parse_tasks(html, "listing")


def test_complete_game_is_one_item_and_answers_are_unambiguous():
    html = page("Вопрос 1. А<br>Вопрос 2. Б<br>Вопрос 3. В", "1) 41<br>2) 36 40<br>3) 35", "19 20 21")
    tasks = parse_tasks(html, "listing")
    assert len(tasks) == 1
    assert answer_line(2, tasks[0]) == "2. 19) 41; 20) 36 40; 21) 35"
    with pytest.raises(SourceError, match="полная тройка"):
        parse_tasks(page(number="19 20 21"), "listing")


def test_external_resources_are_rejected():
    with pytest.raises(SourceError, match="вне разрешённого"):
        normalize_html('<img src=":https://example.com/x.png">', "", "")


def test_filters_pagination_and_exclusions(monkeypatch):
    bank = Bank()
    monkeypatch.setattr(bank, "categories", lambda _: [{"id": 27}])
    monkeypatch.setattr(bank, "fetch", lambda _: httpx.Response(200, text=page(ident=1) + page(ident=2)))
    assert bank.search(5, exclude_ids=[1])["tasks"][0]["id"] == 2
    assert bank.search(5, contains="ЧИСЛО", limit=1)["next_offset"] == 1
    assert bank.search(5, contains="нет совпадений")["total"] == 0
    with pytest.raises(SourceError):
        bank.search(5, category_ids=[163])


def test_network_error_is_explained(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "get", fail)
    with pytest.raises(SourceError, match="Не удалось загрузить"):
        Bank().get(42)


def test_export_rejects_duplicates_and_overwriting(tmp_path):
    with pytest.raises(SourceError, match="уникальных"):
        export_pdf(Bank(), [42, 42], str(tmp_path / "a.pdf"))
    path = tmp_path / "a.pdf"
    path.write_bytes(b"existing")
    with pytest.raises(SourceError, match="уже существуют"):
        export_pdf(Bank(), [42], str(path))
    assert path.read_bytes() == b"existing"
