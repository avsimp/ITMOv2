import base64
import copy
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest

from app.bank_adapter import SourceError
from app.config import Settings
from app.main import create_app

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==")
IMAGE = "https://kpolyakov.spb.ru/figure.png"
ATTACHMENT = "https://kpolyakov.spb.ru/data.ods"


def task(ident, html=None, game=False):
    statement = html or ("Вопрос 1. А<br>Вопрос 2. Б<br>Вопрос 3. В" if game else f"Условие задачи {ident}")
    return {"id": ident, "ege_numbers": [19, 20, 21] if game else [5], "statement_html": statement,
            "statement": statement, "answer": "1) 41 2) 36 40 3) 35" if game else "SECRET",
            "answer_html": "SECRET", "source_url": f"https://kpolyakov.spb.ru/school/ege/gen.php?topicId={ident}",
            "listing_url": "https://kpolyakov.spb.ru/school/ege/gen.php?egeId=5", "images": [], "attachments": []}


class FakeBank:
    def __init__(self):
        self.items = {1: task(1, f'<p>Число 2<sup>3</sup></p><img src="{IMAGE}">'),
                      2: task(2, game=True), 3: task(3, f'<a href="{ATTACHMENT}">data.ods</a>')}
        self.items[1]["images"] = [IMAGE]
        self.items[3]["attachments"] = [ATTACHMENT]
        self.failure = None
        self.requests = []

    def categories(self, number):
        if self.failure:
            raise self.failure
        return [{"id": 7, "title": "Категория"}]

    def search(self, number, category_ids=None, contains="", exclude_ids=None, offset=0, limit=10):
        items = [copy.deepcopy(t) for t in self.items.values() if t["id"] not in (exclude_ids or [])
                 and contains.casefold() in t["statement"].casefold()]
        return {"total": len(items), "offset": offset, "source_url": self.items[1]["listing_url"],
                "tasks": items[offset:offset + limit], "next_offset": offset + limit if offset + limit < len(items) else None}

    def get(self, ident):
        if self.failure:
            raise self.failure
        if ident not in self.items:
            raise SourceError("Unknown source task")
        return copy.deepcopy(self.items[ident])

    def fetch(self, url):
        self.requests.append(url)
        if self.failure:
            raise self.failure
        return httpx.Response(200, content=PNG if url == IMAGE else b"original-ods\x00",
                              headers={"content-type": "image/png" if url == IMAGE else "application/octet-stream"})


class FakeExporter:
    """Controlled bytes, not a real rendered PDF. Real rendering has separate tests."""
    def __init__(self):
        self.calls = []

    def __call__(self, bank, ids, path):
        self.calls.append(list(ids))
        pdf = Path(path)
        tasks = [bank.get(i) for i in ids]
        attached = any(t["attachments"] for t in tasks)
        payload = b"%PDF-controlled-0123456789"
        pdf.write_bytes(payload)
        pdf.with_suffix(".answers.txt").write_text("1. SECRET\n")
        manifest = {"created_at": "2026-10-27T18:00:00Z", "format_version": 1, "tasks": tasks,
                    "pdf_sha256": hashlib.sha256(payload).hexdigest(), "attachments": ["1.ods"] if attached else [],
                    "attachment_map": []}
        pdf.with_suffix(".sources.json").write_text(json.dumps(manifest))
        if attached:
            pdf.with_suffix(".files").mkdir()
            (pdf.with_suffix(".files") / "1.ods").write_bytes(b"original-ods\x00")
            with ZipFile(pdf.with_suffix(".zip"), "x") as archive:
                archive.write(pdf, pdf.name)
                archive.write(pdf.with_suffix(".files") / "1.ods", "work.files/1.ods")
        return {"pdf": str(pdf), "sources": str(pdf.with_suffix(".sources.json")),
                "answers_file": str(pdf.with_suffix(".answers.txt")), "answers": "1. SECRET",
                "count": len(ids), "attachments": manifest["attachments"],
                "result_file": str(pdf.with_suffix(".zip") if attached else pdf),
                "archive": str(pdf.with_suffix(".zip")) if attached else None}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def no_accidental_network(monkeypatch, request):
    if request.node.get_closest_marker("live_api") or request.node.get_closest_marker("live_ui"):
        return

    def reject(*args, **kwargs):
        raise AssertionError("Uncontrolled upstream network in an offline check")

    monkeypatch.setattr(httpx.Client, "get", reject)


@pytest.fixture
def setup(tmp_path):
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text('<script type="module" src="/assets/app.js"></script>')
    (ui / "assets/app.js").write_text("export const fixture = true;")
    bank, exporter = FakeBank(), FakeExporter()
    settings = Settings(storage_root=tmp_path / "works", ui_root=ui)
    application = create_app(settings, bank_factory=lambda: bank, exporter=exporter)
    return application, settings, bank, exporter


@pytest.fixture
async def client(setup):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=setup[0], raise_app_exceptions=False),
                                base_url="http://127.0.0.1:8000") as value:
        yield value
