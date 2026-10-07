"""Единая вёрстка: только нумерация и оригинальные условия, без ответов."""

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from polyakov import SourceError

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


def export_pdf(bank, topic_ids, output_path):
    if not topic_ids or len(topic_ids) > 100 or len(set(topic_ids)) != len(topic_ids):
        raise SourceError("Нужно от 1 до 100 уникальных ID; одна тройка 19–21 — один ID")
    path = Path(output_path).expanduser()
    if not path.is_absolute() or path.suffix.lower() != ".pdf":
        raise SourceError("Укажите абсолютный путь с расширением .pdf")
    manifest_path = path.with_suffix(".sources.json")
    answers_path = path.with_suffix(".answers.txt")
    assets_path = path.with_suffix(".files")
    if any(p.exists() for p in (path, manifest_path, answers_path, assets_path)):
        raise SourceError("Файл или сопутствующие материалы уже существуют; выберите новое имя")
    tasks = [bank.get(ident) for ident in topic_ids]
    answers = "\n".join(answer_line(i, task) for i, task in enumerate(tasks, 1))
    sections = []
    attachments = {}
    for number, task in enumerate(tasks, 1):
        soup = BeautifulSoup(task["statement_html"], "html.parser")
        for img in soup.select("img[src]"):
            response = bank.fetch(img["src"])
            mime = response.headers.get("content-type", "").split(";")[0]
            if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}:
                raise SourceError(f"Не удалось получить изображение {img['src']}")
            encoded = base64.b64encode(response.content).decode()
            img["src"] = f"data:{mime};base64,{encoded}"
        for link in soup.select("a[href]"):
            url = link["href"]
            response = bank.fetch(url)
            filename = Path(urlsplit(url).path).name
            filename = f"{task['id']}-{hashlib.sha256(url.encode()).hexdigest()[:8]}-{filename}"
            attachments[filename] = response.content
            link["href"] = assets_path.name + "/" + filename
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
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                "format_version": 1, "tasks": tasks,
                "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                "attachments": list(attachments)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf)
    answers_path.write_text(answers + "\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if attachments:
        assets_path.mkdir()
        for filename, data in attachments.items():
            (assets_path / filename).write_bytes(data)
    return {"pdf": str(path), "sources": str(manifest_path), "answers_file": str(answers_path),
            "answers": answers, "count": len(tasks), "attachments": list(attachments)}
