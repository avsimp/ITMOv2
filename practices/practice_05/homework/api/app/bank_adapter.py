"""Reuse the original modules without importing/starting the MCP server."""
import re
import sys
from urllib.parse import quote, unquote, urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup, Comment

from app.config import SOURCE_ROOT
from app.errors import ApiError, invalid, missing
from app.schemas import CategoryResult, SearchResult, Task

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from polyakov import Bank as Bank, SourceError, allowed_url  # noqa: E402
from render import export_pdf as export_pdf  # noqa: E402

IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
SVG_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
TAGS = set("p div span br table tr td th thead tbody tfoot caption col colgroup ul ol li b strong i em u sub sup pre code img a font center hr h1 h2 h3 h4 h5 h6 small s del tt".split())
EXECUTABLE = {"script", "style", "iframe", "object", "embed", "meta", "link", "base"}
UNSUPPORTED_ACTIVE = {"form", "input", "button", "template"}


def source_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ApiError:
        raise
    except Exception as exc:
        cause, seen = exc, set()
        while cause is not None and id(cause) not in seen:
            if isinstance(cause, httpx.TimeoutException):
                raise ApiError(504, "source_timeout", "Источник не ответил вовремя") from exc
            seen.add(id(cause))
            cause = cause.__cause__
        raise ApiError(502, "source_error", "Не удалось получить полные данные источника") from exc


class BankAdapter:
    def __init__(self, bank, settings):
        self.bank, self.settings = bank, settings

    def get(self, ident):
        return source_call(self.bank.get, ident)

    def fetch(self, url):
        checked = source_call(allowed_url, url)
        return source_call(self.bank.fetch, checked)

    def categories(self, number):
        return source_call(CategoryResult, requested_ege_number=number,
                           ege_number=19 if number in {20, 21} else number,
                           categories=source_call(self.bank.categories, number)).model_dump()

    def search(self, number, category_ids, contains, exclude_ids, offset, limit):
        available = {item["id"] for item in self.categories(number)["categories"]}
        if category_ids is not None and (not category_ids or not set(category_ids) <= available):
            raise invalid("category_ids", "Категории не принадлежат выбранному номеру ЕГЭ")
        found = source_call(self.bank.search, number, category_ids, contains, exclude_ids, offset, limit)
        result = dict(found, requested_ege_number=number, ege_number=19 if number in {20, 21} else number,
                      limit=limit, tasks=[source_call(self.presentation, item) for item in found["tasks"]])
        return source_call(SearchResult.model_validate, result).model_dump()

    def resource_url(self, ident, kind, url):
        source_call(allowed_url, url)
        return self.settings.url(f"/api/v1/tasks/{ident}/resources/{kind}?") + urlencode({"url": url})

    def presentation(self, task):
        soup = BeautifulSoup(task["statement_html"], "html.parser")
        if soup.find(list(UNSUPPORTED_ACTIVE)):
            # Do not silently discard potentially meaningful task text inside a control.
            raise SourceError("Unsupported active statement content")
        for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
            comment.extract()
        for tag in soup.find_all(list(EXECUTABLE)):
            tag.decompose()
        for tag in soup.find_all(True):
            if tag.name not in TAGS:
                raise SourceError("Unsupported statement element")
            attributes = {}
            if tag.name in {"td", "th", "table", "col", "colgroup"}:
                for key in ("colspan", "rowspan", "border"):
                    if key in tag.attrs and re.fullmatch(r"\d+", str(tag[key])):
                        attributes[key] = tag[key]
            if "class" in tag.attrs:
                classes = [c for c in tag.get("class", []) if c in {"lmar", "in"}]
                if classes:
                    attributes["class"] = classes
            if tag.name == "img":
                if not tag.get("src"):
                    raise SourceError("Missing image")
                attributes["src"] = self.resource_url(task["id"], "image", tag["src"])
                if "alt" in tag.attrs:
                    attributes["alt"] = tag["alt"]
            if tag.name == "a":
                if not tag.get("href"):
                    raise SourceError("Missing attachment")
                attributes["href"] = self.resource_url(task["id"], "attachment", tag["href"])
            tag.attrs = attributes
        value = {key: task[key] for key in ("id", "ege_numbers", "statement", "source_url", "listing_url")}
        value.update(statement_html=str(soup), images=[tag["src"] for tag in soup.select("img[src]")],
                     attachments=[tag["href"] for tag in soup.select("a[href]")])
        return Task.model_validate(value).model_dump()

    def resource(self, ident, kind, url):
        task = self.get(ident)
        if url not in task["images" if kind == "image" else "attachments"]:
            raise missing()
        response = self.fetch(url)
        headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
        if kind == "image":
            mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if mime not in IMAGE_MIMES:
                raise ApiError(502, "source_error", "Не удалось получить изображение")
            headers["Content-Disposition"] = "inline"
            if mime == "image/svg+xml":
                headers["Content-Security-Policy"] = SVG_CSP
        else:
            mime = "application/octet-stream"
            name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            name = re.sub(r"[\x00-\x1f\x7f/\\]", "_", name) or "attachment.bin"
            headers["Content-Disposition"] = "attachment; filename*=utf-8\x27\x27" + quote(name, safe="")
        return response.content, mime, headers
