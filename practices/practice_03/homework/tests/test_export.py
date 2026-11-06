import asyncio
import base64
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

import httpx
import pymupdf
import pytest
from bs4 import BeautifulSoup

import render
import server
from polyakov import SourceError
from render import export_pdf, normalize_pdf_links, plan_attachments


def task(ident, html="Условие без приложений", numbers=None, answer="SECRET"):
    return {"id": ident, "statement_html": html, "ege_numbers": numbers or [9], "answer": answer}


class TaskBank:
    def __init__(self, tasks, files=None):
        self.tasks = {item["id"]: item for item in tasks}
        self.files = files or {}
        self.fetched = []

    def get(self, ident):
        return self.tasks[ident]

    def fetch(self, url):
        self.fetched.append(url)
        response = self.files[url]
        return response if isinstance(response, httpx.Response) else httpx.Response(200, content=response)


@pytest.mark.parametrize(("source", "expected"), [
    ("9-291.ods", "2.ods"),
    ("data.tar.gz", "2.tar.gz"),
    ("DATA.ODS", "2.ODS"),
    ("data", "2"),
    ("", "2"),
    ("%D1%84%D0%B0%D0%B9%D0%BB.ods?download=1", "2.ods"),
])
def test_attachment_number_is_homework_position(source, expected):
    soup = BeautifulSoup(f'<a href="https://kpolyakov.spb.ru/files/{source}">файл</a>', "html.parser")
    plan = plan_attachments(soup, 2, 9111, "урок.files")
    assert [entry["filename"] for entry in plan] == [expected]
    assert plan[0]["relative_path"] == "урок.files/" + expected
    assert plan[0]["task_id"] == 9111
    assert plan[0]["task_number"] == 2


def test_multiple_attachments_follow_first_link_order():
    soup = BeautifulSoup('<a href="https://kpolyakov.spb.ru/b/data.txt">Б</a>'
                         '<a href="https://kpolyakov.spb.ru/a/data.txt">А</a>'
                         '<a href="https://kpolyakov.spb.ru/b/data.txt">повтор</a>', "html.parser")
    plan = plan_attachments(soup, 2, 42, "lesson.files")
    assert [entry["filename"] for entry in plan] == ["2_1.txt", "2_2.txt"]
    assert [entry["source_url"] for entry in plan] == [
        "https://kpolyakov.spb.ru/b/data.txt", "https://kpolyakov.spb.ru/a/data.txt"]
    assert plan_attachments(BeautifulSoup("Без приложений", "html.parser"), 1, 7, "lesson.files") == []


def test_export_keeps_originals_and_all_numbered_attachments(tmp_path):
    url = "https://kpolyakov.spb.ru/files/9-291.ods"
    a = "https://kpolyakov.spb.ru/a/data.txt"
    b = "https://kpolyakov.spb.ru/b/data.txt"
    tasks = [task(7), task(9111, f'<a href="{url}"><b>9-291.ods</b></a> '
                                f'<a href="{url}">Скачать таблицу</a>'),
             task(42, f'<a href="{url}">9-291.ods</a>'),
             task(300, f'<a href="{a}">data.txt</a> <a href="{b}">data.txt</a>')]
    originals = copy.deepcopy(tasks)
    files = {url: b"PK\x00original ODS", a: b"first\x00", b: b"second\xff"}
    bank = TaskBank(tasks, files)
    (tmp_path / "unrelated.txt").write_text("Секретный посторонний файл")
    result = export_pdf(bank, [7, 9111, 42, 300], str(tmp_path / "урок.pdf"))
    expected = {"2.ods": files[url], "3.ods": files[url], "4_1.txt": files[a], "4_2.txt": files[b]}
    assert result["attachments"] == list(expected)
    for name, content in expected.items():
        assert (tmp_path / "урок.files" / name).read_bytes() == content
    with ZipFile(tmp_path / "урок.zip") as archive:
        assert archive.namelist() == ["урок.pdf"] + ["урок.files/" + name for name in expected]
        assert archive.read("урок.pdf") == Path(result["pdf"]).read_bytes()
        for name, content in expected.items():
            assert archive.read("урок.files/" + name) == content
    assert bank.fetched == [url, url, a, b]
    manifest = json.loads(Path(result["sources"]).read_text())
    assert tasks == originals == manifest["tasks"]
    assert manifest["attachments"] == list(expected)
    assert manifest["attachment_map"][0] == {
        "task_number": 2, "task_id": 9111, "source_url": url, "original_filename": "9-291.ods",
        "filename": "2.ods", "relative_path": "урок.files/2.ods"}
    with pymupdf.open(result["pdf"]) as doc:
        text = "".join(page.get_text() for page in doc)
    assert all(name in text for name in expected)
    assert "Скачать таблицу" in text
    assert "9-291.ods" not in text
    assert "SECRET" not in text
    assert manifest["pdf_sha256"] == hashlib.sha256(Path(result["pdf"]).read_bytes()).hexdigest()
    with pymupdf.open(result["pdf"]) as doc:
        links = [link for page in doc for link in page.get_links()]
        assert all(doc.xref_get_key(link["xref"], "A/S") == ("name", "/Launch") for link in links)
    assert len(links) == 5
    # MuPDF представляет Launch как GOTOR и percent-encoding в get_links().
    assert [unquote(link["file"]) for link in links] == [
        "урок.files/2.ods", "урок.files/2.ods", "урок.files/3.ods",
        "урок.files/4_1.txt", "урок.files/4_2.txt"]


def test_missing_pdf_annotation_fails():
    with pymupdf.open() as doc:
        doc.new_page()
        pdf = doc.tobytes()
    with pytest.raises(SourceError, match="потеряны ссылки"):
        normalize_pdf_links(pdf, {"https://homework.invalid/1/1": "lesson.files/1.ods"})


def test_real_pdf_multiline_links_are_relative_and_keep_labels(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("Автономный экспорт не должен обращаться в сеть")

    monkeypatch.setattr(httpx.Client, "get", no_network)
    url = "https://kpolyakov.spb.ru/files/data.ods"
    bank = TaskBank([task(42, f'<a href="{url}"><b>data.ods</b></a> '
                             f'<a href="{url}">Скачать<br>таблицу</a>')], {url: b"ODS bytes"})
    result = export_pdf(bank, [42], str(tmp_path / "Домашняя работа.pdf"))
    with pymupdf.open(result["pdf"]) as doc:
        links = [link for page in doc for link in page.get_links()]
        text = "".join(page.get_text() for page in doc)
        spans = [span for page in doc for block in page.get_text("dict")["blocks"]
                 if "lines" in block for line in block["lines"] for span in line["spans"]]
    assert len(links) >= 3  # Первая ссылка и обе строки второй.
    assert "1.ods" in text and "data.ods" not in text
    assert "Скачать" in text and "таблицу" in text
    assert any(span["text"] == "1.ods" and span["flags"] & 16 for span in spans)  # Bold сохранён.
    for link in links:
        relative = unquote(link["file"])
        assert relative == "Домашняя работа.files/1.ods"
        assert not Path(relative).is_absolute()
        assert "uri" not in link
        assert (tmp_path / relative).read_bytes() == b"ODS bytes"


def test_without_attachments_keeps_plain_pdf_pipeline(tmp_path, monkeypatch):
    def unexpected_postprocessing(*args):
        pytest.fail("PDF без приложений не требует нормализации ссылок")

    monkeypatch.setattr(render, "normalize_pdf_links", unexpected_postprocessing)
    result = export_pdf(TaskBank([task(42)]), [42], str(tmp_path / "plain.pdf"))
    assert not (tmp_path / "plain.files").exists()
    assert not (tmp_path / "plain.zip").exists()
    assert result["attachments"] == []
    manifest = json.loads(Path(result["sources"]).read_text())
    assert manifest["attachment_map"] == []
    assert manifest["pdf_sha256"] == hashlib.sha256(Path(result["pdf"]).read_bytes()).hexdigest()
    with pymupdf.open(result["pdf"]) as doc:
        assert all(not page.get_links() for page in doc)


@pytest.mark.parametrize("suffix", [".pdf", ".zip", ".answers.txt", ".sources.json", ".files"])
@pytest.mark.parametrize("with_attachments", [False, True])
def test_output_conflict_creates_nothing_and_keeps_existing_bytes(tmp_path, suffix, with_attachments):
    path = tmp_path / "lesson.pdf"
    conflict = path.with_suffix(suffix)
    if suffix == ".files":
        conflict.mkdir()
        existing = conflict / "keep.txt"
    else:
        existing = conflict
    existing.write_bytes(b"keep original bytes\x00\xff")
    url = "https://kpolyakov.spb.ru/data.ods"
    html = f'<a href="{url}">data.ods</a>' if with_attachments else "Без приложений"
    bank = TaskBank([task(42, html)], {url: b"new bytes"})
    with pytest.raises(SourceError, match="уже существуют"):
        export_pdf(bank, [42], str(path))
    assert existing.read_bytes() == b"keep original bytes\x00\xff"
    assert list(tmp_path.iterdir()) == [conflict]
    assert bank.fetched == []


def test_file_appearing_after_preflight_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "lesson.pdf"
    bank = TaskBank([task(42)])

    def get_with_conflict(ident):
        path.write_bytes(b"appeared after preflight")
        return bank.tasks[ident]

    monkeypatch.setattr(bank, "get", get_with_conflict)
    with pytest.raises(SourceError, match="уже существуют"):
        export_pdf(bank, [42], str(path))
    assert path.read_bytes() == b"appeared after preflight"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("with_attachments", [False, True])
def test_mcp_export_contract_is_additive(tmp_path, monkeypatch, with_attachments):
    url = "https://kpolyakov.spb.ru/data.ods"
    html = f'<a href="{url}">data.ods</a>' if with_attachments else "Условие"
    monkeypatch.setattr(server, "bank", TaskBank([task(42, html)], {url: b"original ODS"}))
    pdf = tmp_path / "lesson.pdf"
    result = asyncio.run(server.create_pdf([42], str(pdf)))
    assert {"pdf", "sources", "answers_file", "answers", "count", "attachments"} <= result.keys()
    assert result["pdf"] == str(pdf)
    assert result["count"] == 1
    assert result["answers"] == "1. SECRET"
    assert Path(result["sources"]).is_file()
    assert Path(result["answers_file"]).read_text() == "1. SECRET\n"
    assert result["result_file"] == str(pdf.with_suffix(".zip") if with_attachments else pdf)
    assert result["archive"] == (str(pdf.with_suffix(".zip")) if with_attachments else None)
    assert result["attachments"] == (["1.ods"] if with_attachments else [])
    tools = asyncio.run(server.mcp.list_tools())
    assert {tool.name for tool in tools} == {"list_categories", "search_tasks", "get_task", "create_pdf"}
    tool = next(tool for tool in tools if tool.name == "create_pdf")
    assert set(tool.inputSchema["properties"]) == {"topic_ids", "output_path"}
    assert set(tool.inputSchema["required"]) == {"topic_ids", "output_path"}


def test_extracted_bundle_links_content_and_game_numbering(tmp_path):
    ods = "https://kpolyakov.spb.ru/data.ods"
    first = "https://kpolyakov.spb.ru/a/data.txt"
    second = "https://kpolyakov.spb.ru/b/data.txt"
    image = "https://kpolyakov.spb.ru/figure.png"
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==")
    tasks = [task(9175, "Вопрос 1. А<br>Вопрос 2. Б<br>Вопрос 3. В", [19, 20, 21], "1) 41 2) 36 40 3) 35"),
             task(9111, f'<img src="{image}"><table border="1"><tr><td>Таблица</td></tr></table>'
                        f'Число 2<sup>3</sup> <a href="{ods}">data.ods</a>'),
             task(42, f'<a href="{first}">data.txt</a> <a href="{second}">Скачать данные</a>')]
    files = {ods: b"ODS\x00original", first: b"first", second: b"second",
             image: httpx.Response(200, content=png, headers={"content-type": "image/png"})}
    path = tmp_path / "original" / "Домашняя работа.pdf"
    result = export_pdf(TaskBank(tasks, files), [9175, 9111, 42], str(path))
    assert result["count"] == 3
    assert result["answers"].splitlines()[0] == "1. 19) 41; 20) 36 40; 21) 35"
    extracted = tmp_path / "elsewhere" / "unpacked"
    expected = {"Домашняя работа.files/2.ods": files[ods],
                "Домашняя работа.files/3_1.txt": files[first],
                "Домашняя работа.files/3_2.txt": files[second]}
    with ZipFile(result["result_file"]) as archive:
        assert set(archive.namelist()) == {path.name, *expected}
        archive.extractall(extracted)
    extracted_pdf = extracted / path.name
    assert extracted_pdf.read_bytes() == path.read_bytes()
    with pymupdf.open(extracted_pdf) as doc:
        links = [link for page in doc for link in page.get_links()]
        text = "".join(page.get_text() for page in doc)
        assert sum(len(page.get_images()) for page in doc) >= 1
        assert doc[0].rect.width == pytest.approx(595, abs=1)
        assert doc[0].rect.height == pytest.approx(842, abs=1)
    assert [unquote(link["file"]) for link in links] == list(expected)
    for link in links:
        relative = unquote(link["file"])
        assert not Path(relative).is_absolute()
        assert "uri" not in link
        assert (extracted_pdf.parent / relative).read_bytes() == expected[relative]
    assert text.index("1)") < text.index("2)") < text.index("3)")
    assert all(value in text for value in ("Вопрос 1.", "Вопрос 2.", "Вопрос 3.", "Таблица", "Скачать данные"))
    assert "SECRET" not in text
    assert not list(extracted.glob("*.answers.txt"))
    assert not list(extracted.glob("*.sources.json"))
