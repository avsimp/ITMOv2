"""Получение оригинальных задач из генератора К. Полякова без исполнения JS."""

import re
import time
from urllib.parse import urlencode, urljoin, urlsplit

import httpx
import json5
from bs4 import BeautifulSoup

BASE = "https://kpolyakov.spb.ru/school/ege/gen.php"
HOST = "kpolyakov.spb.ru"
LITERAL = r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
CONTENT = re.compile(r"changeImageFilePath\(\s*(" + LITERAL + r")\s*\)", re.DOTALL)


class SourceError(ValueError):
    """Ожидаемая ошибка источника, понятная пользователю MCP."""


def source_url(**params):
    return BASE + "?" + urlencode(params)


def allowed_url(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.hostname != HOST:
        raise SourceError(f"Ресурс вне разрешённого источника: {url}")
    if parts.username or parts.password or parts.port not in {None, 80, 443}:
        raise SourceError("Некорректный адрес ресурса")
    return parts._replace(scheme="https").geturl()


def plain(html):
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return soup.get_text(" ", strip=True).replace("\xa0", " ")


def extract_content(element):
    if element is None:
        raise SourceError("Не найдено условие или ответ: разметка сайта изменилась")
    scripts = "\n".join(s.get_text() for s in element.find_all("script"))
    literals = CONTENT.findall(scripts)
    if not literals:
        raise SourceError("Не удалось извлечь данные из changeImageFilePath")
    return "".join(json5.loads(value) for value in literals)


def normalize_html(html, image_base, file_base):
    soup = BeautifulSoup(html, "html.parser")
    # Сохраняем таблицы, индексы и иллюстрации, но не исполняемый код.
    for tag in soup.find_all(["script", "style", "iframe", "object", "embed"]):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr not in {"src", "href", "colspan", "rowspan", "border", "alt", "class"}:
                del tag[attr]
        for attr, base in (("src", image_base), ("href", file_base)):
            if tag.has_attr(attr):
                value = tag[attr]
                # Именно такая семантика у changeImageFilePath на сайте:
                # начальный ':' означает ссылку без префикса cms/files.
                target = urljoin(BASE, value[1:]) if value.startswith(":") else urljoin(base, value)
                tag[attr] = allowed_url(target)
    return str(soup)


def parse_tasks(html, url, topic_id=None):
    soup = BeautifulSoup(html, "html.parser")
    image = soup.select_one("#imagePath")
    files = soup.select_one("#filePath")
    if not image or not files:
        raise SourceError("Задача не найдена или сайт вернул неожиданную страницу")
    image_base = urljoin(BASE, image["value"])
    file_base = urljoin(BASE, files["value"])
    tasks = []
    page_text = soup.get_text(" ", strip=True)
    for cell in soup.select("td.topicview"):
        row = cell.find_parent("tr")
        if topic_id is None:
            match = re.search(r"№(?:&nbsp;|\s)*(\d+)", str(cell))
            if not match:
                raise SourceError("Не найден ID задачи")
            ident = int(match[1])
            numbers = [int(n) for n in re.findall(r"\d+", row.select_one(".egeno").get_text())]
        else:
            ident = topic_id
            match = re.search(r"Задание КИМ №\s*(\d+)", page_text)
            if not match:
                raise SourceError("Не найден номер КИМ")
            numbers = [int(match[1])]
            if numbers == [19]:
                numbers = [19, 20, 21]
        answer_row = row.find_next_sibling("tr")
        answer = answer_row.select_one(f'div.hidedata[id="{ident}"]') if answer_row else None
        statement = normalize_html(extract_content(cell), image_base, file_base)
        answer_html = normalize_html(extract_content(answer), image_base, file_base)
        if not plain(statement) or not plain(answer_html):
            raise SourceError(f"Пустое условие или ответ у задачи {ident}")
        if numbers == [19, 20, 21] and not all(
            re.search(rf"Вопрос\s+{n}\b", plain(statement)) for n in (1, 2, 3)
        ):
            raise SourceError(f"Не подтверждена полная тройка 19–21 у задачи {ident}")
        fragment = BeautifulSoup(statement, "html.parser")
        tasks.append({
            "id": ident,
            "ege_numbers": numbers,
            "source_url": source_url(action="viewTopic", topicId=ident),
            "listing_url": url,
            "statement_html": statement,
            "statement": plain(statement),
            "answer_html": answer_html,
            "answer": plain(answer_html),
            "images": [img["src"] for img in fragment.select("img[src]")],
            "attachments": [a["href"] for a in fragment.select("a[href]")],
        })
    if not tasks:
        raise SourceError("На странице нет задач: проверьте ID и категории")
    if len({t["id"] for t in tasks}) != len(tasks):
        raise SourceError("Источник вернул повторяющиеся ID")
    return tasks


class Bank:
    def __init__(self):
        self.cache = {}

    def fetch(self, url):
        url = allowed_url(url)
        cached = self.cache.get(url)
        if cached and time.monotonic() - cached[0] < 900:
            return cached[1]
        try:
            with httpx.Client(timeout=45, follow_redirects=False) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceError(f"Не удалось загрузить {url}: {exc}") from exc
        self.cache[url] = (time.monotonic(), response)
        return response

    def categories(self, ege_number):
        if ege_number in (20, 21):
            ege_number = 19
        if not 1 <= ege_number <= 27:
            raise SourceError("Номер КИМ должен быть от 1 до 27")
        response = self.fetch(source_url(action="listCategories", egeId=ege_number))
        try:
            data = response.json()
            if not isinstance(data, list) or not data:
                raise ValueError("Пустой список")
            return [{"id": int(c["id"]), "title": c["title"]} for c in data]
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError("Не удалось прочитать категории сайта") from exc

    def search(self, ege_number, category_ids=None, contains="", exclude_ids=None, offset=0, limit=10):
        categories = self.categories(ege_number)
        available = {c["id"] for c in categories}
        selected = available if category_ids is None else set(category_ids)
        if not selected or not selected <= available:
            raise SourceError("Категории не принадлежат выбранному номеру КИМ")
        if offset < 0 or not 1 <= limit <= 30:
            raise SourceError("offset должен быть >= 0, limit — от 1 до 30")
        ege_number = 19 if ege_number in (20, 21) else ege_number
        params = {"action": "viewAllEgeNo", "egeId": ege_number}
        params.update({f"cat{ident}": "on" for ident in sorted(selected)})
        url = source_url(**params)
        tasks = parse_tasks(self.fetch(url).text, url)
        excluded = set(exclude_ids or [])
        tasks = [t for t in tasks if t["id"] not in excluded and contains.casefold() in t["statement"].casefold()]
        return {"total": len(tasks), "offset": offset, "source_url": url,
                "tasks": tasks[offset:offset + limit],
                "next_offset": offset + limit if offset + limit < len(tasks) else None}

    def get(self, topic_id):
        if topic_id <= 0:
            raise SourceError("ID задачи должен быть положительным")
        url = source_url(action="viewTopic", topicId=topic_id)
        response = self.fetch(url)
        return parse_tasks(response.text, url, topic_id=topic_id)[0]
