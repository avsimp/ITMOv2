"""Actual UI + HTTP API + original Bank/export. Levels are never relabelled."""
import hashlib
import io
import json
import time
from pathlib import Path
from zipfile import ZipFile

import httpx
import pymupdf
import pytest
from conftest import add, search
from contract_support import validate
from playwright.sync_api import expect


def selected(page):
    return page.evaluate("""async()=>{const {state}=await import('/assets/state.js');
        return state.selection.ids.map(id=>state.selection.tasks.get(id));}""")


def page_tasks(page):
    return page.evaluate("async()=> (await import('/assets/state.js')).state.page.tasks")


def create(page, journal):
    ids = [task["id"] for task in selected(page)]
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/v1/works"), timeout=240000) as observed:
        page.locator("#create-work").click()
    response = observed.value
    assert response.status == 201, response.text()
    work = validate(response.json(), "Work")
    assert work["topic_ids"] == ids
    journal["works"].append(work)
    expect(page.locator("#export-status")).to_have_attribute("data-state", "succeeded", timeout=15000)
    return work


def receive(page, kind, folder):
    page.locator(f'[data-download="{kind}"]').click()
    expect(page.locator("#save-file")).to_be_visible(timeout=90000)
    with page.expect_download() as pending:
        page.locator("#save-file").click()
    download = pending.value
    path = folder / download.suggested_filename
    download.save_as(path)
    return path.read_bytes()


def check_materials(page, work, journal, expected_tasks):
    folder = Path(journal["folder"]) / work["work_id"]
    folder.mkdir()
    result = receive(page, "result", folder)
    answers = receive(page, "answers", folder).decode("utf-8")
    manifest = validate(json.loads(receive(page, "sources", folder)), "SourcesManifest")
    pdf_response = page.request.get(work["pdf"]["url"])
    assert pdf_response.status == 200
    pdf = pdf_response.body()
    (folder / "preview.pdf").write_bytes(pdf)
    assert manifest["pdf_sha256"] == hashlib.sha256(pdf).hexdigest()
    assert [task["id"] for task in manifest["tasks"]] == work["topic_ids"]
    # Browser projection changes resource URLs, not plain original statement content.
    for before, exported in zip(expected_tasks, manifest["tasks"]):
        assert before["id"] == exported["id"]
        assert before["statement"] == exported["statement"]
    assert "19)" in answers and "20)" in answers and "21)" in answers
    if work["archive"]:
        with ZipFile(io.BytesIO(result)) as archive:
            assert set(archive.namelist()) == {"work.pdf", *("work.files/" + name for name in work["attachments"])}
            assert archive.read("work.pdf") == pdf
            archive.extractall(folder / "unpacked")
            with pymupdf.open(stream=pdf, filetype="pdf") as document:
                for sheet in document:
                    for link in sheet.get_links():
                        if "file" in link:
                            assert (folder / "unpacked" / link["file"]).is_file()
    else:
        assert result == pdf
    assert page.request.get(work["result"]["url"]).body() == result
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        assert len(document) > 0
        assert all(abs(sheet.rect.width - 595) < 2 for sheet in document)
        for index, sheet in enumerate(document):
            sheet.get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(folder / f"page-{index + 1}.png")
    journal.setdefault("material_checks", []).append({"work_id": work["work_id"],
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(), "count": work["count"], "kind": work["result"]["media_type"]})
    return manifest, pdf


def clear(page):
    while page.locator("#selection li").count():
        page.locator("#selection li").first.get_by_role("button", name="Удалить", exact=True).click()


@pytest.mark.real_local
def test_fixed_source_real_ui_pdf_zip_contract_restart(page, api_server, journal):
    page.goto(api_server.origin)
    search(page)
    add(page, 1)
    add(page, 4)
    expect(page.locator('.task-card[data-task-id="1"] table')).to_contain_text("Таблица")
    assert page.locator('.task-card[data-task-id="1"] img').evaluate("img=>img.complete && img.naturalWidth>0")
    search(page, "19")
    add(page, 2)
    page.locator('#selection li[data-task-id="2"] [data-action="up"]').click()
    originals = selected(page)
    work = create(page, journal)
    assert work["topic_ids"] == [1, 2, 4]
    manifest, pdf = check_materials(page, work, journal, originals)
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        content = "\n".join(sheet.get_text() for sheet in document)
        assert content.index("TASK-001") < content.index("TASK-002") < content.index("TASK-004")
        assert "SECRET_" not in content and "Вопрос 3." in content
    assert manifest["tasks"][0]["images"]
    clear(page)
    search(page, "19")
    add(page, 2)
    search(page)
    add(page, 3)
    originals = selected(page)
    zipped = create(page, journal)
    assert zipped["result"]["media_type"] == "application/zip"
    expect(page.locator("#preview-pdf")).to_have_attribute("href", zipped["pdf"]["url"])
    check_materials(page, zipped, journal, originals)
    api_server.stop()
    api_server.start()
    page.locator("#refresh-work").click()
    expect(page.locator("#metadata-status")).to_have_text("Сведения о работе обновлены.")
    assert page.request.get(zipped["result"]["url"]).status == 200
    # Isolated test-owned storage, not source code or the API's default exports.
    (api_server.settings.storage_root / zipped["work_id"] / "work.answers.txt").unlink()
    page.locator('[data-download="answers"]').click()
    expect(page.locator("#download-status")).to_have_attribute("data-state", "error")
    assert page.request.get(zipped["sources"]["url"]).status == 200
    for header, status in [("bytes=0-3", 206), ("bytes=0-3,8-11", 206), ("items=0-3", 400), ("bytes=999999999-", 416)]:
        response = page.request.get(zipped["pdf"]["url"], headers={"Range": header})
        assert response.status == status
        if status in {400, 416}:
            assert "text/plain" in response.headers["content-type"]
    missing = page.request.get(zipped["answers"]["url"], headers={"Range": "items=0-3"})
    assert missing.status == 404 and missing.json()["error"]["code"] == "not_found"
    wrong_post = page.request.post(api_server.origin + "/api/v1/works/", data={"topic_ids": [1]}, max_redirects=0)
    assert wrong_post.status == 404 and "location" not in wrong_post.headers
    page.screenshot(path=str(Path(journal["folder"]) / "ui.png"), full_page=True)


@pytest.mark.real_local
def test_real_api_confirmed_source_error(page, api_server, monkeypatch, journal):
    page.goto(api_server.origin)
    search(page)
    add(page, 4)
    def unavailable(client, url):
        raise httpx.ConnectError("Controlled upstream outage", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", unavailable)
    page.locator("#create-work").click()
    expect(page.locator("#export-status")).to_have_attribute("data-state", "failed", timeout=90000)
    expect(page.locator("#create-work")).to_be_enabled(timeout=1000)
    expect(page.locator("#selection-count")).to_have_text("1 / 100")
    assert [call["status"] for call in journal["calls"] if call["method"] == "POST"] == [502]


@pytest.mark.live_ui
def test_live_full_cycle_without_substitutions(page, api_server, journal):
    page.goto(api_server.origin)
    chosen = []
    for number in ["1", "5", "19"]:
        search(page, number)
        task = next(task for task in page_tasks(page) if not task["attachments"])
        add(page, task["id"])
        chosen.append(task)
        if page.locator("#next-page").is_enabled():
            page.locator("#next-page").click()
            expect(page.locator("#search-status")).to_have_attribute("data-state", "ready", timeout=180000)
            expect(page.locator("#selection-count")).to_have_text(f"{len(chosen)} / 100")
            page.locator("#previous-page").click()
            expect(page.locator("#search-status")).to_have_attribute("data-state", "ready", timeout=180000)
    assert any(task["images"] for task in chosen)
    page.locator(f'#selection li[data-task-id="{chosen[2]["id"]}"] [data-action="up"]').click()
    originals = selected(page)
    work = create(page, journal)
    check_materials(page, work, journal, originals)
    clear(page)
    search(page, "19")
    game = page_tasks(page)[0]
    add(page, game["id"])
    search(page, "9")
    attached = next(task for task in page_tasks(page) if task["attachments"])
    add(page, attached["id"])
    originals = selected(page)
    zipped = create(page, journal)
    assert zipped["result"]["media_type"] == "application/zip"
    check_materials(page, zipped, journal, originals)
    api_server.stop()
    api_server.start()
    page.locator("#refresh-work").click()
    expect(page.locator("#metadata-status")).to_have_text("Сведения о работе обновлены.")
    (api_server.settings.storage_root / zipped["work_id"] / "work.answers.txt").unlink()
    page.locator('[data-download="answers"]').click()
    expect(page.locator("#download-status")).to_have_attribute("data-state", "error")
    assert page.request.get(zipped["sources"]["url"]).status == 200
    assert page.request.post(api_server.origin + "/api/v1/works/", data={"topic_ids": [game["id"]]}, max_redirects=0).status == 404
    for header, status in [("bytes=0-3", 206), ("bytes=0-3,8-11", 206), ("items=0-3", 400), ("bytes=999999999-", 416)]:
        response = page.request.get(zipped["pdf"]["url"], headers={"Range": header})
        assert response.status == status
        if status in {400, 416}:
            assert "text/plain" in response.headers["content-type"]
    assert page.request.get(zipped["answers"]["url"], headers={"Range": "items=0-3"}).json()["error"]["code"] == "not_found"
    malformed = page.request.post(api_server.origin + "/api/v1/works", data=b"{", headers={"Content-Type": "application/json"})
    assert malformed.status == 400
    validate(malformed.json(), "ErrorResponse")
    page.screenshot(path=str(Path(journal["folder"]) / "ui.png"), full_page=True)


@pytest.mark.live_ui
def test_live_transport_error_preserves_selection(page, api_server, journal):
    page.goto(api_server.origin)
    search(page, "5")
    task = next(task for task in page_tasks(page) if not task["attachments"])
    add(page, task["id"])
    page.context.set_offline(True)
    page.get_by_role("button", name="Найти задачи", exact=True).click()
    expect(page.locator("#search-status")).to_have_attribute("data-state", "error")
    expect(page.locator("#selection-count")).to_have_text("1 / 100")
    assert [task["id"] for task in selected(page)] == [task["id"]]
    page.locator("#selection li [data-action=remove]").click()
    expect(page.locator("#selection-count")).to_have_text("0 / 100")
    page.context.set_offline(False)
    page.locator("#retry-search").click()
    expect(page.locator("#search-status")).to_have_attribute("data-state", "ready", timeout=90000)
    invalid = page.request.get(api_server.origin + "/api/v1/tasks?ege_number=0")
    assert invalid.status == 422
    validate(invalid.json(), "ErrorResponse")


@pytest.mark.live_ui
def test_live_selection_and_pages_without_export(page, api_server, journal):
    page.goto(api_server.origin)
    posts = []
    page.on("request", lambda req: posts.append(req.url) if req.method == "POST" else None)
    ids = []
    for number in ["1", "5", "19"]:
        search(page, number)
        if number == "5":
            category = page.get_by_label("Категория", exact=True).locator("option").nth(1).get_attribute("value")
            page.get_by_label("Категория", exact=True).select_option(category)
            page.get_by_role("button", name="Найти задачи", exact=True).click()
            expect(page.locator("#search-status")).to_have_attribute("data-state", "ready", timeout=180000)
        task = next(task for task in page_tasks(page) if not task["attachments"])
        add(page, task["id"])
        ids.append(task["id"])
        expect(page.locator(f'.task-card[data-task-id="{task["id"]}"] .add-task')).to_be_disabled()
    page.locator(f'#selection li[data-task-id="{ids[2]}"] [data-action="up"]').click()
    page.locator(f'#selection li[data-task-id="{ids[0]}"] [data-action="remove"]').click()
    search(page, "1")
    add(page, ids[0])
    expected = [ids[2], ids[1], ids[0]]
    page.locator("#next-page").click()
    expect(page.locator("#search-status")).to_have_attribute("data-state", "ready", timeout=180000)
    page.locator("#previous-page").click()
    expect(page.locator("#search-status")).to_have_attribute("data-state", "ready", timeout=180000)
    assert [task["id"] for task in selected(page)] == expected
    assert page.locator("#selection li").evaluate_all("els=>els.map(e=>Number(e.dataset.taskId))") == expected
    assert not posts
    journal["selection_without_export"] = {"topic_ids": expected, "post_count": 0}


@pytest.mark.real_local
def test_real_file_transfer_cut_never_offers_partial_blob(page, cutting_api_server, journal):
    server, proxy = cutting_api_server
    page.goto(server.origin)
    search(page)
    add(page, 4)
    work = create(page, journal)
    proxy.cut_file = True
    page.locator('[data-download="result"]').click()
    expect(page.locator("#download-status")).to_have_attribute("data-state", "error")
    expect(page.locator("#save-file")).to_be_hidden()
    expect(page.locator("#export-status")).to_have_attribute("data-state", "succeeded")
    proxy.cut_file = False
    page.locator('[data-download="result"]').click()
    expect(page.locator("#save-file")).to_be_visible()
    assert len(list(server.settings.storage_root.glob("*"))) == 1
    assert page.request.get(work["sources"]["url"]).status == 200


def disconnect_scenario(page, cutting_api_server, journal, before_headers=False):
    server, proxy = cutting_api_server
    page.goto(server.origin)
    search(page, "5")
    task = next(task for task in page_tasks(page) if not task["attachments"])
    add(page, task["id"])
    posts = []
    page.on("request", lambda req: posts.append(req.post_data_json) if req.method == "POST" else None)
    page.locator("#create-work").click()
    deadline = time.monotonic() + 60
    folder = None
    while time.monotonic() < deadline:
        folders = list(server.settings.storage_root.glob("*"))
        if folders:
            folder = folders[0]
            break
        page.wait_for_timeout(5)
    assert folder and not (folder / "work.json").exists(), "Need a real in-progress server export before cutting TCP"
    if before_headers:
        proxy.cut()
    else:
        proxy.cut_response = True
    try:
        expect(page.locator("#export-status")).to_have_attribute("data-state", "unknown", timeout=15000)
    finally:
        journal["disconnect_probe"] = {"before_headers": before_headers, "fetch_requests": len(posts),
            "relay_post_requests": proxy.post_count,
            "server_work_ids": [p.name for p in server.settings.storage_root.glob("*")],
            "ui_state": page.locator("#export-status").get_attribute("data-state")}
    expect(page.locator("#create-work")).to_be_enabled(timeout=1000)
    expect(page.locator("#selection-count")).to_have_text("1 / 100")
    expect(page.locator("#export-status")).to_contain_text("Предыдущая работа могла быть создана")
    assert len(posts) == 1
    # Private storage observation proves server completion, not a recovery endpoint for UI.
    deadline = time.monotonic() + 180
    while not (folder / "work.json").exists() and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert (folder / "work.json").exists()
    assert len(posts) == 1
    assert len(list(server.settings.storage_root.glob("*"))) == 1
    proxy.cut_response = False
    page.locator("#create-work").click()
    expect(page.locator("#export-status")).to_have_attribute("data-state", "succeeded", timeout=240000)
    assert len(posts) == 2
    journal["disconnect"] = {"method": "TCP loss after real response headers, before complete JSON body",
        "topic_ids": [task["id"]], "observed_previous_work_id": folder.name,
        "observation": "test-only private storage, never shown/recovered by UI",
        "automatic_retries": 0, "explicit_new_posts": 1}
    page.screenshot(path=str(Path(journal["folder"]) / "ui.png"), full_page=True)


@pytest.mark.live_ui
def test_live_post_disconnect_is_unknown_not_retry(page, cutting_api_server, journal):
    disconnect_scenario(page, cutting_api_server, journal)


@pytest.mark.boundary_probe
def test_pre_header_disconnect_boundary_probe(page, cutting_api_server, journal):
    """Known unresolved boundary. Explicit opt-in, no xfail/skip disguising it."""
    disconnect_scenario(page, cutting_api_server, journal, before_headers=True)
