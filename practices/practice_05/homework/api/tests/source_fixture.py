"""Synthetic upstream HTTP only: Bank/parser/export_pdf remain real."""
import json
from urllib.parse import parse_qs

import httpx

from tests.conftest import ATTACHMENT, IMAGE, PNG


def statement(ident):
    if ident == 2:
        return 'TASK-002 Вопрос 1. А<br>Вопрос 2. Б<br>Вопрос 3. В'
    if ident == 3:
        return f'TASK-003 <a href="{ATTACHMENT}">data.ods</a> <a href="{ATTACHMENT}">Скачать таблицу</a>'
    if ident == 1:
        return f'TASK-001 <table border="1"><tr><td>Таблица 2<sup>3</sup></td></tr></table><img src="{IMAGE}">'
    return f'TASK-{ident:03d} Оригинал тестового источника'


def row(ident):
    number = "19 20 21" if ident == 2 else "5"
    answer = "1) 41<br>2) 36 40<br>3) 35" if ident == 2 else f"SECRET_{ident:03d}"
    return (f'<tr><td class="egeno">{number}</td><td class="topicview">(№&nbsp;{ident})'
            f'<script>document.write(changeImageFilePath({json.dumps(statement(ident))}));</script></td></tr>'
            f'<tr><td></td><td><div class="hidedata" id="{ident}"><script>'
            f'document.write(changeImageFilePath({json.dumps(answer)}));</script></div></td></tr>')


def page(ids, number=5):
    return (f'Задание КИМ № {number}<input id="imagePath" value="/cms/images/">'
            '<input id="filePath" value="/cms/files/"><table>' + ''.join(row(i) for i in ids) + '</table>')


def install_source(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == IMAGE:
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"}, request=request)
        if str(request.url) == ATTACHMENT:
            return httpx.Response(200, content=b"PK\x00fixture-ods", request=request)
        params = parse_qs(request.url.query.decode())
        action = params.get("action", [""])[0]
        if action == "listCategories":
            return httpx.Response(200, json=[{"id": 7, "title": "Тестовая категория"}], request=request)
        if action == "viewTopic":
            ident = int(params["topicId"][0])
            if not 1 <= ident <= 100:
                return httpx.Response(404, request=request)
            return httpx.Response(200, text=page([ident], 19 if ident == 2 else 5), request=request)
        if action == "viewAllEgeNo":
            number = int(params["egeId"][0])
            ids = [2] if number == 19 else [i for i in range(1, 101) if i != 2]
            return httpx.Response(200, text=page(ids, number), request=request)
        return httpx.Response(404, request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.Client, "get", lambda client, url: transport.handle_request(httpx.Request("GET", url)))
    return calls
