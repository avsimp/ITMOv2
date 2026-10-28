"""Единая вёрстка: только нумерация и оригинальные условия, без ответов."""

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

import pymupdf
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from polyakov import SourceError


class OutputConflictError(SourceError):
    """Existing output must not be overwritten; compatible with SourceError callers."""


CSS = """
@page { size: A4; margin: 18mm; }
body { font-family: 'Times New Roman', 'Liberation Serif', serif;
       font-size: 12pt; line-height: 1.25; color: black; margin: 0; }
.task { margin-bottom: 8mm; break-inside: avoid; }
.number { float: left; margin-right: 2mm; }
p { margin: 0 0 3mm; } .lmar { margin-left: 6mm; }
img { display: block; max-width: 100%; max-height: 225mm;
      object-fit: contain; margin: 3mm 0; break-inside: avoid; }
img.in { display: inline; margin: 0; }
table { border-collapse: collapse; max-width: 100%; break-inside: avoid; }
td, th { padding: 2px 5px; } table[border] td, table[border] th { border: 1px solid; }
a { color: black; text-decoration: none; }
pre { white-space: pre-wrap; } sub, sup { line-height: 0; }
"""


def answer_line(number, task):
    answer = task["answer"]
    if task["ege_numbers"] == [19, 20, 21]:
        parts = re.split(r"[123]\)", answer)
        if len(parts) != 4 or parts[0].strip() or not all(p.strip() for p in parts[1:]):
            raise SourceError(f"Не распознаны три ответа задачи {task['id']}")
        answer = "; ".join(f"{n}) {' '.join(value.split())}" for n, value in zip((19, 20, 21), parts[1:]))
    else:
        answer = " ".join(answer.split())
    return f"{number}. {answer}"


def plan_attachments(soup, number, task_id, assets_name):
    """Имена по позиции пункта; повтор URL внутри пункта — одно приложение."""
    urls = list(dict.fromkeys(link["href"] for link in soup.select("a[href]")))
    plan = []
    for index, url in enumerate(urls, 1):
        original = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        extension = "".join(Path(original).suffixes)
        stem = str(number) if len(urls) == 1 else f"{number}_{index}"
        filename = stem + extension
        plan.append({"task_number": number, "task_id": task_id, "source_url": url,
                     "original_filename": original, "filename": filename,
                     "relative_path": assets_name + "/" + filename})
    return plan


def normalize_pdf_links(pdf, markers):
    """Сохраняем геометрию ссылок Chromium, делая файловые назначения переносимыми."""
    found = set()
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        for page in document:
            for link in page.get_links():
                marker = link.get("uri")
                if marker in markers:
                    link["kind"] = pymupdf.LINK_LAUNCH
                    link["file"] = markers[marker]
                    del link["uri"]
                    page.update_link(link)
                    found.add(marker)
        if found != set(markers):
            raise SourceError("В PDF потеряны ссылки на приложения; экспорт не создан")
        return document.tobytes(garbage=4, deflate=True)


def write_new(path, data):
    with path.open("xb") as output:
        output.write(data)


def export_pdf(bank, topic_ids, output_path):
    if not topic_ids or len(topic_ids) > 100 or len(set(topic_ids)) != len(topic_ids):
        raise SourceError("Нужно от 1 до 100 уникальных ID; одна тройка 19–21 — один ID")
    path = Path(output_path).expanduser()
    if not path.is_absolute() or path.suffix.lower() != ".pdf":
        raise SourceError("Укажите абсолютный путь с расширением .pdf")
    manifest_path = path.with_suffix(".sources.json")
    answers_path = path.with_suffix(".answers.txt")
    assets_path = path.with_suffix(".files")
    archive_path = path.with_suffix(".zip")
    if any(p.exists() or p.is_symlink() for p in (path, manifest_path, answers_path, assets_path, archive_path)):
        raise OutputConflictError("Файл или сопутствующие материалы уже существуют; выберите новое имя")
    tasks = [bank.get(ident) for ident in topic_ids]
    answers = "\n".join(answer_line(i, task) for i, task in enumerate(tasks, 1))
    sections = []
    attachments = {}
    attachment_map = []
    link_markers = {}
    for number, task in enumerate(tasks, 1):
        soup = BeautifulSoup(task["statement_html"], "html.parser")
        for img in soup.select("img[src]"):
            response = bank.fetch(img["src"])
            mime = response.headers.get("content-type", "").split(";")[0]
            if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}:
                raise SourceError(f"Не удалось получить изображение {img['src']}")
            encoded = base64.b64encode(response.content).decode()
            img["src"] = f"data:{mime};base64,{encoded}"
        plan = plan_attachments(soup, number, task["id"], assets_path.name)
        attachment_map.extend(plan)
        by_url = {entry["source_url"]: entry for entry in plan}
        for entry in plan:
            attachments[entry["filename"]] = bank.fetch(entry["source_url"]).content
        for link_index, link in enumerate(soup.select("a[href]"), 1):
            entry = by_url[link["href"]]
            if link.get_text() == entry["original_filename"]:
                # Меняем текстовые узлы, сохраняя оформляющие теги внутри ссылки.
                nodes = list(link.find_all(string=True))
                remaining = entry["filename"]
                for index, node in enumerate(nodes):
                    text = remaining if index == len(nodes) - 1 else remaining[:len(node)]
                    remaining = remaining[len(node):]
                    node.replace_with(text)
                if not nodes:
                    link.append(remaining)
            marker = f"https://homework.invalid/{number}/{link_index}"
            link_markers[marker] = entry["relative_path"]
            link["href"] = marker
        sections.append(f'<div class="task"><span class="number">{number})</span>{soup}</div>')
    html = '<!doctype html><html lang="ru"><meta charset="utf-8"><style>' + CSS + '</style><body>' + "".join(sections) + '</body></html>'
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(html)
            page.evaluate("document.fonts.ready")
            if not page.evaluate("Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)"):
                raise SourceError("Есть незагруженные изображения; PDF не создан")
            pdf = page.pdf(format="A4", display_header_footer=False, prefer_css_page_size=True)
        finally:
            browser.close()
    if link_markers:
        pdf = normalize_pdf_links(pdf, link_markers)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                "format_version": 1, "tasks": tasks,
                "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                "attachments": list(attachments), "attachment_map": attachment_map}
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_new(path, pdf)
        write_new(answers_path, (answers + "\n").encode("utf-8"))
        write_new(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        if attachments:
            assets_path.mkdir()
            for filename, data in attachments.items():
                write_new(assets_path / filename, data)
            with ZipFile(archive_path, "x", compression=ZIP_DEFLATED) as archive:
                archive.writestr(path.name, pdf)
                for filename, data in attachments.items():
                    archive.writestr(assets_path.name + "/" + filename, data)
    except FileExistsError as exc:
        raise OutputConflictError("Файл или сопутствующие материалы уже существуют; выберите новое имя") from exc
    return {"pdf": str(path), "sources": str(manifest_path), "answers_file": str(answers_path),
            "answers": answers, "count": len(tasks), "attachments": list(attachments),
            "result_file": str(archive_path if attachments else path),
            "archive": str(archive_path) if attachments else None}
