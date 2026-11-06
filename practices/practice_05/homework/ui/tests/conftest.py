"""Three explicit levels: substituted API, fixed upstream, or fully live."""
import base64
import json
import select
import socket
import sys
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import uvicorn
from contract_support import validate
from playwright.sync_api import sync_playwright

UI_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = UI_ROOT.parent / "api"
sys.path.insert(0, str(API_ROOT))
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==")


def pytest_addoption(parser):
    parser.addoption("--ui-browser", choices=["chromium", "firefox"], default="chromium")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, "rep_" + outcome.get_result().when, outcome.get_result())


@pytest.fixture
def journal(request, page):
    level = "LIVE-UI" if request.node.get_closest_marker("live_ui") or request.node.get_closest_marker("boundary_probe") else "REAL-LOCAL"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    folder = UI_ROOT / ".test-artifacts" / "runs" / f"{level.lower()}-{stamp}"
    folder.mkdir(parents=True)
    record = {"level": level, "source_replaced": level != "LIVE-UI", "contract": "1.0.0",
              "browser": page.context.browser.version, "works": [], "calls": [], "folder": str(folder)}
    def observe(response):
        if "/api/v1/" in response.url:
            record["calls"].append({"method": response.request.method, "url": response.url, "status": response.status})
    page.on("response", observe)
    yield record
    record["status"] = "passed" if getattr(request.node, "rep_call", None) and request.node.rep_call.passed else "failed"
    (folder / "journal.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"\n{level} journal: {folder / 'journal.json'}")


class APIServer:
    """Own isolated runtime storage; never edits API source/default var/works."""
    def __init__(self, storage):
        from app.config import Settings
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.origin = f"http://127.0.0.1:{port}"
        self.port = port
        self.settings = Settings(origin=self.origin, storage_root=storage, ui_root=UI_ROOT)
        self.server = None

    def start(self):
        from app.main import create_app
        self.server = uvicorn.Server(uvicorn.Config(
            create_app(self.settings), host="127.0.0.1",
            port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(.05)
        raise RuntimeError("API server did not start")

    def stop(self):
        if self.server:
            self.server.should_exit = True
            self.thread.join(timeout=180)
            assert not self.thread.is_alive(), "Export/server still running"


@pytest.fixture
def api_server(tmp_path, monkeypatch, request):
    if request.node.get_closest_marker("real_local"):
        # Reuse API's fixed raw upstream pages; actual Bank/export remain unchanged.
        from tests.source_fixture import install_source
        install_source(monkeypatch)
    server = APIServer(tmp_path / "works").start()
    yield server
    server.stop()


class CuttingProxy:
    """Byte-for-byte TCP relay: cut real sockets, never manufacture API responses."""
    def __init__(self, target_port):
        self.target_port = target_port
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(.1)
        self.origin = f"http://127.0.0.1:{self.listener.getsockname()[1]}"
        self.running = True
        self.cut_response = False
        self.cut_file = False
        self.post_count = 0
        self.connections = set()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def accept(self):
        while self.running:
            try:
                client, _ = self.listener.accept()
            except (TimeoutError, OSError):
                continue
            threading.Thread(target=self.relay, args=(client,), daemon=True).start()

    def relay(self, client):
        remote = socket.create_connection(("127.0.0.1", self.target_port))
        pair = (client, remote)
        with self.lock:
            self.connections.update(pair)
        is_create = False
        is_file = False
        response_buffer = bytearray()
        try:
            while self.running:
                readable, _, _ = select.select(pair, [], [], .1)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    if source is client and b"POST /api/v1/works HTTP/1.1" in data:
                        is_create = True
                        with self.lock:
                            self.post_count += 1
                    if source is client and data.startswith(b"GET "):
                        is_file = b"/api/v1/works/" in data.split(b"\r\n")[0] and b"/files/" in data.split(b"\r\n")[0]
                    if source is remote and ((is_create and self.cut_response) or (is_file and self.cut_file)):
                        response_buffer.extend(data)
                        boundary = response_buffer.find(b"\r\n\r\n")
                        if boundary < 0:
                            continue
                        # Forward real headers and at most one body byte, then lose TCP.
                        client.sendall(response_buffer[:boundary + 5])
                        client.shutdown(socket.SHUT_RDWR)
                        return
                    (remote if source is client else client).sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                self.connections.difference_update(pair)
            for connection in pair:
                connection.close()

    def cut(self):
        with self.lock:
            for connection in list(self.connections):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self):
        self.running = False
        self.cut()
        self.listener.close()
        self.thread.join(timeout=5)


@pytest.fixture
def cutting_api_server(tmp_path, request, monkeypatch):
    if request.node.get_closest_marker("real_local"):
        from tests.source_fixture import install_source
        install_source(monkeypatch)
    server = APIServer(tmp_path / "works")
    proxy = CuttingProxy(server.port)
    server.origin = proxy.origin
    server.settings = replace(server.settings, origin=proxy.origin)
    server.start()
    yield server, proxy
    proxy.close()
    server.stop()


@pytest.fixture(scope="session")
def browser(request):
    with sync_playwright() as p:
        name = request.config.getoption("--ui-browser")
        value = getattr(p, name).launch()
        print(f"\nUI browser: {value.browser_type.name} {value.version}")
        yield value
        value.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(accept_downloads=True)
    value = context.new_page()
    value.set_default_timeout(15000)
    yield value
    context.close()


class Scenario:
    """CONTROLLED ONLY. File bodies here are not real exported PDFs/ZIPs."""
    def __init__(self, origin):
        self.origin = origin
        self.posts = []
        self.requests = []
        self.work = None
        self.error = None
        self.download_error = None
        self.hold_export = False
        self.pending = None
        self.abort_export = False
        self.redirect_export = False
        self.bad_image = False
        self.category_error = False
        self.empty = False
        self.hold_search = False
        self.search_pending = None

    def task(self, ident):
        image = f"{self.origin}/api/v1/tasks/1/resources/image?url=https%3A%2F%2Fkpolyakov.spb.ru%2Ffigure.png"
        attachment = f"{self.origin}/api/v1/tasks/3/resources/attachment?url=https%3A%2F%2Fkpolyakov.spb.ru%2Fdata.ods"
        html = (f'<p>Условие {ident}: 2<sup>3</sup></p>'
                + ('<table border="1"><tr><td>Таблица</td><td>8</td></tr></table>'
                   f'<img src="{image}" alt="Рисунок">' if ident == 1 else "")
                + (f'<a href="{attachment}">data.ods</a>' if ident == 3 else "")
                + ("Вопрос 1. А<br>Вопрос 2. Б<br>Вопрос 3. В" if ident == 2 else ""))
        return validate({"id": ident, "ege_numbers": [19, 20, 21] if ident == 2 else [5],
                         "statement": f"Условие {ident}", "statement_html": html,
                         "source_url": f"https://kpolyakov.spb.ru/school/ege/gen.php?topicId={ident}",
                         "listing_url": "https://kpolyakov.spb.ru/school/ege/gen.php?egeId=5",
                         "images": [image] if ident == 1 else [],
                         "attachments": [attachment] if ident == 3 else []}, "Task")

    def make_work(self, ids):
        ident = str(uuid4())
        attached = 3 in ids
        def artifact(kind, filename, media, audience):
            return {"url": f"{self.origin}/api/v1/works/{ident}/files/{kind}",
                    "filename": filename, "media_type": media, "audience": audience}
        value = {"work_id": ident, "name": "Работа 2026-10-27 18:00:00",
                 "created_at": "2026-10-27T18:00:00Z", "topic_ids": ids,
                 "count": len(ids), "attachments": ["2.ods"] if attached else [],
                 "result": artifact("result", "work.zip" if attached else "work.pdf",
                                    "application/zip" if attached else "application/pdf", "student"),
                 "pdf": artifact("pdf", "work.pdf", "application/pdf", "preview"),
                 "archive": artifact("archive", "work.zip", "application/zip", "student") if attached else None,
                 "answers": artifact("answers", "work.answers.txt", "text/plain; charset=utf-8", "teacher"),
                 "sources": artifact("sources", "work.sources.json", "application/json", "teacher")}
        return validate(value, "Work")

    def finish(self):
        route, ids = self.pending
        self.pending = None
        self.work = self.make_work(ids)
        route.fulfill(status=201, json=self.work)

    def route(self, route):
        request = route.request
        parts = urlsplit(request.url)
        self.requests.append((request.method, parts.path, request.headers))
        path = parts.path
        params = parse_qs(parts.query)
        if "/resources/image" in path:
            if self.bad_image:
                route.abort()
            else:
                route.fulfill(body=PNG, content_type="image/png")
        elif path == "/api/v1/categories":
            if self.category_error:
                route.fulfill(status=502, json={"error": {"code": "source_error", "message": "Не удалось загрузить категории", "fields": []}})
                return
            number = int(params["ege_number"][0])
            route.fulfill(json=validate({"requested_ege_number": number, "ege_number": number,
                                        "categories": [{"id": 7, "title": "Категория"}]}, "CategoryResult"))
        elif path == "/api/v1/tasks":
            if self.error:
                status, code = self.error
                route.fulfill(status=status, json={"error": {"code": code, "message": "Источник недоступен", "fields": []}})
                return
            number = int(params["ege_number"][0])
            ids = [2] if number == 19 else [i for i in range(1, 112) if i != 2]
            if self.empty:
                ids = []
            offset = int(params.get("offset", [0])[0])
            value = validate({"requested_ege_number": number, "ege_number": number,
                              "total": len(ids), "offset": offset, "limit": 10,
                              "next_offset": offset + 10 if offset + 10 < len(ids) else None,
                              "source_url": "https://kpolyakov.spb.ru/school/ege/gen.php?egeId=5",
                              "tasks": [self.task(i) for i in ids[offset:offset + 10]]}, "SearchResult")
            if self.hold_search:
                self.search_pending = (route, value)
            else:
                route.fulfill(json=value)
        elif path == "/api/v1/works" and request.method == "POST":
            body = request.post_data_json
            validate(body, "CreateWork")
            assert list(body) == ["topic_ids"]
            self.posts.append(body)
            if self.abort_export:
                route.abort()
            elif self.redirect_export:
                route.fulfill(status=307, headers={"Location": self.origin + "/redirect-target"})
            elif self.error:
                status, code = self.error
                route.fulfill(status=status, json={"error": {"code": code, "message": "Не удалось создать работу", "fields": []}})
            elif self.hold_export:
                self.pending = (route, body["topic_ids"])
            else:
                self.work = self.make_work(body["topic_ids"])
                route.fulfill(status=201, json=self.work)
        elif "/files/" in path:
            if self.download_error:
                status, media, body = self.download_error
                route.fulfill(status=status, content_type=media, body=body)
            else:
                kind = path.rsplit("/", 1)[1]
                media = self.work[kind]["media_type"]
                body = json.dumps({"fixture": "teacher sources"}) if kind == "sources" else "CONTROLLED-FILE"
                route.fulfill(body=body, content_type=media)
        elif self.work and path.endswith(self.work["work_id"]):
            route.fulfill(json=self.work)
        else:
            route.abort()


@pytest.fixture
def scenario(page, api_server):
    value = Scenario(api_server.origin)
    page.route("**/*", lambda route: route.continue_() if
               urlsplit(route.request.url).netloc == urlsplit(api_server.origin).netloc else route.abort())
    page.route("**/api/v1/**", value.route)
    page.goto(api_server.origin)
    return value


def search(page, number="5"):
    page.get_by_label("Номер задания ЕГЭ", exact=True).select_option(number)
    page.get_by_label("Категория", exact=True).wait_for(state="visible")
    from playwright.sync_api import expect
    expect(page.get_by_label("Категория", exact=True)).to_be_enabled(timeout=90000)
    with page.expect_response(lambda r: "/api/v1/tasks?" in r.url, timeout=180000) as observed:
        page.get_by_role("button", name="Найти задачи", exact=True).click()
    assert observed.value.status == 200, observed.value.text()
    validate(observed.value.json(), "SearchResult")
    expect(page.locator("#search-status")).to_have_attribute("data-state", "ready", timeout=180000)


def add(page, ident):
    page.locator(f'.task-card[data-task-id="{ident}"] .add-task').click()
